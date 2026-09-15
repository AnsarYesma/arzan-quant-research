"""Offline aggregate artifacts; raw offer rows are never embedded in the dashboard."""

from __future__ import annotations

import json
from pathlib import Path


def dump_json(path: Path, value):
    path.write_text(json.dumps(value, indent=2, default=str, allow_nan=False) + "\n")


def create_report(output: Path, result: dict, index_rows: list[dict]):
    summary = result["evaluation"]["aggregate"]
    lines = [
        "# Arzan research run",
        "",
        f"Run status: {result['status']}.",
        f"Daily dataset: {result['data_kind']}.",
        "",
        "## Data and readiness",
        "",
        (
            f"Observations: {result['inputs']['observations']:,}. "
            f"Crawl coverage rows: {result['inputs']['coverage_rows']:,}."
        ),
        "",
        *[f"- {key}: {value}" for key, value in result["panel"].items()],
        "",
        f"Model evaluation: {result['evaluation']['status']}.",
        "",
        (
            "Continuous crawler observation is assumed: carried unchanged prices remain eligible "
            "without an age-since-event cap. Invalid prices, unavailable products and explicit "
            "collection failures remain excluded. Frozen mappings are accepted retrospectively."
            if result.get("assume_continuous_observation", False)
            else "No-event days are not automatically no-change labels. Store-level success confirms "
            "a carried state only when that explicit configuration assumption is enabled. "
            "Historical mapping validity is required unless retrospective matching is explicitly enabled."
        ),
        "",
        "## Chronological held-out evaluation",
        "",
    ]
    if summary:
        lines += [
            "| Model | Rows | Brier | Log loss | Return MAE |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
        lines += [
            f"| {name} | {m['n']} | {m['brier']:.5f} | {m['log_loss']:.5f} | {m['return_mae']:.5f} |"
            for name, m in summary.items()
        ]
    else:
        lines += ["Insufficient eligible history. No fitted performance claim is available."]
    excitation = result.get("excitation_experiment", {})
    lines += [
        "",
        (
            "Primary selection metric: Brier error. Log loss and calibration are secondary. "
            "Every within-family comparison uses the same chronological folds and risk rows."
        ),
        "",
        "## Response timing and excitation",
        "",
        (
            f"Response timing is reported through {result['response_timing']['horizon_days']} days. "
            "The isolated-event view removes target-days linked to multiple source events; "
            "retailer-category-date means provide a descriptive common-shock adjustment."
        ),
        "",
        (
            f"Focused excitation experiment: {excitation.get('status', 'not run')}. "
            f"Selected products: {excitation.get('selection', {}).get('products', 0)}. "
            "This is a coarse-grained daily Poisson excitation comparison, not a continuous-time "
            "Hawkes estimate or a causal test."
        ),
        "",
        f"Timestamp audit: {result['timestamp_audit']['interpretation']}.",
    ]
    lines += [
        "",
        "## Robustness checks",
        "",
        "| Variant | Eligible rows | Status | Diffusion Brier |",
        "| --- | ---: | --- | ---: |",
    ]
    for name, variant in result["robustness"].items():
        assessment = variant["evaluation"]
        score = assessment["aggregate"].get("hazard_diffusion", {}).get("brier")
        formatted = f"{score:.5f}" if score is not None else "not estimated"
        lines.append(
            f"| {name} | {variant['features']['rows']} | {assessment['status']} | {formatted} |"
        )
    if not result["robustness"]:
        lines.append("| Not requested | — | skipped | — |")
    changes = sum(p["changes"] for p in result["promotions"])
    followed = sum(p["complete_followups"] for p in result["promotions"])
    lines += [
        "",
        "## Promotion follow-up",
        "",
        (
            f"{changes:,} eligible daily price changes; {followed:,} have seven fully eligible follow-up days. "
            "Retailer and promotion-state breakdowns are in `results.json`."
        ),
        "",
    ]
    lines += [
        "",
        "## Interpretation",
        "",
        (
            "The hazard model estimates a daily probability of a net price change between eligible "
            "daily states. The marked-intensity model uses a Poisson GLM with past exponentially "
            "decayed activity and signed marks; it is a daily binned approximation, not a continuous-time "
            "Hawkes model. Magnitude is a ridge regression conditional on a change. Within-day reversals "
            "can cancel in a daily net change."
        ),
        "",
        (
            "The network shows descriptive excess change rates after recent source activity. "
            "Shared feeds, promotions, common shocks and collection timing can generate these patterns. "
            "Coefficients and network edges do not establish causality. No inferential p-values are claimed."
        ),
        "",
        (
            "Promotion persistence uses future follow-up only for descriptive outcomes and never as "
            "a predictor. Robustness variants may change the eligible sample; compare sample sizes as "
            "well as metrics."
        ),
        "",
        "## Index",
        "",
        result["index"]["label"] + ". " + result["index"]["method"] + ".",
        "",
        result["index"]["limitation"],
        (
            f"Basket offers: {result['index']['basket_offers']:,}; published days: {result['index']['published_days']}; "
            f"minimum observed basket weight: {result['index']['min_weight_coverage']}."
        ),
        "",
        "## Inflation nowcast",
        "",
        f"Status: {result['nowcast']['status']}.",
        "",
        (
            "Target data must include release timestamps and vintages. Training uses only releases "
            "available at the forecast origin and evaluation uses the first release. Feature vintages "
            "must be supplied as available at each origin; reconstructed historical data is not "
            "automatically a real-time vintage."
        ),
        "",
        "## Artifacts",
        "",
        "- `dashboard.html`: offline interactive aggregate network and diagnostics.",
        "- `diagnostics.png`: evaluation and index figure.",
        "- `results.json`: aggregate diagnostics, robustness runs and nowcast results.",
        "- `model_fits.json`: fold-specific preprocessing, coefficients and convergence diagnostics.",
        "- `research.duckdb`: private inputs, reconstructed states and feature tables.",
        "- `predictions.parquet`: private held-out prediction rows (when history is sufficient).",
        "- `run.json`: input hashes, configuration, code hashes and dependency versions.",
        "",
        (
            "Raw exports, database tables, model inputs and production samples must not be redistributed. "
            "Publication permission for aggregate findings does not make raw artifacts public."
        ),
    ]
    monthly = result["nowcast"].get("metrics", {})
    if monthly:
        table = ["| Monthly model | Held-out months | MAE | RMSE |", "| --- | ---: | ---: | ---: |"]
        table += [
            f"| {name} | {m['n']} | {m['mae']:.5f} | {m['rmse']:.5f} |"
            for name, m in monthly.items()
        ]
        position = lines.index("## Artifacts")
        lines[position:position] = table + [""]
    (output / "report.md").write_text("\n".join(lines) + "\n")
    data = {
        "network": result["network"],
        "metrics": summary,
        "index": index_rows,
        "readiness": result["data_kind"]
        + " — "
        + result["evaluation"]["status"]
        + (
            " — continuous observation assumed"
            if result.get("assume_continuous_observation")
            else ""
        ),
        "panel": result["panel"],
    }
    payload = json.dumps(data, default=str, allow_nan=False).replace("<", "\\u003c")
    page = DASHBOARD.replace("__DATA__", payload)
    (output / "dashboard.html").write_text(page)


def create_figure(output: Path, result: dict, index_rows: list[dict]):
    import matplotlib

    matplotlib.use("Agg")
    from datetime import date

    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), constrained_layout=True)
    metrics = result["evaluation"]["aggregate"]
    if metrics:
        names = list(metrics)
        axes[0].barh(names, [metrics[n]["brier"] for n in names], color="#227c89")
        axes[0].set_xlabel("Held-out Brier score (lower is better)")
    else:
        axes[0].text(
            0.5, 0.5, "Insufficient eligible history", ha="center", transform=axes[0].transAxes
        )
    axes[0].set_title("Daily change prediction")
    valid = [r for r in index_rows if r["index_value"] is not None]
    if valid:
        axes[1].plot(
            [date.fromisoformat(str(r["date"])[:10]) for r in index_rows],
            [r["index_value"] for r in index_rows],
            color="#d48a21",
        )
        axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
        axes[1].tick_params(axis="x", rotation=25)
    else:
        axes[1].text(
            0.5, 0.5, "No eligible opening basket", ha="center", transform=axes[1].transAxes
        )
    axes[1].set_title(result["index"]["label"].capitalize())
    axes[1].set_ylabel("Opening basket = 100")
    fig.savefig(output / "diagnostics.png", dpi=160)
    plt.close(fig)


