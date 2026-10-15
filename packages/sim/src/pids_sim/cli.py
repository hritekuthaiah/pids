"""``pids-sim`` — quick comparison of PIDS against the naive baselines.

The full evaluation harness (thousands of scenarios, ablations, figures) lives in
``pids_ml``; this command is the fast sanity check used during development.
"""

from __future__ import annotations

import argparse
import statistics
import sys
from collections.abc import Callable
from pathlib import Path

from pids_core.baseline import NaiveGeofence
from pids_core.engine import DecisionEngine
from pids_core.site import Site
from pids_sim.outcomes import RunOutcome, score_run
from pids_sim.runner import Engine, run
from pids_sim.scenarios import Family, ScenarioSpec

ENGINES: dict[str, Callable[[Site], Engine]] = {
    "pids": DecisionEngine,
    "line-crossing": lambda s: NaiveGeofence(s, "line-crossing"),
    "gps-only": lambda s: NaiveGeofence(s, "gps-only"),
}


def summarise(name: str, outcomes: list[RunOutcome]) -> str:
    threats = [t for o in outcomes for t in o.threats]
    detected = [t for t in threats if t.detected]
    hours = sum(o.duration_s for o in outcomes) / 3600.0
    nuisance = sum(o.nuisance_alarms for o in outcomes)
    leads = [t.lead_time_s for t in detected if t.lead_time_s is not None]
    pd = len(detected) / len(threats) if threats else float("nan")
    lead = f"{statistics.median(leads):6.1f}s" if leads else "    n/a"
    return (
        f"{name:14s} Pd={pd:6.1%}  ({len(detected)}/{len(threats)})  "
        f"NAR={nuisance / hours:7.1f}/h  median lead={lead}"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pids-sim", description=__doc__)
    ap.add_argument("--site", type=Path, default=Path("config/sites/site-alpha.yaml"))
    ap.add_argument("-n", "--per-family", type=int, default=5)
    ap.add_argument("--seed", type=int, default=1000)
    args = ap.parse_args(argv)

    site = Site.from_yaml(args.site)
    results: dict[str, list[RunOutcome]] = {k: [] for k in ENGINES}
    for f_idx, family in enumerate(Family):
        for i in range(args.per_family):
            spec = ScenarioSpec(seed=args.seed + 100 * f_idx + i, family=family)
            for name, factory in ENGINES.items():
                results[name].append(score_run(run(site, spec, factory(site))))
    for name, outs in results.items():
        sys.stdout.write(summarise(name, outs) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
