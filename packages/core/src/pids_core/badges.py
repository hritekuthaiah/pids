"""Passive BLE badges: rolling identifiers and unambiguous badge-to-track linking (ADR-0012).

Whitelisted people never tap anything: their phone (or an ESP32 badge) advertises a
short identifier over Bluetooth Low Energy, and the edge node's scanner hears it.
Two problems have to be solved for that to be safe:

**Replay.** A fixed identifier can be recorded once and rebroadcast by anyone. So the
identifier rolls: every ``WINDOW_S`` seconds it is the first 8 bytes of
``HMAC-SHA256(badge_secret, "pids-ble" || window)``, and each badge's secret is
``HMAC-SHA256(site_key, tag_id)`` — the scanner derives every badge's secret from the
one site key and the tag registry, and a captured identifier is useless a minute later.

**Which person is it?** A scanner in a room hears a badge but not *where* it is. The
naive answer — give it to the nearest track — whitelists an intruder walking beside
an authorised person, or one in view while the badge holder is behind a wall. Instead
we use physics: received signal strength falls with distance (log-distance path
loss), so as the badge holder moves, their badge's RSSI must rise and fall with
*their* distance to the scanner and not with anyone else's. A badge is linked to a
track only when the rank correlation between its RSSI and that track's
``-log10(distance)`` over the last few seconds is strong **and** clearly better than
every other person in range. Standing still gives no evidence; two people walking
side by side are ambiguous — and if in doubt, nobody is whitelisted (recall first).
"""

from __future__ import annotations

import hashlib
import hmac
import math
import struct
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field

import numpy as np

WINDOW_S = 30
#: Bluetooth SIG company id reserved for testing; PIDS payloads are tagged with MAGIC.
COMPANY_ID = 0xFFFF
MAGIC = b"PD"
VERSION_STATIC = 0
VERSION_ROLLING = 1
ID_BYTES = 8


# ---------------------------------------------------------------------------
# Identifiers
# ---------------------------------------------------------------------------


def badge_secret(site_key: bytes, tag_id: str) -> bytes:
    return hmac.new(site_key, b"pids-badge:" + tag_id.encode(), hashlib.sha256).digest()


def window_of(t: float) -> int:
    return math.floor(t / WINDOW_S)


def rolling_id(secret: bytes, window: int) -> bytes:
    msg = b"pids-ble" + struct.pack(">Q", window)
    return hmac.new(secret, msg, hashlib.sha256).digest()[:ID_BYTES]


def static_id(secret: bytes) -> bytes:
    """Fixed identifier for advertisers that cannot roll (bench testing only: replayable)."""
    return hmac.new(secret, b"pids-static", hashlib.sha256).digest()[:ID_BYTES]


def payload(identifier: bytes, version: int = VERSION_ROLLING) -> bytes:
    """Manufacturer-specific data (after the company id) a badge advertises."""
    return MAGIC + bytes([version]) + identifier


def parse_payload(data: bytes) -> tuple[int, bytes] | None:
    """``(version, identifier)`` from manufacturer data, or None if it is not a PIDS badge."""
    if len(data) != len(MAGIC) + 1 + ID_BYTES or not data.startswith(MAGIC):
        return None
    version = data[len(MAGIC)]
    if version not in (VERSION_STATIC, VERSION_ROLLING):
        return None
    return version, data[len(MAGIC) + 1 :]


class BadgeResolver:
    """Maps heard identifiers back to tag ids; accepts one window of clock skew either way."""

    def __init__(
        self, site_key: bytes, tag_ids: Iterable[str], *, allow_static: bool = False
    ) -> None:
        self._secrets = {tag: badge_secret(site_key, tag) for tag in tag_ids}
        self._static = (
            {static_id(s): tag for tag, s in self._secrets.items()} if allow_static else {}
        )
        self._window: int | None = None
        self._rolling: dict[bytes, str] = {}

    def resolve(self, version: int, identifier: bytes, t: float) -> str | None:
        if version == VERSION_STATIC:
            return self._static.get(identifier)
        w = window_of(t)
        if w != self._window:
            self._rolling = {
                rolling_id(secret, w + k): tag
                for tag, secret in self._secrets.items()
                for k in (-1, 0, 1)
            }
            self._window = w
        return self._rolling.get(identifier)


# ---------------------------------------------------------------------------
# Linking badges to camera tracks
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LinkPolicy:
    window_s: float = 10.0
    #: a badge not heard for this long is no longer present
    badge_fresh_s: float = 6.0
    min_reads: int = 6
    #: a track must move at least this much (closer/farther) to give evidence
    min_range_change_m: float = 1.0
    min_correlation: float = 0.6
    min_margin: float = 0.3


@dataclass
class _Heard:
    reads: deque[tuple[float, float]] = field(default_factory=deque)  # (t, rssi)

    def recent(self, now: float, seconds: float) -> list[tuple[float, float]]:
        return [r for r in self.reads if now - r[0] <= seconds]


