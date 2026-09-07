import pytest
from PySide6.QtWidgets import QApplication

from signal_gui.widgets import ParameterForm


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(["test", "-platform", "offscreen"])
    return app


def test_engine_initial_terrain_lock(qapp):
    form = ParameterForm()
    
    # Standard engine is default
    assert form.engine.currentText() == "Standard"
    assert form.terrain.currentText() == "SDF (terrain)"
    assert not form.terrain.isEnabled()
    assert not form.sdf_btn.isHidden()
    assert not form.sdf_path.isHidden()
    assert form.lidar_btn.isHidden()
    assert form.lidar_path.isHidden()

    data = form.collect()
    assert data["engine"] == "Standard"
    assert data["terrain_source"] == "sdf"


def test_engine_switch_to_lidar_and_back(qapp):
    form = ParameterForm()

    # Switch to LIDAR
    form.engine.setCurrentText("LIDAR")
    assert form.terrain.currentText() == "LIDAR (.asc)"
    assert not form.terrain.isEnabled()
    assert form.sdf_btn.isHidden()
    assert form.sdf_path.isHidden()
    assert not form.lidar_btn.isHidden()
    assert not form.lidar_path.isHidden()

    data = form.collect()
    assert data["engine"] == "LIDAR"
    assert data["terrain_source"] == "lidar"

    # Switch to HD
    form.engine.setCurrentText("HD")
    assert form.terrain.currentText() == "SDF (terrain)"
    assert not form.terrain.isEnabled()
    assert not form.sdf_btn.isHidden()
    assert not form.sdf_path.isHidden()
    assert form.lidar_btn.isHidden()
    assert form.lidar_path.isHidden()

    data_hd = form.collect()
    assert data_hd["engine"] == "HD"
    assert data_hd["terrain_source"] == "sdf"


def test_engine_load_locking(qapp):
    form = ParameterForm()

    # Load config with LIDAR engine
    form.load({"engine": "LIDAR"})
    assert form.engine.currentText() == "LIDAR"
    assert form.terrain.currentText() == "LIDAR (.asc)"
    assert not form.terrain.isEnabled()
    assert form.sdf_btn.isHidden()
    assert not form.lidar_btn.isHidden()

    # Load config with Standard engine
    form.load({"engine": "Standard"})
    assert form.engine.currentText() == "Standard"
    assert form.terrain.currentText() == "SDF (terrain)"
    assert not form.terrain.isEnabled()
    assert not form.sdf_btn.isHidden()
    assert form.lidar_btn.isHidden()
