"""Supervision target: *should an alert be active for this entity right now?*

Labelling every moment of a threat agent's life as positive would teach the model
that any untagged person 300 m out in open ground is an alarm. Instead:

* non-threat agents and ghost tracks are always negative;
* a threat agent is positive once its behaviour is threat-relevant — inside the
  warning band or the core, within ``LEAD_WINDOW_S`` of its breach, or after a
  containment breach — and *excluded* (not negative) before that, because at that
  point it is indistinguishable from a passer-by by design.
"""

from __future__ import annotations

from pids_core.contracts import ZoneKind
from pids_sim.runner import AgentTruth

LEAD_WINDOW_S = 45.0


def alert_worthy(truth: AgentTruth | None, t: float, zone_kind: ZoneKind | None) -> int | None:
    if truth is None or not truth.is_threat:
        return 0
    if zone_kind in (ZoneKind.WARNING, ZoneKind.CRITICAL):
        return 1
    if truth.breach_t is not None and t >= truth.breach_t - LEAD_WINDOW_S:
        return 1
    if truth.containment_breach_t is not None and t >= truth.containment_breach_t:
        return 1
    return None
