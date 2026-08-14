from signal_gui import coords


def test_parse_decimal():
    assert coords.parse_decimal("51.849") == 51.849
    assert coords.parse_decimal("-2.2299") == -2.2299


def test_parse_dms_variants():
    assert abs(coords.parse_dms("51 50 56 N") - 51.8489) < 1e-3
    assert abs(coords.parse_dms("51:50:56N") - 51.8489) < 1e-3
    assert abs(coords.parse_dms("2 13 47 W") - (-2.2297)) < 1e-3


def test_mgrs_roundtrip():
    # A MGRS reference in UTM zone 30U (western Europe / British Isles area)
    lat, lon = coords.mgrs_to_latlon("30UWB9345214601")
    assert isinstance(lat, float) and isinstance(lon, float)
    assert 45.0 < lat < 56.0
    assert -7.0 < lon < 3.0
