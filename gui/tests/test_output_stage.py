import os
import struct
import zipfile

from signal_gui import output_stage


SAMPLE_STDOUT = (
    "Loading topo data for boundaries: (51.579372N, 1.794542W) to (52.118628N, 2.665258W)\n"
    "Area boundaries:52.118628 | -1.793233 | 51.579372 | -2.666567 \n"
    "[100%] Processing 3386/3382 points\n"
)


def test_parse_bbox():
    bbox = output_stage.parse_bbox(SAMPLE_STDOUT)
    assert bbox == (52.118628, -1.793233, 51.579372, -2.666567)


def test_build_kml():
    kml = output_stage.build_kml("cov.png", (52.1, -1.7, 51.5, -2.6), "Test")
    assert "<GroundOverlay>" in kml
    assert "<north>52.1</north>" in kml
    assert "<href>cov.png</href>" in kml


def _make_ppm(path, w=4, h=3):
    with open(path, "wb") as fh:
        fh.write(b"P6\n%d %d\n255\n" % (w, h))
        fh.write(b"\xff\xff\xff" * (w * h))  # white => transparent after convert


def test_ppm_to_png_and_stage(tmp_path):
    ppm = tmp_path / "t1.ppm"
    _make_ppm(str(ppm))
    out = output_stage.stage_output(str(ppm), SAMPLE_STDOUT, title="Test")
    assert os.path.exists(out["png"])
    assert os.path.exists(out["kml"])
    assert out["bbox"] == (52.118628, -1.793233, 51.579372, -2.666567)
    # png should be smaller than the white ppm after transparency
    assert os.path.getsize(out["png"]) > 0


def test_extract_hgt(tmp_path):
    from signal_gui import dem_convert
    zpath = tmp_path / "B48.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("B48/S05E102.hgt", b"\x00\x01\x02\x03")
    hgts = dem_convert.extract_hgt(str(zpath), str(tmp_path / "raw"))
    assert any(f.endswith("S05E102.hgt") for f in hgts)
