from __future__ import annotations

from collections import Counter
from dataclasses import replace
import math
import os
import re
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QDoubleSpinBox,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .data_io import COORDINATE_FILTER_EPSILON, filter_pins, get_comp_devices, get_net_names, load_pin_records
from .help_figures import draw_callout
from .help_viewer import HelpDialog
from .models import GenerationOptions, GenerationResult, PinRecord
from .script_builder import build_script, classify_pin_sides, source_group_name_for_pin


APP_TITLE = f"CIS Probe Placement Scriptor v{__version__}"
BLANK_LABEL = "(blank)"
RANGE_DECIMALS = 6
SIDE_LABELS = {
    "right": "right",
    "top": "top",
    "left": "left",
    "bottom": "bottom",
}


def _mixed_sort_key(value: str) -> tuple[int, float | str]:
    text = str(value).strip()
    try:
        return (0, float(text))
    except ValueError:
        return (1, text.upper())


def _net_display_text(value: str) -> str:
    return BLANK_LABEL if value == "" else value


def _wildcard_match(pattern: str, candidate: str) -> bool:
    """Match with ``*`` as the only wildcard; every other character is literal.

    Net names routinely contain ``[``, ``]`` and ``?``, which shell-style
    matching would treat as special characters.
    """
    expression = ".*".join(re.escape(part) for part in pattern.split("*"))
    return re.fullmatch(expression, candidate, flags=re.DOTALL) is not None


def _format_coordinate(value: float) -> str:
    """Show a coordinate with the same precision as the range spin boxes."""
    text = f"{value:.{RANGE_DECIMALS}f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _range_lower_bound(value: float) -> float:
    """Largest range-spin-box value that still includes ``value`` as a minimum."""
    rounded = round(value, RANGE_DECIMALS)
    if rounded > value + COORDINATE_FILTER_EPSILON:
        scale = 10.0**RANGE_DECIMALS
        rounded = math.floor(value * scale) / scale
    return rounded


def _range_upper_bound(value: float) -> float:
    """Smallest range-spin-box value that still includes ``value`` as a maximum."""
    rounded = round(value, RANGE_DECIMALS)
    if rounded < value - COORDINATE_FILTER_EPSILON:
        scale = 10.0**RANGE_DECIMALS
        rounded = math.ceil(value * scale) / scale
    return rounded


def _net_matches_search(value: str, query: str) -> bool:
    text = query.strip()
    if not text:
        return True

    negate = text.startswith("!")
    if negate:
        text = text[1:].strip()
        if not text:
            return True

    pattern = text.upper()
    candidates = {value.upper(), _net_display_text(value).upper()}
    if "*" in pattern:
        matched = any(_wildcard_match(pattern, candidate) for candidate in candidates)
    else:
        matched = any(pattern in candidate for candidate in candidates)
    return not matched if negate else matched


