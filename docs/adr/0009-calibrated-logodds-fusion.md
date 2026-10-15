# ADR-0009: Log-odds fusion, domain-constrained calibration, recall-first operating point

- **Status:** Accepted
- **Date:** 2026-10-16
- **Requirements:** AIL-09, AIL-05, AIL-04, NFR-02

## Context

Fusion must turn heterogeneous, partly-missing evidence (geofence state, detector
class and confidence, track age, thermal, behavioural anomaly, predicted breach,
cooperative-tag identity, spoof suspicion) into one *calibrated* threat probability,
explain itself to an operator, and never let a missing channel suppress an alarm.
The PRD's "weighted-rule" stub could do none of that rigorously.

## Decision

1. **Model.** Logistic (log-odds) evidence accumulation over 13 fixed evidence terms —
   the naive-Bayes view of fusion, plus one corroboration interaction term to correct
   for non-independent channels. Unavailable channels contribute exactly zero; absence
   of heat *inside* thermal coverage is its own term. Zone terms are scaled by an
   *existence* belief (detector confidence × track age) so a one-second low-confidence
   flicker inside the compound is not treated as a person.
2. **Calibration.** Weights are fitted by maximum likelihood on labelled simulation
   (training seeds 0–999), **with sign and magnitude bounds from domain knowledge**
   (bounded L-BFGS). An unconstrained fit reached held-out AUC 0.87 but learned
   simulator shortcuts — "no heat signature ⇒ more threatening", "animal ⇒ −11 log-odds
   (absolute veto)", "longer-tracked ⇒ less threatening". In a safety system those
   are bugs; the constrained fit (AUC 0.79, ECE 0.036) is accepted instead.
3. **Behaviour.** An Isolation Forest is trained on *non-cooperative normal traffic only*
   (cooperative entities are separated by identity, not behaviour), Platt-calibrated on a
   labelled set, and emitted in likelihood-ratio form (0.5 = uninformative) so ordinary
   behaviour never lowers a threat.
4. **Operating point.** Thresholds are chosen on training seeds for maximum detection
   (recall first): WARNING/CRITICAL at P ≥ 0.30, ELEVATED at P ≥ 0.20. Weights and
   thresholds ship together as one versioned file, `config/models/decision-model.json`.
5. **Safety rails outside the learned model.** CRITICAL requires a geometric breach; a
   recall floor keeps any sustained (≥ 3 s, conf ≥ 0.45) untagged person/vehicle inside
   the core at WARNING regardless of the model; containment breaches are always CRITICAL.

## Consequences

- Held-out evaluation (80 unseen scenarios, 70 threats): Pd 98.6 % vs 100 % for naive
  line-crossing, at 33 nuisance alarms/h vs 187/h (−82 %), with a median 62 s of warning
  before a breach. See `docs/evaluation/results.md`.
- The residual failure mode is an intruder carrying a **cloned, genuinely authorised tag**
  (1 of 10 missed): identity lowers threat by design, and behaviour does not always
  outweigh it. Mitigations are operational (duty rosters, tag revocation, tag-behaviour
  policies) and are listed as future work.
- All weights are learned from simulation; transfer to real sites requires recalibration
  on site data (the procedure is the same command: `make train`).
