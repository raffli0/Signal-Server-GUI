"""Cache-integrity guards for DEM conversion (dem_convert)."""

import os
import stat

import pytest

from signal_gui import dem_convert as dc


GOOD_SDF = (
    "252.500000\n"
    "-7.000000\n"
    "252.400000\n"
    "-6.900000\n"
    "600 625 650\n"
    "615 640 665\n"
)


def test_sdf_valid_accepts_complete(tmp_path):
    p = tmp_path / "t.sdf"
    p.write_text(GOOD_SDF)
    assert dc.sdf_valid(str(p))


def test_sdf_valid_rejects_ragged_or_short(tmp_path):
    short = tmp_path / "short.sdf"
    short.write_text(GOOD_SDF.splitlines()[0] + "\n")       # header only
    assert not dc.sdf_valid(str(short))
    ragged = tmp_path / "ragged.sdf"                        # mid-row cut
    ragged.write_text(GOOD_SDF + "600 62")
    assert not dc.sdf_valid(str(ragged))
    empty = tmp_path / "empty.sdf"
    empty.write_text("")
    assert not dc.sdf_valid(str(empty))


def test_hgt_valid_size_check(tmp_path):
    p = tmp_path / "S06E107.hgt"
    p.write_bytes(b"\x00\x01" * (1201 * 1201))
    assert dc.hgt_valid(str(p))
    p.write_bytes(b"\x00\x01" * 100)                        # truncated
    assert not dc.hgt_valid(str(p))
    assert not dc.hgt_valid(str(tmp_path / "missing.hgt"))


def test_hgt_void_pct_counts_sentinels(tmp_path):
    import struct
    p = tmp_path / "v.hgt"
    vals = [100, -32768, 200, 32767, 100, 100]
    p.write_bytes(b"".join(struct.pack(">h", v) for v in vals))
    # voids: -32768 and 40000 -> 2/6
    assert dc.hgt_void_pct(str(p)) == pytest.approx(100.0 / 3.0)


def test_evaluate_void_thresholds():
    assert dc.evaluate_void(0.0)[0] == "ok"
    assert dc.evaluate_void(10.0)[0] == "warn"
    assert dc.evaluate_void(50.0)[0] == "reject"


def test_convert_hgt_to_sdf_heals_poisoned_cache(tmp_path, monkeypatch):
    """A truncated .sdf from a killed run must be replaced by a fresh one."""
    sdf_dir = tmp_path / "sdf"
    sdf_dir.mkdir()
    poison = sdf_dir / "0_1_0_1.sdf"
    poison.write_text("252.5\n-7\n")                        # truncated junk

    hgt = tmp_path / "N00E000.hgt"
    hgt.write_bytes(b"\x00\x01" * (1201 * 1201))

    fake = tmp_path / "fake_srtm2sdf.sh"
    good = GOOD_SDF
    fake.write_text(
        "#!/bin/sh\n"
        f"printf '%s' '{good}' > 0_1_0_1.sdf\n"
    )
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)

    out = dc.convert_hgt_to_sdf(str(fake), str(hgt), str(sdf_dir))
    assert out == str(poison)
    assert poison.read_text() == good                       # healed
    assert dc.sdf_valid(out)


def test_convert_hgt_to_sfd_missing_output_raises(tmp_path):
    fake = tmp_path / "noop.sh"
    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    hgt = tmp_path / "N00E000.hgt"
    hgt.write_bytes(b"\x00\x01")
    with pytest.raises(dc.DemResolveError):
        dc.convert_hgt_to_sdf(str(fake), str(hgt), str(tmp_path / "sdf"))