def _ranks(x: np.ndarray) -> np.ndarray:
    """Ranks with ties averaged (a person standing still has many equal distances)."""
    order = np.argsort(x, kind="stable")
    ranks = np.empty(len(x))
    ranks[order] = np.arange(len(x), dtype=float)
    _, inverse, counts = np.unique(x, return_inverse=True, return_counts=True)
    sums = np.bincount(inverse, weights=ranks)
    return np.asarray(sums[inverse] / counts[inverse], dtype=float)


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    """Rank correlation (robust to RSSI's non-linearity and multipath outliers)."""
    if len(x) < 3 or np.ptp(x) == 0 or np.ptp(y) == 0:
        return 0.0
    return float(np.corrcoef(_ranks(x), _ranks(y))[0, 1])


@dataclass(frozen=True, slots=True)
class Candidate:
    """A person track within a reader's range: its recent ``(t, distance_m)`` samples."""

    entity_id: str
    distances: list[tuple[float, float]]


@dataclass(frozen=True, slots=True)
class Decision:
    tag_id: str
    entity_id: str | None
    correlation: float
    margin: float
    reason: str


class BadgeLinker:
    """Per reader: which track (if any) each heard badge belongs to, unambiguously."""

    def __init__(self, policy: LinkPolicy | None = None) -> None:
        self.policy = policy or LinkPolicy()
        self._heard: dict[str, _Heard] = {}
        self.links: dict[str, str] = {}  # tag_id -> entity_id

    def hear(self, tag_id: str, t: float, rssi_dbm: float) -> None:
        h = self._heard.setdefault(tag_id, _Heard())
        h.reads.append((t, rssi_dbm))
        while h.reads and t - h.reads[0][0] > 4 * self.policy.window_s:
            h.reads.popleft()

    def present(self, now: float) -> list[str]:
        p = self.policy
        return [
            tag
            for tag, h in self._heard.items()
            if h.reads and now - h.reads[-1][0] <= p.badge_fresh_s
        ]

    def _score(self, reads: list[tuple[float, float]], cand: Candidate) -> float | None:
        """Correlation of RSSI with -log10(distance), or None if the track gave no evidence."""
        p = self.policy
        if len(cand.distances) < 2:
            return None
        ts = np.array([d[0] for d in cand.distances])
        ds = np.array([d[1] for d in cand.distances])
        if np.ptp(ds) < p.min_range_change_m:
            return None  # standing still: no evidence for or against
        rt = np.array([r[0] for r in reads])
        inside = (rt >= ts[0]) & (rt <= ts[-1])
        if inside.sum() < p.min_reads:
            return None
        dist_at = np.interp(rt[inside], ts, ds)
        rssi = np.array([r[1] for r in reads])[inside]
        return spearman(rssi, -np.log10(np.maximum(dist_at, 0.3)))

    def update(self, now: float, candidates: list[Candidate]) -> list[Decision]:
        """Re-evaluate every present badge against the person tracks in range."""
        p = self.policy
        decisions: list[Decision] = []
        alive = {c.entity_id for c in candidates}
        for tag in list(self.links):
            if tag not in self.present(now) or self.links[tag] not in alive:
                del self.links[tag]  # badge gone silent, or its person left view
        for tag in self.present(now):
            reads = self._heard[tag].recent(now, p.window_s)
            scored = {c.entity_id: self._score(reads, c) for c in candidates}
            # Anyone in range who gave no evidence counts as uncorrelated (0), not as absent.
            value = {e: (sc if sc is not None else 0.0) for e, sc in scored.items()}
            ranked = sorted(value.items(), key=lambda kv: kv[1], reverse=True)
            held = self.links.get(tag)
            if not ranked or all(sc is None for sc in scored.values()):
                decisions.append(Decision(tag, held, 0.0, 0.0, "no motion evidence"))
                continue
            who, best = ranked[0]
            margin = best - (ranked[1][1] if len(ranked) > 1 else 0.0)
            if held is not None:
                # Hysteresis: an earned link holds until someone else clearly fits better.
                rival = best - value.get(held, 0.0)
                if who != held and best >= p.min_correlation and rival >= p.min_margin:
                    self.links[tag] = who
                    decisions.append(Decision(tag, who, best, rival, "moved to a better fit"))
                else:
                    decisions.append(Decision(tag, held, value.get(held, 0.0), margin, "link held"))
            elif best >= p.min_correlation and margin >= p.min_margin:
                self.links[tag] = who
                decisions.append(Decision(tag, who, best, margin, "linked"))
            else:
                decisions.append(
                    Decision(
                        tag,
                        None,
                        best,
                        margin,
                        "ambiguous" if best >= p.min_correlation else "weak",
                    )
                )
        # one badge per track: if two badges claim one person, trust neither
        owners: dict[str, list[str]] = {}
        for tag, ent in self.links.items():
            owners.setdefault(ent, []).append(tag)
        for tags in owners.values():
            if len(tags) > 1:
                for tag in tags:
                    del self.links[tag]
        return decisions
