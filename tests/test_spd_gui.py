import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QThread
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

import cisprobeplace.gui as gui
from cisprobeplace.models import PinRecord


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def settle(app, window):
    deadline = time.monotonic() + 5
    while window._load_worker or window._selection_worker or window._selection_timer.isActive():
        assert time.monotonic() < deadline, "GUI workers did not finish"
        app.processEvents()
        QTest.qWait(5)


def pin(name="N1", x=0.0):
    return PinRecord("U1", "1", "", "", "", x, 0.0, name)


class SpdData:
    components = ["R1", "U1", "DUT2"]

    def sites(self, component):
        return {"R1": [None], "U1": [4, 7, None], "DUT2": list(range(256)) + [None]}[component]

    def pins(self, component, site):
        return [pin(f"{component}_{site}", -1.0), pin("GROUND", 1.0)]


def test_spd_choice_uses_available_components_and_numeric_sites(app):
    dialog = gui.SpdSelectionDialog(SpdData())
    assert dialog.selection() == ("DUT2", 0)
    assert dialog.site_combo.count() == 257
    dialog.site_combo.setCurrentIndex(200)
    assert dialog.selection() == ("DUT2", 200)
    dialog.component_combo.setCurrentText("U1")
    assert dialog.selection() == ("U1", 4)
    dialog.component_combo.setCurrentText("R1")
    assert dialog.selection() == ("R1", None)
    dialog.close()


@pytest.mark.parametrize("sites, expected", [([1, 5, None], 1), ([3, 8, None], 3), ([None], None)])
def test_spd_site_default_fallbacks_without_dut_name(app, sites, expected):
    data = SpdData()
    data.components = ["U7"]
    data.sites = lambda _: sites
    dialog = gui.SpdSelectionDialog(data)
    assert dialog.selection() == ("U7", expected)
    dialog.close()


