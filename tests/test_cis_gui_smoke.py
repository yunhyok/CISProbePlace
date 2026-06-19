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
    assert [window.selected_table.horizontalHeaderItem(index).text() for index in range(7)] == [
        "PIN_NUMBER",
        "NET_NAME",
        "COMP_DEVICE",
        "PIN_X",
        "PIN_Y",
        "SIDE",
        "SOURCE_GROUP",
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
    assert "REFDES,PIN_NUMBER,SYM_NAME,COMP_DEVICE,PAD_STACK_NAME,PIN_X,PIN_Y,NET_NAME" in tutorial_text
    assert "PIX_X" in tutorial_text
    assert "Source_<COMP_DEVICE>" in tutorial_text
    assert "CISRotAng_Right" in tutorial_text
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

    assert [window.selected_table.item(row, 5).text() for row in range(3)] == ["right", "top", "left"]
    assert [window.selected_table.item(row, 6).text() for row in range(3)] == [
        "Source_CIS_LONG",
        "Source_CIS_SHORT",
        "Source_CIS_SHORT",
    ]
    window.close()
    app.quit()