class CoordinatePlot(QWidget):
    MAX_PLOT_POINTS = 8000
    boundsChanged = Signal(float, float, float, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(360, 260)
        self.setMouseTracking(True)
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

    def set_data(
        self,
        all_pins: list[PinRecord],
        selected_pins: list[PinRecord],
        bounds: tuple[float, float, float, float] | None,
    ) -> None:
        previous_data_limits = self._data_limits_cache
        self._all_pins = all_pins
        self._selected_pins = selected_pins
        self._data_limits_cache = self._calculate_data_limits(all_pins)
        if previous_data_limits != self._data_limits_cache:
            self._view_limits_cache = self._data_limits_cache
        elif self._view_limits_cache is None:
            self._view_limits_cache = self._data_limits_cache
        self._bounds = bounds
        self._refresh_display_samples()
        self.update()

    def set_highlighted_pins(self, highlighted_pins: list[PinRecord]) -> None:
        self._highlighted_pins = list(highlighted_pins)
        self._refresh_display_samples()
        self.update()

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

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#c4c9d2"))
        for pin in self._display_all_pins:
            point = self.data_to_widget_point(pin.pin_x, pin.pin_y)
            painter.drawEllipse(point, 3.0, 3.0)

        painter.setBrush(QColor("#2563eb"))
        for pin in self._display_selected_pins:
            point = self.data_to_widget_point(pin.pin_x, pin.pin_y)
            painter.drawEllipse(point, 3.5, 3.5)

        painter.setBrush(QColor("#dc2626"))
        for pin in self._display_highlighted_pins:
            point = self.data_to_widget_point(pin.pin_x, pin.pin_y)
            painter.drawEllipse(point, 6.0, 6.0)

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
            self._dragging_edge = self._hit_test_edge(self._event_position(event))
            if self._dragging_edge:
                event.accept()
                return
            if self._all_pins:
                self._is_panning = True
                self._last_pan_pos = self._event_position(event)
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt API
        point = self._event_position(event)
        if self._dragging_edge and self._bounds:
            self._update_bounds_from_drag(self._dragging_edge, self.widget_to_data_point(point))
            event.accept()
            return
        if self._is_panning and self._last_pan_pos is not None:
            self._pan_by_pixels(point - self._last_pan_pos)
            self._last_pan_pos = point
            event.accept()
            return
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
        if event.button() == Qt.MouseButton.LeftButton and self._dragging_edge:
            self._dragging_edge = None
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._is_panning:
            self._is_panning = False
            self._last_pan_pos = None
            if self._is_zoomed():
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            else:
                self.unsetCursor()
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
        step = len(pins) / self.MAX_PLOT_POINTS
        return [pins[int(index * step)] for index in range(self.MAX_PLOT_POINTS)]

    def _refresh_display_samples(self) -> None:
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
        return self.rect().adjusted(12, 12, -12, -12)

    def _event_position(self, event) -> QPointF:
        if hasattr(event, "position"):
            return event.position()
        return QPointF(event.pos())


class GenerateThread(QThread):
    generated = Signal(object, str)
    failed = Signal(str)

    def __init__(
        self,
        pins: list[PinRecord],
        options: GenerationOptions,
        output_path: Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._pins = pins
        self._options = options
        self._output_path = output_path

    def run(self) -> None:
        try:
            result = build_script(self._pins, self._options)
            self._output_path.write_text(result.script, encoding="utf-8")
            self.generated.emit(result, str(self._output_path))
        except Exception as exc:  # pragma: no cover - surfaced through GUI signal
            self.failed.emit(str(exc))


class LoadInputsThread(QThread):
    progress = Signal(str)
    loaded = Signal(object)
    failed = Signal(str)

    def __init__(self, pin_path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pin_path = pin_path

    def run(self) -> None:
        try:
            self.progress.emit(f"Loading pin report: {self._pin_path}")
            pins = load_pin_records(self._pin_path)
            self.progress.emit(f"Loaded {len(pins)} pin rows.")
            self.loaded.emit(pins)
        except Exception as exc:  # pragma: no cover - surfaced through GUI signal
            self.failed.emit(str(exc))


class SelectionThread(QThread):
    selected = Signal(object, float, float, float, float)
    failed = Signal(str)

    def __init__(
        self,
        pins: list[PinRecord],
        devices: set[str] | None,
        net_names: set[str],
        x_min: float,
        x_max: float,
        y_min: float,
        y_max: float,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._pins = pins
        self._devices = devices
        self._net_names = net_names
        self._x_min = x_min
        self._x_max = x_max
        self._y_min = y_min
        self._y_max = y_max

    def run(self) -> None:
        try:
            selected = filter_pins(
                self._pins,
                comp_devices=self._devices,
                net_names=self._net_names,
                x_min=self._x_min,
                x_max=self._x_max,
                y_min=self._y_min,
                y_max=self._y_max,
            )
            self.selected.emit(selected, self._x_min, self._x_max, self._y_min, self._y_max)
        except Exception as exc:  # pragma: no cover - surfaced through GUI signal
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    MAX_TABLE_ROWS = 5000

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.all_pins: list[PinRecord] = []
        self.selected_pins: list[PinRecord] = []
        self._visible_pins: list[PinRecord] = []
        self._loading_controls = False
        self._load_worker: LoadInputsThread | None = None
        self._selection_worker: SelectionThread | None = None
        self._pending_selection_update = False
        self._worker: GenerateThread | None = None
        self._table_sort_column: int | None = None
        self._table_sort_order = Qt.SortOrder.AscendingOrder
        self._all_net_names: list[str] = []
        self._net_check_states: dict[str, bool] = {}
        self._source_group_overrides: dict[int, str] = {}
        self._help_dialog: HelpDialog | None = None
        self._selection_timer = QTimer(self)
        self._selection_timer.setSingleShot(True)
        self._selection_timer.setInterval(150)
        self._selection_timer.timeout.connect(self._start_selection_update)

        self.project_edit = QLineEdit("Project1")
        self.design_edit = QLineEdit("HFSSDesign1")
        self.pin_path_edit = QLineEdit()
        self.pin_path_edit.setReadOnly(True)

        self.comp_list = QListWidget()
        self.comp_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.net_list = QListWidget()
        self.net_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.net_search_edit = QLineEdit()
        self.net_search_edit.setPlaceholderText("Search NET (*, ! supported)")

        self.x_min_spin = self._make_spin()
        self.x_max_spin = self._make_spin()
        self.y_min_spin = self._make_spin()
        self.y_max_spin = self._make_spin()
        self.right_rotation_spin = self._make_angle_spin(0.0)
        self.top_rotation_spin = self._make_angle_spin(270.0)
        self.left_rotation_spin = self._make_angle_spin(180.0)
        self.bottom_rotation_spin = self._make_angle_spin(90.0)

        self.selected_table = QTableWidget(0, 5)
        self.selected_table.setHorizontalHeaderLabels(["X", "Y", "NET_NAME", "SOURCE_GROUP", "SIDE"])
        self.selected_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.selected_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.selected_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.selected_table.horizontalHeader().setSortIndicatorShown(True)

        self.plot = CoordinatePlot()
        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.generate_button = QPushButton("Generate AEDT Script")
        self.reset_button = QPushButton("Reset Range")
        self.net_select_all_button = QPushButton("Select All")
        self.net_clear_all_button = QPushButton("Clear All")
        self.browse_pin_button = QPushButton("Browse Coordinate File")
        self.load_button = QPushButton("Load Inputs")
        self.source_group_edit = QLineEdit()
        self.source_group_edit.setPlaceholderText("HFSS group name, e.g. LongProbe")
        self.apply_source_selected_button = QPushButton("Apply to selected rows")
        self.apply_source_all_button = QPushButton("Apply to current coordinates")
        self.clear_source_overrides_button = QPushButton("Clear overrides")

        self._build_layout()
        self._connect_signals()
        self.resize(self._initial_size())

    def _build_layout(self) -> None:
        help_menu = self.menuBar().addMenu("Help")
        help_action = help_menu.addAction("How to Use", self.show_help)
        help_action.setShortcut(QKeySequence(QKeySequence.StandardKey.HelpContents))

        root = QWidget()
        layout = QVBoxLayout(root)

        project_group = self.project_group = QGroupBox("AEDT Target")
        project_form = QFormLayout(project_group)
        project_form.addRow("Project", self.project_edit)
        project_form.addRow("Design", self.design_edit)
        project_form.addRow("Right rotation", self.right_rotation_spin)
        project_form.addRow("Top rotation", self.top_rotation_spin)
        project_form.addRow("Left rotation", self.left_rotation_spin)
        project_form.addRow("Bottom rotation", self.bottom_rotation_spin)

        file_group = self.file_group = QGroupBox("Input Files")
        file_layout = QGridLayout(file_group)
        file_layout.addWidget(QLabel("Coordinate file"), 0, 0)
        file_layout.addWidget(self.pin_path_edit, 0, 1)
        file_layout.addWidget(self.browse_pin_button, 0, 2)
        file_layout.addWidget(QLabel("AEDT source groups: Source_probe name, or Source_Group when omitted"), 1, 0, 1, 3)
        file_layout.addWidget(self.load_button, 2, 2)
        self.browse_pin_button.clicked.connect(lambda: self._browse_file(self.pin_path_edit))
        self.load_button.clicked.connect(self.load_inputs)

        filter_group = self.filter_group = QGroupBox("COMP_DEVICE Selection")
        filter_layout = QGridLayout(filter_group)
        filter_layout.addWidget(QLabel("COMP_DEVICE (legacy Allegro only)"), 0, 0, 1, 4)
        filter_layout.addWidget(self.comp_list, 1, 0, 1, 4)
        filter_layout.addWidget(QLabel("X min"), 2, 0)
        filter_layout.addWidget(self.x_min_spin, 2, 1)
        filter_layout.addWidget(QLabel("X max"), 2, 2)
        filter_layout.addWidget(self.x_max_spin, 2, 3)
        filter_layout.addWidget(QLabel("Y min"), 3, 0)
        filter_layout.addWidget(self.y_min_spin, 3, 1)
        filter_layout.addWidget(QLabel("Y max"), 3, 2)
        filter_layout.addWidget(self.y_max_spin, 3, 3)
        filter_layout.addWidget(self.reset_button, 4, 3)

        net_group = self.net_group = QGroupBox("NET Selection")
        net_layout = QGridLayout(net_group)
        net_layout.addWidget(QLabel("NET_NAME"), 0, 0)
        net_layout.addWidget(self.net_list, 1, 0)
        net_actions = QWidget()
        net_actions_layout = QVBoxLayout(net_actions)
        net_actions_layout.addWidget(QLabel("Search"))
        net_actions_layout.addWidget(self.net_search_edit)
        net_actions_layout.addWidget(self.net_select_all_button)
        net_actions_layout.addWidget(self.net_clear_all_button)
        net_actions_layout.addStretch(1)
        net_layout.addWidget(net_actions, 1, 1)
        net_layout.setColumnStretch(0, 1)
        net_layout.setColumnStretch(1, 1)

        source_group = self.source_group_box = QGroupBox("Source Group Override")
        source_layout = QGridLayout(source_group)
        source_layout.addWidget(QLabel("HFSS group"), 0, 0)
        source_layout.addWidget(self.source_group_edit, 0, 1, 1, 2)
        source_layout.addWidget(self.apply_source_selected_button, 1, 0)
        source_layout.addWidget(self.apply_source_all_button, 1, 1)
        source_layout.addWidget(self.clear_source_overrides_button, 1, 2)

        left_content = self._left_content = QWidget()
        left_content_layout = QVBoxLayout(left_content)
        left_content_layout.setContentsMargins(0, 0, 0, 0)
        for group in (project_group, file_group, filter_group, net_group, source_group):
            left_content_layout.addWidget(group)
        left_content_layout.addStretch(1)

        # The controls need more height than small or scaled-up screens offer, so
        # they scroll when necessary; the Generate button always stays visible.
        left_scroll = self._left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.Shape.NoFrame)
        left_scroll.setWidget(left_content)
        left_scroll.setMinimumWidth(
            left_content.minimumSizeHint().width() + left_scroll.verticalScrollBar().sizeHint().width()
        )

        left = self._left_panel = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(left_scroll, 1)
        left_layout.addWidget(self.generate_button)

        preview_splitter = self.preview_splitter = QSplitter(Qt.Orientation.Horizontal)
        preview_splitter.addWidget(self.selected_table)
        preview_splitter.addWidget(self.plot)
        preview_splitter.setSizes([460, 560])

        right = self._right_panel = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(preview_splitter, 1)
        right_layout.addWidget(QLabel("Log"))
        right_layout.addWidget(self.log_edit, 0)

        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_splitter.addWidget(left)
        main_splitter.addWidget(right)
        main_splitter.setSizes([340, 820])
        layout.addWidget(main_splitter)
        self.setCentralWidget(root)

    def full_content_height(self) -> int:
        """Window height at which the left panel shows every control without scrolling."""
        left_height = self._left_panel.minimumSizeHint().height()
        right_height = self._right_panel.minimumSizeHint().height()
        chrome_height = self.minimumSizeHint().height() - max(left_height, right_height)
        full_left_height = (
            left_height
            - self._left_scroll.minimumSizeHint().height()
            + self._left_content.minimumSizeHint().height()
        )
        return chrome_height + max(full_left_height, right_height)

    def _initial_size(self) -> QSize:
        """Open large enough to show every control, but never larger than the screen."""
        width, height = 1180, max(760, self.full_content_height())
        screen = self.screen()
        if screen is not None:
            available = screen.availableGeometry()
            width = min(width, available.width() - 40)
            height = min(height, available.height() - 80)
        return QSize(width, height)

    def _connect_signals(self) -> None:
        self.comp_list.itemChanged.connect(lambda _: self._request_selection_update())
        self.net_list.itemChanged.connect(self._on_net_item_changed)
        self.net_search_edit.textChanged.connect(self._refresh_net_list)
        self.net_select_all_button.clicked.connect(lambda: self._set_all_nets_checked(True))
        self.net_clear_all_button.clicked.connect(lambda: self._set_all_nets_checked(False))
        self.apply_source_selected_button.clicked.connect(self.apply_source_group_to_selected_rows)
        self.apply_source_all_button.clicked.connect(self.apply_source_group_to_current_coordinates)
        self.clear_source_overrides_button.clicked.connect(self.clear_source_group_overrides)
        self.reset_button.clicked.connect(self.reset_range)
        self.generate_button.clicked.connect(self.generate_script)
        self.plot.boundsChanged.connect(self._apply_plot_bounds)
        self.selected_table.horizontalHeader().sectionClicked.connect(self._sort_selected_table_by_column)
        self.selected_table.itemSelectionChanged.connect(self._on_table_selection_changed)
        for spin in (self.x_min_spin, self.x_max_spin, self.y_min_spin, self.y_max_spin):
            spin.valueChanged.connect(lambda _: self._request_selection_update())

    def _make_spin(self) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(-1_000_000_000.0, 1_000_000_000.0)
        spin.setDecimals(RANGE_DECIMALS)
        spin.setSingleStep(0.1)
        return spin

    def _make_angle_spin(self, value: float) -> QDoubleSpinBox:
        spin = self._make_spin()
        spin.setRange(-360000.0, 360000.0)
        spin.setValue(value)
        return spin

    def show_help(self) -> None:
        if self._help_dialog is not None and self._help_dialog.isVisible():
            self._help_dialog.raise_()
            self._help_dialog.activateWindow()
            return
        if self._help_dialog is None:
            # No parent: an owned dialog would always stay in front of this window,
            # and the help is meant to be kept open next to it.
            self._help_dialog = HelpDialog(extra_figures={"gui-overview": render_gui_overview})
        self._help_dialog.show()

    def show_sample_state(self) -> None:
        """Fill the window with a small built-in example (used for the help picture)."""
        pins = _sample_pins()
        self.pin_path_edit.setText("C:\\Work\\cis_coordinates.xlsx")
        self._apply_loaded_pins(pins)
        self.selected_pins = list(pins)
        self._refresh_table()
        bounds = (self.x_min_spin.value(), self.x_max_spin.value(), self.y_min_spin.value(), self.y_max_spin.value())
        self.plot.set_data(pins, pins, bounds)
        self.preview_splitter.setSizes([400, 380])
        self.selected_table.selectRow(1)
        self._log(f"Loaded {len(pins)} pin rows.")
        self._log("Coordinates were automatically recentered so the input bounding-box center is at the origin.")
        self._log(f"Selection updated: {len(pins)} rows selected, {len(pins)} rows displayed.")

    def _browse_file(self, target: QLineEdit) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select input file", "", "Input files (*.csv *.xlsx);;All files (*.*)")
        if path:
            target.setText(path)

    def load_inputs(self) -> None:
        pin_path = self.pin_path_edit.text().strip()
        if not pin_path:
            QMessageBox.warning(self, "Missing input", "Select a pin report before loading.")
            return
        self._selection_timer.stop()
        self._set_controls_enabled(False)
        self._log("Starting input load...")
        self._load_worker = LoadInputsThread(Path(pin_path), self)
        self._load_worker.progress.connect(self._log)
        self._load_worker.loaded.connect(self._on_inputs_loaded)
        self._load_worker.failed.connect(self._on_load_failed)
        self._load_worker.finished.connect(lambda: setattr(self, "_load_worker", None))
        self._load_worker.finished.connect(self._load_worker.deleteLater)
        self._load_worker.start()

    def _on_inputs_loaded(self, pins: list[PinRecord]) -> None:
        self._apply_loaded_pins(pins)
        self._log(f"Input load complete: {len(self.all_pins)} pin rows.")
        self._log("Coordinates were automatically recentered so the input bounding-box center is at the origin.")
        self._start_selection_update()

    def _apply_loaded_pins(self, pins: list[PinRecord]) -> None:
        """Adopt ``pins`` as the loaded input and reset every filter control to match."""
        self.all_pins = pins
        self._source_group_overrides.clear()
        self._loading_controls = True
        try:
            devices = get_comp_devices(self.all_pins)
            if devices and any(not pin.comp_device for pin in self.all_pins):
                # Without an entry of their own, rows with an empty COMP_DEVICE
                # could never be selected once the device filter is in use.
                devices = ["", *devices]
            self._populate_check_list(self.comp_list, devices, blank_label=BLANK_LABEL)
            net_names = get_net_names(self.all_pins)
            if any(not pin.net_name for pin in self.all_pins):
                net_names = ["", *net_names]
            self._all_net_names = net_names
            self._net_check_states = {net_name: True for net_name in self._all_net_names}
            self.net_search_edit.blockSignals(True)
            self.net_search_edit.clear()
            self.net_search_edit.blockSignals(False)
            self._refresh_net_list()
            self._set_range_to_all_pins()
        finally:
            self._loading_controls = False

    def _set_range_to_all_pins(self) -> None:
        """Set the range spin boxes so that they enclose every loaded coordinate.

        The spin boxes hold a fixed number of decimals, so plain rounding could
        pull a bound inside the data and silently drop the outermost pins.
        """
        if not self.all_pins:
            return
        self.x_min_spin.setValue(_range_lower_bound(min(pin.pin_x for pin in self.all_pins)))
        self.x_max_spin.setValue(_range_upper_bound(max(pin.pin_x for pin in self.all_pins)))
        self.y_min_spin.setValue(_range_lower_bound(min(pin.pin_y for pin in self.all_pins)))
        self.y_max_spin.setValue(_range_upper_bound(max(pin.pin_y for pin in self.all_pins)))

    def _on_load_failed(self, message: str) -> None:
        self._log(f"Input error: {message}")
        self._set_controls_enabled(True)
        QMessageBox.critical(self, "Input error", message)

    def reset_range(self) -> None:
        if not self.all_pins:
            return
        self._loading_controls = True
        try:
            self._set_range_to_all_pins()
        finally:
            self._loading_controls = False
        self._request_selection_update()

    def update_selection(self) -> None:
        self._start_selection_update()

    def _request_selection_update(self) -> None:
        if self._loading_controls:
            return
        if not self.all_pins:
            self.selected_pins = []
            self._refresh_table()
            self.plot.set_data([], [], None)
            return
        # The filter inputs stay usable while the selection catches up, so typing
        # a range value or dragging a plot edge is never interrupted. Only the
        # actions that need an up-to-date selection wait for it.
        self._set_action_controls_enabled(False)
        if self._selection_worker is not None:
            self._pending_selection_update = True
            return
        self._selection_timer.start()

    def _start_selection_update(self) -> None:
        if self._loading_controls:
            return
        self._selection_timer.stop()
        if not self.all_pins:
            self.selected_pins = []
            self._refresh_table()
            self.plot.set_data([], [], None)
            self._set_controls_enabled(True)
            return
        if self._selection_worker is not None:
            self._pending_selection_update = True
            return
        devices = self._checked_devices()
        nets = self._checked_nets()
        x_min, x_max = sorted((self.x_min_spin.value(), self.x_max_spin.value()))
        y_min, y_max = sorted((self.y_min_spin.value(), self.y_max_spin.value()))
        self._set_action_controls_enabled(False)
        self._log("Updating coordinate selection...")
        worker = SelectionThread(self.all_pins, devices, nets, x_min, x_max, y_min, y_max, self)
        self._selection_worker = worker
        worker.selected.connect(self._on_selection_ready)
        worker.failed.connect(self._on_selection_failed)
        worker.finished.connect(self._on_selection_finished)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_selection_ready(self, selected: list[PinRecord], x_min: float, x_max: float, y_min: float, y_max: float) -> None:
        self.selected_pins = selected
        self._apply_current_table_sort()
        self._refresh_table()
        self.plot.set_data(self.all_pins, self.selected_pins, (x_min, x_max, y_min, y_max))
        displayed = min(len(self.selected_pins), self.MAX_TABLE_ROWS)
        self._log(f"Selection updated: {len(self.selected_pins)} rows selected, {displayed} rows displayed.")

    def _on_selection_failed(self, message: str) -> None:
        self._log(f"Selection update failed: {message}")
        QMessageBox.critical(self, "Selection update failed", message)

    def _on_selection_finished(self) -> None:
        self._selection_worker = None
        if self._pending_selection_update:
            self._pending_selection_update = False
            self._selection_timer.start()
            return
        if self._selection_timer.isActive():
            return
        self._set_controls_enabled(True)

    def _apply_plot_bounds(self, x_min: float, x_max: float, y_min: float, y_max: float) -> None:
        self._loading_controls = True
        self.x_min_spin.setValue(x_min)
        self.x_max_spin.setValue(x_max)
        self.y_min_spin.setValue(y_min)
        self.y_max_spin.setValue(y_max)
        self._loading_controls = False
        self._request_selection_update()

    def _checked_devices(self) -> set[str] | None:
        if self.comp_list.count() == 0:
            return None
        return self._checked_list_values(self.comp_list)

    def _checked_nets(self) -> set[str]:
        return {net_name for net_name, checked in self._net_check_states.items() if checked}

    def _set_all_nets_checked(self, checked: bool) -> None:
        comp_state = self._check_state_snapshot(self.comp_list)
        try:
            for net_name in self._filtered_net_names():
                self._net_check_states[net_name] = checked
            self._refresh_net_list()
        finally:
            self._restore_check_state_snapshot(self.comp_list, comp_state)
        self._request_selection_update()

    def _on_net_item_changed(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.ItemDataRole.UserRole)
        net_name = str(data) if data is not None else item.text()
        self._net_check_states[net_name] = item.checkState() == Qt.CheckState.Checked
        self._request_selection_update()

    def _filtered_net_names(self) -> list[str]:
        query = self.net_search_edit.text()
        return [net_name for net_name in self._all_net_names if _net_matches_search(net_name, query)]

    def _refresh_net_list(self) -> None:
        self.net_list.blockSignals(True)
        self.net_list.setUpdatesEnabled(False)
        try:
            self.net_list.clear()
            for net_name in self._filtered_net_names():
                item = QListWidgetItem(_net_display_text(net_name))
                item.setData(Qt.ItemDataRole.UserRole, net_name)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(
                    Qt.CheckState.Checked if self._net_check_states.get(net_name, True) else Qt.CheckState.Unchecked
                )
                self.net_list.addItem(item)
        finally:
            self.net_list.setUpdatesEnabled(True)
            self.net_list.blockSignals(False)

    def _checked_list_values(self, widget: QListWidget) -> set[str]:
        values: set[str] = set()
        for index in range(widget.count()):
            item = widget.item(index)
            if item.checkState() == Qt.CheckState.Checked:
                data = item.data(Qt.ItemDataRole.UserRole)
                values.add(str(data) if data is not None else item.text())
        return values

    def _check_state_snapshot(self, widget: QListWidget) -> dict[str, Qt.CheckState]:
        snapshot: dict[str, Qt.CheckState] = {}
        for index in range(widget.count()):
            item = widget.item(index)
            data = item.data(Qt.ItemDataRole.UserRole)
            key = str(data) if data is not None else item.text()
            snapshot[key] = item.checkState()
        return snapshot

    def _restore_check_state_snapshot(self, widget: QListWidget, snapshot: dict[str, Qt.CheckState]) -> None:
        widget.blockSignals(True)
        try:
            for index in range(widget.count()):
                item = widget.item(index)
                data = item.data(Qt.ItemDataRole.UserRole)
                key = str(data) if data is not None else item.text()
                if key in snapshot:
                    item.setCheckState(snapshot[key])
        finally:
            widget.blockSignals(False)

    def _populate_check_list(self, widget: QListWidget, values: list[str], blank_label: str | None = None) -> None:
        widget.blockSignals(True)
        widget.setUpdatesEnabled(False)
        try:
            widget.clear()
            for value in values:
                text = blank_label if blank_label is not None and value == "" else value
                item = QListWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, value)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked)
                widget.addItem(item)
        finally:
            widget.setUpdatesEnabled(True)
            widget.blockSignals(False)

    def _refresh_table(self) -> None:
        display_pins = self.selected_pins[: self.MAX_TABLE_ROWS]
        sides = classify_pin_sides(self.selected_pins)
        self._visible_pins = list(display_pins)
        self.selected_table.blockSignals(True)
        self.selected_table.setUpdatesEnabled(False)
        try:
            self.selected_table.clearSelection()
            self.selected_table.setRowCount(len(display_pins))
            for row, pin in enumerate(display_pins):
                values = [
                    _format_coordinate(pin.pin_x),
                    _format_coordinate(pin.pin_y),
                    pin.net_name,
                    self._effective_source_group_for_pin(pin),
                    sides[row],
                ]
                for column, value in enumerate(values):
                    self.selected_table.setItem(row, column, QTableWidgetItem(value))
            self.selected_table.resizeColumnsToContents()
        finally:
            self.selected_table.setUpdatesEnabled(True)
            self.selected_table.blockSignals(False)
        self.plot.set_highlighted_pins([])

    def _sort_selected_table_by_column(self, column: int) -> None:
        if self._table_sort_column == column:
            self._table_sort_order = (
                Qt.SortOrder.DescendingOrder
                if self._table_sort_order == Qt.SortOrder.AscendingOrder
                else Qt.SortOrder.AscendingOrder
            )
        else:
            self._table_sort_column = column
            self._table_sort_order = Qt.SortOrder.AscendingOrder
        self._apply_current_table_sort()
        self.selected_table.horizontalHeader().setSortIndicator(column, self._table_sort_order)
        self._refresh_table()

    def _apply_current_table_sort(self) -> None:
        column = self._table_sort_column
        if column is None or not self.selected_pins:
            return
        reverse = self._table_sort_order == Qt.SortOrder.DescendingOrder
        pins = self.selected_pins
        # Keys are resolved up front: the SIDE of a pin depends on the whole
        # selection, and list.sort() empties the list for as long as it runs.
        keys = self._table_sort_keys(pins, column)
        order = sorted(range(len(pins)), key=keys.__getitem__, reverse=reverse)
        self.selected_pins = [pins[index] for index in order]

    def _table_sort_keys(self, pins: list[PinRecord], column: int) -> list:
        if column == 0:
            return [pin.pin_x for pin in pins]
        if column == 1:
            return [pin.pin_y for pin in pins]
        if column == 2:
            return [pin.net_name.upper() for pin in pins]
        if column == 3:
            return [self._effective_source_group_for_pin(pin).upper() for pin in pins]
        if column == 4:
            return classify_pin_sides(pins)
        return [""] * len(pins)

    def _effective_source_group_for_pin(self, pin: PinRecord) -> str:
        return self._source_group_overrides.get(id(pin), source_group_name_for_pin(pin))

    def _effective_pin(self, pin: PinRecord) -> PinRecord:
        source_group = self._source_group_overrides.get(id(pin))
        if source_group is None:
            return pin
        return replace(pin, source_probe_name=source_group)

    def _effective_pins(self) -> list[PinRecord]:
        return [self._effective_pin(pin) for pin in self.selected_pins]

    def apply_source_group_to_selected_rows(self) -> None:
        source_group = self.source_group_edit.text().strip()
        if not source_group:
            QMessageBox.warning(self, "Missing source group", "Enter an HFSS source group name first.")
            return
        rows = sorted(index.row() for index in self.selected_table.selectionModel().selectedRows())
        if not rows:
            QMessageBox.warning(self, "No table rows", "Select one or more preview table rows first.")
            return
        for row in rows:
            if 0 <= row < len(self._visible_pins):
                self._source_group_overrides[id(self._visible_pins[row])] = source_group
        self._refresh_table()
        self._log(f"Applied source group override to {len(rows)} table rows: {source_group}")

    def apply_source_group_to_current_coordinates(self) -> None:
        source_group = self.source_group_edit.text().strip()
        if not source_group:
            QMessageBox.warning(self, "Missing source group", "Enter an HFSS source group name first.")
            return
        for pin in self.selected_pins:
            self._source_group_overrides[id(pin)] = source_group
        self._refresh_table()
        self._log(f"Applied source group override to {len(self.selected_pins)} selected coordinates: {source_group}")

    def clear_source_group_overrides(self) -> None:
        count = len(self._source_group_overrides)
        self._source_group_overrides.clear()
        self._refresh_table()
        self._log(f"Cleared {count} source group overrides.")

    def _on_table_selection_changed(self) -> None:
        rows = sorted(index.row() for index in self.selected_table.selectionModel().selectedRows())
        highlighted = [self._visible_pins[row] for row in rows if 0 <= row < len(self._visible_pins)]
        self.plot.set_highlighted_pins(highlighted)

    def generate_script(self) -> None:
        if not self.selected_pins:
            QMessageBox.warning(self, "No selection", "Load input files and select at least one coordinate.")
            return
        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save AEDT IronPython script",
            "cis_probe_placement.py",
            "Python script (*.py);;All files (*.*)",
        )
        if not output_path:
            return
        options = GenerationOptions(
            project_name=self.project_edit.text().strip() or "Project1",
            design_name=self.design_edit.text().strip() or "HFSSDesign1",
            right_rotation_angle=self.right_rotation_spin.value(),
            top_rotation_angle=self.top_rotation_spin.value(),
            left_rotation_angle=self.left_rotation_spin.value(),
            bottom_rotation_angle=self.bottom_rotation_spin.value(),
        )
        self.generate_button.setEnabled(False)
        self._set_controls_enabled(False)
        effective_pins = self._effective_pins()
        self._log(f"Generating script for {len(effective_pins)} coordinates using row-level HFSS source groups...")
        self._log_selection_summary(effective_pins)
        self._worker = GenerateThread(effective_pins, options, Path(output_path), self)
        self._worker.generated.connect(self._on_generated)
        self._worker.failed.connect(self._on_generate_failed)
        self._worker.finished.connect(self._on_generate_finished)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    def _on_generate_finished(self) -> None:
        self._worker = None
        self._set_controls_enabled(True)

    def _on_generated(self, result: GenerationResult, output_path: str) -> None:
        self._log(f"Script saved: {output_path}")
        for warning in result.warnings:
            self._log(f"Warning: {warning}")
        if result.name_mappings:
            self._log(f"Sanitized {len(result.name_mappings)} generated object names.")
            for mapping in result.name_mappings[:100]:
                self._log(f"  {mapping.original} -> {mapping.generated}")
            if len(result.name_mappings) > 100:
                self._log("  ... additional mappings omitted from GUI log")

    def _on_generate_failed(self, message: str) -> None:
        self._log(f"Generation failed: {message}")
        QMessageBox.critical(self, "Generation failed", message)

    def _log(self, message: str) -> None:
        self.log_edit.append(message)

    def _log_selection_summary(self, pins: list[PinRecord]) -> None:
        side_counts = Counter(classify_pin_sides(pins))
        source_counts = Counter(source_group_name_for_pin(pin) for pin in pins)
        self._log("Side summary: " + ", ".join(f"{side}={side_counts.get(side, 0)}" for side in SIDE_LABELS))
        self._log("Source group summary: " + ", ".join(f"{name}={count}" for name, count in sorted(source_counts.items())))

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        # A QThread must not be destroyed while it is still running, so let any
        # worker finish before the window (their parent) goes away.
        self._selection_timer.stop()
        for worker in (self._load_worker, self._selection_worker, self._worker):
            if worker is not None and worker.isRunning():
                worker.wait()
        if self._help_dialog is not None:
            self._help_dialog.close()
        super().closeEvent(event)

    def _set_action_controls_enabled(self, enabled: bool) -> None:
        """Enable or disable only the actions that require a settled selection."""
        for widget in (self.browse_pin_button, self.load_button, self.generate_button):
            widget.setEnabled(enabled)

    def _set_controls_enabled(self, enabled: bool) -> None:
        for widget in (
            self.project_edit,
            self.design_edit,
            self.browse_pin_button,
            self.load_button,
            self.comp_list,
            self.net_list,
            self.net_search_edit,
            self.net_select_all_button,
            self.net_clear_all_button,
            self.x_min_spin,
            self.x_max_spin,
            self.y_min_spin,
            self.y_max_spin,
            self.right_rotation_spin,
            self.top_rotation_spin,
            self.left_rotation_spin,
            self.bottom_rotation_spin,
            self.source_group_edit,
            self.apply_source_selected_button,
            self.apply_source_all_button,
            self.clear_source_overrides_button,
            self.reset_button,
            self.generate_button,
            self.selected_table,
            self.plot,
        ):
            widget.setEnabled(enabled)


