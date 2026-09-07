import os
import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from signal_gui import color_manager
from signal_gui.widgets import ParameterForm


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(["test", "-platform", "offscreen"])
    return app


def test_dcf_save_and_parse(tmp_path):
    dcf_path = str(tmp_path / "test_palette.dcf")
    bands = [
        color_manager.ColorBand(0.0, (255, 0, 0)),
        color_manager.ColorBand(-10.0, (255, 128, 0)),
        color_manager.ColorBand(-20.0, (0, 255, 0)),
    ]
    pal = color_manager.ColorPalette(name="TestPalette", unit="dBm", bands=bands)

    # Save
    saved_path = color_manager.save_palette_to_dcf(pal, dcf_path)
    assert os.path.exists(saved_path)

    # Parse back
    loaded = color_manager.parse_dcf_file(dcf_path)
    assert loaded is not None
    assert loaded.name == "test_palette"
    assert len(loaded.bands) == 3
    assert loaded.bands[0].level == 0.0
    assert loaded.bands[0].rgb == (255, 0, 0)
    assert loaded.bands[1].level == -10.0
    assert loaded.bands[1].rgb == (255, 128, 0)
    assert loaded.bands[2].level == -20.0
    assert loaded.bands[2].rgb == (0, 255, 0)


def test_interpolate_palette_hsl_and_rgb():
    top_c = QColor(255, 0, 0)      # Red (Hue 0)
    bot_c = QColor(0, 0, 255)      # Blue (Hue 240)

    # HSL mode
    bands_hsl = color_manager.interpolate_palette(
        top_val=0.0, steps=5, step_size=10.0, top_color=top_c, bottom_color=bot_c, mode="HSL"
    )
    assert len(bands_hsl) == 5
    assert bands_hsl[0].level == 0.0
    assert bands_hsl[4].level == -40.0
    # Top is reddish, bottom is bluish
    assert bands_hsl[0].rgb[0] > 200
    assert bands_hsl[4].rgb[2] > 200

    # RGB mode
    bands_rgb = color_manager.interpolate_palette(
        top_val=10.0, steps=3, step_size=5.0, top_color=top_c, bottom_color=bot_c, mode="RGB"
    )
    assert len(bands_rgb) == 3
    assert bands_rgb[0].level == 10.0
    assert bands_rgb[1].level == 5.0
    assert bands_rgb[2].level == 0.0
    assert bands_rgb[0].rgb == (255, 0, 0)
    assert bands_rgb[2].rgb == (0, 0, 255)


def test_standard_presets_discovered():
    palettes = color_manager.discover_all_palettes()
    names = [p.name for p in palettes]
    assert "5G" in names
    assert "BASIC" in names
    assert "BSA1" in names
    assert "CUSTOM" in names
    assert "FS" in names


def test_color_manager_dialog(qapp, tmp_path):
    dlg = color_manager.ColorManagerDialog(current_color_file="")
    assert dlg.edit_name.text() != ""
    assert dlg.slider_steps.value() >= 2
    assert dlg.preview_strip.count() if hasattr(dlg.preview_strip, "count") else len(dlg.preview_strip.bands) > 0

    # Test selecting a preset
    p_5g = next((p for p in dlg.all_palettes if p.name == "5G"), None)
    assert p_5g is not None
    dlg._on_palette_selected(p_5g)
    assert dlg.selected_palette.name == "5G"


def test_color_manager_save_and_apply(qapp, tmp_path):
    dlg = color_manager.ColorManagerDialog(current_color_file="")
    dlg.edit_name.setText("Test5GSpecial")
    dlg.spin_top.setValue(10)
    dlg.slider_steps.setValue(4)
    dlg.spin_step_size.setValue(10)
    dlg._on_inputs_changed()

    applied_paths = []
    dlg.palette_applied.connect(applied_paths.append)
    dlg._apply_palette()

    assert len(applied_paths) == 1
    assert os.path.exists(applied_paths[0])
    assert applied_paths[0].endswith(".dcf")


def test_delete_button_present_on_all_cards(qapp):
    dlg = color_manager.ColorManagerDialog(current_color_file="")
    assert len(dlg.card_widgets) > 0
    # Every single card has the delete (trash) button
    for card in dlg.card_widgets:
        assert hasattr(card, "del_btn")
        assert card.del_btn is not None
        assert not card.del_btn.isHidden()

    # Header delete button exists
    assert hasattr(dlg, "btn_delete_selected")
    assert dlg.btn_delete_selected is not None


def test_delete_and_restore_palette(qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    dlg = color_manager.ColorManagerDialog(current_color_file="")
    orig_count = len(dlg.all_palettes)
    target = dlg.all_palettes[0]

    # Mock QMessageBox.question to return Yes
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)

    # Delete target palette
    dlg._on_palette_deleted(target)
    assert len(dlg.all_palettes) == orig_count - 1
    assert target.name not in [p.name for p in dlg.all_palettes]

    # Restore presets
    dlg._restore_presets()
    assert len(dlg.all_palettes) == orig_count
    assert target.name in [p.name for p in dlg.all_palettes]


def test_widgets_color_integration(qapp):
    form = ParameterForm()

    # Verify combo exists and has items
    assert hasattr(form, "color_combo")
    assert form.color_combo.count() > 0
    assert form.color_btn is not None
    assert form.color_path is not None

    # Test setting color file
    p = os.path.abspath("gui/data/5color.dcf")
    form.set_color_file(p)
    assert form.color_path.text() == p

    data = form.collect()
    assert data["color_file"] == p

    # Test load
    form.load({"color_file": p})
    assert form.color_path.text() == p