DASHBOARD = """<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Arzan research diagnostics</title>
<style>
:root{font:16px system-ui;color:#18343c;background:#f2f5f3}body{max-width:1120px;margin:36px auto;padding:0 24px}
h1{font-size:34px;margin-bottom:6px}.muted{color:#536b70}section{background:white;border:1px solid #d6e1dd;border-radius:12px;padding:22px;margin:20px 0}
label{display:inline-block;margin:8px 16px 8px 0}svg{width:100%;height:auto;max-height:580px}button,select,input{font:inherit}
table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:9px;border-bottom:1px solid #dde7e2}
.node{cursor:pointer}.node:hover circle{fill:#cc8950}.scroll{overflow:auto;max-height:480px}th{position:sticky;top:0;background:white}#details{min-height:50px}
</style>
<h1>Arzan price research</h1><p class="muted">Observed associations and chronological prediction diagnostics</p>
<p id="readiness"></p>
<section><h2>Held-out model comparison</h2><p id="verdict"></p><div class="scroll"><table id="models"></table></div></section>
<section><h2>Propagation candidates</h2><p>Arrows connect recent source changes to a target's subsequent change rate. They do not establish influence.</p>
<label>Minimum exposed rows <input id="minimum" type="range" min="1" max="500" value="20"><output id="threshold">20</output></label>
<label>Retailer <select id="retailer"><option value="">All retailers</option></select></label>
<svg id="network" viewBox="0 0 960 500" role="img" aria-label="Directed network of retailer change associations"></svg>
<p id="details" aria-live="polite">Select a retailer to inspect its connections.</p><div class="scroll"><table id="edges"></table></div></section>
<section><h2>Index and diagnostics</h2><img src="diagnostics.png" style="width:100%" alt="Held-out prediction scores and sample price index">
<p>Index values use an opening basket and a minimum observed weight threshold. This is not official CPI.</p></section>
<script>
const data=__DATA__;
const $=s=>document.querySelector(s), ns='http://www.w3.org/2000/svg';
const node=(tag,attrs,text)=>{const e=document.createElementNS(ns,tag);for(const [k,v] of Object.entries(attrs))e.setAttribute(k,v);if(text!==undefined)e.textContent=text;return e;};
const retailers=[...new Set(data.network.flatMap(e=>[e.source_retailer,e.target_retailer]))].sort();
$('#minimum').max=Math.max(500,...data.network.map(e=>e.exposed_risk_rows));
for(const r of retailers){const o=document.createElement('option');o.value=r;o.textContent=r;$('#retailer').append(o);}
$('#readiness').textContent='Evaluation: '+data.readiness+'. Eligible daily transitions: '+data.panel.eligible_transitions.toLocaleString()+'.';
function table(el,headers,rows){el.replaceChildren();const head=document.createElement('tr');for(const h of headers){const th=document.createElement('th');th.textContent=h;head.append(th);}el.append(head);for(const row of rows){const tr=document.createElement('tr');for(const value of row){const td=document.createElement('td');td.textContent=value;tr.append(td);}el.append(tr);}}
function render(){const minimum=+$('#minimum').value,selected=$('#retailer').value;$('#threshold').textContent=minimum;
const edges=data.network.filter(e=>e.exposed_risk_rows>=minimum&&(!selected||e.source_retailer===selected||e.target_retailer===selected));
const svg=$('#network');svg.replaceChildren();const defs=node('defs',{});const marker=node('marker',{id:'arrow',viewBox:'0 0 10 10',refX:9,refY:5,markerWidth:6,markerHeight:6,orient:'auto-start-reverse'});marker.append(node('path',{d:'M 0 0 L 10 5 L 0 10 z',fill:'#678b89'}));defs.append(marker);svg.append(defs);
const points=new Map(retailers.map((r,i)=>{const a=2*Math.PI*i/Math.max(1,retailers.length)-Math.PI/2;return [r,[480+350*Math.cos(a),250+190*Math.sin(a)]];}));
for(const e of edges){const [x1,y1]=points.get(e.source_retailer),[x2,y2]=points.get(e.target_retailer);const dx=x2-x1,dy=y2-y1,l=Math.hypot(dx,dy);if(!l)continue;const path=node('path',{d:`M ${x1+dx/l*22} ${y1+dy/l*22} Q ${(x1+x2)/2-dy*.07} ${(y1+y2)/2+dx*.07} ${x2-dx/l*25} ${y2-dy/l*25}`,fill:'none',stroke:e.rate_difference>0?'#227c89':'#b1bfbb','stroke-width':1+Math.min(5,Math.abs(e.rate_difference)*20),'marker-end':'url(#arrow)',opacity:.7});path.append(node('title',{},`${e.source_retailer} → ${e.target_retailer}: ${e.exposed_risk_rows} exposed rows`));svg.append(path);}
for(const [r,[x,y]] of points){const g=node('g',{class:'node',tabindex:0,role:'button','aria-label':'Select '+r});g.append(node('circle',{cx:x,cy:y,r:19,fill:selected===r?'#cc8950':'#18343c'}),node('text',{x,y:y+37,'text-anchor':'middle','font-size':13},r));const select=()=>{$('#retailer').value=r;render();};g.onclick=select;g.onkeydown=e=>{if(e.key==='Enter')select();};svg.append(g);}
$('#details').textContent=edges.length?`${edges.length} connections pass this filter. Rate difference compares exposed rows with all eligible target rows; sample composition can confound it.`:'No connections pass this filter, or matching/history is insufficient.';
table($('#edges'),['Source','Target','Exposed rows','Exposed change rate','Target overall rate'],edges.map(e=>[e.source_retailer,e.target_retailer,e.exposed_risk_rows,(100*e.exposed_change_rate).toFixed(1)+'%',(100*e.baseline_rate).toFixed(1)+'%']));}
$('#minimum').oninput=render;$('#retailer').onchange=render;render();
const labels={persistence:'Always no change',training_rate:'Past change frequency',hazard_baseline:'Improved logistic baseline',hazard_diffusion:'Logistic + competitor signals',boosted_baseline:'Boosted-tree baseline',boosted_competitor:'Boosted tree + competitor signals',marked_intensity:'Daily intensity'};
if(data.metrics.hazard_baseline&&data.metrics.hazard_diffusion){const delta=100*(data.metrics.hazard_diffusion.brier/data.metrics.hazard_baseline.brier-1);$('#verdict').textContent=`Adding activity signals changes Brier error by ${delta>=0?'+':''}${delta.toFixed(3)}% versus baseline. Lower error is better.`;}
table($('#models'),['Model','Held-out rows','Brier','Log loss','Predicted changes','Observed changes'],Object.entries(data.metrics).map(([name,m])=>[labels[name]||name,m.n.toLocaleString(),m.brier.toFixed(6),m.log_loss.toFixed(6),(100*m.mean_predicted_probability).toFixed(2)+'%',(100*m.event_rate).toFixed(2)+'%']));
</script></html>"""
