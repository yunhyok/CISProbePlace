"""Diagrams for the built-in help, drawn with QPainter when the help opens.

Drawing them at run time keeps them sharp on high-DPI screens, lets the labels
use the fonts installed on the user's machine, and avoids shipping image files.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QApplication

from .models import PinRecord
from .script_builder import SIDE_LINE_EDGE_BAND_RATIO, classify_pin_sides


FigureRenderer = Callable[[float], QImage]

INK = QColor("#1f2937")
MUTED = QColor("#64748b")
LINE = QColor("#94a3b8")
PANEL = QColor("#f8fafc")
ACCENT = QColor("#2563eb")
ACCENT_SOFT = QColor("#dbeafe")
WARM_SOFT = QColor("#fef3c7")
GREEN_SOFT = QColor("#dcfce7")
SIDE_COLORS = {
    "right": QColor("#2563eb"),
    "top": QColor("#16a34a"),
    "left": QColor("#d97706"),
    "bottom": QColor("#9333ea"),
}


def new_canvas(width: int, height: int, dpr: float) -> tuple[QImage, QPainter]:
    """Create a white image of ``width`` x ``height`` logical pixels and a painter on it."""
    dpr = max(float(dpr), 1.0)
    image = QImage(round(width * dpr), round(height * dpr), QImage.Format.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(dpr)
    image.fill(QColor("#ffffff"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    return image, painter


def figure_font(pixel_size: int, bold: bool = False) -> QFont:
    font = QFont(QApplication.font())
    font.setPixelSize(pixel_size)
    font.setBold(bold)
    return font


def _text(
    painter: QPainter,
    rect: QRectF,
    text: str,
    size: int = 13,
    bold: bool = False,
    color: QColor = INK,
    align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignCenter,
) -> None:
    painter.setFont(figure_font(size, bold))
    painter.setPen(color)
    painter.drawText(rect, int(align) | int(Qt.TextFlag.TextWordWrap), text)


def _box(painter: QPainter, rect: QRectF, fill: QColor, border: QColor = LINE, radius: float = 8.0) -> None:
    painter.setPen(QPen(border, 1.4))
    painter.setBrush(fill)
    painter.drawRoundedRect(rect, radius, radius)


def _arrow(painter: QPainter, start: QPointF, end: QPointF, color: QColor = MUTED, width: float = 2.0) -> None:
    painter.setPen(QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawLine(start, end)
    direction = end - start
    length = (direction.x() ** 2 + direction.y() ** 2) ** 0.5
    if length == 0:
        return
    ux, uy = direction.x() / length, direction.y() / length
    head = 9.0
    left = QPointF(end.x() - head * ux + head * 0.5 * uy, end.y() - head * uy - head * 0.5 * ux)
    right = QPointF(end.x() - head * ux - head * 0.5 * uy, end.y() - head * uy + head * 0.5 * ux)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawPolygon(QPolygonF([end, left, right]))


def _badge(painter: QPainter, center: QPointF, label: str, radius: float = 11.0, color: QColor = ACCENT) -> None:
    painter.setPen(QPen(QColor("#ffffff"), 2))
    painter.setBrush(color)
    painter.drawEllipse(center, radius, radius)
    painter.setFont(figure_font(round(radius * 1.15), bold=True))
    painter.setPen(QColor("#ffffff"))
    painter.drawText(
        QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2),
        int(Qt.AlignmentFlag.AlignCenter),
        label,
    )


def draw_callout(painter: QPainter, center: QPointF, label: str) -> None:
    """Numbered marker used on top of the main-window picture."""
    _badge(painter, center, label, radius=12.0, color=QColor("#dc2626"))


# --------------------------------------------------------------------------- workflow


def render_workflow(dpr: float) -> QImage:
    width, height = 760, 214
    image, painter = new_canvas(width, height, dpr)
    box_width, box_height, gap, top = 163, 84, 36, 14
    steps = [
        ("1", "좌표 파일", "CSV 또는 XLSX\n(X, Y, Net Name ...)", WARM_SOFT),
        ("2", "이 프로그램", "불러오기 → 좌표 선택\n→ SIDE·source group 확인", ACCENT_SOFT),
        ("3", "AEDT script", "IronPython .py 파일\n저장", PANEL),
        ("4", "AEDT / HFSS", "script 실행\n→ probe 자동 배치", GREEN_SOFT),
    ]
    rects: list[QRectF] = []
    for index, (number, title, body, fill) in enumerate(steps):
        rect = QRectF(index * (box_width + gap) + 1, top, box_width, box_height)
        rects.append(rect)
        _box(painter, rect, fill)
        _badge(painter, QPointF(rect.left() + 17, rect.top() + 17), number, radius=10.0)
        _text(painter, QRectF(rect.left() + 30, rect.top() + 5, box_width - 34, 24), title, 14, bold=True)
        _text(painter, QRectF(rect.left() + 6, rect.top() + 30, box_width - 12, 50), body, 12, color=MUTED)
    for left, right in zip(rects, rects[1:]):
        y = left.center().y()
        _arrow(painter, QPointF(left.right() + 5, y), QPointF(right.left() - 5, y))

    prepare = QRectF(rects[3].left(), top + box_height + 46, box_width, 62)
    _box(painter, prepare, QColor("#ffffff"), border=QColor("#16a34a"))
    _text(painter, QRectF(prepare.left() + 4, prepare.top() + 4, box_width - 8, 24), "HFSS source group", 13, bold=True)
    _text(painter, QRectF(prepare.left() + 4, prepare.top() + 27, box_width - 8, 32), "원본 probe를 group으로\n미리 준비", 12, color=MUTED)
    _arrow(
        painter,
        QPointF(prepare.center().x(), prepare.top() - 4),
        QPointF(prepare.center().x(), rects[3].bottom() + 5),
        color=QColor("#16a34a"),
    )
    _text(
        painter,
        QRectF(0, prepare.top() + 2, rects[3].left() - 14, 58),
        "script는 실행을 시작할 때 필요한 group이 HFSS design에 있는지 먼저 검사합니다.\n"
        "group이 없거나 비어 있으면 아무것도 배치하지 않고 오류로 멈춥니다.",
        12,
        color=MUTED,
        align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
    )
    painter.end()
    return image


# --------------------------------------------------------------------------- recenter


def render_recenter(dpr: float) -> QImage:
    width, height = 760, 268
    image, painter = new_canvas(width, height, dpr)
    panel_width, panel_height, top = 318, 214, 40
    left_panel = QRectF(1, top, panel_width, panel_height)
    right_panel = QRectF(width - panel_width - 1, top, panel_width, panel_height)
    _text(painter, QRectF(left_panel.left(), 6, panel_width, 28), "입력 파일에 적힌 좌표", 14, bold=True)
    _text(painter, QRectF(right_panel.left(), 6, panel_width, 28), "프로그램과 script가 사용하는 좌표", 14, bold=True)
    for panel in (left_panel, right_panel):
        _box(painter, panel, PANEL)

    offsets = [(-1.0, -0.6), (-1.0, 0.0), (-1.0, 0.6), (1.0, -0.6), (1.0, 0.0), (1.0, 0.6), (-0.5, 1.0), (0.0, 1.0), (0.5, 1.0), (-0.5, -1.0), (0.0, -1.0), (0.5, -1.0)]
    half_w, half_h = 58.0, 44.0

    def draw_cluster(center: QPointF) -> None:
        painter.setPen(QPen(QColor("#dc2626"), 1.4, Qt.PenStyle.DashLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(QRectF(center.x() - half_w, center.y() - half_h, half_w * 2, half_h * 2))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(ACCENT)
        for dx, dy in offsets:
            painter.drawEllipse(QPointF(center.x() + dx * half_w, center.y() - dy * half_h), 3.6, 3.6)
        painter.setPen(QPen(QColor("#dc2626"), 2))
        painter.drawLine(QPointF(center.x() - 6, center.y()), QPointF(center.x() + 6, center.y()))
        painter.drawLine(QPointF(center.x(), center.y() - 6), QPointF(center.x(), center.y() + 6))

    def draw_axes(origin: QPointF, panel: QRectF) -> None:
        painter.setPen(QPen(INK, 1.3))
        painter.drawLine(QPointF(panel.left() + 12, origin.y()), QPointF(panel.right() - 12, origin.y()))
        painter.drawLine(QPointF(origin.x(), panel.bottom() - 12), QPointF(origin.x(), panel.top() + 12))
        _text(painter, QRectF(panel.right() - 30, origin.y() + 2, 20, 18), "X", 12, color=MUTED)
        _text(painter, QRectF(origin.x() + 4, panel.top() + 10, 20, 18), "Y", 12, color=MUTED)

    left_origin = QPointF(left_panel.left() + 34, left_panel.bottom() - 30)
    draw_axes(left_origin, left_panel)
    _text(
        painter,
        QRectF(left_origin.x() + 6, left_origin.y() + 3, 60, 18),
        "(0, 0)",
        11,
        color=MUTED,
        align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
    )
    left_center = QPointF(left_panel.left() + 222, left_panel.top() + 82)
    draw_cluster(left_center)
    _text(
        painter,
        QRectF(left_center.x() - 110, left_center.y() + half_h + 6, 220, 36),
        "bounding box 중심\n예: (1010, 2030)",
        11,
        color=QColor("#b91c1c"),
    )

    right_origin = QPointF(right_panel.center().x(), right_panel.center().y())
    draw_axes(right_origin, right_panel)
    draw_cluster(right_origin)
    _text(
        painter,
        QRectF(right_origin.x() + 9, right_origin.y() + half_h + 8, 120, 18),
        "중심 = (0, 0)",
        11,
        color=QColor("#b91c1c"),
        align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
    )

    middle_y = top + panel_height / 2
    _arrow(painter, QPointF(left_panel.right() + 12, middle_y), QPointF(right_panel.left() - 12, middle_y), color=ACCENT, width=2.6)
    _text(painter, QRectF(left_panel.right() + 2, middle_y - 46, right_panel.left() - left_panel.right() - 4, 38), "모든 좌표에서\n중심을 뺌", 11, color=ACCENT)
    painter.end()
    return image


# ------------------------------------------------------------------------------- side


def _side_demo_pins() -> list[PinRecord]:
    pins: list[PinRecord] = []
    for index in range(1, 8):
        pins.append(PinRecord("", f"L{index}", "", "", "", 0.0, float(index), "N"))
        pins.append(PinRecord("", f"R{index}", "", "", "", 10.0, float(index), "N"))
    for index in range(1, 10):
        pins.append(PinRecord("", f"T{index}", "", "", "", float(index), 8.0, "N"))
        pins.append(PinRecord("", f"B{index}", "", "", "", float(index), 0.0, "N"))
    # Two pins that sit on no edge line: they take the nearest outer edge.
    pins.append(PinRecord("", "C1", "", "", "", 3.4, 5.2, "N"))
    pins.append(PinRecord("", "C2", "", "", "", 6.3, 2.4, "N"))
    return pins


def render_side(dpr: float) -> QImage:
    width, height = 760, 372
    image, painter = new_canvas(width, height, dpr)
    pins = _side_demo_pins()
    sides = classify_pin_sides(pins)

    plot = QRectF(58, 40, 372, 290)
    min_x, max_x, min_y, max_y = 0.0, 10.0, 0.0, 8.0

    def to_point(x: float, y: float) -> QPointF:
        return QPointF(
            plot.left() + (x - min_x) / (max_x - min_x) * plot.width(),
            plot.bottom() - (y - min_y) / (max_y - min_y) * plot.height(),
        )

    band_x = plot.width() * SIDE_LINE_EDGE_BAND_RATIO
    band_y = plot.height() * SIDE_LINE_EDGE_BAND_RATIO
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(148, 163, 184, 46))
    painter.drawRect(QRectF(plot.left(), plot.top(), band_x, plot.height()))
    painter.drawRect(QRectF(plot.right() - band_x, plot.top(), band_x, plot.height()))
    painter.drawRect(QRectF(plot.left(), plot.top(), plot.width(), band_y))
    painter.drawRect(QRectF(plot.left(), plot.bottom() - band_y, plot.width(), band_y))
    painter.setPen(QPen(LINE, 1.3, Qt.PenStyle.DashLine))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRect(plot)

    for pin, side in zip(pins, sides):
        painter.setPen(QPen(QColor("#ffffff"), 1.2))
        painter.setBrush(SIDE_COLORS[side])
        painter.drawEllipse(to_point(pin.pin_x, pin.pin_y), 6.2, 6.2)

    _text(painter, QRectF(plot.left(), 8, plot.width(), 26), "top  (Y가 가장 큰 쪽)", 13, bold=True, color=SIDE_COLORS["top"])
    _text(painter, QRectF(plot.left(), plot.bottom() + 12, plot.width(), 26), "bottom  (Y가 가장 작은 쪽)", 13, bold=True, color=SIDE_COLORS["bottom"])
    painter.save()
    painter.translate(22, plot.center().y())
    painter.rotate(-90)
    _text(painter, QRectF(-150, -13, 300, 26), "left  (X가 가장 작은 쪽)", 13, bold=True, color=SIDE_COLORS["left"])
    painter.restore()
    painter.save()
    painter.translate(plot.right() + 26, plot.center().y())
    painter.rotate(90)
    _text(painter, QRectF(-150, -13, 300, 26), "right  (X가 가장 큰 쪽)", 13, bold=True, color=SIDE_COLORS["right"])
    painter.restore()

    for pin in pins[-2:]:
        point = to_point(pin.pin_x, pin.pin_y)
        painter.setPen(QPen(INK, 1.2, Qt.PenStyle.DotLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(point, 11.0, 11.0)

    legend = QRectF(482, 40, 277, 290)
    _box(painter, legend, PANEL)
    _text(
        painter,
        QRectF(legend.left() + 14, legend.top() + 10, legend.width() - 28, 24),
        "색 = 인식된 side",
        14,
        bold=True,
        align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
    )
    rows = [
        ("right", "CISRotAng_Right", "0°"),
        ("top", "CISRotAng_Top", "270°"),
        ("left", "CISRotAng_Left", "180°"),
        ("bottom", "CISRotAng_Bottom", "90°"),
    ]
    row_top = legend.top() + 44
    for side, variable, angle in rows:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(SIDE_COLORS[side])
        painter.drawEllipse(QPointF(legend.left() + 24, row_top + 11), 6.2, 6.2)
        _text(painter, QRectF(legend.left() + 40, row_top, 60, 22), side, 13, bold=True, align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        _text(painter, QRectF(legend.left() + 98, row_top, 132, 22), variable, 12, color=MUTED, align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        _text(painter, QRectF(legend.right() - 50, row_top, 40, 22), angle, 12, color=MUTED, align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row_top += 28
    _text(
        painter,
        QRectF(legend.left() + 98, row_top - 2, legend.width() - 108, 18),
        "회전 변수와 기본값",
        11,
        color=MUTED,
        align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
    )

    note_top = row_top + 26
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(148, 163, 184, 70))
    painter.drawRect(QRectF(legend.left() + 16, note_top + 3, 16, 12))
    _text(
        painter,
        QRectF(legend.left() + 40, note_top - 4, legend.width() - 50, 40),
        "회색 띠: 각 외곽 변에서 전체 폭·높이의 30% 안쪽까지",
        11,
        color=INK,
        align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
    )
    note_top += 44
    painter.setPen(QPen(INK, 1.2, Qt.PenStyle.DotLine))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(QPointF(legend.left() + 24, note_top + 14), 9.0, 9.0)
    _text(
        painter,
        QRectF(legend.left() + 40, note_top - 4, legend.width() - 50, 40),
        "점선 원: 줄 위에 없는 좌표 → 가장 가까운 외곽 변의 side",
        11,
        color=INK,
        align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
    )
    painter.end()
    return image


# ---------------------------------------------------------------------- source groups


def render_source_groups(dpr: float) -> QImage:
    width, height = 760, 306
    image, painter = new_canvas(width, height, dpr)

    table = QRectF(1, 40, 336, 196)
    _text(painter, QRectF(table.left(), 6, table.width(), 28), "입력 파일의 각 행", 14, bold=True)
    columns = [("X좌표", 58), ("Y좌표", 58), ("Net Name", 92), ("Source_probe name", 128)]
    rows = [
        ("10", "5", "SIG_A", "LongProbe"),
        ("10", "6", "SIG_A_RET", "ShortProbe"),
        ("5", "10", "SIG_B", "LongProbe"),
        ("0", "5", "DGND", ""),
    ]
    row_height = 39.0
    painter.setPen(QPen(LINE, 1.2))
    x = table.left()
    for title, column_width in columns:
        cell = QRectF(x, table.top(), column_width, row_height)
        painter.setBrush(QColor("#e2e8f0"))
        painter.drawRect(cell)
        _text(painter, cell, title, 12, bold=True)
        painter.setPen(QPen(LINE, 1.2))
        x += column_width
    row_centers: list[float] = []
    for row_index, row in enumerate(rows):
        y = table.top() + row_height * (row_index + 1)
        row_centers.append(y + row_height / 2)
        x = table.left()
        for column_index, ((_, column_width), value) in enumerate(zip(columns, row)):
            cell = QRectF(x, y, column_width, row_height)
            highlight = column_index == 3
            painter.setPen(QPen(LINE, 1.2))
            painter.setBrush(WARM_SOFT if highlight else QColor("#ffffff"))
            painter.drawRect(cell)
            if highlight and not value:
                _text(painter, cell, "(빈칸)", 12, color=MUTED)
            else:
                _text(painter, cell, value, 12, bold=highlight)
            x += column_width

    tree = QRectF(456, 40, 303, 258)
    _text(painter, QRectF(tree.left(), 6, tree.width(), 28), "HFSS design의 group", 14, bold=True)
    _box(painter, tree, PANEL)
    groups = [
        ("LongProbe", "Long_Body · Long_Tip · Long_Sheet", GREEN_SOFT),
        ("ShortProbe", "Short_Body · Short_Sheet", GREEN_SOFT),
        ("Source_Group", "이름을 적지 않은 행이 쓰는 기본 group", GREEN_SOFT),
        ("Generated_Group", "script가 복제한 object가 들어가는 곳", QColor("#e2e8f0")),
    ]
    group_height, group_gap = 50.0, 12.0
    group_rects: list[QRectF] = []
    y = tree.top() + 12
    for name, body, fill in groups:
        rect = QRectF(tree.left() + 14, y, tree.width() - 28, group_height)
        group_rects.append(rect)
        _box(painter, rect, fill, radius=6.0)
        _text(painter, QRectF(rect.left() + 12, rect.top() + 4, rect.width() - 24, 22), name, 13, bold=True, align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        _text(painter, QRectF(rect.left() + 12, rect.top() + 25, rect.width() - 24, 20), body, 11, color=MUTED, align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        y += group_height + group_gap

    targets = [0, 1, 0, 2]
    colors = [QColor("#16a34a"), QColor("#0891b2"), QColor("#16a34a"), QColor("#d97706")]
    for row_center, target, color in zip(row_centers, targets, colors):
        start = QPointF(table.right() + 6, row_center)
        end = QPointF(group_rects[target].left() - 6, group_rects[target].center().y())
        path = QPainterPath(start)
        middle = (start.x() + end.x()) / 2
        path.cubicTo(QPointF(middle, start.y()), QPointF(middle, end.y()), QPointF(end.x() - 9, end.y()))
        painter.setPen(QPen(color, 1.8))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        _arrow(painter, QPointF(end.x() - 10, end.y()), end, color=color, width=1.8)

    _text(
        painter,
        QRectF(table.left(), table.bottom() + 12, table.width() + 96, 50),
        "Source_probe name에 적은 글자가 그대로 HFSS group 이름이 됩니다.\n"
        "빈칸인 행은 Source_Group을 사용합니다.",
        12,
        color=MUTED,
        align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
    )
    painter.end()
    return image


# -------------------------------------------------------------------------- placement


def _probe_shape(painter: QPainter, tip: QPointF, angle_degrees: float, fill: QColor, dashed: bool = False) -> None:
    painter.save()
    painter.translate(tip)
    painter.rotate(angle_degrees)
    shape = QPolygonF([QPointF(0, 0), QPointF(16, -9), QPointF(62, -9), QPointF(62, 9), QPointF(16, 9)])
    pen = QPen(INK if not dashed else MUTED, 1.4, Qt.PenStyle.DashLine if dashed else Qt.PenStyle.SolidLine)
    painter.setPen(pen)
    painter.setBrush(fill)
    painter.drawPolygon(shape)
    painter.restore()


def _origin_mark(painter: QPainter, origin: QPointF, label: str = "원점 (0, 0)") -> None:
    painter.setPen(QPen(QColor("#dc2626"), 1.6))
    painter.drawLine(QPointF(origin.x() - 9, origin.y()), QPointF(origin.x() + 9, origin.y()))
    painter.drawLine(QPointF(origin.x(), origin.y() - 9), QPointF(origin.x(), origin.y() + 9))
    if label:
        _text(painter, QRectF(origin.x() - 60, origin.y() + 12, 120, 18), label, 11, color=QColor("#b91c1c"))


def render_placement(dpr: float) -> QImage:
    width, height = 760, 214
    image, painter = new_canvas(width, height, dpr)
    panel_width, panel_height, gap, top = 236, 168, 26, 40
    titles = ["원본 probe (원점 기준)", "Z축 기준 회전 복제", "좌표 (X, Y)만큼 이동"]
    panels = [QRectF(index * (panel_width + gap) + 1, top, panel_width - 2, panel_height) for index in range(3)]
    for index, (panel, title) in enumerate(zip(panels, titles)):
        _badge(painter, QPointF(panel.left() + 12, 20), str(index + 1), radius=10.0)
        _text(painter, QRectF(panel.left() + 28, 6, panel_width - 30, 28), title, 13, bold=True, align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        _box(painter, panel, PANEL)
    for left, right in zip(panels, panels[1:]):
        y = left.center().y()
        _arrow(painter, QPointF(left.right() + 5, y), QPointF(right.left() - 5, y))

    probe_fill = QColor("#bfdbfe")
    origin_1 = QPointF(panels[0].left() + 70, panels[0].center().y() - 8)
    _probe_shape(painter, origin_1, 0.0, probe_fill)
    _origin_mark(painter, origin_1)
    _text(painter, QRectF(panels[0].left() + 6, panels[0].bottom() - 38, panel_width - 14, 34), "pad에 닿는 지점을\n원점에 맞춰 둡니다", 11, color=MUTED)

    origin_2 = QPointF(panels[1].center().x(), panels[1].center().y() - 8)
    _probe_shape(painter, origin_2, 0.0, QColor("#ffffff"), dashed=True)
    _probe_shape(painter, origin_2, 180.0, probe_fill)
    _origin_mark(painter, origin_2, label="")
    _text(painter, QRectF(panels[1].left() + 6, panels[1].bottom() - 38, panel_width - 14, 34), "각도 = 그 좌표의 side 변수\n(그림은 left = 180° 예)", 11, color=MUTED)

    origin_3 = QPointF(panels[2].left() + 48, panels[2].bottom() - 52)
    target = QPointF(panels[2].left() + 150, panels[2].top() + 46)
    _origin_mark(painter, origin_3, label="")
    painter.setPen(QPen(MUTED, 1.4, Qt.PenStyle.DashLine))
    painter.drawLine(origin_3, target)
    _probe_shape(painter, target, 180.0, probe_fill)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#dc2626"))
    painter.drawEllipse(target, 4.0, 4.0)
    _text(painter, QRectF(target.x() - 14, target.y() + 10, 90, 18), "(X, Y)", 11, bold=True, color=QColor("#b91c1c"))
    _text(painter, QRectF(panels[2].left() + 84, panels[2].bottom() - 40, panel_width - 92, 34), "기준점이 입력 좌표에\n놓입니다", 11, color=MUTED)
    painter.end()
    return image


def render_unavailable(dpr: float, message: str = "그림을 표시할 수 없습니다.") -> QImage:
    image, painter = new_canvas(520, 60, dpr)
    _box(painter, QRectF(1, 1, 518, 58), PANEL)
    _text(painter, QRectF(10, 4, 500, 52), message, 12, color=MUTED)
    painter.end()
    return image


FIGURE_RENDERERS: dict[str, FigureRenderer] = {
    "workflow": render_workflow,
    "recenter": render_recenter,
    "side": render_side,
    "source-groups": render_source_groups,
    "placement": render_placement,
}
