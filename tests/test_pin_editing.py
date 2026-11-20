import os
import time
from dataclasses import replace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import cisprobeplace.gui as gui
from cisprobeplace.models import PinRecord


@pytest.fixture
def window():
    app = QApplication.instance() or QApplication([])
    widget = gui.MainWindow()
    yield app, widget
    widget.close()


def settle(app, window):
    deadline = time.monotonic() + 5
    while window._load_worker or window._selection_worker or window._selection_timer.isActive() or window._worker:
        assert time.monotonic() < deadline
        app.processEvents()
        QTest.qWait(5)


def pin(number, x, y, group="LongProbe"):
    return PinRecord("DUT", number, "", "", "", x, y, f"N{number}", group)


def load_ring(app, window):
    pins = [pin("R", 10, 0), pin("T", 0, 10), pin("L", -10, 0), pin("B", 0, -10)]
    window._on_inputs_loaded(pins)
    settle(app, window)
    return pins


def test_map_table_batch_edits_survive_sort_and_group_refresh(window):
    app, widget = window
    pins = load_ring(app, widget)
    widget.plot.pinsPicked.emit([pins[0], pins[2]], False)
    assert {index.row() for index in widget.selected_table.selectionModel().selectedRows()} == {0, 2}
    widget._sort_selected_table_by_column(0)
    assert {id(pin) for pin in widget.plot._highlighted_pins} == {id(pins[0]), id(pins[2])}
    widget.source_group_edit.setText("ShortProbe")
    widget.apply_source_selected_button.click()
    assert {widget._effective_source_group_for_pin(pin) for pin in widget._picked_pins()} == {"ShortProbe"}
    widget.side_combo.setCurrentText("bottom")
    widget.apply_side_button.click()
    assert {widget.plot._style_for_pin(pin)[1] for pin in widget._picked_pins()} == {"bottom"}
    assert len(widget.selected_table.selectionModel().selectedRows()) == 2
    widget._set_source_group_color("ShortProbe", "#ff8040")
    for row, record in enumerate(widget._visible_pins):
        if id(record) in widget._picked_ids:
            assert widget.selected_table.item(row, 3).data(Qt.ItemDataRole.DecorationRole).name() == "#ff8040"
            assert widget.plot._style_for_pin(record)[0] == "#ff8040"
            assert f"Pin {record.pin_number}" in widget.selected_table.item(row, 3).toolTip()

    # Table Ctrl-selection is reflected in the map, then map Ctrl toggles it off.
    selection_model = widget.selected_table.selectionModel()
    target = next(row for row, record in enumerate(widget._visible_pins) if record is pins[1])
    selection_model.select(widget.selected_table.model().index(target, 0),
                           QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
    assert id(pins[1]) in widget._picked_ids
    widget.plot.pinsPicked.emit([pins[1]], True)
    assert id(pins[1]) not in widget._picked_ids
    assert "Picked: 2 / Filtered: 4" == widget.picked_count_label.text()


def test_auto_side_stays_fixed_after_filter_and_matches_generated_script(window, monkeypatch, tmp_path):
    app, widget = window
    pins = load_ring(app, widget)
    top = pins[1]
    widget.plot.pinsPicked.emit([top, pins[2]], False)
    widget._net_check_states = {record.net_name: record is top for record in pins}
    widget.update_selection()
    settle(app, widget)
    assert widget._picked_pins() == [top]
    assert widget.selected_table.item(0, 4).text() == "top"
    assert widget.plot._style_for_pin(top)[1] == "top"
    widget.side_combo.setCurrentText("left")
    widget.apply_side_button.click()
    assert widget.selected_table.item(0, 4).text() == "left"
    widget.source_group_edit.setText("ManualProbe")
    widget.apply_source_selected_button.click()
    widget.picked_only_check.setChecked(True)
    output = tmp_path / "picked.py"
    monkeypatch.setattr(gui.QFileDialog, "getSaveFileName", lambda *args: (str(output), ""))
    widget.generate_script()
    settle(app, widget)
    script = output.read_text(encoding="utf-8")
    assert '"T", "NT", 0, 10, "left", "ManualProbe", "CISRotAng_Left"' in script
    widget.side_combo.setCurrentText("Auto")
    widget.apply_side_button.click()
    assert widget.selected_table.item(0, 4).text() == "top"
    assert widget.plot._style_for_pin(top)[1] == "top"
    widget.generate_script()
    settle(app, widget)
    assert '"T", "NT", 0, 10, "top", "ManualProbe", "CISRotAng_Top"' in output.read_text(encoding="utf-8")
    assert top.source_probe_name == "LongProbe"


def test_picked_export_opt_in_and_empty_guard(window, monkeypatch, tmp_path):
    app, widget = window
    pins = load_ring(app, widget)
    assert not widget.picked_only_check.isChecked()
    widget.plot.pinsPicked.emit([pins[0]], False)
    assert len(widget._effective_pins()) == 4
    widget.picked_only_check.setChecked(True)
    assert len(widget._effective_pins()) == 1
    widget.plot.pinsPicked.emit([], False)
    warnings = []
    monkeypatch.setattr(gui.QMessageBox, "warning", lambda *args: warnings.append(args[-1]))
    monkeypatch.setattr(gui.QFileDialog, "getSaveFileName", lambda *args: pytest.fail("Empty picked export opened save dialog"))
    widget.generate_script()
    assert "Pick at least one pin" in warnings[0]
    assert widget._worker is None


def test_map_pin_beyond_table_limit_remains_editable_and_resets_on_new_input(window):
    app, widget = window
    pins = [pin(str(index), index, 0) for index in range(widget.MAX_TABLE_ROWS + 1)]
    widget._on_inputs_loaded(pins)
    settle(app, widget)
    last = pins[-1]
    assert last not in widget._visible_pins
    widget.plot.pinsPicked.emit([last], False)
    assert widget._picked_pins() == [last]
    assert last in widget._visible_pins
    assert len(widget.selected_table.selectionModel().selectedRows()) == 1
    widget.source_group_edit.setText("LastProbe")
    widget.apply_source_selected_button.click()
    widget.side_combo.setCurrentText("bottom")
    widget.apply_side_button.click()
    assert widget._effective_source_group_for_pin(last) == "LastProbe"
    assert widget.plot._style_for_pin(last)[1] == "bottom"
    widget._sort_selected_table_by_column(0)
    widget._sort_selected_table_by_column(0)
    assert widget._visible_pins[0] is last
    assert [index.row() for index in widget.selected_table.selectionModel().selectedRows()] == [0]
    widget._on_inputs_loaded([pin("new", 1, 1)])
    settle(app, widget)
    assert not widget._picked_ids and not widget._side_overrides and not widget._source_group_overrides


def test_map_click_and_ctrl_click_select_table_rows(window):
    app, widget = window
    pins = load_ring(app, widget)
    widget.resize(1200, 750)
    widget.show()
    app.processEvents()
    for record, modifiers in [(pins[0], Qt.KeyboardModifier.NoModifier),
                              (pins[1], Qt.KeyboardModifier.ControlModifier)]:
        point = widget.plot.data_to_widget_point(record.pin_x, record.pin_y).toPoint()
        QTest.mouseClick(widget.plot, Qt.MouseButton.LeftButton, modifiers, point)
    assert widget._picked_pins() == pins[:2]
    assert len(widget.selected_table.selectionModel().selectedRows()) == 2


def test_plain_table_pick_replaces_hidden_map_picks(window):
    app, widget = window
    pins = [pin(str(index), index, 0) for index in range(widget.MAX_TABLE_ROWS + 2)]
    widget._on_inputs_loaded(pins)
    settle(app, widget)
    widget.plot.pinsPicked.emit([pins[0], pins[-1]], False)
    assert len(widget._picked_pins()) == 2
    widget.show()
    app.processEvents()
    cell = widget.selected_table.visualRect(widget.selected_table.model().index(1, 0)).center()
    QTest.mouseClick(widget.selected_table.viewport(), Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier, cell)
    assert widget._picked_pins() == [widget._visible_pins[1]]


def staggered_bond_rows():
    pins = []
    for side in ("right", "top", "left", "bottom"):
        for lane, normal, tangents in (("outer", 12, (-6, -2, 2, 6)), ("inner", 10, (-5, -1, 3, 7))):
            for index, tangent in enumerate(tangents):
                signed_normal = -normal if side in ("left", "bottom") else normal
                x, y = (signed_normal, tangent) if side in ("left", "right") else (tangent, signed_normal)
                pins.append(pin(f"{side}_{lane}_{index}", x, y, ""))
    return pins


def test_two_bond_rows_infer_groups_on_load_and_keep_filter_export_consistent(window, monkeypatch, tmp_path):
    app, widget = window
    pins = staggered_bond_rows()
    input_path = tmp_path / "bond_rows.csv"
    input_path.write_text("REFDES,PIN_NUMBER,SYM_NAME,COMP_DEVICE,PAD_STACK_NAME,PIN_X,PIN_Y,NET_NAME\n" +
                          "\n".join(f"DUT,{record.pin_number},,,,{record.pin_x},{record.pin_y},{record.net_name}" for record in pins),
                          encoding="utf-8")
    widget.pin_path_edit.setText(str(input_path))
    widget.load_inputs()
    settle(app, widget)
    pins = widget.all_pins
    assert widget._automatic_probe_groups and widget._tips_toward_center
    assert "Long 16 / Short 16 / Undetermined 0" in widget.probe_type_count_label.text()
    assert "Geometry probe estimate: Long 16 / Short 16 / Undetermined 0" in widget.log_edit.toPlainText()
    for row, record in enumerate(pins):
        kind = "Long" if "outer" in record.pin_number else "Short"
        side = record.pin_number.split("_")[0]
        assert widget._predicted_probe_type(record) == kind
        assert widget.selected_table.item(row, 3).text() == f"{kind}Probe"
        assert widget.selected_table.item(row, 4).text() == side
        assert f"Predicted probe: {kind}" in widget.selected_table.item(row, 3).toolTip()
        assert widget.plot._style_for_pin(record)[1] == side
        assert widget.plot._groups_by_id[id(record)] == f"{kind}Probe"
    inner = next(record for record in pins if record.pin_number == "top_inner_0")
    widget._net_check_states = {record.net_name: record is inner for record in pins}
    widget.update_selection()
    settle(app, widget)
    assert widget._predicted_probe_type(inner) == "Short"
    assert widget.selected_table.item(0, 4).text() == "top"
    assert "Long 0 / Short 1 / Undetermined 0" in widget.probe_type_count_label.text()
    output = tmp_path / "inferred.py"
    monkeypatch.setattr(gui.QFileDialog, "getSaveFileName", lambda *args: (str(output), ""))
    widget.generate_script()
    settle(app, widget)
    assert '"top_inner_0", "Ntop_inner_0", -5, 10, "top", "ShortProbe", "CISRotAng_Top"' in output.read_text(encoding="utf-8")
    assert all(not record.source_probe_name for record in pins)


def test_probe_polarity_names_and_side_override_are_independent(window, monkeypatch, tmp_path):
    app, widget = window
    pins = staggered_bond_rows()
    widget._on_inputs_loaded(pins)
    settle(app, widget)
    outer, inner = pins[0], pins[4]
    widget.long_probe_group_edit.setText("RealLongGroup")
    widget.long_probe_group_edit.editingFinished.emit()
    widget.short_probe_group_edit.setText("RealShortGroup")
    widget.short_probe_group_edit.editingFinished.emit()
    long_color = widget.plot._style_for_pin(outer)[0]
    short_color = widget.plot._style_for_pin(inner)[0]
    assert long_color != short_color
    assert widget.plot._tips_toward_center
    widget.tip_orientation_combo.setCurrentText("Toward outside")
    assert not widget.plot._tips_toward_center
    assert widget.plot._style_for_pin(outer)[0] == short_color
    assert widget.plot._style_for_pin(inner)[0] == long_color
    assert widget.selected_table.item(0, 3).data(Qt.ItemDataRole.DecorationRole).name() == short_color
    assert widget.plot._style_for_pin(outer)[1] == "right"
    assert widget.selected_table.item(0, 4).text() == "right"
    assert widget._predicted_probe_type(outer) == "Short"
    assert widget._predicted_probe_type(inner) == "Long"
    assert widget._effective_source_group_for_pin(outer) == "RealShortGroup"
    widget.plot.pinsPicked.emit([outer], False)
    widget.side_combo.setCurrentText("top")
    widget.apply_side_button.click()
    assert widget._predicted_probe_type(outer) == "Undetermined"
    assert widget._effective_source_group_for_pin(outer) == "Source_Group"
    widget.source_group_edit.setText("ManualGroup")
    widget.apply_source_selected_button.click()
    assert widget._effective_source_group_for_pin(outer) == "ManualGroup"
    widget.side_combo.setCurrentText("Auto")
    widget.apply_side_button.click()
    assert widget._predicted_probe_type(outer) == "Short"
    assert widget._effective_source_group_for_pin(outer) == "ManualGroup"
    widget.plot.pinsPicked.emit([inner], False)
    widget.picked_only_check.setChecked(True)
    output = tmp_path / "reversed.py"
    monkeypatch.setattr(gui.QFileDialog, "getSaveFileName", lambda *args: (str(output), ""))
    widget.generate_script()
    settle(app, widget)
    assert '"right_inner_0", "Nright_inner_0", 10, -5, "right", "RealLongGroup", "CISRotAng_Right"' in output.read_text(encoding="utf-8")


def test_manual_and_named_input_groups_take_precedence_over_geometry(window):
    app, widget = window
    pins = staggered_bond_rows()
    pins[0] = replace(pins[0], source_probe_name="InputProbe")
    pins[1] = replace(pins[1], comp_device="CIS_LONG")
    widget._on_inputs_loaded(pins)
    settle(app, widget)
    assert widget._predicted_probe_type(pins[0]) == "Long"
    assert widget._effective_source_group_for_pin(pins[0]) == "InputProbe"
    assert widget._effective_source_group_for_pin(pins[1]) == "Source_CIS_LONG"
    assert widget._effective_source_group_for_pin(pins[2]) == "LongProbe"
    widget.plot.pinsPicked.emit([pins[0]], False)
    widget.source_group_edit.setText("ManualProbe")
    widget.apply_source_selected_button.click()
    widget.replace_input_groups_check.setChecked(True)
    assert widget._effective_source_group_for_pin(pins[0]) == "ManualProbe"
    assert widget._effective_source_group_for_pin(pins[1]) == "LongProbe"
    widget.automatic_probe_groups_check.setChecked(False)
    assert widget._effective_source_group_for_pin(pins[0]) == "ManualProbe"
    assert widget._effective_source_group_for_pin(pins[1]) == "Source_CIS_LONG"
    assert widget._effective_source_group_for_pin(pins[2]) == "Source_Group"
    assert widget._predicted_probe_type(pins[2]) == "Long"


def test_uncertain_geometry_keeps_existing_groups_and_invalid_settings_do_not_apply(window, monkeypatch):
    app, widget = window
    pins = load_ring(app, widget)
    assert {widget._predicted_probe_type(record) for record in pins} == {"Undetermined"}
    assert {widget._effective_source_group_for_pin(record) for record in pins} == {"LongProbe"}
    pins = staggered_bond_rows()
    widget._on_inputs_loaded(pins)
    settle(app, widget)
    warnings = []
    monkeypatch.setattr(gui.QMessageBox, "warning", lambda *args: warnings.append(args[-1]))
    widget.long_probe_group_edit.clear()
    widget.apply_probe_inference_button.click()
    assert warnings and "nonblank" in warnings[0]
    assert widget._effective_source_group_for_pin(pins[0]) == "LongProbe"
    widget.tip_orientation_combo.setCurrentText("Toward outside")
    assert widget.tip_orientation_combo.currentText() == "Toward outside"
    assert widget._predicted_probe_type(pins[0]) == "Short"
    assert len(warnings) == 1


def test_spd_site_load_infers_probe_groups_without_input_names(window, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QDialog

    app, widget = window

    pins = staggered_bond_rows()
    nodes = [f"Node{index}!!{record.pin_number}::{record.net_name} X = {record.pin_x}mm Y = {record.pin_y}mm"
             for index, record in enumerate(pins, start=1)]
    connections = [f"{record.pin_number} $Package.Node{index}!!{record.pin_number}::{record.net_name}"
                   for index, record in enumerate(pins, start=1)]
    input_path = tmp_path / "bond_rows.spd"
    input_path.write_text("\n".join([*nodes, ".Connect SITE0 DUT", *connections, ".EndC"]), encoding="utf-8")
    monkeypatch.setattr(gui.SpdSelectionDialog, "exec", lambda dialog: QDialog.DialogCode.Accepted)
    widget.pin_path_edit.setText(str(input_path))
    widget.load_inputs()
    settle(app, widget)
    assert widget._spd_selection == ("DUT", 0)
    assert {widget.selected_table.item(row, 3).text() for row in range(32)} == {"LongProbe", "ShortProbe"}
    assert "Long 16 / Short 16 / Undetermined 0" in widget.probe_type_count_label.text()
