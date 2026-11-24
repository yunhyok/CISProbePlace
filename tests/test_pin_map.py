import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from cisprobeplace.models import PinRecord
from cisprobeplace.pin_map import CoordinatePlot


@pytest.fixture
def plot():
    app = QApplication.instance() or QApplication([])
    widget = CoordinatePlot()
    widget.resize(640, 440)
    widget.show()
    app.processEvents()
    yield widget
    widget.close()
    app.processEvents()


def pin(number, x, y, group="A"):
    return PinRecord("U1", str(number), "SYM", group, "PAD", float(x), float(y), f"N{number}")


def click(plot, record, modifiers=Qt.KeyboardModifier.NoModifier):
    QTest.mouseClick(plot, Qt.MouseButton.LeftButton, modifiers,
                     plot.data_to_widget_point(record.pin_x, record.pin_y).toPoint())


def test_source_group_colors_stay_stable_across_filtering_and_side_is_independent(plot):
    records = [pin(1, 0, 0, "B"), pin(2, 10, 10, "A")]
    groups = {id(records[0]): "Source_B", id(records[1]): "Source_A"}
    sides = {id(records[0]): "top", id(records[1]): "left"}
    plot.set_data(records, records, None)
    plot.set_pin_styles(groups, sides, {"Source_A": "#123456"})
    before = [plot._style_for_pin(record) for record in records]

    plot.set_data(records, records[1:], (0, 10, 0, 10))

    assert [plot._style_for_pin(record) for record in records] == before
    assert before == [(plot.GROUP_COLORS[0], "top"), ("#123456", "left")]
    assert "SOURCE_GROUP" in plot.accessibleDescription()
    assert "Source_A: #123456" in plot.accessibleDescription()


def test_map_has_equal_physical_aspect_and_reversible_coordinates(plot):
    records = [pin(1, 0, 0), pin(2, 100, 20)]
    plot.set_data(records, records, None)
    origin = plot.data_to_widget_point(0, 0)
    x = plot.data_to_widget_point(10, 0)
    y = plot.data_to_widget_point(0, 10)
    assert x.x() - origin.x() == pytest.approx(origin.y() - y.y())
    restored = plot.widget_to_data_point(plot.data_to_widget_point(37, 13))
    assert restored.x() == pytest.approx(37)
    assert restored.y() == pytest.approx(13)
    plot.resize(420, 650)
    origin = plot.data_to_widget_point(0, 0)
    assert plot.data_to_widget_point(10, 0).x() - origin.x() == pytest.approx(
        origin.y() - plot.data_to_widget_point(0, 10).y())


def test_white_map_renders_oriented_source_colored_markers_with_distinct_states(plot):
    records = [pin(1, 0, 0), pin(2, 0, 10), pin(3, 10, 0), pin(4, 10, 10), pin(5, 5, 5)]
    sides = dict(zip(map(id, records), ["top", "left", "bottom", "right", "right"]))
    plot.set_data(records, records[:4], (0, 10, 0, 10))
    plot.set_pin_styles({id(record): "G" for record in records}, sides, {"G": "#006600"})
    plot.set_highlighted_pins([records[0]])
    plot.setStyleSheet("background-color: #15181d; color: white;")
    rendered = plot.grab().toImage()
    assert rendered.pixelColor(0, 0).name() == "#ffffff"
    center = plot.data_to_widget_point(0, 10).toPoint()
    assert rendered.pixelColor(center).name() == "#006600"
    highlighted = plot.data_to_widget_point(0, 0).toPoint()
    assert rendered.pixelColor(highlighted).name() == "#006600"
    outside = plot.data_to_widget_point(5, 5).toPoint()
    assert rendered.pixelColor(outside).green() > rendered.pixelColor(center).green()
    plot.set_highlighted_pins([])
    rendered = plot.grab().toImage()
    for record, (dx, dy) in zip(records[:4], [(0, 1), (1, 0), (0, -1), (-1, 0)]):
        center = plot.data_to_widget_point(record.pin_x, record.pin_y).toPoint()
        wide_base = center + QPoint(-dx * 3 - dy * 2, -dy * 3 + dx * 2)
        narrow_tip = center + QPoint(dx * 3 - dy * 2, dy * 3 + dx * 2)
        assert rendered.pixelColor(wide_base).green() < rendered.pixelColor(narrow_tip).green()


