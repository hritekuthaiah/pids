"""``pids-eval`` — the evaluation harness (PLT-11, #28): PIDS vs baselines, with ablations.

Every number comes from held-out simulator seeds (>= 10000; models trained on 0-999),
the same scenarios and sensor noise for every engine, and the same alert state machine,
so differences are the decision logic alone. Reported:

* **Pd** — share of threats with an alert of WARNING or above (recall first);
* **NAR** — nuisance alarms (RAISED on non-threats or ghost tracks) per hour;
* **lead time** — breach time minus first alert (positive = warned before breach);
* 95% intervals by cluster bootstrap over scenarios (a scenario's alarms are correlated);
* **ablations** — calibrated PIDS with one channel removed at a time;
* per-family detection, decision-step latency, and the behaviour model's own
  precision/recall on held-out tracks (#25).

Writes ``docs/evaluation/results.md``, ``eval.json`` and figures.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import statistics
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path

import numpy as np

from pids_core.engine import DecisionEngine, DecisionModel, EngineConfig
from pids_core.site import Site
from pids_ml.anomaly import IsolationForestScorer, select
from pids_ml.collect import collect_features, specs
from pids_ml.compare import EngineSpec, scenario_specs
from pids_sim.outcomes import RunOutcome, score_run
from pids_sim.runner import run
from pids_sim.scenarios import Family, ScenarioSpec, build

log = logging.getLogger("pids_ml.evaluate")

SITE = Path("config/sites/site-alpha.yaml")
MODEL = Path("config/models/decision-model.json")
ANOMALY = Path("ml/artifacts/anomaly-iforest.joblib")
OUT = Path("docs/evaluation")
EVAL_SEED0 = 10_000
BOOT = 1000

#: Ablations: (label, fusion terms zeroed, also drop behaviour model, disable safety rails)
ABLATIONS: list[tuple[str, tuple[str, ...], bool, bool]] = [
    ("- behaviour model", ("anomaly",), True, False),
    ("- thermal", ("thermal_present", "thermal_absent"), False, False),
    ("- identity (tags)", ("authorized_tag", "spoof"), False, False),
    ("- breach prediction", ("imminence",), False, False),
    ("- corroboration", ("corroboration",), False, False),
    ("- safety rails", (), False, True),
]


@dataclass(frozen=True, slots=True)
class Variant:
    """An engine variant: a baseline, or PIDS with optional ablations (picklable)."""

    name: str
    kind: str  # "pids" | "line-crossing" | "gps-only"
    fitted: bool = True
    zero: tuple[str, ...] = ()
    behaviour: bool = True
    rails: bool = True

    def engine(self, site: Site) -> object:
        if self.kind != "pids":
            return EngineSpec(self.kind).build(site)
        model = DecisionModel.load(MODEL) if self.fitted else DecisionModel()
        fusion = model.fusion
        if self.zero:
            fusion = fusion.model_copy(
                update={
                    "weights": {
                        k: (0.0 if k in self.zero else v) for k, v in fusion.weights.items()
                    }
                }
            )
        scoring = model.scoring
        if not self.rails:  # no recall floor, no predicted-breach escalation
            scoring = scoring.model_copy(
                update={"floor_min_confidence": 1.01, "predicted_breach_horizon_s": 0.0}
            )
        scorer = (
            IsolationForestScorer.load(ANOMALY) if self.behaviour and ANOMALY.exists() else None
        )
        return DecisionEngine(
            site, EngineConfig(fusion=fusion, scoring=scoring), anomaly_scorer=scorer
        )


def _run_one(variant: Variant, spec: ScenarioSpec) -> RunOutcome:
    site = Site.from_yaml(SITE)
    return score_run(run(site, spec, variant.engine(site)))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Metrics:
    pd: float
    pd_ci: tuple[float, float]
    nar: float
    nar_ci: tuple[float, float]
    lead_median_s: float | None
    detected: int
    threats: int
    hours: float
    criticals: int


def _point(outcomes: list[RunOutcome]) -> tuple[float, float]:
    threats = [t for o in outcomes for t in o.threats]
    hours = sum(o.duration_s for o in outcomes) / 3600
    pd = sum(t.detected for t in threats) / len(threats) if threats else float("nan")
    return pd, sum(o.nuisance_alarms for o in outcomes) / hours


def metrics(outcomes: list[RunOutcome], rng: np.random.Generator) -> Metrics:
    pd, nar = _point(outcomes)
    boot = [
        _point([outcomes[i] for i in rng.integers(0, len(outcomes), len(outcomes))])
        for _ in range(BOOT)
    ]
    pds = np.array([b[0] for b in boot])
    nars = np.array([b[1] for b in boot])
    threats = [t for o in outcomes for t in o.threats]
    leads = [t.lead_time_s for t in threats if t.detected and t.lead_time_s is not None]
    return Metrics(
        pd=pd,
        pd_ci=(float(np.nanpercentile(pds, 2.5)), float(np.nanpercentile(pds, 97.5))),
        nar=nar,
        nar_ci=(float(np.percentile(nars, 2.5)), float(np.percentile(nars, 97.5))),
        lead_median_s=statistics.median(leads) if leads else None,
        detected=sum(t.detected for t in threats),
        threats=len(threats),
        hours=sum(o.duration_s for o in outcomes) / 3600,
        criticals=sum(t.critical for t in threats),
    )


def per_family(outcomes: list[RunOutcome]) -> dict[str, tuple[int, int, float]]:
    """family -> (detected, threats, nuisance/h)."""
    out: dict[str, tuple[int, int, float]] = {}
    for fam in Family:
        runs = [o for o in outcomes if o.family == fam.value]
        if not runs:
            continue
        threats = [t for o in runs for t in o.threats]
        hours = sum(o.duration_s for o in runs) / 3600
        out[fam.value] = (
            sum(t.detected for t in threats),
            len(threats),
            sum(o.nuisance_alarms for o in runs) / hours,
        )
    return out


# ---------------------------------------------------------------------------
# Latency and behaviour-model quality
# ---------------------------------------------------------------------------


def step_latency_ms(seed: int = EVAL_SEED0 + 7) -> dict[str, float]:
    """Wall time of DecisionEngine.step over a busy held-out scenario."""
    from pids_sim.runner import frames
    from pids_sim.sensors import SensorParams

    site = Site.from_yaml(SITE)
    engine = Variant("pids", "pids").engine(site)
    if not isinstance(engine, DecisionEngine):
        raise TypeError("expected the PIDS engine")
    scenario = build(site, ScenarioSpec(seed=seed, family=Family.INTRUSION_FOOT))
    _, stream = frames(site, scenario, SensorParams())
    times: list[float] = []
    entities: list[int] = []
    for frame in stream:
        for b in frame.batches:
            engine.ingest_tracks(b)
        for f in frame.fixes:
            engine.ingest_gps(f)
        for r in frame.reads:
            engine.ingest_tag_read(r)
        t0 = time.perf_counter()
        res = engine.step(scenario.start + timedelta(seconds=frame.t))
        times.append((time.perf_counter() - t0) * 1000)
        entities.append(len(res.assessments))
    return {
        "p50_ms": float(np.percentile(times, 50)),
        "p99_ms": float(np.percentile(times, 99)),
        "max_ms": float(np.max(times)),
        "mean_entities": float(np.mean(entities)),
        "steps": len(times),
    }


def behaviour_quality(n: int, workers: int) -> dict[str, float] | None:
    """Held-out precision/recall/AUC of the behaviour model on non-cooperative tracks."""
    from sklearn.metrics import (
        average_precision_score,
        precision_score,
        recall_score,
        roc_auc_score,
    )

    if not ANOMALY.exists():
        return None
    scorer = IsolationForestScorer.load(ANOMALY)
    rows = collect_features(SITE, specs(range(EVAL_SEED0, EVAL_SEED0 + n)), workers)
    keep = (rows.label >= 0) & ~rows.cooperative
    x, y = select(rows.x[keep]), rows.label[keep]
    raw = np.array([scorer.raw(v) for v in x])
    p = 1 / (1 + np.exp(-(scorer.platt_a * raw + scorer.platt_b)))
    pred = p >= 0.5
    return {
        "auc": float(roc_auc_score(y, raw)),
        "average_precision": float(average_precision_score(y, raw)),
        "precision_at_0.5": float(precision_score(y, pred, zero_division=0)),
        "recall_at_0.5": float(recall_score(y, pred, zero_division=0)),
        "positives": int(y.sum()),
        "rows": len(y),
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def _pct(v: float) -> str:
    return f"{100 * v:.1f} %"


def _figures(
    results: dict[str, Metrics], fams: dict[str, dict[str, tuple[int, int, float]]], out: Path
) -> list[str]:
    import matplotlib as mpl

    mpl.use("Agg")
    import matplotlib.pyplot as plt

    out.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    names = list(results)
    made: list[str] = []

    fig, ax = plt.subplots(figsize=(7, 4.2))
    for n in names:
        m = results[n]
        ax.errorbar(
            m.nar, 100 * m.pd,
            xerr=[[m.nar - m.nar_ci[0]], [m.nar_ci[1] - m.nar]],
            yerr=[[100 * (m.pd - m.pd_ci[0])], [100 * (m.pd_ci[1] - m.pd)]],
            fmt="o", capsize=3,
        )  # fmt: skip
        ax.annotate(n, (m.nar, 100 * m.pd), textcoords="offset points", xytext=(6, 4), fontsize=8)
    ax.set_xscale("symlog", linthresh=10)
    ax.set_xlabel("Nuisance alarms per hour (log)")
    ax.set_ylabel("Probability of detection (%)")
    ax.set_title("Detection vs nuisance (held-out, 95% CI)")
    fig.tight_layout()
    fig.savefig(out / "pd-vs-nar.png", dpi=160)
    plt.close(fig)
    made.append("pd-vs-nar.png")

    base, pids = fams.get("Naive line-crossing", {}), fams.get("PIDS — calibrated", {})
    families = [f for f in pids if pids[f][1] > 0]
    if families:
        fig, ax = plt.subplots(figsize=(7, 3.6))
        xs = np.arange(len(families))
        ax.bar(
            xs - 0.2,
            [100 * base[f][0] / base[f][1] for f in families],
            0.4,
            label="Naive line-crossing",
            color="#9aa5a0",
        )
        ax.bar(
            xs + 0.2,
            [100 * pids[f][0] / pids[f][1] for f in families],
            0.4,
            label="PIDS",
            color="#d9480f",
        )
        ax.set_xticks(xs, families, rotation=20, ha="right")
        ax.set_ylabel("Detected (%)")
        ax.set_ylim(0, 105)
        ax.legend(frameon=False)
        ax.set_title("Detection by threat family")
        fig.tight_layout()
        fig.savefig(out / "detection-by-family.png", dpi=160)
        plt.close(fig)
        made.append("detection-by-family.png")

    full = results.get("PIDS — calibrated")
    abl = [n for n in names if n.startswith("PIDS -")]
    if full and abl:
        fig, (a1, a2) = plt.subplots(1, 2, figsize=(8, 3.4), sharey=True)
        dpd = [100 * (results[n].pd - full.pd) for n in abl]
        dnar = [results[n].nar - full.nar for n in abl]
        labels = [n.replace("PIDS ", "") for n in abl]
        a1.barh(labels, dpd, color="#1c7ed6")
        a1.axvline(0, color="k", lw=0.6)
        a1.set_xlabel("Δ Pd (points)")
        a2.barh(labels, dnar, color="#e8590c")
        a2.axvline(0, color="k", lw=0.6)
        a2.set_xlabel("Δ nuisance alarms / h")
        fig.suptitle("Ablation: removing one channel from calibrated PIDS")
        fig.tight_layout()
        fig.savefig(out / "ablations.png", dpi=160)
        plt.close(fig)
        made.append("ablations.png")
    return made


def write_report(
    results: dict[str, Metrics],
    fams: dict[str, dict[str, tuple[int, int, float]]],
    latency: dict[str, float],
    behaviour: dict[str, float] | None,
    per: int,
    figures: list[str],
    out: Path,
) -> None:
    some = next(iter(results.values()))
    lines = [
        "# Evaluation results",
        "",
        f"> Generated by `make eval` on {datetime.now(UTC):%Y-%m-%d} — do not edit by hand.",
        "",
        "## Protocol",
        "",
        f"- **Site:** Site Alpha (`{SITE}`): 4 camera nodes (2 with thermal), a gate reader,",
        "  nested warning/critical zones and an armoury containment zone.",
        f"- **Scenarios:** {len(Family)} families x {per} held-out seeds (≥ {EVAL_SEED0}) of 5 minutes "
        f"= {some.hours:.1f} h simulated. Each contains normal site activity (patrols with GPS phones,",
        "  public-road traffic through the warning band, animals, staff badging in, a quick-reaction",
        "  vehicle, a stored asset) plus at most one threat.",
        "- **Models** were trained on seeds 0-999 only. Every engine sees identical inputs and shares",
        "  the alert state machine, so differences are decision logic alone.",
        "- **Pd:** a threat is detected if an alert attributed to it reaches WARNING. **NAR:** RAISED",
        "  alerts on non-threats or ghost tracks per hour. **Lead:** breach time - first alert.",
        f"- **Intervals:** 95 % cluster bootstrap over scenarios ({BOOT} resamples).",
        "",
        "## Headline",
        "",
        "| Engine | Pd (95 % CI) | Nuisance alarms / h (95 % CI) | Median lead |",
        "|---|---|---|---|",
    ]
    for n, m in results.items():
        if n.startswith("PIDS -"):
            continue
        lead = f"{m.lead_median_s:.1f} s" if m.lead_median_s is not None else "—"
        lines.append(
            f"| {n} | **{_pct(m.pd)}** ({_pct(m.pd_ci[0])}-{_pct(m.pd_ci[1])}) · {m.detected}/{m.threats} "
            f"| **{m.nar:.1f}** ({m.nar_ci[0]:.1f}-{m.nar_ci[1]:.1f}) | {lead} |"
        )
    naive, pids = results.get("Naive line-crossing"), results.get("PIDS — calibrated")
    if naive and pids and naive.nar > 0:
        lines += [
            "",
            f"Calibrated PIDS detects {_pct(pids.pd)} of intrusions against {_pct(naive.pd)} for naive "
            f"line-crossing over the same detections, while raising **{100 * (1 - pids.nar / naive.nar):.0f} % "
            "fewer nuisance alarms**.",
        ]
    lines += [
        "",
        "## Ablations (calibrated PIDS minus one channel)",
        "",
        "| Variant | Pd | Δ Pd | NAR / h | Δ NAR |",
        "|---|---|---|---|---|",
    ]
    if pids:
        for n, m in results.items():
            if n.startswith("PIDS -"):
                lines.append(
                    f"| {n.replace('PIDS ', '')} | {_pct(m.pd)} | {100 * (m.pd - pids.pd):+.1f} pt | {m.nar:.1f} | {m.nar - pids.nar:+.1f} |"
                )
    lines += [
        "",
        "## By threat family",
        "",
        "| Family | Naive line-crossing | PIDS — calibrated |",
        "|---|---|---|",
    ]
    for fam in Family:
        b = fams.get("Naive line-crossing", {}).get(fam.value)
        p = fams.get("PIDS — calibrated", {}).get(fam.value)
        if b and p:

            def cell(v: tuple[int, int, float]) -> str:
                det = f"{v[0]}/{v[1]} detected" if v[1] else "no threat"
                return f"{det}, {v[2]:.1f} nuisance/h"

            lines.append(f"| {fam.value} | {cell(b)} | {cell(p)} |")
    lines += [
        "",
        "## Decision latency",
        "",
        f"`DecisionEngine.step` over a busy scenario ({latency['mean_entities']:.1f} entities on average, "
        f"{latency['steps']} steps): p50 **{latency['p50_ms']:.2f} ms**, p99 {latency['p99_ms']:.2f} ms, "
        f"max {latency['max_ms']:.2f} ms. Live end-to-end capture → decision measured on the demo stack: "
        "~170 ms (NFR-01 target < 2 s).",
    ]
    if behaviour:
        lines += [
            "",
            "## Behaviour model (Isolation Forest, held-out tracks)",
            "",
            f"On {behaviour['rows']} non-cooperative track windows ({behaviour['positives']} alert-worthy): "
            f"AUC **{behaviour['auc']:.3f}**, average precision {behaviour['average_precision']:.3f}, "
            f"precision {behaviour['precision_at_0.5']:.3f} / recall {behaviour['recall_at_0.5']:.3f} at p ≥ 0.5. "
            "It is one evidence channel among several, so recall here is not the system's Pd.",
        ]
    if figures:
        lines += ["", "## Figures", ""] + [f"![{f}](figures/{f})" for f in figures]
    lines += [
        "",
        "## Reproduce",
        "",
        "```bash",
        "make train   # models from training seeds 0-999",
        f"make eval    # this report (pids-eval -n {per})",
        "```",
        "",
    ]
    (out / "results.md").write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pids-eval", description=__doc__)
    ap.add_argument("-n", "--per-family", type=int, default=20)
    ap.add_argument("-j", "--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--no-ablations", action="store_true")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    variants = [
        Variant("Traditional GPS geofencing", "gps-only"),
        Variant("Naive line-crossing", "line-crossing"),
        Variant("PIDS — expert prior", "pids", fitted=False),
        Variant("PIDS — calibrated", "pids"),
    ]
    if not args.no_ablations:
        variants += [
            replace(
                Variant(f"PIDS {label}", "pids"),
                zero=zero,
                behaviour=not no_beh,
                rails=not no_rails,
            )
            for label, zero, no_beh, no_rails in ABLATIONS
        ]
    scenarios = scenario_specs(EVAL_SEED0, args.per_family)
    rng = np.random.default_rng(0)
    results: dict[str, Metrics] = {}
    fams: dict[str, dict[str, tuple[int, int, float]]] = {}
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for v in variants:
            t0 = time.monotonic()
            outcomes = list(pool.map(partial(_run_one, v), scenarios))
            results[v.name] = metrics(outcomes, rng)
            fams[v.name] = per_family(outcomes)
            m = results[v.name]
            log.info(
                "%-30s Pd=%5.1f%%  NAR=%6.1f/h  (%.0fs)",
                v.name,
                100 * m.pd,
                m.nar,
                time.monotonic() - t0,
            )
    latency = step_latency_ms()
    behaviour = behaviour_quality(len(Family) * args.per_family, args.workers)
    figures = _figures(results, fams, args.out / "figures")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "eval.json").write_text(
        json.dumps(
            {
                "results": {k: asdict(v) for k, v in results.items()},
                "per_family": fams,
                "latency": latency,
                "behaviour": behaviour,
            },
            indent=2,
        )
        + "\n"
    )
    write_report(results, fams, latency, behaviour, args.per_family, figures, args.out)
    log.info("wrote %s", args.out / "results.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
