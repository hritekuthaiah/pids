# Evaluation results

> Provisional (M1). The full harness — more scenarios, confidence intervals,
> per-family breakdowns, ablations, latency, figures — lands with milestone M6.

## Protocol

- **Site:** Site Alpha (`config/sites/site-alpha.yaml`), 4 camera nodes (2 with thermal),
  1 gate reader, nested warning/critical zones and an armoury containment zone.
- **Scenarios:** 8 families × 10 seeds = 80 scenarios of 5 minutes each (6.7 h simulated),
  every one containing normal site activity (patrols with GPS phones, public-road traffic
  through the warning band, animals, staff badging in, a quick-reaction vehicle, a stored
  asset) plus at most one threat: intruder on foot, intruder vehicle, fence prober,
  loiterer, spoofed GPS tag, cloned (genuine) tag, asset theft.
- **Held-out:** evaluation seeds ≥ 10000; models were trained on seeds 0–999 only.
- **Same inputs for every engine:** identical scenarios, seeds and sensor noise; all
  engines share the same alert state machine, so differences come from decision logic.
- **Pd:** a threat is detected if any alert attributed to it reaches WARNING or above.
- **NAR:** RAISED alerts attributed to non-threat agents or ghost tracks, per hour.
- **Lead time:** breach time minus first alert time (positive = warned before breach).

## Results (held-out)

| Engine | Pd | Nuisance alarms / h | Median lead |
|---|---|---|---|
| Traditional GPS geofencing (`gps-only`) | 14.3 % (10/70) | 0.0 | — |
| Naive line-crossing over the same detections | 100 % (70/70) | 186.9 | 104.7 s |
| PIDS — expert-prior weights | 88.6 % (62/70) | 21.3 | 18.3 s |
| **PIDS — calibrated (decision-model.json)** | **98.6 % (69/70)** | **33.3** | **62.1 s** |

**Reading this.** Traditional GPS geofencing cannot see intruders who carry no device.
Naive line-crossing over the same camera detections catches everything but raises an
alarm roughly every 20 seconds — dominated by ghost tracks, patrols, road traffic and
animals. Calibrated PIDS keeps detection within one event of the naive baseline while
cutting nuisance alarms by **82 %**, and warns a median **62 s** before a breach.

**The one miss** is an intruder carrying a *cloned, genuinely authorised* tag — the
hardest case by design, discussed in ADR-0009.

**Remaining nuisance sources** (calibrated PIDS): road pedestrians walking toward the
compound, tagged patrols seen by two cameras at once (one track linked to the tag, the
other not — cross-camera track merging is the planned fix), short ghost tracks, and staff
walking the access path before their badge is read.

## Reproduce

```bash
make train          # anomaly model + decision model from training seeds
uv run python -m pids_ml.compare   # (harness CLI arrives with M6)
```
