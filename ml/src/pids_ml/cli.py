"""``pids-train`` — train the anomaly scorer and calibrate the fusion weights.

    pids-train anomaly   # Isolation Forest on normal activity + Platt calibration
    pids-train fusion    # logistic fit of fusion weights (uses the anomaly model)
    pids-train all

Training seeds are 0-999; evaluation uses seeds >= 10000 (never seen in training).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.model_selection import train_test_split

from pids_core.engine import DecisionModel
from pids_core.fusion import TERMS, FusionWeights
from pids_core.scoring import ScoringPolicy
from pids_ml.anomaly import IsolationForestScorer, select
from pids_ml.collect import collect_features, collect_terms, specs
from pids_ml.fusion_fit import fit_constrained

log = logging.getLogger("pids_ml")

SITE = Path("config/sites/site-alpha.yaml")
ANOMALY_OUT = Path("ml/artifacts/anomaly-iforest.joblib")
MODEL_OUT = Path("config/models/decision-model.json")
# Operating point chosen on training seeds for maximum Pd (recall first); see ADR-0009.
WARNING_AT = 0.30
ELEVATED_AT = 0.20


def expected_calibration_error(y: np.ndarray, p: np.ndarray, bins: int = 10) -> float:
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges) - 1, 0, bins - 1)
    ece = 0.0
    for b in range(bins):
        m = idx == b
        if m.any():
            ece += m.mean() * abs(float(y[m].mean()) - float(p[m].mean()))
    return ece


def train_anomaly(n: int, workers: int, out: Path) -> None:
    rows = collect_features(SITE, specs(range(n)), workers)
    normal = select(rows.x[rows.normal])
    log.info("anomaly: %d feature rows (%d normal)", len(rows.x), len(normal))
    forest = IsolationForest(
        n_estimators=150, max_samples=256, contamination="auto", random_state=0
    ).fit(normal)
    probe = IsolationForestScorer(forest, 1.0, 0.0)

    # Behaviour only needs to separate threats from *non-cooperative* traffic; tagged
    # entities are handled by identity. Calibrate and report on that population.
    labelled = (rows.label >= 0) & ~rows.cooperative
    raw = np.array([probe.raw(x) for x in select(rows.x[labelled])])
    y = rows.label[labelled]
    platt = LogisticRegression().fit(raw.reshape(-1, 1), y)
    a, b = float(platt.coef_[0, 0]), float(platt.intercept_[0])
    base = float(y.mean())
    scorer = IsolationForestScorer(forest, a, b, prior_logit=float(np.log(base / (1.0 - base))))
    p = 1.0 / (1.0 + np.exp(-(a * raw + b)))
    log.info(
        "anomaly: AUC(raw)=%.3f  Brier=%.3f  ECE=%.3f  (positives %d / %d)",
        roc_auc_score(y, raw),
        brier_score_loss(y, p),
        expected_calibration_error(y, p),
        int(y.sum()),
        len(y),
    )
    scorer.save(out)
    log.info("anomaly: saved %s", out)


def train_fusion(n: int, workers: int, anomaly: Path | None, out: Path) -> None:
    rows = collect_terms(SITE, specs(range(1000 - n, 1000)), anomaly, workers)
    log.info("fusion: %d labelled assessments (%d positive)", len(rows.y), int(rows.y.sum()))
    x_tr, x_te, y_tr, y_te = train_test_split(
        rows.x, rows.y, test_size=0.25, random_state=0, stratify=rows.y
    )
    free = LogisticRegression(C=1.0, max_iter=2000).fit(x_tr, y_tr)
    p_free = free.predict_proba(x_te)[:, 1]
    fit = fit_constrained(x_tr, y_tr)
    p = fit.predict(x_te)
    for name, probs in (("unconstrained", p_free), ("constrained  ", p)):
        log.info(
            "fusion %s (held-out): AUC=%.3f  logloss=%.3f  Brier=%.4f  ECE=%.4f",
            name,
            roc_auc_score(y_te, probs),
            log_loss(y_te, probs),
            brier_score_loss(y_te, probs),
            expected_calibration_error(y_te, probs),
        )
    weights = FusionWeights(
        source="fitted",
        version=f"constrained-n{n}",
        bias=round(fit.bias, 4),
        weights={k: round(w, 4) for k, w in fit.weights.items()},
    )
    log.info("   %-16s %8s %8s", "term", "free", "fitted")
    for k, w_free in zip(TERMS, free.coef_[0], strict=True):
        log.info("   %-16s %+8.3f %+8.3f", k, w_free, weights.weights[k])
    log.info("   %-16s %+8.3f %+8.3f", "bias", free.intercept_[0], weights.bias)
    model = DecisionModel(
        fusion=weights,
        scoring=ScoringPolicy(
            elevated_at=ELEVATED_AT, warning_at=WARNING_AT, critical_at=WARNING_AT
        ),
        notes=(
            f"Sign-constrained logistic fit on {len(rows.y)} labelled assessments from "
            f"training seeds; held-out AUC {roc_auc_score(y_te, p):.3f}, "
            f"ECE {expected_calibration_error(y_te, p):.4f}."
        ),
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(model.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
    log.info("fusion: saved %s", out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pids-train", description=__doc__)
    ap.add_argument("what", choices=["anomaly", "fusion", "all"])
    ap.add_argument("-n", "--scenarios", type=int, default=240)
    ap.add_argument("-j", "--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.what in ("anomaly", "all"):
        train_anomaly(args.scenarios, args.workers, ANOMALY_OUT)
    if args.what in ("fusion", "all"):
        anomaly = ANOMALY_OUT if ANOMALY_OUT.exists() else None
        train_fusion(args.scenarios, args.workers, anomaly, MODEL_OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