def test_rendered_tip_polarity_flips_all_sides_without_changing_physical_side(plot):
    records = [pin(1, 0, 10), pin(2, 0, 0), pin(3, 10, 0), pin(4, 10, 10)]
    sides = dict(zip(map(id, records), ("top", "left", "bottom", "right")))
    plot.set_data(records, records, None)
    plot.set_pin_styles({id(record): "G" for record in records}, sides, {"G": "#006600"})
    original_styles = [plot._style_for_pin(record) for record in records]
    inward = plot.grab().toImage()
    cached = plot._marker_image_cache
    plot.set_tip_orientation(False)
    assert plot._marker_image_cache is None
    outward = plot.grab().toImage()
    assert plot._marker_image_cache is not cached
    assert [plot._style_for_pin(record) for record in records] == original_styles
    for record in records:
        dx, dy = plot.SIDE_VECTORS[sides[id(record)]]
        center = plot.data_to_widget_point(record.pin_x, record.pin_y).toPoint()
        outside_base = center + QPoint(dx * 3 - dy * 2, dy * 3 + dx * 2)
        inside_base = center + QPoint(-dx * 3 - dy * 2, -dy * 3 + dx * 2)
        assert inward.pixelColor(outside_base).green() < outward.pixelColor(outside_base).green()
        assert inward.pixelColor(inside_base).green() > outward.pixelColor(inside_base).green()
    assert "assumed direction toward outside" in plot.accessibleDescription()
    plot.set_tip_orientation(True)
    restored = plot.grab().toImage()
    for record in records:
        center = plot.data_to_widget_point(record.pin_x, record.pin_y).toPoint()
        assert restored.copy(center.x() - 5, center.y() - 5, 11, 11) == inward.copy(center.x() - 5, center.y() - 5, 11, 11)


