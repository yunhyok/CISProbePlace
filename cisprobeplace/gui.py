from __future__ import annotations

from collections import Counter
from dataclasses import replace
import fnmatch
import sys
from pathlib import Path

from PySide6.QtCore import QPointF, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QFormLayout,
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
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .data_io import filter_pins, get_comp_devices, get_net_names, load_pin_records
from .models import GenerationOptions, GenerationResult, PinRecord
from .script_builder import build_script, classify_pin_side, source_group_name_for_pin


APP_TITLE = f"CIS Probe Placement Scriptor v{__version__}"
BLANK_NET_LABEL = "(blank)"
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
    return BLANK_NET_LABEL if value == "" else value


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
        matched = any(fnmatch.fnmatchcase(candidate, pattern) for candidate in candidates)
    else:
        matched = any(pattern in candidate for candidate in candidates)
    return not matched if negate else matched


def _tutorial_text() -> str:
    return """CIS Probe Placement Scriptor Tutorial

1. 입력 파일 종류
- 기본 입력 파일은 CSV 또는 XLSX입니다.
- 필수 열은 X좌표, Y좌표, Net Name입니다.
- 선택 열 Source_probe name을 추가하면 각 좌표가 복제할 HFSS source group을 row별로 지정할 수 있습니다.
- Source_probe name 열이 없거나 특정 cell이 비어 있으면 1종 probe로 보고 기본 HFSS group Source_Group을 사용합니다.
- 기존 Allegro symbol pin report도 하위 호환으로 읽을 수 있습니다. 기존 형식에서는 COMP_DEVICE 값이 Source_<COMP_DEVICE> group으로 변환됩니다.

2. 새 좌표 파일 header와 alias
필수 header:
X좌표,Y좌표,Net Name

선택 header:
Source_probe name

허용 alias:
- X좌표: X좌표, X, PIN_X, PIX_X
- Y좌표: Y좌표, Y, PIN_Y
- Net Name: Net Name, NET_NAME, NET
- Source_probe name: Source_probe name, SOURCE_PROBE_NAME, PROBE_GROUP

3. 각 열의 의미
- X좌표: probe를 배치할 X 좌표입니다. 단위는 HFSS script에서 mm로 사용됩니다.
- Y좌표: probe를 배치할 Y 좌표입니다. 단위는 HFSS script에서 mm로 사용됩니다.
- Net Name: 해당 좌표의 net 이름입니다. DGND는 복제된 sheet object에 Perfect E boundary를 자동 부여합니다.
- Source_probe name: HFSS에 미리 만들어 둔 source group 이름을 그대로 적습니다. 접두어를 자동으로 붙이지 않습니다.

4. 1종 probe 입력 예시
X좌표,Y좌표,Net Name
10,5,SIGNAL_A
5,10,SIGNAL_B
0,5,DGND

이 경우 모든 row는 HFSS group Source_Group을 사용합니다.

5. 2종/2열 probe 입력 예시
X좌표,Y좌표,Net Name,Source_probe name
10,5,SIGNAL_A,LongProbe
10,6,SIGNAL_A_RETURN,ShortProbe
5,10,SIGNAL_B,LongProbe
5,11,SIGNAL_B_RETURN,ShortProbe
0,5,DGND,ShortProbe

위 예시는 LongProbe와 ShortProbe라는 HFSS group을 row별로 직접 지정합니다. 같은 side 안에 LongProbe와 ShortProbe가 섞여도 각 row의 Source_probe name에 따라 복제 source가 선택됩니다.

6. HFSS source group 준비 방법
- AEDT/HFSS에서 원본 probe object를 먼저 원하는 기준 방향으로 배치합니다.
- 1종 probe라면 원본 object들을 Source_Group group 안에 넣습니다.
- 2종 이상이라면 입력 파일의 Source_probe name 값과 같은 group을 만듭니다. 예: LongProbe, ShortProbe.
- 각 group 안에는 해당 probe를 구성하는 모든 solid/sheet object가 포함되어야 합니다.
- 생성된 script는 실행 초기에 필요한 group이 없거나 비어 있으면 명확한 오류를 내고 중단합니다.

7. CIS side 인식과 회전각
- 선택된 좌표 전체의 bounding box를 기준으로 각 좌표가 가장 가까운 변을 찾습니다.
- max X에 가장 가까우면 right, max Y는 top, min X는 left, min Y는 bottom입니다.
- 거리가 같은 경우 우선순위는 right, top, left, bottom입니다.
- HFSS DuplicateAroundAxis 회전은 시계 방향 기준으로 사용합니다.
- 기본 변수는 CISRotAng_Right=0, CISRotAng_Top=270, CISRotAng_Left=180, CISRotAng_Bottom=90입니다.
- 최초 source object 방향이 다르면 GUI의 Right/Top/Left/Bottom 회전값을 조정해서 대응합니다.

8. GUI 사용 순서
1) Project와 Design 이름을 입력합니다.
2) 필요한 경우 Right/Top/Left/Bottom 회전각을 조정합니다.
3) CSV/XLSX 파일을 선택하고 Load Inputs를 누릅니다.
4) NET_NAME과 좌표 범위로 배치할 row를 선택합니다. 기존 Allegro 파일이면 COMP_DEVICE 선택도 사용할 수 있습니다.
5) Preview table에서 X, Y, NET_NAME, SOURCE_GROUP, SIDE를 확인합니다.
6) Source group을 임시로 바꾸려면 Source Group Override에 group명을 입력합니다.
   - Apply to selected rows: table에서 선택한 row에만 적용합니다.
   - Apply to current coordinates: 현재 선택된 모든 좌표에 일괄 적용합니다.
   - Clear overrides: 원본 파일에서 읽은 Source_probe name 또는 기본 Source_Group으로 되돌립니다.
7) Generate AEDT Script를 눌러 IronPython script를 저장합니다.
8) AEDT/HFSS에서 해당 project/design을 열고 script를 실행합니다.

9. 주의사항
- Source_probe name 값은 HFSS group 이름 그대로입니다. LongProbe라고 쓰면 HFSS group도 LongProbe여야 합니다.
- Source_probe name이 비어 있는 row만 Source_Group으로 fallback됩니다.
- GUI override는 현재 script 생성에만 반영되며 원본 CSV/XLSX 파일은 수정하지 않습니다.
"""


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
        devices: set[str],
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
        self.resize(1180, 760)
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
        self._tutorial_dialog: QDialog | None = None
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

    def _build_layout(self) -> None:
        tutorial_menu = self.menuBar().addMenu("Tutorial")
        tutorial_menu.addAction("How to Use", self.show_tutorial)

        root = QWidget()
        layout = QVBoxLayout(root)

        project_group = QGroupBox("AEDT Target")
        project_form = QFormLayout(project_group)
        project_form.addRow("Project", self.project_edit)
        project_form.addRow("Design", self.design_edit)
        project_form.addRow("Right rotation", self.right_rotation_spin)
        project_form.addRow("Top rotation", self.top_rotation_spin)
        project_form.addRow("Left rotation", self.left_rotation_spin)
        project_form.addRow("Bottom rotation", self.bottom_rotation_spin)

        file_group = QGroupBox("Input Files")
        file_layout = QGridLayout(file_group)
        file_layout.addWidget(QLabel("Coordinate file"), 0, 0)
        file_layout.addWidget(self.pin_path_edit, 0, 1)
        file_layout.addWidget(self.browse_pin_button, 0, 2)
        file_layout.addWidget(QLabel("AEDT source groups: Source_probe name, or Source_Group when omitted"), 1, 0, 1, 3)
        file_layout.addWidget(self.load_button, 2, 2)
        self.browse_pin_button.clicked.connect(lambda: self._browse_file(self.pin_path_edit))
        self.load_button.clicked.connect(self.load_inputs)

        filter_group = QGroupBox("COMP_DEVICE Selection")
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

        net_group = QGroupBox("NET Selection")
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

        source_group = QGroupBox("Source Group Override")
        source_layout = QGridLayout(source_group)
        source_layout.addWidget(QLabel("HFSS group"), 0, 0)
        source_layout.addWidget(self.source_group_edit, 0, 1, 1, 2)
        source_layout.addWidget(self.apply_source_selected_button, 1, 0)
        source_layout.addWidget(self.apply_source_all_button, 1, 1)
        source_layout.addWidget(self.clear_source_overrides_button, 1, 2)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(project_group)
        left_layout.addWidget(file_group)
        left_layout.addWidget(filter_group)
        left_layout.addWidget(net_group)
        left_layout.addWidget(source_group)
        left_layout.addStretch(1)
        left_layout.addWidget(self.generate_button)

        preview_splitter = QSplitter(Qt.Orientation.Horizontal)
        preview_splitter.addWidget(self.selected_table)
        preview_splitter.addWidget(self.plot)
        preview_splitter.setSizes([460, 560])

        right = QWidget()
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
        spin.setDecimals(6)
        spin.setSingleStep(0.1)
        return spin

    def _make_angle_spin(self, value: float) -> QDoubleSpinBox:
        spin = self._make_spin()
        spin.setRange(-360000.0, 360000.0)
        spin.setValue(value)
        return spin

    def show_tutorial(self) -> None:
        if self._tutorial_dialog is not None and self._tutorial_dialog.isVisible():
            self._tutorial_dialog.raise_()
            self._tutorial_dialog.activateWindow()
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("CIS Probe Placement Tutorial")
        dialog.resize(820, 660)
        layout = QVBoxLayout(dialog)
        text = QTextEdit(dialog)
        text.setObjectName("tutorial_text")
        text.setReadOnly(True)
        text.setPlainText(_tutorial_text())
        close_button = QPushButton("Close", dialog)
        close_button.clicked.connect(dialog.close)
        layout.addWidget(text, 1)
        layout.addWidget(close_button, 0, alignment=Qt.AlignmentFlag.AlignRight)
        self._tutorial_dialog = dialog
        dialog.show()

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
        self._load_worker.start()

    def _on_inputs_loaded(self, pins: list[PinRecord]) -> None:
        self.all_pins = pins
        self._source_group_overrides.clear()
        self._loading_controls = True
        self._populate_check_list(self.comp_list, get_comp_devices(self.all_pins))
        net_names = get_net_names(self.all_pins)
        if any(not pin.net_name for pin in self.all_pins):
            net_names = ["", *net_names]
        self._all_net_names = net_names
        self._net_check_states = {net_name: True for net_name in self._all_net_names}
        self.net_search_edit.blockSignals(True)
        self.net_search_edit.clear()
        self.net_search_edit.blockSignals(False)
        self._refresh_net_list()
        if self.all_pins:
            self.x_min_spin.setValue(min(pin.pin_x for pin in self.all_pins))
            self.x_max_spin.setValue(max(pin.pin_x for pin in self.all_pins))
            self.y_min_spin.setValue(min(pin.pin_y for pin in self.all_pins))
            self.y_max_spin.setValue(max(pin.pin_y for pin in self.all_pins))
        self._loading_controls = False
        self._log(f"Input load complete: {len(self.all_pins)} pin rows.")
        self._start_selection_update()

    def _on_load_failed(self, message: str) -> None:
        self._log(f"Input error: {message}")
        self._set_controls_enabled(True)
        QMessageBox.critical(self, "Input error", message)

    def reset_range(self) -> None:
        if not self.all_pins:
            return
        self._loading_controls = True
        self.x_min_spin.setValue(min(pin.pin_x for pin in self.all_pins))
        self.x_max_spin.setValue(max(pin.pin_x for pin in self.all_pins))
        self.y_min_spin.setValue(min(pin.pin_y for pin in self.all_pins))
        self.y_max_spin.setValue(max(pin.pin_y for pin in self.all_pins))
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
        if self._selection_worker and self._selection_worker.isRunning():
            self._pending_selection_update = True
            return
        self._selection_timer.start()

    def _start_selection_update(self) -> None:
        if self._loading_controls:
            return
        if not self.all_pins:
            self.selected_pins = []
            self._refresh_table()
            self.plot.set_data([], [], None)
            self._set_controls_enabled(True)
            return
        if self._selection_worker and self._selection_worker.isRunning():
            self._pending_selection_update = True
            return
        devices = self._checked_devices()
        nets = self._checked_nets()
        x_min, x_max = sorted((self.x_min_spin.value(), self.x_max_spin.value()))
        y_min, y_max = sorted((self.y_min_spin.value(), self.y_max_spin.value()))
        self._set_controls_enabled(False)
        self._log("Updating coordinate selection...")
        self._selection_worker = SelectionThread(self.all_pins, devices, nets, x_min, x_max, y_min, y_max, self)
        self._selection_worker.selected.connect(self._on_selection_ready)
        self._selection_worker.failed.connect(self._on_selection_failed)
        self._selection_worker.finished.connect(self._on_selection_finished)
        self._selection_worker.start()

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
        self._set_controls_enabled(True)

    def _apply_plot_bounds(self, x_min: float, x_max: float, y_min: float, y_max: float) -> None:
        self._loading_controls = True
        self.x_min_spin.setValue(x_min)
        self.x_max_spin.setValue(x_max)
        self.y_min_spin.setValue(y_min)
        self.y_max_spin.setValue(y_max)
        self._loading_controls = False
        self._request_selection_update()

    def _checked_devices(self) -> set[str]:
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
        self._visible_pins = list(display_pins)
        self.selected_table.blockSignals(True)
        self.selected_table.setUpdatesEnabled(False)
        try:
            self.selected_table.clearSelection()
            self.selected_table.setRowCount(len(display_pins))
            for row, pin in enumerate(display_pins):
                side = classify_pin_side(pin, self.selected_pins) if self.selected_pins else ""
                values = [
                    f"{pin.pin_x:g}",
                    f"{pin.pin_y:g}",
                    pin.net_name,
                    self._effective_source_group_for_pin(pin),
                    side,
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
        if self._table_sort_column is None:
            return
        reverse = self._table_sort_order == Qt.SortOrder.DescendingOrder
        self.selected_pins.sort(key=lambda pin: self._table_sort_key(pin, self._table_sort_column), reverse=reverse)

    def _table_sort_key(self, pin: PinRecord, column: int):
        if column == 0:
            return pin.pin_x
        if column == 1:
            return pin.pin_y
        if column == 2:
            return pin.net_name.upper()
        if column == 3:
            return self._effective_source_group_for_pin(pin).upper()
        if column == 4:
            return classify_pin_side(pin, self.selected_pins)
        return ""

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
        self._worker.finished.connect(lambda: self._set_controls_enabled(True))
        self._worker.start()

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
        side_counts = Counter(classify_pin_side(pin, pins) for pin in pins)
        source_counts = Counter(source_group_name_for_pin(pin) for pin in pins)
        self._log("Side summary: " + ", ".join(f"{side}={side_counts.get(side, 0)}" for side in SIDE_LABELS))
        self._log("Source group summary: " + ", ".join(f"{name}={count}" for name, count in sorted(source_counts.items())))

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


def run_app() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()
