from __future__ import annotations

import math

import numpy as np
import pytest

from pids_core.contracts import ZoneKind
from pids_core.features import Sample, TrackFeatures, TrackHistory, extract
from pids_core.geo import Enu
from pids_core.kalman import KalmanCV
from pids_core.site import Site


def test_kalman_velocity_is_unbiased_and_consistent() -> None:
    """Over many noise realisations the velocity error is ~zero-mean and its spread
    matches the filter's own reported uncertainty (a filter-consistency check)."""
    errors, sigmas = [], []
    for seed in range(200):
        rng = np.random.default_rng(seed)
        kf = KalmanCV.initialise(0.0, 0.0, 0.0, sigma_m=2.0)
        for i in range(1, 60):
            t = i * 0.5
            kf.update(t, 1.5 * t + rng.normal(0, 2.0), -0.5 * t + rng.normal(0, 2.0), 2.0)
        errors.append(np.subtract(kf.velocity, (1.5, -0.5)))
        sigmas.append(kf.velocity_sigma)
    err = np.array(errors)
    assert np.abs(err.mean(axis=0)).max() < 0.1
    rmse = float(np.sqrt((err**2).mean()))
    assert 0.5 < rmse / float(np.mean(sigmas)) < 2.0
    assert rmse < 0.5


def test_kalman_innovation_flags_a_jump() -> None:
    kf = KalmanCV.initialise(0.0, 0.0, 0.0, sigma_m=1.0, velocity=(1.0, 0.0))
    for i in range(1, 10):
        kf.update(float(i), float(i), 0.0, 1.0)
    normal = kf.update(10.0, 10.0, 0.0, 1.0)
    jump = kf.update(11.0, 200.0, 0.0, 1.0)
    assert normal < 5.0
    assert jump > 100.0


def test_kalman_ignores_non_increasing_time_in_predict() -> None:
    kf = KalmanCV.initialise(5.0, 0.0, 0.0, 1.0, velocity=(1.0, 0.0))
    kf.predict(4.0)
    assert kf.position == (0.0, 0.0)
    assert kf.forecast(10.0) == (10.0, 0.0)


def _history(site: Site, points: list[tuple[float, float, float]]) -> TrackHistory:
    h = TrackHistory()
    for t, e, n in points:
        h.append(Sample(t=t, east=e, north=n, zone_kind=site.zones.locate(Enu(e, n)).kind))
    return h


def _features(site: Site, points: list[tuple[float, float, float]]) -> TrackFeatures:
    h = _history(site, points)
    f = extract(h, site.zones, points[-1][0], local_hour=2.0)
    assert f is not None
    return f


def test_head_on_approach_has_positive_approach_rate(site: Site) -> None:
    f = _features(site, [(i, 0.0, 200.0 - 1.5 * i) for i in range(20)])
    assert f.approach_rate == pytest.approx(1.5, abs=0.05)
    assert f.speed_mean == pytest.approx(1.5, abs=0.01)
    assert f.tortuosity == pytest.approx(1.0, abs=0.01)
    assert f.boundary_parallel < 0.1


def test_fence_walker_moves_parallel_to_the_boundary(site: Site) -> None:
    f = _features(site, [(i, -80.0 + 1.0 * i, 115.0) for i in range(25)])
    assert f.boundary_parallel > 0.95
    assert abs(f.approach_rate) < 0.1


def test_loiterer_dwells_and_stops(site: Site) -> None:
    pts = [(i * 0.5, 30.0 + 0.05 * math.sin(i), 150.0 + 0.05 * math.cos(i)) for i in range(60)]
    f = _features(site, pts)
    assert f.stop_fraction > 0.9
    assert f.dwell_warning_s == pytest.approx(29.5)


def test_time_of_day_is_cyclic(site: Site) -> None:
    h = _history(site, [(i, 0.0, 200.0 - i) for i in range(10)])
    midnight = extract(h, site.zones, 9.0, local_hour=0.0)
    late = extract(h, site.zones, 9.0, local_hour=24.0)
    assert midnight is not None
    assert late is not None
    assert midnight.hour_sin == pytest.approx(late.hour_sin)
    assert midnight.hour_cos == pytest.approx(1.0)


def test_features_need_enough_history(site: Site) -> None:
    h = _history(site, [(0.0, 0.0, 200.0), (0.5, 0.0, 199.0)])
    assert extract(h, site.zones, 0.5, local_hour=12.0) is None


def test_feature_vector_order_is_stable() -> None:
    assert TrackFeatures.names()[0] == "speed_mean"
    assert len(TrackFeatures.names()) == 12


def test_history_rejects_out_of_order_and_tracks_dwell() -> None:
    h = TrackHistory(max_age_s=10.0)
    h.append(Sample(0.0, 0, 0, ZoneKind.WARNING))
    h.append(Sample(5.0, 0, 0, ZoneKind.WARNING))
    h.append(Sample(4.0, 0, 0, None))  # out of order: dropped
    h.append(Sample(20.0, 0, 0, None))
    assert len(h) == 1  # old samples aged out
    assert h.dwell_warning_s == pytest.approx(20.0)
    assert h.last is not None
    assert h.last.t == 20.0
