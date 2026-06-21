import os
import sys

from cisprobeplace.models import PinRecord


def test_main_window_uses_cis_title_side_angles_and_tutorial_menu():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QDialog, QTextEdit

    from cisprobeplace.gui import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()

    assert window.windowTitle() == "CIS Probe Placement Scriptor v0.1.0"
    assert window.right_rotation_spin.value() == 0.0
    assert window.top_rotation_spin.value() == 270.0
    assert window.left_rotation_spin.value() == 180.0
    assert window.bottom_rotation_spin.value() == 90.0
    assert [window.selected_table.horizontalHeaderItem(index).text() for index in range(5)] == [
        "X",
        "Y",
        "NET_NAME",
        "SOURCE_GROUP",
        "SIDE",
    ]

    tutorial_actions = [
        action
        for action in window.menuBar().actions()
        if action.menu() is not None and action.menu().title() == "Tutorial"
    ]
    assert tutorial_actions

    window.show_tutorial()
    dialogs = [dialog for dialog in window.findChildren(QDialog) if dialog.windowTitle() == "CIS Probe Placement Tutorial"]
    assert dialogs
    tutorial_text = dialogs[-1].findChild(QTextEdit, "tutorial_text").toPlainText()
    assert "X\uc88c\ud45c,Y\uc88c\ud45c,Net Name,Source_probe name" in tutorial_text
    assert "Source_probe name" in tutorial_text
    assert "Source_Group" in tutorial_text
    assert "LongProbe" in tutorial_text
    assert "CISRotAng_Right" in tutorial_text
    assert "\uc790\ub3d9 \uc88c\ud45c \uc911\uc2ec \ubcf4\uc815" in tutorial_text
    assert "bounding box \uc911\uc2ec" in tutorial_text
    dialogs[-1].close()
    window.close()
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

