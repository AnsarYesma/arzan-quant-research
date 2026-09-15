"""Regularized daily hazard, discrete intensity, and conditional mark models.

All preprocessing is fitted on training rows. No significance or causal interpretation
is attached to penalized coefficients. Daily intensity is a binned point-process
approximation, not continuous-time Hawkes likelihood.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import sparse
from scipy.optimize import minimize
from scipy.special import expit

BASE_NUMERIC = [
    "lag_promotion",
    "lag_return",
    "lag_state_age",
    "days_since_own_change",
    "own_change_rate_7d",
    "own_change_rate_30d",
    "own_change_rate_90d",
]
DIFFUSION_NUMERIC = [
    "peer_active_days",
    "peer_mark",
    "peer_decay",
    "cross_city_count",
    "category_count",
    "cross_category_count",
    "peer_active_1d",
    "peer_active_3d",
    "peer_active_7d",
    "peer_active_14d",
    "cheapest_peer_log_gap",
    "mean_peer_log_gap",
    "was_cheapest",
    "priced_peer_families",
]
CATEGORICAL = ["retailer_id", "city_id", "category_id", "day_of_week"]


@dataclass
class Encoder:
    numeric: list[str]
    means: np.ndarray
    scales: np.ndarray
    categories: dict[str, list[str]]

    @classmethod
    def fit(cls, frame, diffusion=True):
        numeric = BASE_NUMERIC + (DIFFUSION_NUMERIC if diffusion else [])
        values = frame[numeric].astype(float).to_numpy()
        means = np.nanmean(values, axis=0)
        means = np.nan_to_num(means)
        scales = np.nanstd(values, axis=0)
        scales = np.where(np.isfinite(scales) & (scales > 1e-8), scales, 1.0)
        categories = {
            name: sorted(frame[name].astype("string").fillna("unknown").unique().tolist())
            for name in CATEGORICAL
        }
        return cls(numeric, means, scales, categories)

    @property
    def names(self):
        return (
            ["intercept"]
            + self.numeric
            + [f"{key}={value}" for key, values in self.categories.items() for value in values[1:]]
        )

    def transform(self, frame, sparse_output=False):
        values = frame[self.numeric].astype(float).to_numpy()
        values = np.where(np.isfinite(values), values, self.means)
        blocks = [np.ones((len(frame), 1)), (values - self.means) / self.scales]
        if sparse_output:
            from pandas import Index

            blocks = [sparse.csr_matrix(block) for block in blocks]
            for key, categories in self.categories.items():
                if len(categories) < 2:
                    continue
                codes = Index(categories).get_indexer(frame[key].astype("string").fillna("unknown"))
                selected = np.flatnonzero(codes > 0)
                blocks.append(
                    sparse.csr_matrix(
                        (np.ones(len(selected)), (selected, codes[selected] - 1)),
                        shape=(len(frame), len(categories) - 1),
                    )
                )
            return sparse.hstack(blocks, format="csr")
        for key, categories in self.categories.items():
            v = frame[key].astype("string").fillna("unknown").to_numpy()
            blocks.extend((v == value).astype(float)[:, None] for value in categories[1:])
        return np.column_stack(blocks)

    def as_dict(self):
        return {
            "numeric": self.numeric,
            "means": self.means.tolist(),
            "scales": self.scales.tolist(),
            "categories": self.categories,
            "names": self.names,
        }


@dataclass
class TreeEncoder:
    """Training-only numeric and smoothed categorical encoding for boosted trees."""

    numeric: list[str]
    medians: np.ndarray
    category_rates: dict[str, dict[str, float]]
    global_rate: float

    @classmethod
    def fit(cls, frame, y, diffusion=True):
        numeric = BASE_NUMERIC + (DIFFUSION_NUMERIC if diffusion else [])
        values = frame[numeric].astype(float).to_numpy()
        medians = np.nanmedian(values, axis=0)
        medians = np.nan_to_num(medians)
        global_rate = float(np.mean(y))
        category_rates = {}
        for name in CATEGORICAL:
            labels = frame[name].astype("string").fillna("unknown")
            totals = {}
            for label, target in zip(labels, y, strict=True):
                count, events = totals.get(str(label), (0, 0.0))
                totals[str(label)] = count + 1, events + float(target)
            # Twenty prior observations at the overall rate stabilize small groups.
            category_rates[name] = {
                label: (events + 20 * global_rate) / (count + 20)
                for label, (count, events) in totals.items()
            }
        return cls(numeric, medians, category_rates, global_rate)

    @property
    def names(self):
        return self.numeric + [f"{name}_training_rate" for name in CATEGORICAL]

    def transform(self, frame):
        values = frame[self.numeric].astype(float).to_numpy()
        values = np.where(np.isfinite(values), values, self.medians)
        categories = []
        for name in CATEGORICAL:
            mapping = self.category_rates[name]
            encoded = (
                frame[name]
                .astype("string")
                .fillna("unknown")
                .map(mapping)
                .fillna(self.global_rate)
                .to_numpy(float)
            )
            categories.append(encoded[:, None])
        return np.column_stack([values, *categories]).astype(np.float32, copy=False)

    def as_dict(self):
        return {
            "numeric": self.numeric,
            "medians": self.medians.tolist(),
            "category_rates": self.category_rates,
            "global_rate": self.global_rate,
            "names": self.names,
        }


def fit_boosted_tree(train, test, diffusion=True, seed=20260913, max_train_rows=200_000):
    """Fit deterministic depth-two histogram trees by logistic gradient boosting."""
    y = train.changed.to_numpy(np.int8)
    if len(train) > max_train_rows:
        rng = np.random.default_rng(seed)
        selected = np.sort(rng.choice(len(train), max_train_rows, replace=False))
        fit_frame, fit_y = train.iloc[selected], y[selected]
    else:
        fit_frame, fit_y = train, y
    encoder = TreeEncoder.fit(fit_frame, fit_y, diffusion)
    x_train = encoder.transform(fit_frame).astype(float, copy=False)
    bins = 16
    edges = [np.unique(np.quantile(x_train[:, j], np.linspace(0, 1, bins + 1)[1:-1]))
             for j in range(x_train.shape[1])]
    binned = np.column_stack(
        [np.searchsorted(edge, x_train[:, j], side="right") for j, edge in enumerate(edges)]
    ).astype(np.uint8)
    learning_rate, iterations, l2 = 0.08, 40, 1.0
    initial = float(np.log(np.clip(fit_y.mean(), 1e-6, 1 - 1e-6) /
                           np.clip(1 - fit_y.mean(), 1e-6, 1)))
    score = np.full(len(fit_y), initial)
    trees = []

    def leaf_value(indices, gradient, hessian):
        return float(gradient[indices].sum() / (hessian[indices].sum() + l2))

    def build(indices, gradient, hessian, depth):
        if depth == 0 or len(indices) < 200:
            return {"value": leaf_value(indices, gradient, hessian)}
        best = None
        for feature, edge in enumerate(edges):
            if not len(edge):
                continue
            feature_bins = binned[indices, feature]
            count = np.bincount(feature_bins, minlength=len(edge) + 1)
            grad = np.bincount(feature_bins, weights=gradient[indices], minlength=len(edge) + 1)
            hess = np.bincount(feature_bins, weights=hessian[indices], minlength=len(edge) + 1)
            left_n, left_g, left_h = np.cumsum(count)[:-1], np.cumsum(grad)[:-1], np.cumsum(hess)[:-1]
            valid = (left_n >= 100) & (len(indices) - left_n >= 100)
            gains = np.where(
                valid,
                left_g**2 / (left_h + l2)
                + (grad.sum() - left_g) ** 2 / (hess.sum() - left_h + l2)
                - grad.sum() ** 2 / (hess.sum() + l2),
                -np.inf,
            )
            split = int(np.argmax(gains))
            candidate = float(gains[split])
            if candidate > 1e-10 and (best is None or candidate > best[0]):
                best = candidate, feature, split
        if best is None:
            return {"value": leaf_value(indices, gradient, hessian)}
        _, feature, split = best
        left_mask = binned[indices, feature] <= split
        return {
            "feature": feature,
            "threshold": float(edges[feature][split]),
            "left": build(indices[left_mask], gradient, hessian, depth - 1),
            "right": build(indices[~left_mask], gradient, hessian, depth - 1),
        }

    def tree_predict(tree, values):
        output = np.empty(len(values))
        stack = [(tree, np.arange(len(values)))]
        while stack:
            node, indices = stack.pop()
            if "value" in node:
                output[indices] = node["value"]
                continue
            left = values[indices, node["feature"]] <= node["threshold"]
            stack.append((node["left"], indices[left]))
            stack.append((node["right"], indices[~left]))
        return output

    all_indices = np.arange(len(fit_y))
    for _ in range(iterations):
        probability = expit(score)
        gradient = fit_y - probability
        hessian = probability * (1 - probability)
        tree = build(all_indices, gradient, hessian, depth=2)
        score += learning_rate * tree_predict(tree, x_train)
        trees.append(tree)
    predictions = np.empty(len(test), dtype=float)
    chunk_size = 250_000
    for start in range(0, len(test), chunk_size):
        stop = min(start + chunk_size, len(test))
        values = encoder.transform(test.iloc[start:stop])
        chunk_score = np.full(len(values), initial)
        for tree in trees:
            chunk_score += learning_rate * tree_predict(tree, values)
        predictions[start:stop] = expit(chunk_score)
    return predictions, {
        "encoder": encoder.as_dict(),
        "trees": trees,
        "diagnostics": {
            "family": "histogram_gradient_boosting_depth_2",
            "train_rows": len(fit_frame),
            "available_train_rows": len(train),
            "max_train_rows": max_train_rows,
            "parameters": {
                "iterations": iterations,
                "learning_rate": learning_rate,
                "max_depth": 2,
                "bins": bins,
                "min_samples_leaf": 100,
                "l2_regularization": l2,
            },
        },
    }


def fit_glm(x, y, family="logistic", penalty=1.0):
    if family not in ("logistic", "poisson"):
        raise ValueError("Unsupported GLM family")
    entries = x.data if sparse.issparse(x) else x
    if len(y) == 0 or not np.isfinite(entries).all() or not np.isfinite(y).all():
        raise ValueError("GLM requires finite non-empty data")
    if penalty < 0 or np.any(y < 0) or (family == "logistic" and np.any(y > 1)):
        raise ValueError("Invalid penalty or response domain")
    regularization = np.full(x.shape[1], penalty)
    regularization[0] = 0

    def objective(beta):
        eta = x @ beta
        if family == "logistic":
            mu = expit(eta)
            loss = np.sum(np.logaddexp(0, eta) - y * eta)
        else:
            # Convex linear continuation at extreme eta keeps loss and gradient consistent.
            mu = np.exp(np.minimum(eta, 30))
            loss = np.sum(mu + np.exp(30) * np.maximum(eta - 30, 0) - y * eta)
        gradient = x.T @ (mu - y) + regularization * beta
        return float(loss + 0.5 * np.sum(regularization * beta * beta)), gradient

    initial = np.zeros(x.shape[1])
    rate = np.clip(np.mean(y), 1e-5, 1 - 1e-5)
    initial[0] = np.log(rate / (1 - rate)) if family == "logistic" else np.log(rate)
    fitted = minimize(
        objective, initial, jac=True, method="L-BFGS-B", options={"maxiter": 3000, "ftol": 1e-10}
    )
    if not fitted.success:
        raise RuntimeError(f"{family} optimizer failed: {fitted.message}")
    if family == "poisson" and np.max(x @ fitted.x) > 30:
        raise RuntimeError("Intensity fit exceeded numerical range")
    return fitted.x, {
        "converged": bool(fitted.success),
        "iterations": int(fitted.nit),
        "objective": float(fitted.fun),
        "family": family,
        "penalty": penalty,
    }


def predict_glm(x, beta, family="logistic"):
    if family == "logistic":
        return expit(x @ beta)
    if family != "poisson":
        raise ValueError("Unsupported GLM family")
    return -np.expm1(-np.exp(np.clip(x @ beta, -30, 30)))


def fit_marks(x, y, penalty=1.0):
    if not len(y):
        raise ValueError("No observed marks")
    ridge = np.eye(x.shape[1]) * penalty
    ridge[0, 0] = 0
    gram = x.T @ x
    if sparse.issparse(gram):
        gram = gram.toarray()
    return np.linalg.solve(gram + ridge, x.T @ y)


def metrics(y, p, magnitude, expected):
    p = np.clip(np.asarray(p), 1e-9, 1 - 1e-9)
    y = np.asarray(y)
    magnitude = np.asarray(magnitude)
    expected = np.asarray(expected)
    return {
        "n": len(y),
        "events": int(y.sum()),
        "brier": float(np.mean((p - y) ** 2)),
        "log_loss": float(-np.mean(y * np.log(p) + (1 - y) * np.log1p(-p))),
        "mean_predicted_probability": float(np.mean(p)),
        "event_rate": float(np.mean(y)),
        "return_mae": float(np.mean(abs(expected - magnitude))),
        "return_rmse": float(np.sqrt(np.mean((expected - magnitude) ** 2))),
    }


def calibration(y, p, bins=10):
    y, p = np.asarray(y), np.asarray(p)
    assigned = np.minimum((p * bins).astype(int), bins - 1)
    return [
        {
            "bin": i,
            "n": int(np.sum(assigned == i)),
            "predicted": float(p[assigned == i].mean()),
            "observed": float(y[assigned == i].mean()),
        }
        for i in range(bins)
        if np.any(assigned == i)
    ]