def test_white_custom_color_keeps_visible_outline_and_legend_stays_compact(plot):
    records = [pin(1, 0, 0), pin(2, 10, 10), pin(3, 5, 5)]
    plot.set_data(records, records, None)
    plot.set_pin_styles({id(record): "Source white" for record in records}, {}, {"Source white": "#ffffff"})
    image = plot.grab().toImage()
    center = plot.data_to_widget_point(5, 5).toPoint()
    assert any(image.pixelColor(center + QPoint(dx, dy)).red() < 220
               for dx in range(-6, 7) for dy in range(-6, 7))
    assert plot._legend_entries() == ([("Source white", "Source white")], 0)
    assert plot._plot_rect().bottom() < plot.height() - 65
    many = [pin(index, index % 10, index // 10, f"Group {index}") for index in range(100)]
    plot.set_pin_styles({}, {}, {})
    plot.set_data(many, many, None)
    entries, remaining = plot._legend_entries()
    assert 1 <= len(entries) <= 4
    assert len(entries) + remaining == 100


def test_click_picks_original_unsampled_pin_but_never_outside_filter(plot):
    records = [pin(1, 0, 0), pin(2, 10, 10), pin(3, 0, 10), pin(4, 10, 0)]
    plot.MAX_PLOT_POINTS = 1
    plot.set_data(records, records[:3], None)
    assert records[1] not in plot._display_selected_pins
    emitted = []
    plot.pinsPicked.connect(lambda pins, toggle: emitted.append((pins, toggle)))
    click(plot, records[1])
    assert emitted == [([records[1]], False)]
    assert emitted[0][0][0] is records[1]
    click(plot, records[3])
    assert len(emitted) == 1
    click(plot, records[2], Qt.KeyboardModifier.ControlModifier)
    assert emitted[-1] == ([records[2]], True)


def test_boundary_pin_click_selects_and_boundary_drag_still_changes_filter(plot):
    records = [pin(1, 0, 0), pin(2, 10, 10), pin(3, 10, 5)]
    plot.set_data(records, records, (0, 10, 0, 10))
    picked, bounds = [], []
    plot.pinsPicked.connect(lambda pins, toggle: picked.extend(pins))
    plot.boundsChanged.connect(lambda *values: bounds.append(values))
    click(plot, records[2])
    assert picked == [records[2]]
    assert not bounds
    start = plot.data_to_widget_point(10, 5).toPoint()
    end = plot.data_to_widget_point(7, 5).toPoint()
    QTest.mousePress(plot, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    QTest.mouseMove(plot, end)
    QTest.mouseRelease(plot, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)
    assert bounds[-1][1] == pytest.approx(7, abs=0.1)
    assert picked == [records[2]]


@pytest.mark.parametrize("toggle", [False, True])
def test_left_drag_rectangle_picks_pins_without_shift_and_when_zoomed(plot, toggle):
    records = [pin(1, 0, 0), pin(2, 10, 10), pin(3, 3, 3), pin(4, 4, 4), pin(5, 5, 5)]
    plot.set_data(records, records[:4], (0, 10, 0, 10))
    emitted = []
    plot.pinsPicked.connect(lambda pins, ctrl: emitted.append((pins, ctrl)))
    modifiers = Qt.KeyboardModifier.ControlModifier if toggle else Qt.KeyboardModifier.NoModifier
    start = plot.data_to_widget_point(2, 6).toPoint()
    end = plot.data_to_widget_point(6, 2).toPoint()
    QTest.mousePress(plot, Qt.MouseButton.LeftButton, modifiers, start)
    QTest.mouseMove(plot, end)
    QTest.mouseRelease(plot, Qt.MouseButton.LeftButton, modifiers, end)
    assert emitted == [(records[2:4], toggle)]

    plot._zoom_at(plot.data_to_widget_point(4, 4), 2)
    emitted.clear()
    start = plot.data_to_widget_point(2.5, 4.5).toPoint()
    end = plot.data_to_widget_point(4.5, 2.5).toPoint()
    QTest.mousePress(plot, Qt.MouseButton.LeftButton, modifiers, start)
    QTest.mouseMove(plot, end)
    QTest.mouseRelease(plot, Qt.MouseButton.LeftButton, modifiers, end)
    assert emitted == [(records[2:4], toggle)]


@pytest.mark.parametrize("toggle", [False, True])
def test_shift_rectangle_emits_all_original_in_filter_pins_including_unsampled(plot, toggle):
    records = [pin(1, 0, 0), pin(2, 10, 10), pin(3, 3, 3), pin(4, 4, 4), pin(5, 5, 5)]
    plot.MAX_PLOT_POINTS = 1
    plot.set_data(records, records[:4], None)
    emitted = []
    plot.pinsPicked.connect(lambda pins, ctrl: emitted.append((pins, ctrl)))
    modifiers = Qt.KeyboardModifier.ShiftModifier
    if toggle:
        modifiers |= Qt.KeyboardModifier.ControlModifier
    start = plot.data_to_widget_point(2, 6).toPoint()
    end = plot.data_to_widget_point(6, 2).toPoint()
    QTest.mousePress(plot, Qt.MouseButton.LeftButton, modifiers, start)
    QTest.mouseMove(plot, end)
    QTest.mouseRelease(plot, Qt.MouseButton.LeftButton, modifiers, end)
    assert emitted == [(records[2:4], toggle)]
    assert emitted[0][0][0] is records[2]


def test_zoom_reveals_dense_pins_and_drag_pans_without_picking(plot):
    records = [pin(index, index % 100, index // 100) for index in range(10000)]
    plot.MAX_PLOT_POINTS = 50
    plot.set_data(records, records, None)
    hidden = records[5051]
    assert hidden not in plot._display_selected_pins
    point = plot.data_to_widget_point(hidden.pin_x, hidden.pin_y)
    plot._zoom_at(point, 14)
    assert hidden in plot._display_selected_pins
    assert plot._hit_test_pin(plot.data_to_widget_point(hidden.pin_x, hidden.pin_y)) is hidden
    before = plot._view_limits_cache
    picked = []
    plot.pinsPicked.connect(lambda *values: picked.append(values))
    start = plot._plot_rect().center().toPoint()
    end = start + QPoint(20, 10)
    QTest.mousePress(plot, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, start)
    QTest.mouseMove(plot, end)
    QTest.mouseRelease(plot, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, end)
    assert plot._view_limits_cache != before
    assert not picked


def test_hover_tooltip_identifies_pin_net_physical_side_and_source_group(plot):
    records = [pin(1, 0, 0), pin(2, 10, 10)]
    plot.set_data(records, records, None)
    plot.set_pin_styles({id(records[0]): "Custom source"}, {id(records[0]): "bottom"}, {})
    plot.set_probe_types({id(records[0]): "Long"})
    QTest.mouseMove(plot, plot.data_to_widget_point(0, 0).toPoint())
    assert "Pin 1 (U1)" in plot.toolTip()
    assert "NET: N1" in plot.toolTip()
    assert "SIDE: bottom" in plot.toolTip()
    assert "SOURCE_GROUP: Custom source" in plot.toolTip()
    assert "Predicted probe: Long" in plot.toolTip()
    assert "Assumed tips: toward center" in plot.toolTip()
