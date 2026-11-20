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


def _contrast(first, second):
    """WCAG contrast ratio of two colours."""
    def luminance(color):
        channels = []
        for value in (color.redF(), color.greenF(), color.blueF()):
            channels.append(value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4)
        return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]

    lighter, darker = sorted((luminance(first), luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _frame_contrast(image, rect):
    """Best contrast between the left frame of an indicator and what lies just outside it."""
    row = rect.center().y()
    outside = image.pixelColor(rect.left() - 3, row)
    return max(_contrast(image.pixelColor(rect.left() + offset, row), outside) for offset in range(3))


def _lightest(image, rect):
    return max(image.pixelColor(x, y).lightnessF()
               for x in range(rect.left(), rect.right() + 1) for y in range(rect.top(), rect.bottom() + 1))


@pytest.fixture
def themed_window():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    import cisprobeplace.gui as gui

    app = QApplication.instance() or QApplication([])
    window = gui.MainWindow()
    window.show_sample_state()
    window.resize(1180, 840)
    window.show()
    app.processEvents()
    yield app, window
    window.close()
    app.processEvents()


def test_check_boxes_show_their_frame_and_tick_on_the_dark_theme(themed_window):
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QStyle, QStyleOptionButton

    from cisprobeplace.theme import CHECK_MARK

    app, window = themed_window
    assert CHECK_MARK.is_file()
    for tab, check in ((0, window.picked_only_check), (1, window.replace_input_groups_check),
                       (1, window.automatic_probe_groups_check)):
        window.control_tabs.setCurrentIndex(tab)
        option = QStyleOptionButton()
        check.initStyleOption(option)
        indicator = check.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, option, check)
        indicator = QRect(check.mapTo(window, indicator.topLeft()), indicator.size())

        check.setChecked(False)
        app.processEvents()
        unchecked = window.grab().toImage()
        # A state that is told apart by the frame alone needs 3:1 (WCAG 2.1, 1.4.11).
        assert _frame_contrast(unchecked, indicator) >= 3.0, check.text()
        assert _lightest(unchecked, indicator.adjusted(3, 3, -3, -3)) < 0.5, check.text()

        check.setChecked(True)
        app.processEvents()
        checked = window.grab().toImage()
        assert _frame_contrast(checked, indicator) >= 3.0, check.text()
        # The white tick comes from the bundled picture.
        assert _lightest(checked, indicator.adjusted(3, 3, -3, -3)) > 0.9, check.text()


def test_net_list_shows_unchecked_boxes_and_still_toggles_on_a_click(themed_window):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QStyle, QStyleOptionViewItem

    app, window = themed_window
    net_list = window.net_list
    item = net_list.item(0)
    net_name = item.data(Qt.ItemDataRole.UserRole)
    option = QStyleOptionViewItem()
    option.initFrom(net_list)
    option.rect = net_list.visualItemRect(item)
    option.features |= QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
    indicator = net_list.style().subElementRect(QStyle.SubElement.SE_ItemViewItemCheckIndicator, option, net_list)

    assert item.checkState() == Qt.CheckState.Checked
    assert _lightest(net_list.viewport().grab().toImage(), indicator.adjusted(3, 3, -3, -3)) > 0.9

    QTest.mouseClick(net_list.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, indicator.center())
    app.processEvents()
    assert item.checkState() == Qt.CheckState.Unchecked
    assert window._net_check_states[net_name] is False
    unchecked = net_list.viewport().grab().toImage()
    assert _frame_contrast(unchecked, indicator) >= 3.0
    assert _lightest(unchecked, indicator.adjusted(3, 3, -3, -3)) < 0.5

    QTest.mouseClick(net_list.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, indicator.center())
    app.processEvents()
    assert item.checkState() == Qt.CheckState.Checked
    assert window._net_check_states[net_name] is True


def test_start_up_check_reports_a_missing_theme_picture(monkeypatch, tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    import cisprobeplace.gui as gui
    import cisprobeplace.theme as theme

    QApplication.instance() or QApplication([])
    assert gui.run_smoke_check() == 0

    monkeypatch.setattr(theme, "ASSETS", tmp_path)
    monkeypatch.setattr(gui.sys, "stderr", None)
    log = tmp_path / "start-up.log"
    monkeypatch.setenv("CIS_PROBE_SMOKE_LOG", str(log))
    assert gui.run_smoke_check() == 1
    assert "missing theme picture: check.png" in log.read_text(encoding="utf-8")

    monkeypatch.undo()
    assert gui.run_smoke_check() == 0
