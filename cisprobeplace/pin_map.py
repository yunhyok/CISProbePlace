from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import QWidget

from .models import PinRecord
from .script_builder import classify_pin_sides, source_group_name_for_pin


class CoordinatePlot(QWidget):
    MAX_PLOT_POINTS = 8000
    GROUP_COLORS = ("#2563eb", "#16a34a", "#f97316", "#7c3aed", "#0891b2", "#db2777", "#65a30d", "#9333ea")
    SIDE_VECTORS = {"top": (0, -1), "left": (-1, 0), "bottom": (0, 1), "right": (1, 0)}
    boundsChanged = Signal(float, float, float, float)
    pinsPicked = Signal(object, bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(360, 260)
        self.setMouseTracking(True)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#ffffff"))
        self.setPalette(palette)
        self.setAutoFillBackground(True)
        self.setAccessibleName("Pin coordinate map")
        self._groups_by_id: dict[int, str] = {}
        self._sides_by_id: dict[int, str] = {}
        self._default_sides_by_id: dict[int, str] = {}
        self._colors: dict[str, str] = {}
        self._probe_types_by_id: dict[int, str] = {}
        self._tips_toward_center = True
        self._group_order: list[str] = []
        self._group_index: dict[str, int] = {}
        self._all_pins: list[PinRecord] = []
        self._selected_pins: list[PinRecord] = []
        self._display_all_pins: list[PinRecord] = []
        self._display_selected_pins: list[PinRecord] = []
        self._highlighted_pins: list[PinRecord] = []
        self._display_highlighted_pins: list[PinRecord] = []
        self._data_limits_cache: tuple[float, float, float, float] | None = None
        self._view_limits_cache: tuple[float, float, float, float] | None = None
        self._bounds: tuple[float, float, float, float] | None = None
        self._dragging_edge: str | None = None
        self._is_panning = False
        self._last_pan_pos: QPointF | None = None
        self._press_pos: QPointF | None = None
        self._selection_rect: QRectF | None = None
        self._press_modifiers = Qt.KeyboardModifier.NoModifier
        self._moved = False
        self._marker_image_cache = None

    def set_data(
        self,
        all_pins: list[PinRecord],
        selected_pins: list[PinRecord],
        bounds: tuple[float, float, float, float] | None,
    ) -> None:
        previous_data_limits = self._data_limits_cache
        dataset_changed = all_pins is not self._all_pins
        self._all_pins = all_pins
        self._selected_pins = selected_pins
        self._data_limits_cache = self._calculate_data_limits(all_pins)
        if previous_data_limits != self._data_limits_cache:
            self._view_limits_cache = self._data_limits_cache
        elif self._view_limits_cache is None:
            self._view_limits_cache = self._data_limits_cache
        self._bounds = bounds
        if dataset_changed:
            self._default_sides_by_id = ({} if all(id(pin) in self._sides_by_id for pin in all_pins)
                                         else dict(zip(map(id, all_pins), classify_pin_sides(all_pins))))
        self._rebuild_group_cache()
        self._refresh_display_samples()
        self.update()

    def set_pin_styles(
        self, groups_by_id: dict[int, str], sides_by_id: dict[int, str], colors: dict[str, str]
    ) -> None:
        """Use original PinRecord identities; SIDE is independent of editable rotation."""
        self._groups_by_id = dict(groups_by_id)
        self._sides_by_id = dict(sides_by_id)
        self._colors = {group: color for group, color in colors.items() if QColor(color).isValid()}
        self._rebuild_group_cache()
        self._refresh_display_samples()
        self.update()

    def set_highlighted_pins(self, highlighted_pins: list[PinRecord]) -> None:
        self._highlighted_pins = list(highlighted_pins)
        self._refresh_display_samples()
        self.update()

    def set_probe_types(self, types_by_id: dict[int, str]) -> None:
        self._probe_types_by_id = dict(types_by_id)

    def set_tip_orientation(self, toward_center: bool) -> None:
        if self._tips_toward_center == toward_center:
            return
        self._tips_toward_center = toward_center
        self._marker_image_cache = None
        self._rebuild_group_cache()
        self.update()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._refresh_display_samples()
        super().resizeEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self._plot_rect()
        painter.fillRect(self.rect(), QColor("#ffffff"))
        painter.setPen(QPen(QColor("#b6bcc6"), 1))
        painter.drawRect(rect)

        if not self._all_pins:
            painter.setPen(QColor("#6b7280"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Load input files to preview coordinates")
            return

        if self._bounds:
            x_min, x_max, y_min, y_max = self._bounds
            top_left = self.data_to_widget_point(x_min, y_max)
            bottom_right = self.data_to_widget_point(x_max, y_min)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor("#dc2626"), 2))
            painter.drawLine(top_left.x(), top_left.y(), bottom_right.x(), top_left.y())
            painter.drawLine(bottom_right.x(), top_left.y(), bottom_right.x(), bottom_right.y())
            painter.drawLine(bottom_right.x(), bottom_right.y(), top_left.x(), bottom_right.y())
            painter.drawLine(top_left.x(), bottom_right.y(), top_left.x(), top_left.y())

        self._draw_pin_paths(painter, rect)

        if self._selection_rect is not None:
            painter.setPen(QPen(QColor("#1d4ed8"), 1, Qt.PenStyle.DashLine))
            painter.setBrush(QColor(37, 99, 235, 35))
            painter.drawRect(self._selection_rect)
        painter.setPen(QColor("#374151"))
        self._draw_group_legend(painter)
        painter.setPen(QColor("#374151"))
        footer = QRectF(12, self.height() - 44, max(self.width() - 24, 1), 40)
        orientation = "toward center" if self._tips_toward_center else "toward outside"
        text = f"Triangle tips assumed {orientation}\nPicked: dark outline · Outside filter: pale"
        painter.drawText(footer, Qt.AlignmentFlag.AlignCenter, text)

    def _group_for_pin(self, pin: PinRecord) -> str:
        return self._groups_by_id.get(id(pin), source_group_name_for_pin(pin))

    def _rebuild_group_cache(self) -> None:
        self._group_order = list(dict.fromkeys(self._group_for_pin(pin) for pin in self._all_pins))
        groups = "; ".join(f"{group}: {self.group_color(group)}" for group in self._group_order)
        orientation = "toward center" if self._tips_toward_center else "toward outside"
        description = (
            f"Triangle tips show the assumed direction {orientation}; physical SIDE is unchanged. "
            "SOURCE_GROUP controls color. "
            "Outside-filter pins are pale; picked pins have a dark outline. "
            "Click to pick, Ctrl+click to toggle. Shift+drag selects a rectangle; "
            "Ctrl+Shift+drag toggles. Wheel zooms, drag pans when zoomed, middle click resets. "
            "Drag a range edge to adjust the filter. SOURCE_GROUP colors: " + groups
        )
        self.setAccessibleDescription(description)
        self.setToolTip(description)

    def group_color(self, group: str) -> str:
        # A group keeps its swatch when polarity or manual assignments change.
        index = self._group_index.setdefault(group, len(self._group_index))
        return self._colors.get(group, self.GROUP_COLORS[index % len(self.GROUP_COLORS)])

    def _style_for_pin(self, pin: PinRecord) -> tuple[str, str]:
        return (
            self.group_color(self._group_for_pin(pin)),
            self._sides_by_id.get(id(pin), self._default_sides_by_id.get(id(pin), "right")),
        )

    def _draw_pin_paths(self, painter: QPainter, rect: QRectF) -> None:
        ratio = self.devicePixelRatioF()
        geometry = (rect.x(), rect.y(), rect.width(), rect.height(), ratio)
        if self._marker_image_cache is not None and self._marker_image_cache[0] == geometry:
            painter.drawImage(QPointF(0, 0), self._marker_image_cache[1])
            return
        x_min, x_max, y_min, _ = self._data_limits()
        scale = rect.width() / (x_max - x_min)
        selected_ids = {id(pin) for pin in self._selected_pins}
        layers = (
            (0, [pin for pin in self._display_all_pins if id(pin) not in selected_ids]),
            (1, self._display_selected_pins),
            (2, self._display_highlighted_pins),
        )
        paths = {}
        for layer, pins in layers:
            size = 7 if layer == 2 else 4.5
            for index, pin in enumerate(pins):
                color, side = self._style_for_pin(pin)
                outside = id(pin) not in selected_ids
                key = (layer, color, outside, index // 128)
                path = paths.get(key)
                if path is None:
                    path = QPainterPath()
                    path.setFillRule(Qt.FillRule.WindingFill)
                    paths[key] = path
                x = rect.left() + (pin.pin_x - x_min) * scale
                y = rect.bottom() - (pin.pin_y - y_min) * scale
                dx, dy = self.SIDE_VECTORS.get(side, (1, 0))
                if self._tips_toward_center:
                    dx, dy = -dx, -dy
                path.moveTo(x + dx * size, y + dy * size)
                path.lineTo(x - dx * size - dy * size * 0.7, y - dy * size + dx * size * 0.7)
                path.lineTo(x - dx * size + dy * size * 0.7, y - dy * size - dx * size * 0.7)
                path.closeSubpath()
        image = QImage(round(self.width() * ratio), round(self.height() * ratio), QImage.Format.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(ratio)
        image.fill(Qt.GlobalColor.transparent)
        marker_painter = QPainter(image)
        marker_painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for (layer, color, outside, _), path in paths.items():
            fill = QColor(color)
            if outside:
                fill.setAlpha(55)
            marker_painter.setBrush(fill)
            marker_painter.setPen(QPen(QColor("#111827" if layer == 2 else "#77808d"), 2 if layer == 2 else 0.6)
                           if outside or layer == 2 or fill.lightnessF() > 0.8 else QPen(Qt.PenStyle.NoPen))
            marker_painter.drawPath(path)
        marker_painter.end()
        self._marker_image_cache = (geometry, image)
        painter.drawImage(QPointF(0, 0), image)

    def _legend_entries(self) -> tuple[list[tuple[str, str]], int]:
        metrics = self.fontMetrics()
        available = self.width() - 24
        entries = []
        for group in self._group_order[:4]:
            label = metrics.elidedText(group, Qt.TextElideMode.ElideRight, min(180, max(70, available // 2 - 24)))
            width = metrics.horizontalAdvance(label) + 28
            remaining = len(self._group_order) - len(entries) - 1
            reserve = metrics.horizontalAdvance(f"+{remaining} groups") + 12 if remaining else 0
            if width + reserve > available:
                break
            entries.append((group, label))
            available -= width
        return entries, len(self._group_order) - len(entries)

    def _draw_group_legend(self, painter: QPainter) -> None:
        x, y = 12.0, self.height() - 65.0
        entries, remaining = self._legend_entries()
        for group, label in entries:
            painter.fillRect(QRectF(x, y, 10, 10), QColor(self.group_color(group)))
            painter.setPen(QPen(QColor("#77808d"), 0.6))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(QRectF(x, y, 10, 10))
            painter.setPen(QColor("#374151"))
            painter.drawText(QPointF(x + 15, y + 10), label)
            x += painter.fontMetrics().horizontalAdvance(label) + 28
        if remaining:
            painter.setPen(QColor("#374151"))
            painter.drawText(QPointF(x, y + 10), f"+{remaining} groups")

    def data_to_widget_point(self, x: float, y: float) -> QPointF:
        min_x, max_x, min_y, max_y = self._data_limits()
        rect = self._plot_rect()
        px = rect.left() + ((x - min_x) / (max_x - min_x)) * rect.width()
        py = rect.bottom() - ((y - min_y) / (max_y - min_y)) * rect.height()
        return QPointF(px, py)

    def widget_to_data_point(self, point: QPointF) -> QPointF:
        min_x, max_x, min_y, max_y = self._data_limits()
        rect = self._plot_rect()
        clamped_x = min(max(point.x(), rect.left()), rect.right())
        clamped_y = min(max(point.y(), rect.top()), rect.bottom())
        x = min_x + ((clamped_x - rect.left()) / rect.width()) * (max_x - min_x)
        y = min_y + ((rect.bottom() - clamped_y) / rect.height()) * (max_y - min_y)
        return QPointF(x, y)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.MiddleButton:
            self.reset_view()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            point = self._event_position(event)
            if self._all_pins and self._plot_rect().adjusted(-8, -8, 8, 8).contains(point):
                self._press_pos = point
                self._press_modifiers = event.modifiers()
                self._moved = False
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    self._selection_rect = QRectF(point, point)
                else:
                    self._dragging_edge = self._hit_test_edge(point)
                self._last_pan_pos = point
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt API
        point = self._event_position(event)
        if self._press_pos is not None:
            if not self._moved and (point - self._press_pos).manhattanLength() <= 4:
                event.accept()
                return
            self._moved = True
            if self._selection_rect is not None:
                self._selection_rect = QRectF(self._press_pos, point).normalized()
                self.update()
            elif self._dragging_edge:
                self._update_bounds_from_drag(self._dragging_edge, self.widget_to_data_point(point))
            elif self._is_zoomed() and self._last_pan_pos is not None:
                self._is_panning = True
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                self._pan_by_pixels(point - self._last_pan_pos)
            self._last_pan_pos = point
            event.accept()
            return
        pin = self._hit_test_pin(point)
        if pin is not None:
            group = self._group_for_pin(pin)
            _, side = self._style_for_pin(pin)
            probe_type = self._probe_types_by_id.get(id(pin), "Undetermined")
            orientation = "toward center" if self._tips_toward_center else "toward outside"
            self.setToolTip(f"Pin {pin.pin_number} ({pin.refdes})\nNET: {pin.net_name}\nSIDE: {side}\nSOURCE_GROUP: {group}\nPredicted probe: {probe_type}\nAssumed tips: {orientation}")
        else:
            self.setToolTip(self.accessibleDescription())
        edge = self._hit_test_edge(point)
        if edge in {"left", "right"}:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif edge in {"top", "bottom"}:
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        elif self._is_zoomed():
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton and self._press_pos is not None:
            point = self._event_position(event)
            toggle = bool(self._press_modifiers & Qt.KeyboardModifier.ControlModifier)
            if self._selection_rect is not None and self._moved:
                self.pinsPicked.emit(self._pins_in_rect(QRectF(self._press_pos, point).normalized()), toggle)
            elif not self._moved:
                pin = self._hit_test_pin(point)
                if pin is not None:
                    self.pinsPicked.emit([pin], toggle)
            self._press_pos = None
            self._selection_rect = None
            self._dragging_edge = None
            self._is_panning = False
            self._last_pan_pos = None
            if self._is_zoomed():
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            else:
                self.unsetCursor()
            self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt API
        if not self._dragging_edge and not self._is_panning:
            self.unsetCursor()
        super().leaveEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt API
        if not self._all_pins:
            super().wheelEvent(event)
            return
        delta = event.angleDelta().y()
        if delta == 0:
            super().wheelEvent(event)
            return
        self._zoom_at(self._event_position(event), delta / 120.0)
        event.accept()

    def reset_view(self) -> None:
        self._view_limits_cache = self._data_limits_cache
        self._refresh_display_samples()
        self.update()

    def _update_bounds_from_drag(self, edge: str, point: QPointF) -> None:
        if not self._bounds:
            return
        x_min, x_max, y_min, y_max = self._bounds
        if edge == "left":
            x_min = min(point.x(), x_max)
        elif edge == "right":
            x_max = max(point.x(), x_min)
        elif edge == "bottom":
            y_min = min(point.y(), y_max)
        elif edge == "top":
            y_max = max(point.y(), y_min)
        self._bounds = (x_min, x_max, y_min, y_max)
        self.boundsChanged.emit(x_min, x_max, y_min, y_max)
        self.update()

    def _hit_test_edge(self, point: QPointF) -> str | None:
        if not self._bounds or not self._all_pins:
            return None
        x_min, x_max, y_min, y_max = self._bounds
        left_mid = self.data_to_widget_point(x_min, (y_min + y_max) / 2)
        right_mid = self.data_to_widget_point(x_max, (y_min + y_max) / 2)
        bottom_mid = self.data_to_widget_point((x_min + x_max) / 2, y_min)
        top_mid = self.data_to_widget_point((x_min + x_max) / 2, y_max)
        tolerance = 8.0
        vertical_range = sorted((self.data_to_widget_point(x_min, y_min).y(), self.data_to_widget_point(x_min, y_max).y()))
        horizontal_range = sorted((self.data_to_widget_point(x_min, y_min).x(), self.data_to_widget_point(x_max, y_min).x()))
        if vertical_range[0] - tolerance <= point.y() <= vertical_range[1] + tolerance:
            if abs(point.x() - left_mid.x()) <= tolerance:
                return "left"
            if abs(point.x() - right_mid.x()) <= tolerance:
                return "right"
        if horizontal_range[0] - tolerance <= point.x() <= horizontal_range[1] + tolerance:
            if abs(point.y() - top_mid.y()) <= tolerance:
                return "top"
            if abs(point.y() - bottom_mid.y()) <= tolerance:
                return "bottom"
        return None

    def _data_limits(self) -> tuple[float, float, float, float]:
        return self._view_limits_cache or self._data_limits_cache or (0.0, 1.0, 0.0, 1.0)

    def _calculate_data_limits(self, pins: list[PinRecord]) -> tuple[float, float, float, float]:
        if not pins:
            return 0.0, 1.0, 0.0, 1.0
        min_x = min(pin.pin_x for pin in pins)
        max_x = max(pin.pin_x for pin in pins)
        min_y = min(pin.pin_y for pin in pins)
        max_y = max(pin.pin_y for pin in pins)
        span_x = max(max_x - min_x, 1.0)
        span_y = max(max_y - min_y, 1.0)
        pad_x = span_x * 0.05
        pad_y = span_y * 0.05
        return min_x - pad_x, max_x + pad_x, min_y - pad_y, max_y + pad_y

    def _sample_pins(self, pins: list[PinRecord]) -> list[PinRecord]:
        if len(pins) <= self.MAX_PLOT_POINTS:
            return list(pins)
        rect = self._plot_rect()
        x_min, x_max, y_min, _ = self._data_limits()
        scale = rect.width() / (x_max - x_min) / 9
        occupied = set()
        visible = []
        for pin in pins:
            key = (int((pin.pin_x - x_min) * scale), int((pin.pin_y - y_min) * scale),
                   self._group_for_pin(pin), self._sides_by_id.get(id(pin), self._default_sides_by_id.get(id(pin))))
            if key not in occupied:
                occupied.add(key)
                visible.append(pin)
        if len(visible) <= self.MAX_PLOT_POINTS:
            return visible
        pins = visible
        step = len(pins) / self.MAX_PLOT_POINTS
        return [pins[int(index * step)] for index in range(self.MAX_PLOT_POINTS)]

    def _refresh_display_samples(self) -> None:
        self._marker_image_cache = None
        self._display_all_pins = self._sample_pins(self._visible_pins(self._all_pins))
        self._display_selected_pins = self._sample_pins(self._visible_pins(self._selected_pins))
        self._display_highlighted_pins = self._sample_pins(self._visible_pins(self._highlighted_pins))

    def _visible_pins(self, pins: list[PinRecord]) -> list[PinRecord]:
        if not pins:
            return []
        if self._view_limits_cache is None and self._data_limits_cache is None:
            return list(pins)
        x_min, x_max, y_min, y_max = self._data_limits()
        return [pin for pin in pins if x_min <= pin.pin_x <= x_max and y_min <= pin.pin_y <= y_max]

    def _hit_test_pin(self, point: QPointF) -> PinRecord | None:
        rect = self._plot_rect()
        if not rect.adjusted(-8, -8, 8, 8).contains(point):
            return None
        x_min, x_max, y_min, y_max = self._data_limits()
        scale = rect.width() / (x_max - x_min)
        # Test the full eligible data: display sampling must never limit selection.
        best_distance = 8.0 ** 2
        nearest = None
        for pin in self._selected_pins:
            if not (x_min <= pin.pin_x <= x_max and y_min <= pin.pin_y <= y_max):
                continue
            dx = rect.left() + (pin.pin_x - x_min) * scale - point.x()
            dy = rect.bottom() - (pin.pin_y - y_min) * scale - point.y()
            distance = dx * dx + dy * dy
            if distance <= best_distance:
                best_distance = distance
                nearest = pin
        return nearest

    def _pins_in_rect(self, rect: QRectF) -> list[PinRecord]:
        clipped = rect.intersected(self._plot_rect())
        if clipped.isEmpty():
            return []
        low = self.widget_to_data_point(clipped.bottomLeft())
        high = self.widget_to_data_point(clipped.topRight())
        return [pin for pin in self._selected_pins
                if low.x() <= pin.pin_x <= high.x() and low.y() <= pin.pin_y <= high.y()]

    def _zoom_at(self, widget_point: QPointF, steps: float) -> None:
        full_limits = self._data_limits_cache
        view_limits = self._view_limits_cache
        if full_limits is None or view_limits is None:
            return
        zoom_base = 1.25
        scale = 1.0 / (zoom_base**steps)
        x_min, x_max, y_min, y_max = view_limits
        anchor = self.widget_to_data_point(widget_point)
        new_x_min = anchor.x() - (anchor.x() - x_min) * scale
        new_x_max = anchor.x() + (x_max - anchor.x()) * scale
        new_y_min = anchor.y() - (anchor.y() - y_min) * scale
        new_y_max = anchor.y() + (y_max - anchor.y()) * scale
        self._set_view_limits(new_x_min, new_x_max, new_y_min, new_y_max)

    def _pan_by_pixels(self, delta: QPointF) -> None:
        if self._view_limits_cache is None:
            return
        rect = self._plot_rect()
        if rect.width() <= 0 or rect.height() <= 0:
            return
        x_min, x_max, y_min, y_max = self._view_limits_cache
        x_span = x_max - x_min
        y_span = y_max - y_min
        data_dx = -(delta.x() / rect.width()) * x_span
        data_dy = (delta.y() / rect.height()) * y_span
        self._set_view_limits(x_min + data_dx, x_max + data_dx, y_min + data_dy, y_max + data_dy)

    def _set_view_limits(self, x_min: float, x_max: float, y_min: float, y_max: float) -> None:
        full = self._data_limits_cache
        if full is None:
            return
        full_x_min, full_x_max, full_y_min, full_y_max = full
        full_width = full_x_max - full_x_min
        full_height = full_y_max - full_y_min
        width = min(max(x_max - x_min, full_width / 10000.0), full_width)
        height = min(max(y_max - y_min, full_height / 10000.0), full_height)

        if width >= full_width:
            x_min, x_max = full_x_min, full_x_max
        else:
            center_x = (x_min + x_max) / 2.0
            x_min = center_x - width / 2.0
            x_max = center_x + width / 2.0
            if x_min < full_x_min:
                x_max += full_x_min - x_min
                x_min = full_x_min
            if x_max > full_x_max:
                x_min -= x_max - full_x_max
                x_max = full_x_max

        if height >= full_height:
            y_min, y_max = full_y_min, full_y_max
        else:
            center_y = (y_min + y_max) / 2.0
            y_min = center_y - height / 2.0
            y_max = center_y + height / 2.0
            if y_min < full_y_min:
                y_max += full_y_min - y_min
                y_min = full_y_min
            if y_max > full_y_max:
                y_min -= y_max - full_y_max
                y_max = full_y_max

        self._view_limits_cache = (x_min, x_max, y_min, y_max)
        self._refresh_display_samples()
        self.update()

    def _is_zoomed(self) -> bool:
        return self._data_limits_cache is not None and self._view_limits_cache != self._data_limits_cache

    def _plot_rect(self):
        available = QRectF(self.rect()).adjusted(12, 12, -12, -72)
        x_min, x_max, y_min, y_max = self._data_limits()
        scale = min(available.width() / (x_max - x_min), available.height() / (y_max - y_min))
        width, height = (x_max - x_min) * scale, (y_max - y_min) * scale
        return QRectF(available.center().x() - width / 2, available.center().y() - height / 2, width, height)

    def _event_position(self, event) -> QPointF:
        if hasattr(event, "position"):
            return event.position()
        return QPointF(event.pos())
