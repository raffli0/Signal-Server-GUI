"""Integration test: the area-run retry loop actually re-invokes the engine.

Uses a fake engine script whose first invocation prints garbage boundaries
(the threaded-LIDAR longitude race) and whose second invocation is healthy,
then asserts the worker retries with a halved -segments value and finishes
with the healthy result.
"""

import os

import pytest

from signal_gui.backend import RunWorker


GOOD_BBOX = "-6.016668 | 108.514967 | -7.816666 | 106.701633"
BROKEN_BBOX = "-6.016668 | 1195.608300 | -7.816666 | -980.391700"

PPM = b"P6\n4 4\n255\n" + bytes([255, 0, 0] * 16)


def _fake_engine(tmp_path, template_ppm):
    """Engine that is broken on call #1 and healthy afterwards.

    Records every argv to argv.log so the test can assert the second attempt
    carried the halved segment count.
    """
    script = tmp_path / "fake_engine.sh"
    script.write_text(f"""#!/bin/bash
out=""
prev=""
for a in "$@"; do
  if [ "$prev" = "-o" ]; then out="$a"; fi
  prev="$a"
done
dir=$(dirname "$out")
cnt_file="$dir/attempts"
n=$(( $(cat "$cnt_file" 2>/dev/null || echo 0) + 1 ))
echo "$n" > "$cnt_file"
echo "$*" >> "$dir/argv.log"
cp "{template_ppm}" "$out.ppm"
if [ "$n" = "1" ]; then
  echo "Area boundaries:{BROKEN_BBOX} "
else
  echo "Area boundaries:{GOOD_BBOX} "
fi
""")
    script.chmod(script.stat().st_mode | 0o111)
    return str(script)


def test_area_retry_reinvokes_with_halved_segments(tmp_path):
    engine = _fake_engine(tmp_path, str((tmp_path / "template.ppm")))
    (tmp_path / "template.ppm").write_bytes(PPM)
    out_base = str(tmp_path / "run" / "cov")
    os.makedirs(os.path.dirname(out_base), exist_ok=True)

    params = {
        "engine": "LIDAR",
        "tx_lat": -6.916667, "tx_lon": 107.6083, "tx_height": 1.0,
        "radius": 100, "resolution": 1200,
        "frequency_mhz": 900, "rf_power_w": 1.0, "tx_gain_dbi": 10.0,
        "rx_threshold_dbm": -100.0,
        "plot_segments": 16,
        "units": "metric", "model_pm": 1,
    }
    worker = RunWorker(engine, out_base, params, dem_spec=None)
    state: dict = {}

    def on_finished(ok, stdout, result):
        state["ok"] = ok
        state["result"] = result

    def on_error(msg):
        state["error"] = msg

    worker.finished.connect(on_finished)
    worker.error_occurred.connect(on_error)

    # Direct in-thread invocation: signals fire synchronously, no event loop.
    worker.run()

    assert "error" not in state, state.get("error")
    assert state["ok"]

    bbox = state["result"]["bbox"]
    n, e, s, w = (float(v) for v in bbox)
    assert abs(e - 108.514967) < 1e-4          # healthy attempt won
    assert abs(w - 106.701633) < 1e-4

    attempts_file = tmp_path / "run" / "attempts"
    assert attempts_file.read_text().strip() == "2"

    argv_log = (tmp_path / "run" / "argv.log").read_text().splitlines()
    assert len(argv_log) == 2
    assert "-segments 16" in argv_log[0]
    assert "-segments 8" in argv_log[1]        # ladder halved on retry
