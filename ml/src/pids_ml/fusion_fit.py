"""Domain-constrained calibration of the fusion weights.

An unconstrained logistic regression fitted on simulated data learns whatever
correlations the simulator happens to contain — e.g. "a missing heat signature
makes a threat *more* likely" because one camera without thermal happened to
watch most intrusions. That is a shortcut, not physics, and in a safety system it
is dangerous. So each evidence term gets a sign (monotonicity) constraint and a
magnitude bound from domain knowledge, and the weights are fitted by bounded
L-BFGS on the L2-regularised log-loss. The cost of the constraints in held-out
AUC/calibration is reported alongside, so the trade-off is explicit.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import minimize

from pids_core.fusion import TERMS

FloatArray = NDArray[np.float64]

MAX_ABS = 6.0
# (lower, upper) per term — sign encodes the direction the evidence must push.
BOUNDS: dict[str, tuple[float, float]] = {
    "zone_warning": (0.0, MAX_ABS),
    "zone_critical": (0.0, MAX_ABS),
    "class_person": (0.0, MAX_ABS),
    "class_vehicle": (0.0, MAX_ABS),
    # Animals lower the threat, but a misclassified crawling intruder must still be
    # recoverable by other channels: cap the suppression well short of absolute.
    "class_animal": (-4.0, 0.0),
    "persistence": (0.0, MAX_ABS),
    "thermal_present": (0.0, MAX_ABS),
    "thermal_absent": (-MAX_ABS, 0.0),
    "anomaly": (0.0, MAX_ABS),
    "imminence": (0.0, MAX_ABS),
    # A tag lowers threat but must stay overridable by strong behavioural evidence.
    "authorized_tag": (-6.0, 0.0),
    "spoof": (0.0, MAX_ABS),
    "corroboration": (0.0, MAX_ABS),
}


@dataclass(frozen=True, slots=True)
class Fit:
    bias: float
    weights: dict[str, float]

    def predict(self, x: FloatArray) -> FloatArray:
        w = np.array([self.weights[k] for k in TERMS])
        z: FloatArray = x @ w + self.bias
        return 1.0 / (1.0 + np.exp(-z))


def fit_constrained(x: FloatArray, y: NDArray[np.int8], l2: float = 1e-3) -> Fit:
    yf = y.astype(np.float64)
    n = len(yf)

    def loss_grad(theta: FloatArray) -> tuple[float, FloatArray]:
        b, w = theta[0], theta[1:]
        z = x @ w + b
        # numerically stable log(1 + exp(z)) - y z
        loss = float(np.mean(np.logaddexp(0.0, z) - yf * z) + l2 * float(w @ w))
        p = 1.0 / (1.0 + np.exp(-z))
        r = (p - yf) / n
        grad = np.concatenate([[r.sum()], x.T @ r + 2.0 * l2 * w])
        return loss, grad

    theta0 = np.zeros(len(TERMS) + 1)
    bounds = [(-20.0, 20.0)] + [BOUNDS[k] for k in TERMS]
    res = minimize(loss_grad, theta0, jac=True, method="L-BFGS-B", bounds=bounds)
    if not res.success:
        raise RuntimeError(f"constrained fusion fit failed: {res.message}")
    return Fit(
        bias=float(res.x[0]), weights={k: float(v) for k, v in zip(TERMS, res.x[1:], strict=True)}
    )
