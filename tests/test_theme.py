import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")


def test_theme_icon_and_light_help_page():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QApplication, QWidget

    from cisprobeplace.help_viewer import HelpDialog
    from cisprobeplace.theme import APP_ICON, apply_theme

    app = QApplication.instance() or QApplication([])
    window = QWidget()
    apply_theme(window)
    assert app.style().objectName().lower() == "fusion"
    assert window.palette().color(QPalette.ColorRole.Window).name() == "#202226"
    assert not window.windowIcon().isNull()
    for size in (16, 32, 48, 256):
        pixmap = window.windowIcon().pixmap(size, size)
        assert (pixmap.width(), pixmap.height()) == (size, size)
        assert pixmap.toImage().pixelColor(0, 0).alpha() == 0

    dialog = HelpDialog()
    dialog.ensurePolished()
    page_palette = dialog.browser.viewport().palette()
    assert page_palette.color(QPalette.ColorRole.Base).name() == "#ffffff"
    assert page_palette.color(QPalette.ColorRole.Text).name() == "#1f2937"
    assert not dialog.windowIcon().isNull()
    dialog.close()
    window.close()

    root = Path(__file__).resolve().parents[1]
    assert APP_ICON == root / "cisprobeplace" / "assets" / "app.ico"
    spec = (root / "CISProbePlacementScriptor.spec").read_text(encoding="utf-8")
    assert "('cisprobeplace/assets', 'cisprobeplace/assets')" in spec
    assert "icon='cisprobeplace/assets/app.ico'" in spec
    installer = (root / "CISProbePlacementScriptor.iss").read_text(encoding="utf-8")
    assert r"SetupIconFile=cisprobeplace\assets\app.ico" in installer
    assert r"UninstallDisplayIcon={app}\CISProbePlacementScriptor.exe" in installer
