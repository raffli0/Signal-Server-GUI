"""Unit tests for Radio Link KML/KMZ exporter (link_kml.py)."""

import math
import os
import xml.etree.ElementTree as ET
import zipfile
import pytest

from signal_gui import link_kml


@pytest.fixture
def sample_link():
    params = {
        "tx_site_name": "Base",
        "rx_site_name": "Mobile",
        "tx_lat": -6.832817,
        "tx_lon": 107.387299,
        "tx_height": 50.0,
        "rx_lat": -7.144055,
        "rx_lon": 106.541397,
        "rx_height": 1500.0,
        "frequency": 1200.0,
        "tx_power_w": 41.1,
        "tx_antenna_gain": 8.0,
        "rx_antenna_gain": 8.0,
        "rx_threshold_dbm": -119.0,
    }
    link_data = {
        "distance_km": 99.57,
        "azimuth_deg": 249.61,
        "free_space_loss_db": 133.9,
        "computed_loss_db": 141.0,
        "total_loss_db": 141.0,
        "terrain_shielding_db": 0.8,
        "rx_power_dbm": -87.2,
        "fade_margin_db": 31.8,
        "obstructed": False,
        "report_text": "Downtilt angle to Rx: +0.4016 degrees",
        "profile": {
            "distance_km": [0.0, 49.78, 99.57],
            "terrain_m": [434.9, 800.0, 491.0],
            "los_m": [484.9, 1091.84, 1991.0],
        },
    }
    return params, link_data


def test_build_radio_link_kml_xml_structure(sample_link):
    params, link_data = sample_link
    kml_str = link_kml.build_radio_link_kml(params, link_data, num_points=501)

    # Validate XML parsing
    root = ET.fromstring(kml_str)
    # Check namespace
    assert "kml" in root.tag.lower()

    # Find Document
    ns = {"kml": "http://www.opengis.net/kml/2.2"}
    doc = root.find("kml:Document", ns)
    assert doc is not None

    name = doc.find("kml:name", ns).text
    assert "Base - Mobile [Base]" in name

    desc = doc.find("kml:description", ns).text
    assert "Distance between Base and Mobile" in desc
    assert "True North Azimuth = 249.61°" in desc
    assert "Average frequency is 1200.000 MHz" in desc
    assert "Free Space = 133.9 dB" in desc
    assert "Total propagation loss is 141.0 dB" in desc

    # Camera LookAt
    look_at = doc.find("kml:LookAt", ns)
    assert look_at is not None
    assert look_at.find("kml:tilt", ns).text == "80.0"
    heading = float(look_at.find("kml:heading", ns).text)
    # Heading perpendicular to 249.61 is ~ 159.61
    assert heading == pytest.approx(159.61, abs=0.1)

    # Placemarks
    placemarks = doc.findall("kml:Placemark", ns)
    pm_names = [p.find("kml:name", ns).text for p in placemarks]
    assert "Base" in pm_names
    assert "Mobile" in pm_names

    # Folder Radio Link
    folder = doc.find("kml:Folder", ns)
    assert folder is not None
    assert folder.find("kml:name", ns).text == "Radio Link"

    sub_pms = folder.findall("kml:Placemark", ns)
    sub_names = [p.find("kml:name", ns).text for p in sub_pms]
    assert "Beam" in sub_names
    assert "0.6F1" in sub_names
    assert "1.0F1" in sub_names
    assert "1.0F2" in sub_names
    assert "1.0F3" in sub_names


def test_fresnel_loops_and_curvature(sample_link):
    params, link_data = sample_link
    kml_str = link_kml.build_radio_link_kml(params, link_data, num_points=501)
    ns = {"kml": "http://www.opengis.net/kml/2.2"}
    root = ET.fromstring(kml_str)
    folder = root.find(".//kml:Folder", ns)

    beam_pm = [p for p in folder.findall("kml:Placemark", ns) if p.find("kml:name", ns).text == "Beam"][0]
    beam_coords = beam_pm.find(".//kml:coordinates", ns).text.strip().split()
    assert len(beam_coords) == 501
    
    # Check start and end of beam
    # Start: Tx
    lon0, lat0, alt0 = map(float, beam_coords[0].split(","))
    assert lon0 == pytest.approx(107.387299, abs=1e-5)
    assert lat0 == pytest.approx(-6.832817, abs=1e-5)
    assert alt0 == pytest.approx(484.9, abs=0.1)

    # End: Rx
    lon_end, lat_end, alt_end = map(float, beam_coords[-1].split(","))
    assert lon_end == pytest.approx(106.541397, abs=1e-5)
    assert lat_end == pytest.approx(-7.144055, abs=1e-5)
    assert alt_end == pytest.approx(1991.0, abs=0.1)

    # Midpoint of beam must include curvature drop
    lon_mid, lat_mid, alt_mid = map(float, beam_coords[250].split(","))
    assert lon_mid == pytest.approx(106.964489, abs=1e-3)
    assert lat_mid == pytest.approx(-6.988625, abs=1e-3)
    assert alt_mid == pytest.approx(1092.05, abs=1.0)  # Profile1 was 1091.84

    # 1.0F1 is a closed loop: 501 points forward + 501 points backward = 1002 points
    f1_pm = [p for p in folder.findall("kml:Placemark", ns) if p.find("kml:name", ns).text == "1.0F1"][0]
    f1_coords = f1_pm.find(".//kml:coordinates", ns).text.strip().split()
    assert len(f1_coords) == 1002


def test_export_radio_link_kml_file(tmp_path, sample_link):
    params, link_data = sample_link
    out_file = str(tmp_path / "test_export.kml")
    res = link_kml.export_radio_link_kml(out_file, params, link_data, num_points=101)
    assert os.path.exists(res)
    with open(res, "r", encoding="utf-8") as f:
        content = f.read()
    assert "<?xml version=" in content
    assert "<Document>" in content
    assert "</kml>" in content


def test_export_radio_link_kmz_file(tmp_path, sample_link):
    params, link_data = sample_link
    out_file = str(tmp_path / "test_export.kmz")
    res = link_kml.export_radio_link_kmz(out_file, params, link_data, num_points=101)
    assert os.path.exists(res)
    assert zipfile.is_zipfile(res)

    with zipfile.ZipFile(res, "r") as z:
        names = z.namelist()
        assert "doc.kml" in names
        doc_kml = z.read("doc.kml").decode("utf-8")
        assert "<kml" in doc_kml
        assert "Radio Link" in doc_kml
