import os
import sys

from cisprobeplace import __version__
from cisprobeplace.models import PinRecord


def test_main_window_uses_cis_title_side_angles_and_help_menu():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMenu

    from cisprobeplace.gui import MainWindow
    from cisprobeplace.help_viewer import HELP_WINDOW_TITLE, HelpDialog

    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()

    assert window.windowTitle() == f"CIS Probe Placement Scriptor v{__version__}"
    assert window.right_rotation_spin.value() == 0.0
    assert window.top_rotation_spin.value() == 90.0
    assert window.left_rotation_spin.value() == 180.0
    assert window.bottom_rotation_spin.value() == 270.0
    assert [window.selected_table.horizontalHeaderItem(index).text() for index in range(5)] == [
        "X",
        "Y",
        "NET_NAME",
        "SOURCE_GROUP",
        "SIDE",
    ]

    help_menus = [menu for menu in window.menuBar().findChildren(QMenu) if menu.title() == "Help"]
    assert help_menus
    assert [action.text() for action in help_menus[0].actions()] == ["How to Use"]

    help_menus[0].actions()[0].trigger()
    dialog = window._help_dialog
    assert isinstance(dialog, HelpDialog)
    assert dialog.windowTitle() == HELP_WINDOW_TITLE
    assert dialog.isVisible()
    # The help is its own window, so the main window can be brought in front of it.
    assert dialog.parent() is None
    help_text = dialog.browser.toPlainText()
    assert "X\uc88c\ud45c,Y\uc88c\ud45c,Net Name,Source_probe name" in help_text
    assert "Source_Group" in help_text
    assert "LongProbe" in help_text
    assert "CISRotAng_Right" in help_text
    assert "\uc790\ub3d9 \uc88c\ud45c \uc911\uc2ec \ubcf4\uc815" in help_text
    assert "bounding box" in help_text

    # Asking again reuses the open window instead of opening a second one.
    window.show_help()
    assert window._help_dialog is dialog

    # Closing the main window takes the help with it.
    window.close()
    assert not dialog.isVisible()
    app.quit()


def test_selected_table_displays_side_and_source_group():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from cisprobeplace.gui import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    window.selected_pins = [
        PinRecord("U", "R", "SYM", "CIS_LONG", "PAD", 10.0, 5.0, "NR"),
        PinRecord("U", "T", "SYM", "CIS_SHORT", "PAD", 5.0, 10.0, "NT"),
        PinRecord("U", "L", "SYM", "CIS_SHORT", "PAD", 0.0, 5.0, "NL"),
    ]

    window._refresh_table()

    assert [window.selected_table.item(row, 4).text() for row in range(3)] == ["right", "top", "left"]
    assert [window.selected_table.item(row, 3).text() for row in range(3)] == [
        "Source_CIS_LONG",
        "Source_CIS_SHORT",
        "Source_CIS_SHORT",
    ]
    window.close()
    app.quit()

def test_selected_table_displays_coordinate_source_group_and_side_with_override():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QItemSelectionModel
    from PySide6.QtWidgets import QApplication

    from cisprobeplace.gui import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    window.selected_pins = [
        PinRecord("", "1", "", "", "", 10.0, 5.0, "NR", "LongProbe"),
        PinRecord("", "2", "", "", "", 5.0, 10.0, "NT", "ShortProbe"),
        PinRecord("", "3", "", "", "", 0.0, 5.0, "NL", ""),
    ]

    window._refresh_table()

    assert [window.selected_table.item(0, column).text() for column in range(5)] == [
        "10",
        "5",
        "NR",
        "LongProbe",
        "right",
    ]
    assert window.selected_table.item(2, 3).text() == "Source_Group"

    selection_model = window.selected_table.selectionModel()
    selection_model.select(
        window.selected_table.model().index(0, 0),
        QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
    )
    window.source_group_edit.setText("OverrideProbe")
    window.apply_source_group_to_selected_rows()

    assert window.selected_table.item(0, 3).text() == "OverrideProbe"
    assert window.selected_pins[0].source_probe_name == "LongProbe"
    assert window._effective_pins()[0].source_probe_name == "OverrideProbe"
    window.close()
    app.quit()