def test_spd_load_parses_on_worker_and_plots_selected_site(app, monkeypatch, tmp_path):
    import cisprobeplace.spd as spd

    parse_threads = []

    def read_spd(path):
        parse_threads.append(QThread.currentThread())
        return SpdData()

    monkeypatch.setattr(spd, "read_spd", read_spd)
    monkeypatch.setattr(gui.SpdSelectionDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    window = gui.MainWindow()
    window.pin_path_edit.setText(str(tmp_path / "board.SPD"))
    window.load_inputs()
    settle(app, window)

    assert parse_threads and parse_threads[0] != app.thread()
    assert [record.net_name for record in window.selected_pins] == ["DUT2_0", "GROUND"]
    assert not window.plot.isHidden()
    assert window.plot._all_pins == window.all_pins
    window.selected_table.selectRow(0)
    assert window.plot._highlighted_pins == [window.all_pins[0]]
    assert "257 sites for DUT2; site=0" in window.log_edit.toPlainText()

    window._on_inputs_loaded([pin("CSV")])
    settle(app, window)
    assert not window.plot.isHidden()
    assert [record.net_name for record in window.plot._all_pins] == ["CSV"]
    window.close()


@pytest.mark.parametrize("outcome", ["cancel", "failure"])
def test_replacing_input_preserves_old_data_on_cancel_or_failure(app, monkeypatch, tmp_path, outcome):
    import cisprobeplace.spd as spd

    def read_spd(path):
        if outcome == "failure":
            raise ValueError("broken SPD")
        return SpdData()

    monkeypatch.setattr(spd, "read_spd", read_spd)
    monkeypatch.setattr(gui.SpdSelectionDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
    monkeypatch.setattr(gui.QMessageBox, "critical", lambda *args: None)
    window = gui.MainWindow()
    window.pin_path_edit.setText("original.csv")
    window._on_inputs_loaded([pin("OLD")])
    settle(app, window)
    window._source_group_overrides[id(window.all_pins[0])] = "OldProbe"
    window.pin_path_edit.setText(str(tmp_path / "replacement.spd"))
    window.load_inputs()
    settle(app, window)

    assert [record.net_name for record in window.all_pins] == ["OLD"]
    assert window.selected_pins == window.all_pins == window._visible_pins
    assert window.selected_table.rowCount() == 1
    assert window._source_group_overrides == {id(window.all_pins[0]): "OldProbe"}
    assert window.plot._all_pins == window.all_pins
    assert window.pin_path_edit.text() == "original.csv"
    assert window.load_button.isEnabled()
    window.close()


def test_selection_from_replaced_dataset_is_discarded(app, monkeypatch, tmp_path):
    import cisprobeplace.spd as spd

    old_pins = [pin("OLD")]
    original_filter = gui.filter_pins

    def slow_old_filter(pins, **kwargs):
        if pins is old_pins:
            time.sleep(0.1)
        return original_filter(pins, **kwargs)

    monkeypatch.setattr(gui, "filter_pins", slow_old_filter)
    monkeypatch.setattr(spd, "read_spd", lambda path: SpdData())
    monkeypatch.setattr(gui.SpdSelectionDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    window = gui.MainWindow()
    window._on_inputs_loaded(old_pins)
    window.pin_path_edit.setText(str(tmp_path / "new.spd"))
    window.load_inputs()
    settle(app, window)

    assert all(record.net_name != "OLD" for record in window.selected_pins)
    assert len(window.selected_pins) == 2
    assert window.plot._all_pins == window.all_pins
    window.close()


def test_coordinate_file_browser_includes_spd(app, monkeypatch):
    filters = []

    def choose(parent, title, directory, file_filter):
        filters.append(file_filter)
        return "board.spd", ""

    monkeypatch.setattr(gui.QFileDialog, "getOpenFileName", choose)
    window = gui.MainWindow()
    window._browse_file(window.pin_path_edit)
    assert "*.spd" in filters[0]
    assert window.pin_path_edit.text() == "board.spd"
    window.close()


def test_real_spd_site_switch_reuses_inventory_and_preserves_unchanged_selection(app, monkeypatch, tmp_path):
    import cisprobeplace.spd as spd

    path = tmp_path / "sites.spd"
    path.write_text("""Node1!!A1::DATA/0 X = 10mm Y = 20mm
Node2!!A2::DGND X = 12mm Y = 24mm
Node3!!B1::DATA/10 X = -10mm Y = -20mm
Node4!!B2::DGND X = -14mm Y = -26mm
.Connect SITE0 DUT
A1 $Package.Node1!!A1::DATA/0
A2 $Package.Node2!!A2::DGND
.EndC
.Connect SITE10 DUT
B1 $Package.Node3!!B1::DATA/10
B2 $Package.Node4!!B2::DGND
.EndC
""", encoding="utf-8")
    parse_calls = []
    real_read = spd.read_spd

    def read_once(source):
        parse_calls.append(source)
        return real_read(source)

    choices = iter([("DUT", 0), ("DUT", 10), ("DUT", 10), None])
    opened = []

    def choose(dialog):
        opened.append(dialog.selection())
        choice = next(choices)
        if choice is None:
            return QDialog.DialogCode.Rejected
        dialog.component_combo.setCurrentText(choice[0])
        dialog.site_combo.setCurrentIndex(dialog.site_combo.findData(choice[1]))
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(spd, "read_spd", read_once)
    monkeypatch.setattr(gui.SpdSelectionDialog, "exec", choose)
    window = gui.MainWindow()
    window.pin_path_edit.setText(str(path))
    window.load_inputs()
    settle(app, window)
    assert window._spd_selection == ("DUT", 0)
    assert window.spd_selection_button.isEnabled()
    assert "Site: 0" in window.spd_selection_label.text()
    first_site_pin = window.all_pins[0]
    window.plot.pinsPicked.emit([first_site_pin], False)
    window.source_group_edit.setText("Site0Probe")
    window.apply_source_selected_button.click()
    window.side_combo.setCurrentText("bottom")
    window.apply_side_button.click()
    assert window.plot._style_for_pin(first_site_pin)[1] == "bottom"
    assert window.selected_table.item(0, 3).text() == "Site0Probe"
    path.unlink()

    window.spd_selection_button.click()
    settle(app, window)
    assert len(parse_calls) == 1
    assert opened == [("DUT", 0), ("DUT", 0)]
    assert window._spd_selection == ("DUT", 10)
    assert "Site: 10" in window.spd_selection_label.text()
    assert [record.refdes for record in window.all_pins] == ["SITE10", "SITE10"]
    assert [(record.pin_x, record.pin_y) for record in window.all_pins] == [(2, 3), (-2, -3)]
    assert [window.selected_table.item(row, 2).text() for row in range(2)] == ["DATA/10", "DGND"]
    assert window.plot._all_pins == window.all_pins
    assert not window._picked_ids and not window._side_overrides and not window._source_group_overrides
    for row, record in enumerate(window.all_pins):
        assert window.plot._style_for_pin(record)[1] == window.selected_table.item(row, 4).text()
        assert window.selected_table.verticalHeaderItem(row).text() == record.pin_number

    window._net_check_states["DGND"] = False
    window._refresh_net_list()
    window.update_selection()
    settle(app, window)
    records = window.all_pins
    window._source_group_overrides[id(records[0])] = "ManualProbe"
    for _ in range(2):
        window.spd_selection_button.click()
        settle(app, window)
        assert window.all_pins is records
        assert window._net_check_states["DGND"] is False
        assert window._source_group_overrides == {id(records[0]): "ManualProbe"}
        assert len(window.selected_pins) == 1
    assert opened[-2:] == [("DUT", 10), ("DUT", 10)]
    assert len(parse_calls) == 1

    window.pin_path_edit.setText(str(tmp_path / "unloaded.spd"))
    assert not window.spd_selection_button.isEnabled()
    window.spd_selection_button.click()
    assert len(opened) == 4
    window.pin_path_edit.setText(str(path))
    assert window.spd_selection_button.isEnabled()

    window._on_inputs_loaded([pin("CSV")])
    settle(app, window)
    assert window._spd_data is None and window._spd_selection is None
    assert window.spd_selection_button.isHidden()
    assert window.spd_selection_label.isHidden()
    window.close()


@pytest.mark.parametrize("outcome", ["cancel", "failure"])
def test_first_load_that_fails_or_is_cancelled_keeps_the_chosen_file(app, monkeypatch, tmp_path, outcome):
    import cisprobeplace.spd as spd

    def read_spd(path):
        if outcome == "failure":
            raise ValueError("broken SPD")
        return SpdData()

    monkeypatch.setattr(spd, "read_spd", read_spd)
    monkeypatch.setattr(gui.SpdSelectionDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
    monkeypatch.setattr(gui.QMessageBox, "critical", lambda *args: None)
    window = gui.MainWindow()
    chosen = str(tmp_path / "first.spd")
    window.pin_path_edit.setText(chosen)
    window.load_inputs()
    settle(app, window)

    # Nothing was loaded before, so there is no earlier file to go back to: the
    # choice stays and Load Inputs can simply be pressed again.
    assert window.pin_path_edit.text() == chosen
    assert window.all_pins == []
    assert window.load_button.isEnabled()
    assert window.spd_selection_button.isHidden()
    last_line = window.log_edit.toPlainText().splitlines()[-1]
    assert last_line == ("SPD selection cancelled." if outcome == "cancel" else "Input error: broken SPD")
    window.close()


def test_spd_sample_state_and_start_up_check_cover_the_spd_reader(app, monkeypatch):
    window = gui.MainWindow()
    window.show_spd_sample_state()

    assert window._spd_selection == ("DUT", 0)
    assert window.spd_selection_label.text() == "SPD component: DUT | Site: 0"
    assert not window.spd_selection_button.isHidden()
    assert not window.plot.isHidden()
    assert window.plot._all_pins == window.all_pins
    assert window.selected_table.rowCount() == len(window.all_pins) > 0
    assert {record.refdes for record in window.all_pins} == {"SITE0"}
    window.close()

    assert gui.run_smoke_check() == 0

    def broken_reader(path):
        raise ImportError("spd reader missing from the build")

    monkeypatch.setattr(gui, "read_spd", broken_reader)
    monkeypatch.setattr(gui.sys, "stderr", None)
    assert gui.run_smoke_check() == 1
