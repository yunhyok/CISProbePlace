import os
import sys


import pytest

from cisprobeplace.models import PinRecord


def test_main_window_uses_product_title():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from cisprobeplace.gui import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()

    assert window.windowTitle() == "CIS Probe Placement Scriptor v0.1.0"
    assert window.project_edit.text() == "Project1"
    assert window.design_edit.text() == "HFSSDesign1"
    assert not hasattr(window, "object_path_edit")
    assert not hasattr(window, "browse_object_button")
    assert not hasattr(window, "rotation_spin")
    assert window.right_rotation_spin.value() == 0.0
    assert window.top_rotation_spin.value() == 270.0
    assert window.left_rotation_spin.value() == 180.0
    assert window.bottom_rotation_spin.value() == 90.0
    window.close()
    app.quit()


def test_coordinate_plot_emits_bounds_when_right_edge_is_dragged():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from cisprobeplace.gui import CoordinatePlot

    app = QApplication.instance() or QApplication(sys.argv)
    plot = CoordinatePlot()
    plot.resize(420, 320)
    pins = [
        PinRecord("U1", "1", "SYM", "PROBE", "PAD", 0.0, 0.0, "N1"),
        PinRecord("U2", "2", "SYM", "PROBE", "PAD", 10.0, 10.0, "N2"),
    ]
    plot.set_data(pins, pins, (0.0, 10.0, 0.0, 10.0))
    emitted = []
    plot.boundsChanged.connect(lambda x_min, x_max, y_min, y_max: emitted.append((x_min, x_max, y_min, y_max)))
    start = plot.data_to_widget_point(10.0, 5.0).toPoint()
    end = plot.data_to_widget_point(6.0, 5.0).toPoint()

    QTest.mousePress(plot, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    QTest.mouseMove(plot, end)
    QTest.mouseRelease(plot, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)

    assert emitted
    assert emitted[-1][0] == 0.0
    assert emitted[-1][1] == pytest.approx(6.0, abs=0.2)
    assert emitted[-1][2] == 0.0
    assert emitted[-1][3] == 10.0
    plot.close()
    app.quit()


def test_coordinate_plot_samples_large_datasets_for_display():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from cisprobeplace.gui import CoordinatePlot

    app = QApplication.instance() or QApplication(sys.argv)
    plot = CoordinatePlot()
    pins = [
        PinRecord("U", str(index), "SYM", "PROBE", "PAD", float(index % 1000), float(index // 1000), f"N{index}")
        for index in range(50000)
    ]

    plot.set_data(pins, pins, (0.0, 999.0, 0.0, 50.0))

    assert len(plot._display_all_pins) <= plot.MAX_PLOT_POINTS
    assert len(plot._display_selected_pins) <= plot.MAX_PLOT_POINTS
    assert plot._data_limits_cache is not None
    plot.close()
    app.quit()


def test_selected_table_display_is_capped_for_large_selection():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from cisprobeplace.gui import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    window.selected_pins = [
        PinRecord("U", str(index), "SYM", "PROBE", "PAD", float(index), 0.0, f"N{index}")
        for index in range(window.MAX_TABLE_ROWS + 250)
    ]

    window._refresh_table()

    assert window.selected_table.rowCount() == window.MAX_TABLE_ROWS
    assert len(window.selected_pins) == window.MAX_TABLE_ROWS + 250
    window.close()
    app.quit()


def test_selected_table_header_sort_toggles_coordinate_order():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from cisprobeplace.gui import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    window.selected_pins = [
        PinRecord("U", "3", "SYM", "PROBE", "PAD", 30.0, 0.0, "N3"),
        PinRecord("U", "1", "SYM", "PROBE", "PAD", 10.0, 0.0, "N1"),
        PinRecord("U", "2", "SYM", "PROBE", "PAD", 20.0, 0.0, "N2"),
    ]
    window._refresh_table()

    window._sort_selected_table_by_column(0)

    assert [window.selected_table.item(row, 0).text() for row in range(3)] == ["10", "20", "30"]
    assert window.selected_table.horizontalHeader().sortIndicatorOrder() == Qt.SortOrder.AscendingOrder

    window._sort_selected_table_by_column(0)

    assert [window.selected_table.item(row, 0).text() for row in range(3)] == ["30", "20", "10"]
    assert window.selected_table.horizontalHeader().sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
    window.close()
    app.quit()


def test_selected_table_supports_ctrl_style_multi_selection_and_plot_highlight():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QItemSelectionModel
    from PySide6.QtWidgets import QApplication, QAbstractItemView

    from cisprobeplace.gui import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    window.selected_pins = [
        PinRecord("U", "1", "SYM", "PROBE", "PAD", 10.0, 0.0, "N1"),
        PinRecord("U", "2", "SYM", "PROBE", "PAD", 20.0, 0.0, "N2"),
        PinRecord("U", "3", "SYM", "PROBE", "PAD", 30.0, 0.0, "N3"),
    ]
    window._refresh_table()

    assert window.selected_table.selectionMode() == QAbstractItemView.SelectionMode.ExtendedSelection

    selection_model = window.selected_table.selectionModel()
    selection_model.select(
        window.selected_table.model().index(0, 0),
        QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
    )
    selection_model.select(
        window.selected_table.model().index(2, 0),
        QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
    )

    highlighted_numbers = [pin.pin_number for pin in window.plot._highlighted_pins]

    assert highlighted_numbers == ["1", "3"]
    assert len(window.plot._display_highlighted_pins) == 2
    window.close()
    app.quit()


def test_net_selection_list_is_populated_and_checked_from_loaded_pins():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from cisprobeplace.gui import MainWindow
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    pins = [
        PinRecord("U", "1", "SYM", "PROBE", "PAD", 10.0, 0.0, "DGND"),
        PinRecord("U", "2", "SYM", "PROBE", "PAD", 20.0, 0.0, "SIGNAL_A"),
        PinRecord("U", "3", "SYM", "PROBE", "PAD", 30.0, 0.0, "SIGNAL_B"),
    ]

    window._on_inputs_loaded(pins)
    while window._selection_worker is not None or window._selection_timer.isActive():
        app.processEvents()

    assert [window.net_list.item(index).text() for index in range(window.net_list.count())] == ["DGND", "SIGNAL_A", "SIGNAL_B"]
    assert all(window.net_list.item(index).checkState() == Qt.CheckState.Checked for index in range(window.net_list.count()))

    window.net_list.item(1).setCheckState(Qt.CheckState.Unchecked)
    window._start_selection_update()
    while window._selection_worker is not None or window._selection_timer.isActive():
        app.processEvents()

    assert [pin.net_name for pin in window.selected_pins] == ["DGND", "SIGNAL_B"]
    window.close()
    app.quit()


def test_net_selection_has_bulk_buttons_and_comp_device_title():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QGroupBox

    from cisprobeplace.gui import MainWindow
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    pins = [
        PinRecord("U", "1", "SYM", "PROBE", "PAD", 10.0, 0.0, "DGND"),
        PinRecord("U", "2", "SYM", "PROBE", "PAD", 20.0, 0.0, "SIGNAL_A"),
    ]

    window._on_inputs_loaded(pins)
    while window._selection_worker is not None or window._selection_timer.isActive():
        app.processEvents()

    group_titles = {group.title() for group in window.findChildren(QGroupBox)}
    assert "COMP_DEVICE Selection" in group_titles
    assert "Selection" not in group_titles

    window.net_clear_all_button.click()
    while window._selection_worker is not None or window._selection_timer.isActive():
        app.processEvents()

    assert all(window.net_list.item(index).checkState() == Qt.CheckState.Unchecked for index in range(window.net_list.count()))
    assert window.selected_pins == []

    window.net_select_all_button.click()
    while window._selection_worker is not None or window._selection_timer.isActive():
        app.processEvents()

    assert all(window.net_list.item(index).checkState() == Qt.CheckState.Checked for index in range(window.net_list.count()))
    assert [pin.net_name for pin in window.selected_pins] == ["DGND", "SIGNAL_A"]
    window.close()
    app.quit()


def test_net_selection_search_filters_with_wildcards_and_preserves_checked_state():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from cisprobeplace.gui import MainWindow
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    pins = [
        PinRecord("U", "1", "SYM", "PROBE", "PAD", 10.0, 0.0, "DGND"),
        PinRecord("U", "2", "SYM", "PROBE", "PAD", 20.0, 0.0, "SIGNAL_A"),
        PinRecord("U", "3", "SYM", "PROBE", "PAD", 30.0, 0.0, "SIGNAL_B"),
        PinRecord("U", "4", "SYM", "PROBE", "PAD", 40.0, 0.0, "VDD"),
    ]

    window._on_inputs_loaded(pins)
    while window._selection_worker is not None or window._selection_timer.isActive():
        app.processEvents()

    window.net_search_edit.setText("signal")
    assert [window.net_list.item(index).text() for index in range(window.net_list.count())] == ["SIGNAL_A", "SIGNAL_B"]

    window.net_search_edit.setText("SIGNAL_*B")
    assert [window.net_list.item(index).text() for index in range(window.net_list.count())] == ["SIGNAL_B"]

    window.net_search_edit.setText("!DGND")
    assert [window.net_list.item(index).text() for index in range(window.net_list.count())] == ["SIGNAL_A", "SIGNAL_B", "VDD"]

    window.net_search_edit.setText("SIGNAL*")
    window.net_clear_all_button.click()
    while window._selection_worker is not None or window._selection_timer.isActive():
        app.processEvents()

    assert [pin.net_name for pin in window.selected_pins] == ["DGND", "VDD"]

    window.net_search_edit.clear()
    visible_states = {
        window.net_list.item(index).text(): window.net_list.item(index).checkState()
        for index in range(window.net_list.count())
    }
    assert visible_states["DGND"] == Qt.CheckState.Checked
    assert visible_states["SIGNAL_A"] == Qt.CheckState.Unchecked
    assert visible_states["SIGNAL_B"] == Qt.CheckState.Unchecked
    assert visible_states["VDD"] == Qt.CheckState.Checked
    window.close()
    app.quit()


def test_net_search_select_all_does_not_change_comp_device_checks():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from cisprobeplace.gui import MainWindow
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    pins = [
        PinRecord("U", "1", "SYM", "PROBE_A", "PAD", 10.0, 0.0, "DGND"),
        PinRecord("U", "2", "SYM", "PROBE_B", "PAD", 20.0, 0.0, "SIGNAL_A"),
        PinRecord("U", "3", "SYM", "PROBE_B", "PAD", 30.0, 0.0, "SIGNAL_B"),
    ]

    window._on_inputs_loaded(pins)
    while window._selection_worker is not None or window._selection_timer.isActive():
        app.processEvents()

    window.comp_list.item(1).setCheckState(Qt.CheckState.Unchecked)
    while window._selection_worker is not None or window._selection_timer.isActive():
        app.processEvents()

    window.net_search_edit.setText("SIGNAL*")
    window.net_select_all_button.click()
    while window._selection_worker is not None or window._selection_timer.isActive():
        app.processEvents()

    assert window.comp_list.item(0).checkState() == Qt.CheckState.Checked
    assert window.comp_list.item(1).checkState() == Qt.CheckState.Unchecked
    assert [pin.comp_device for pin in window.selected_pins] == ["PROBE_A"]
    window.close()
    app.quit()


def test_coordinate_plot_wheel_zoom_and_middle_click_reset_view():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from cisprobeplace.gui import CoordinatePlot

    app = QApplication.instance() or QApplication(sys.argv)
    plot = CoordinatePlot()
    plot.resize(420, 320)
    pins = [
        PinRecord("U1", "1", "SYM", "PROBE", "PAD", 0.0, 0.0, "N1"),
        PinRecord("U2", "2", "SYM", "PROBE", "PAD", 100.0, 100.0, "N2"),
    ]
    plot.set_data(pins, pins, (0.0, 100.0, 0.0, 100.0))
    default_limits = plot._view_limits_cache
    center = QPointF(plot.rect().center())
    wheel_event = QWheelEvent(
        center,
        center,
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )

    QApplication.sendEvent(plot, wheel_event)

    zoomed_limits = plot._view_limits_cache
    assert zoomed_limits is not None
    assert default_limits is not None
    assert zoomed_limits[1] - zoomed_limits[0] < default_limits[1] - default_limits[0]
    assert zoomed_limits[3] - zoomed_limits[2] < default_limits[3] - default_limits[2]

    QTest.mouseClick(plot, Qt.MouseButton.MiddleButton, Qt.KeyboardModifier.NoModifier, plot.rect().center())

    assert plot._view_limits_cache == default_limits
    plot.close()
    app.quit()


def test_coordinate_plot_left_drag_pans_zoomed_view():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from cisprobeplace.gui import CoordinatePlot

    app = QApplication.instance() or QApplication(sys.argv)
    plot = CoordinatePlot()
    plot.resize(420, 320)
    pins = [
        PinRecord("U1", "1", "SYM", "PROBE", "PAD", 0.0, 0.0, "N1"),
        PinRecord("U2", "2", "SYM", "PROBE", "PAD", 100.0, 100.0, "N2"),
    ]
    plot.set_data(pins, pins, (0.0, 100.0, 0.0, 100.0))
    plot._zoom_at(QPointF(plot.rect().center()), 2.0)
    before = plot._view_limits_cache

    QTest.mousePress(plot, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, plot.rect().center())
    QTest.mouseMove(plot, plot.rect().center() + QPoint(40, 20))
    QTest.mouseRelease(plot, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, plot.rect().center() + QPoint(40, 20))

    after = plot._view_limits_cache
    assert after is not None
    assert before is not None
    assert after != before
    assert after[1] - after[0] == pytest.approx(before[1] - before[0])
    assert after[3] - after[2] == pytest.approx(before[3] - before[2])
    plot.close()
    app.quit()
