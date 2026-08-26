"""Guard for the threaded-LIDAR "pizza slice" detection (backend)."""

from signal_gui import backend


PARAMS = {"tx_lat": -6.916667, "tx_lon": 107.6083, "radius": 100}

# Straight from a real engine log.
GOOD_BBOX = (-6.016668, 108.514967, -7.816666, 106.701633)
# The +-1086-degree longitude shift observed on broken runs.
BROKEN_BBOX = (-6.016668, 1194.608300, -7.816666, -979.391700)


def test_plausible_normal_run():
    assert backend.RunWorker._bbox_plausible(GOOD_BBOX, PARAMS)


def test_rejects_longitude_race_shift():
    assert not backend.RunWorker._bbox_plausible(BROKEN_BBOX, PARAMS)
    # Either side alone out of range is enough.
    assert not backend.RunWorker._bbox_plausible(
        (-6.0, 1194.6, -7.8, 106.7), PARAMS)


def test_rejects_missing_or_malformed():
    assert not backend.RunWorker._bbox_plausible(None, PARAMS)
    assert not backend.RunWorker._bbox_plausible((0, 0, 0, 0), PARAMS)   # empty
    assert not backend.RunWorker._bbox_plausible(
        ("x", "y", "z", "w"), PARAMS)
    assert not backend.RunWorker._bbox_plausible(
        (91.0, 108.5, -7.8, 106.7), PARAMS)                  # lat out of world
    assert not backend.RunWorker._bbox_plausible(
        (-6.0, 106.0, -7.8, 108.5), PARAMS)                  # inverted E/W


def test_rejects_oversized_span_for_radius():
    # Valid coordinates, but a 40-degree span cannot come from a 10 km radius.
    p = dict(PARAMS, radius=10)
    assert not backend.RunWorker._bbox_plausible(
        (5.0, 20.0, -35.0, -20.0), p)


def test_accepts_reasonable_crop_growth():
    # Cropping may widen the box slightly beyond the nominal radius.
    assert backend.RunWorker._bbox_plausible(
        (-6.4, 108.2, -7.4, 107.0), PARAMS)


def test_segments_ladder_halves_to_floor_4():
    f = backend.RunWorker._next_segments
    assert f(16) == 8
    assert f(8) == 4
    assert f(4) == 4          # floor: engine needs even >2
    assert f(None) == 8       # sane default when unset
    assert f("12") == 6       # tolerant of strings