def _sample_pins() -> list[PinRecord]:
    """Small four-sided, two-probe layout already centred on the origin."""
    pins: list[PinRecord] = []

    def add(x: float, y: float, net: str, probe: str) -> None:
        pins.append(PinRecord("", str(len(pins) + 1), "", "", "", x, y, net, probe))

    steps = [-2.4, -1.6, -0.8, 0.0, 0.8, 1.6, 2.4]
    for index, offset in enumerate(steps):
        probe = "LongProbe" if index % 2 == 0 else "ShortProbe"
        net = "DGND" if index == 3 else f"SIG_{index + 1}"
        add(3.6, offset, f"R_{net}", probe)
        add(offset, 3.6, f"T_{net}", probe)
        add(-3.6, offset, f"L_{net}", probe)
        add(offset, -3.6, f"B_{net}", probe)
    return pins


GUI_OVERVIEW_WIDTH = 860
GUI_OVERVIEW_WINDOW_WIDTH = 1270


def render_gui_overview(dpr: float) -> QImage:
    """Picture of the main window showing the built-in example, with numbered markers."""
    window = MainWindow()
    try:
        window.resize(GUI_OVERVIEW_WINDOW_WIDTH, window.full_content_height())
        window.show_sample_state()
        shot = window.grab().toImage()
        scale = GUI_OVERVIEW_WIDTH / window.width()
        dpr = max(float(dpr), 1.0)
        image = shot.scaledToWidth(round(GUI_OVERVIEW_WIDTH * dpr), Qt.TransformationMode.SmoothTransformation)
        image = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(dpr)

        markers = [
            (window.project_group, QPoint(104, 2)),
            (window.file_group, QPoint(84, 2)),
            (window.filter_group, QPoint(170, 2)),
            (window.net_group, QPoint(110, 2)),
            (window.source_group_box, QPoint(162, 2)),
            (window.generate_button, QPoint(40, 12)),
            (window.selected_table, QPoint(10, 10)),
            (window.plot, QPoint(30, 30)),
            (window.log_edit, QPoint(window.log_edit.width() - 26, 20)),
        ]
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setPen(QPen(QColor("#94a3b8"), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(0, 0, GUI_OVERVIEW_WIDTH - 1, round(window.height() * scale) - 1)
        for number, (widget, offset) in enumerate(markers, start=1):
            position = widget.mapTo(window, offset)
            draw_callout(painter, QPointF(position.x() * scale, position.y() * scale), str(number))
        painter.end()
        return image
    finally:
        window.deleteLater()


def run_smoke_check() -> int:
    """Build the main window and the help without entering the event loop.

    Returns 0 when everything needed at run time is in place: the Qt plugins,
    the bundled help document and every picture it refers to. Packaged builds
    are verified with this before they are published.
    """
    try:
        app = QApplication.instance() or QApplication(sys.argv)
        window = MainWindow()
        window.show_sample_state()
        dialog = HelpDialog(extra_figures={"gui-overview": render_gui_overview})
        problems = [f"missing help picture: {name}" for name in dialog.missing_figures()]
        if dialog.toc.topLevelItemCount() == 0:
            problems.append("help document has no sections")
        if len(window.selected_pins) != window.selected_table.rowCount():
            problems.append("preview table does not show the sample coordinates")
        app.processEvents()
    except Exception:
        problems = [traceback.format_exc()]
    if problems:
        _report_smoke_problems(problems)
        return 1
    return 0


def _report_smoke_problems(problems: list[str]) -> None:
    text = "\n".join(problems) + "\n"
    log_path = os.environ.get("CIS_PROBE_SMOKE_LOG")
    if log_path:
        try:
            Path(log_path).write_text(text, encoding="utf-8")
        except OSError:
            pass
    if sys.stderr is not None:
        sys.stderr.write(text)


def run_app() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()
