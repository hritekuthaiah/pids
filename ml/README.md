# pids-ml

Training and evaluation for the PIDS decision core.

- `pids-train anomaly` — Isolation Forest over per-track behavioural features, trained
  on *normal* site activity only (unsupervised), then calibrated to a probability
  with a small labelled set (Platt scaling).
- `pids-train fusion` — fits the fusion layer's log-odds weights by maximum likelihood
  on labelled simulation, producing `config/models/fusion-weights.json`.

Training uses simulator seeds `0–999`; evaluation uses seeds `≥ 10000`, so reported
numbers are always on scenarios the models never saw.
