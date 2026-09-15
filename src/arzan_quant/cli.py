from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import tempfile
from pathlib import Path

from .api import ResearchApiClient
from .config import ApiConfig
from .manifest import verify_manifest
from .schema import Observation, parse_timestamp
from .synthetic import generate_observations, write_jsonl


def _generate_synthetic(args: argparse.Namespace) -> None:
    records = generate_observations(seed=args.seed, days=args.days)
    for record in records:
        Observation.from_dict(record)
    write_jsonl(args.output, records)
    print(f"wrote {len(records)} validated synthetic observations to {args.output}")


def _verify_manifest(args: argparse.Namespace) -> None:
    verified = verify_manifest(args.manifest)
    total_bytes = sum(item.size_bytes for item in verified)
    print(f"verified {len(verified)} files ({total_bytes} bytes)")


def _ingest_api(args: argparse.Namespace) -> None:
    start = parse_timestamp(args.observed_from, "observed_from")
    end = parse_timestamp(args.observed_to, "observed_to")
    if end <= start:
        raise SystemExit("observed-to must be later than observed-from")
    if args.output.exists() and not args.overwrite:
        raise SystemExit(f"output already exists: {args.output}; use --overwrite explicitly")

    client = ResearchApiClient(ApiConfig.from_environment())
    params = {
        "observed_from": args.observed_from,
        "observed_to": args.observed_to,
        "limit": args.page_size,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    seen_ids: dict[str, bytes] = {}
    with tempfile.NamedTemporaryFile(
        dir=args.output.parent, prefix=".ingest-", delete=False
    ) as temp:
        temporary = Path(temp.name)
    try:
        with gzip.open(temporary, "wt", encoding="utf-8") as stream:
            for record in client.iter_items("price-observations", params):
                observation = Observation.from_dict(record)
                if not start <= observation.observed_at < end:
                    raise RuntimeError("API returned an observation outside the requested window")
                previous = seen_ids.get(observation.observation_id)
                fingerprint = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).digest()
                if previous is not None:
                    if previous != fingerprint:
                        raise RuntimeError("API returned conflicting duplicate observation IDs")
                    continue
                seen_ids[observation.observation_id] = fingerprint
                stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
                stream.write("\n")
                count += 1
        if args.overwrite:
            os.replace(temporary, args.output)
        else:
            os.link(
                temporary, args.output
            )  # Atomic no-overwrite publication on the same filesystem.
    finally:
        temporary.unlink(missing_ok=True)
    print(f"wrote {count} unique validated observations to {args.output}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="arzan-quant")
    subparsers = parser.add_subparsers(dest="command", required=True)

    synthetic = subparsers.add_parser("generate-synthetic")
    synthetic.add_argument("--output", type=Path, required=True)
    synthetic.add_argument("--seed", type=int, default=20260913)
    synthetic.add_argument("--days", type=int, default=45)
    synthetic.set_defaults(func=_generate_synthetic)

    manifest = subparsers.add_parser("verify-manifest")
    manifest.add_argument("manifest", type=Path)
    manifest.set_defaults(func=_verify_manifest)

    ingest = subparsers.add_parser("ingest-api")
    ingest.add_argument("--observed-from", required=True)
    ingest.add_argument("--observed-to", required=True)
    ingest.add_argument("--output", type=Path, required=True)
    ingest.add_argument("--page-size", type=int, default=5000, choices=range(1, 5001))
    ingest.add_argument("--overwrite", action="store_true")
    ingest.set_defaults(func=_ingest_api)

    demo = subparsers.add_parser(
        "generate-export", help="Generate a complete synthetic research export"
    )
    demo.add_argument("--output", type=Path, required=True)
    demo.add_argument("--days", type=int, default=240)
    demo.add_argument("--seed", type=int, default=20260913)
    demo.add_argument("--independent", action="store_true")
    demo.set_defaults(func=_generate_export)

    research = subparsers.add_parser("run-research", help="Run the full research workflow")
    research.add_argument("--export", type=Path, action="append", required=True, dest="exports")
    research.add_argument("--settings", type=Path, required=True)
    research.add_argument("--output", type=Path, required=True)
    research.add_argument("--opening", type=Path)
    research.add_argument("--weights", type=Path)
    research.add_argument("--monthly-features", type=Path)
    research.add_argument("--targets", type=Path)
    research.add_argument("--skip-robustness", action="store_true")
    research.add_argument(
        "--resume-panel",
        action="store_true",
        help="Resume a failed run from its verified completed panel",
    )
    research.set_defaults(func=_run_research)

    landing = subparsers.add_parser(
        "package-landing", help="Package validated API NDJSON as an export"
    )
    landing.add_argument("--input", type=Path, required=True)
    landing.add_argument("--output", type=Path, required=True)
    landing.add_argument("--observed-from", required=True)
    landing.add_argument("--observed-to", required=True)
    landing.add_argument("--snapshot-at", required=True)
    landing.set_defaults(func=_package_landing)

    monthly = subparsers.add_parser(
        "build-monthly-vintage", help="Save the latest complete monthly index/diffusion signal"
    )
    monthly.add_argument("--run", type=Path, required=True)
    monthly.add_argument("--forecast-at", required=True)
    monthly.add_argument("--output", type=Path, required=True)
    monthly.set_defaults(func=_build_monthly_vintage)

    monthly_demo = subparsers.add_parser(
        "generate-monthly-demo", help="Generate synthetic monthly feature and target vintages"
    )
    monthly_demo.add_argument("--output", type=Path, required=True)
    monthly_demo.add_argument("--months", type=int, default=48)
    monthly_demo.add_argument("--seed", type=int, default=20260913)
    monthly_demo.set_defaults(func=_generate_monthly_demo)
    return parser


def _generate_export(args: argparse.Namespace) -> None:
    from .fixtures import generate_export

    generate_export(args.output, args.days, args.seed, args.independent)
    print(f"Wrote synthetic export and settings to {args.output}")


def _run_research(args: argparse.Namespace) -> None:
    from .research import run_research
    from .settings import ResearchSettings

    result = run_research(
        args.exports,
        args.output,
        ResearchSettings.read(args.settings),
        args.opening,
        args.weights,
        args.monthly_features,
        args.targets,
        not args.skip_robustness,
        args.resume_panel,
    )
    print(f"Research artifacts: {args.output}; evaluation: {result['evaluation']['status']}")


def _package_landing(args: argparse.Namespace) -> None:
    from .landing import package_landing

    package_landing(args.input, args.output, args.observed_from, args.observed_to, args.snapshot_at)
    print(f"Packaged API landing data in {args.output}")


def _build_monthly_vintage(args: argparse.Namespace) -> None:
    from .nowcast import build_monthly_vintage

    build_monthly_vintage(args.run, args.output, args.forecast_at)
    print(f"Saved monthly feature vintage to {args.output}")


def _generate_monthly_demo(args: argparse.Namespace) -> None:
    from .fixtures import generate_monthly_history

    generate_monthly_history(args.output, args.months, args.seed)
    print(f"Saved synthetic monthly experiment to {args.output}")


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
