from __future__ import annotations

from collections import Counter
from dataclasses import replace
import math
import os
import re
import sys
import tempfile
import traceback
from pathlib import Path

from PySide6.QtCore import QEvent, QItemSelection, QItemSelectionModel, QPoint, QPointF, QRect, QRectF, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QKeySequence, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QAbstractScrollArea,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
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
    QStyle,
    QStyleOptionGroupBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .data_io import COORDINATE_FILTER_EPSILON, filter_pins, get_comp_devices, get_net_names, load_pin_records
from .help_figures import CALLOUT_RADIUS, draw_callout, figure_font, new_canvas
from .help_viewer import HelpDialog
from .models import GenerationOptions, GenerationResult, PinRecord
from .pin_map import CoordinatePlot
from .probe_geometry import infer_bond_layout
from .theme import ASSET_PREFIX, CHECK_MARK, apply_theme
from .script_builder import build_script, classify_pin_sides, source_group_name_for_pin
from .spd import SpdData, read_spd


APP_TITLE = f"CIS Probe Placement Scriptor v{__version__}"
LEFT_PANEL_MIN_WIDTH = 340
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


class GenerateThread(QThread):
    generated = Signal(object, str)
    failed = Signal(str)

    def __init__(
        self,
        pins: list[PinRecord],
        options: GenerationOptions,
        output_path: Path,
        parent: QWidget | None = None,
        *,
        pin_sides: list[str] | None = None,
    ) -> None:
        super().__init__(parent)
        self._pins = pins
        self._pin_sides = pin_sides
        self._options = options
        self._output_path = output_path

    def run(self) -> None:
        try:
            result = build_script(self._pins, self._options, pin_sides=self._pin_sides)
            self._output_path.write_text(result.script, encoding="utf-8")
            self.generated.emit(result, str(self._output_path))
        except Exception as exc:  # pragma: no cover - surfaced through GUI signal
            self.failed.emit(str(exc))


class LoadInputsThread(QThread):
    progress = Signal(str)
    loaded = Signal(object)
    spd_loaded = Signal(object)
    failed = Signal(str)

    def __init__(self, pin_path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pin_path = pin_path

    def run(self) -> None:
        try:
            self.progress.emit(f"Loading pin report: {self._pin_path}")
            if self._pin_path.suffix.lower() == ".spd":
                from .spd import read_spd

                data = read_spd(self._pin_path)
                self.progress.emit(f"Loaded SPD: {len(data.components)} components.")
                self.spd_loaded.emit(data)
                return
            pins = load_pin_records(self._pin_path)
            self.progress.emit(f"Loaded {len(pins)} pin rows.")
            self.loaded.emit(pins)
        except Exception as exc:  # pragma: no cover - surfaced through GUI signal
            self.failed.emit(str(exc))


class SpdSelectionDialog(QDialog):
    def __init__(self, data, parent: QWidget | None = None, selection: tuple[str, int | None] | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Select SPD DUT and site")
        self._data = data
        self.component_combo = QComboBox()
        self.site_combo = QComboBox()
        for combo in (self.component_combo, self.site_combo):
            combo.setMaxVisibleItems(16)
            combo.setMinimumContentsLength(20)
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        components = sorted(data.components, key=_mixed_sort_key)
        self.component_combo.addItems(components)
        preferred = next(
            (name for name in components if re.match(r"^DUT(?:$|[\d_.-])", name, re.IGNORECASE)),
            components[0] if components else "",
        )
        self.component_combo.setCurrentText(selection[0] if selection else preferred)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout = QFormLayout(self)
        layout.addRow("DUT component", self.component_combo)
        layout.addRow("Site", self.site_combo)
        layout.addRow(self.buttons)
        self.component_combo.currentTextChanged.connect(self._refresh_sites)
        self._refresh_sites()
        if selection:
            self.site_combo.setCurrentIndex(list(data.sites(selection[0])).index(selection[1]))

    def _refresh_sites(self) -> None:
        self.site_combo.clear()
        component = self.component_combo.currentText()
        sites = list(self._data.sites(component)) if component else []
        # The first item is selected automatically: lowest numbered site, then unassigned.
        for site in sites:
            self.site_combo.addItem("(unassigned)" if site is None else str(site), site)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(sites))

    def selection(self) -> tuple[str, int | None]:
        return self.component_combo.currentText(), self.site_combo.currentData()


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
        self._table_start = 0
        self._loading_controls = False
        self._loading_input = False
        self._loaded_pin_path = ""
        self._spd_data = None
        self._spd_selection: tuple[str, int | None] | None = None
        self._load_worker: LoadInputsThread | None = None
        self._selection_worker: SelectionThread | None = None
        self._pending_selection_update = False
        self._worker: GenerateThread | None = None
        self._table_sort_column: int | None = None
        self._table_sort_order = Qt.SortOrder.AscendingOrder
        self._all_net_names: list[str] = []
        self._net_check_states: dict[str, bool] = {}
        self._source_group_overrides: dict[int, str] = {}
        self._source_group_colors: dict[str, str] = {}
        self._auto_sides: dict[int, str] = {}
        self._bond_lanes: dict[int, str | None] = {}
        self._automatic_probe_groups = True
        self._tips_toward_center = True
        self._long_probe_group = "LongProbe"
        self._short_probe_group = "ShortProbe"
        self._replace_input_groups = False
        self._side_overrides: dict[int, str] = {}
        self._picked_ids: set[int] = set()
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
        self.comp_list.setMaximumHeight(128)
        self.net_list = QListWidget()
        self.net_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.net_list.setMaximumHeight(128)
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
        self.log_edit.setMaximumHeight(110)
        self.generate_button = QPushButton("Generate AEDT Script")
        self.generate_button.setProperty("primary", True)
        self.log_edit.setObjectName("output_log")
        self.picked_only_check = QCheckBox("Place picked pins only")
        self.picked_count_label = QLabel("Picked: 0 / Filtered: 0")
        self.reset_button = QPushButton("Reset Range")
        self.net_select_all_button = QPushButton("Select All")
        self.net_clear_all_button = QPushButton("Clear All")
        self.browse_pin_button = QPushButton("Browse Coordinate File")
        self.load_button = QPushButton("Load Inputs")
        self.spd_selection_button = QPushButton("Change DUT / site")
        self.spd_selection_button.setToolTip("Choose from the loaded SPD inventory without rereading the file")
        self.spd_selection_button.setEnabled(False)
        self.spd_selection_button.hide()
        self.spd_selection_label = QLabel()
        self.spd_selection_label.setWordWrap(True)
        self.spd_selection_label.hide()
        self.source_group_edit = QLineEdit()
        self.source_group_edit.setPlaceholderText("HFSS group name, e.g. LongProbe")
        self.apply_source_selected_button = QPushButton("Apply to picked pins")
        self.apply_source_all_button = QPushButton("Apply to filtered pins")
        self.clear_source_overrides_button = QPushButton("Clear group overrides")
        self.source_group_color_combo = QComboBox()
        self.source_group_color_combo.setMinimumContentsLength(10)
        self.source_group_color_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.choose_source_color_button = QPushButton("Choose color")
        self.reset_source_color_button = QPushButton("Reset color")
        self.side_combo = QComboBox()
        self.side_combo.addItems(["Auto", "right", "top", "left", "bottom"])
        self.side_combo.setToolTip("Auto restores the side classified from the complete loaded layout.")
        self.apply_side_button = QPushButton("Apply CIS side")
        self.automatic_probe_groups_check = QCheckBox("Automatic probe groups")
        self.automatic_probe_groups_check.setChecked(True)
        self.tip_orientation_combo = QComboBox()
        self.tip_orientation_combo.addItems(["Toward center", "Toward outside"])
        self.long_probe_group_edit = QLineEdit("LongProbe")
        self.short_probe_group_edit = QLineEdit("ShortProbe")
        self.replace_input_groups_check = QCheckBox("Replace input groups")
        self.replace_input_groups_check.setToolTip("Replace named input groups for inferred pins; manual per-pin group overrides always take priority.")
        self.apply_probe_inference_button = QPushButton("Apply inference")
        self.probe_type_count_label = QLabel("Probe type: Long 0 / Short 0 / Undetermined 0")
        self.probe_type_count_label.setWordWrap(True)

        self._build_layout()
        self._connect_signals()
        apply_theme(self)
        self._fit_left_panel_width()
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
        file_layout.addWidget(QLabel("Coordinate file"), 0, 0, 1, 2)
        file_layout.addWidget(self.pin_path_edit, 1, 0, 1, 2)
        file_layout.addWidget(self.browse_pin_button, 2, 0, 1, 2)
        file_layout.addWidget(self.load_button, 3, 0, 1, 2)
        source_hint = QLabel("HFSS source groups: input names or automatic Long/Short groups (Pin editing)")
        source_hint.setWordWrap(True)
        file_layout.addWidget(source_hint, 4, 0, 1, 2)
        file_layout.addWidget(self.spd_selection_label, 5, 0, 1, 2)
        file_layout.addWidget(self.spd_selection_button, 6, 0, 1, 2)
        self.browse_pin_button.clicked.connect(lambda: self._browse_file(self.pin_path_edit))
        self.load_button.clicked.connect(self.load_inputs)
        self.spd_selection_button.clicked.connect(self._change_spd_selection)
        self.pin_path_edit.textChanged.connect(self._update_spd_controls)

        filter_group = self.filter_group = QGroupBox("Coordinate filters")
        filter_layout = QGridLayout(filter_group)
        self.comp_device_label = QLabel("COMP_DEVICE (legacy Allegro only)")
        self.comp_device_label.hide()
        self.comp_list.hide()
        filter_layout.addWidget(self.comp_device_label, 0, 0, 1, 2)
        filter_layout.addWidget(self.comp_list, 1, 0, 1, 2)
        for row, (label, spin) in enumerate((("X min", self.x_min_spin), ("X max", self.x_max_spin),
                                           ("Y min", self.y_min_spin), ("Y max", self.y_max_spin)), start=2):
            filter_layout.addWidget(QLabel(label), row, 0)
            filter_layout.addWidget(spin, row, 1)
        filter_layout.addWidget(self.reset_button, 6, 0, 1, 2)

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
        source_layout.addWidget(self.apply_source_selected_button, 1, 0, 1, 3)
        source_layout.addWidget(self.apply_source_all_button, 2, 0, 1, 3)
        source_layout.addWidget(self.clear_source_overrides_button, 3, 0, 1, 3)
        source_layout.addWidget(QLabel("Group color"), 4, 0)
        source_layout.addWidget(self.source_group_color_combo, 4, 1, 1, 2)
        source_layout.addWidget(self.choose_source_color_button, 5, 0)
        source_layout.addWidget(self.reset_source_color_button, 5, 1, 1, 2)
        source_layout.addWidget(QLabel("CIS side"), 6, 0)
        source_layout.addWidget(self.side_combo, 6, 1, 1, 2)
        source_layout.addWidget(self.apply_side_button, 7, 0, 1, 3)
        inference_group = QGroupBox("Probe inference")
        inference_layout = QFormLayout(inference_group)
        inference_layout.addRow(self.automatic_probe_groups_check)
        inference_layout.addRow("Tips point", self.tip_orientation_combo)
        inference_layout.addRow("Long group", self.long_probe_group_edit)
        inference_layout.addRow("Short group", self.short_probe_group_edit)
        inference_layout.addRow(self.replace_input_groups_check)
        inference_layout.addRow(self.apply_probe_inference_button)
        inference_layout.addRow(self.probe_type_count_label)

        self.control_tabs = QTabWidget()
        for title, groups in (
            ("Input and filters", (file_group, filter_group, net_group)),
            ("Pin editing", (inference_group, source_group)),
            ("AEDT target", (project_group,)),
        ):
            content = QWidget()
            content_layout = QVBoxLayout(content)
            content_layout.setContentsMargins(0, 0, 0, 0)
            for group in groups:
                content_layout.addWidget(group)
            content_layout.addStretch(1)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setWidget(content)
            self.control_tabs.addTab(scroll, title)
            if title == "Input and filters":
                self._left_scroll, self._left_content = scroll, content

        left = self._left_panel = QWidget()
        left.setMinimumWidth(LEFT_PANEL_MIN_WIDTH)
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(self.control_tabs, 1)
        left_layout.addWidget(self.picked_count_label)
        left_layout.addWidget(self.picked_only_check)
        left_layout.addWidget(self.generate_button)

        preview_splitter = self.preview_splitter = QSplitter(Qt.Orientation.Horizontal)
        preview_splitter.addWidget(self.selected_table)
        preview_splitter.addWidget(self.plot)
        preview_splitter.setSizes([460, 560])

        right = self._right_panel = QWidget()
        right_layout = QVBoxLayout(right)
        preview_hint = QLabel("Map: click or drag to pick · Ctrl to toggle · right-drag to pan · wheel to zoom · middle-click to reset")
        preview_hint.setWordWrap(True)
        right_layout.addWidget(preview_hint)
        right_layout.addWidget(preview_splitter, 1)
        right_layout.addWidget(QLabel("Log"))
        right_layout.addWidget(self.log_edit, 0)

        main_splitter = self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_splitter.addWidget(left)
        main_splitter.addWidget(right)
        main_splitter.setSizes([LEFT_PANEL_MIN_WIDTH, 820])
        layout.addWidget(main_splitter)
        self.setCentralWidget(root)

    def _fit_left_panel_width(self) -> None:
        """Keep the left panel as wide as its tab captions and the controls of its widest tab.

        How wide they are depends on the font of the machine. A tab narrower
        than its controls would have to be scrolled sideways.
        """
        for index in range(self.control_tabs.count()):
            scroll = self.control_tabs.widget(index)
            scroll.setMinimumWidth(
                scroll.widget().minimumSizeHint().width()
                + scroll.verticalScrollBar().sizeHint().width()
                + 2 * scroll.frameWidth()
            )
        # Asked of the tabs themselves: the layout of the panel still holds the
        # sizes from before, until the event loop has run.
        margins = self._left_panel.layout().contentsMargins()
        tabs_width = max(self.control_tabs.minimumSizeHint().width(), self.control_tabs.tabBar().sizeHint().width())
        self._left_panel.setMinimumWidth(max(LEFT_PANEL_MIN_WIDTH, tabs_width + margins.left() + margins.right()))

    def full_content_height(self) -> int:
        """Window height at which the left panel shows every control without scrolling."""
        left_height = self._left_panel.minimumSizeHint().height()
        right_height = self._right_panel.minimumSizeHint().height()
        chrome_height = self.minimumSizeHint().height() - max(left_height, right_height)
        full_left_height = (
            left_height
            - self._left_scroll.minimumSizeHint().height()
            + self._left_content_height()
        )
        return chrome_height + max(full_left_height, right_height)

    def _left_content_height(self) -> int:
        """Height at which every tab shows all of its controls."""
        margins = self._left_panel.layout().contentsMargins()
        frame = self.control_tabs.style().pixelMetric(QStyle.PixelMetric.PM_DefaultFrameWidth, None, self.control_tabs)
        width = self._left_panel.minimumWidth() - margins.left() - margins.right() - 2 * frame
        heights = []
        for index in range(self.control_tabs.count()):
            scroll = self.control_tabs.widget(index)
            content = scroll.widget()
            height = content.minimumSizeHint().height()
            layout = content.layout()
            if layout.hasHeightForWidth():
                # With a word-wrapped label inside, a scroll area sizes its content by
                # the height for the width it is shown at, not by the minimum size.
                # That width is taken without the scroll bar: once the bar is there,
                # the text wraps more, and the bar stays although it is not needed.
                bar = scroll.verticalScrollBar().sizeHint().width()
                height = max(height, layout.totalHeightForWidth(width - bar))
            heights.append(height)
        return max(heights)

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
        self.plot.pinsPicked.connect(self._on_map_pins_picked)
        self.apply_side_button.clicked.connect(self.apply_side_to_picked_pins)
        self.apply_probe_inference_button.clicked.connect(self.apply_probe_inference)
        self.long_probe_group_edit.editingFinished.connect(lambda: self.apply_probe_inference(show_warning=False))
        self.short_probe_group_edit.editingFinished.connect(lambda: self.apply_probe_inference(show_warning=False))
        self.tip_orientation_combo.currentIndexChanged.connect(lambda _: self.apply_probe_inference(validate_groups=False))
        self.automatic_probe_groups_check.toggled.connect(lambda _: self.apply_probe_inference(validate_groups=False))
        self.replace_input_groups_check.toggled.connect(lambda _: self.apply_probe_inference(validate_groups=False))
        self.source_group_color_combo.currentTextChanged.connect(self._refresh_source_group_color_button)
        self.choose_source_color_button.clicked.connect(self._choose_source_group_color)
        self.reset_source_color_button.clicked.connect(self._reset_current_source_group_color)
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
            self._help_dialog = HelpDialog(extra_figures=HELP_EXTRA_FIGURES)
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

    def show_spd_sample_state(self) -> None:
        """Show a small built-in SPD example as if it had just been loaded (used for the help picture)."""
        data = _sample_spd_data()
        component, site = "DUT", 0
        pins = data.pins(component, site)
        self.pin_path_edit.setText("C:\\Work\\probe_card.spd")
        self._loaded_pin_path = self.pin_path_edit.text()
        self._apply_loaded_pins(pins)
        self.selected_pins = list(pins)
        self._refresh_table()
        bounds = (self.x_min_spin.value(), self.x_max_spin.value(), self.y_min_spin.value(), self.y_max_spin.value())
        self.plot.set_data(pins, pins, bounds)
        self._show_spd_selection(data, component, site)

    def _browse_file(self, target: QLineEdit) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select input file", "", "Input files (*.csv *.xlsx *.spd);;All files (*.*)")
        if path:
            target.setText(path)

    def load_inputs(self) -> None:
        if self._loading_input or self._load_worker is not None or self._worker is not None:
            return
        pin_path = self.pin_path_edit.text().strip()
        if not pin_path:
            QMessageBox.warning(self, "Missing input", "Select a pin report before loading.")
            return
        self._selection_timer.stop()
        self._pending_selection_update = False
        self._loading_input = True
        self._set_controls_enabled(False)
        self._log("Starting input load...")
        self._load_worker = LoadInputsThread(Path(pin_path), self)
        self._load_worker.progress.connect(self._log)
        self._load_worker.loaded.connect(self._on_inputs_loaded)
        self._load_worker.spd_loaded.connect(self._on_spd_loaded)
        self._load_worker.failed.connect(self._on_load_failed)
        self._load_worker.finished.connect(lambda: setattr(self, "_load_worker", None))
        self._load_worker.finished.connect(self._load_worker.deleteLater)
        self._load_worker.start()

    def _change_spd_selection(self) -> None:
        if self.spd_selection_button.isEnabled():
            self._on_spd_loaded(self._spd_data, self._spd_selection)

    def _update_spd_controls(self) -> None:
        available = self._spd_data is not None
        self.spd_selection_button.setVisible(available)
        self.spd_selection_label.setVisible(available)
        self.spd_selection_button.setEnabled(
            available and self.pin_path_edit.text() == self._loaded_pin_path
            and not self._loading_input and self._worker is None
            and self._selection_worker is None and not self._selection_timer.isActive()
        )

    def _restore_loaded_path(self) -> None:
        """After a failed or cancelled load, show the file that is actually loaded again.

        With nothing loaded there is nothing to go back to, so the chosen path
        stays: the file can be corrected and loaded again without browsing twice.
        """
        if self.all_pins:
            self.pin_path_edit.setText(self._loaded_pin_path)

    def _show_spd_selection(self, data, component: str, site: int | None) -> None:
        self._spd_data = data
        self._spd_selection = (component, site)
        site_label = "unassigned" if site is None else str(site)
        self.spd_selection_label.setText(f"SPD component: {component} | Site: {site_label}")
        self.spd_selection_label.setToolTip(self.spd_selection_label.text())
        self._update_spd_controls()

    def _on_spd_loaded(self, data, selection: tuple[str, int | None] | None = None) -> None:
        try:
            dialog = SpdSelectionDialog(data, self, selection=selection)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                dialog.deleteLater()
                if selection is not None:
                    return
                self._loading_input = False
                self._restore_loaded_path()
                self._set_controls_enabled(True)
                self._request_selection_update()
                self._log(
                    "SPD selection cancelled; previous input retained." if self.all_pins else "SPD selection cancelled."
                )
                return
            component, site = dialog.selection()
            dialog.deleteLater()
            if selection == (component, site):
                return
            pins = data.pins(component, site)
            if not pins:
                raise ValueError("The selected SPD component and site contain no pins.")
            site_label = "unassigned" if site is None else str(site)
            self._log(
                f"SPD selection: {len(data.components)} components, "
                f"{len(data.sites(component))} sites for {component}; site={site_label}."
            )
            self._on_inputs_loaded(pins, is_spd=True)
            self._show_spd_selection(data, component, site)
        except Exception as exc:
            self._on_load_failed(str(exc))

    def _on_inputs_loaded(self, pins: list[PinRecord], *, is_spd: bool = False) -> None:
        self._loading_input = False
        self._loaded_pin_path = self.pin_path_edit.text()
        if not is_spd:
            self._spd_data = None
            self._spd_selection = None
            self.spd_selection_label.clear()
            self._update_spd_controls()
        self._apply_loaded_pins(pins)
        self._log(f"Input load complete: {len(self.all_pins)} pin rows.")
        self._log("Coordinates were automatically recentered so the input bounding-box center is at the origin.")
        self._log_probe_summary()
        self._start_selection_update()

    def _apply_loaded_pins(self, pins: list[PinRecord]) -> None:
        """Adopt ``pins`` as the loaded input and reset every filter control to match."""
        self.all_pins = pins
        self.selected_pins = []
        self._table_start = 0
        self.plot.show()
        self._picked_ids.clear()
        self._source_group_overrides.clear()
        self._source_group_colors.clear()
        self._side_overrides.clear()
        self._cache_bond_layout(pins)
        self._replace_input_groups = False
        self.replace_input_groups_check.blockSignals(True)
        self.replace_input_groups_check.setChecked(False)
        self.replace_input_groups_check.blockSignals(False)
        self._refresh_table()
        self.plot.set_data([], [], None)
        self._loading_controls = True
        try:
            devices = get_comp_devices(self.all_pins)
            if devices and any(not pin.comp_device for pin in self.all_pins):
                # Without an entry of their own, rows with an empty COMP_DEVICE
                # could never be selected once the device filter is in use.
                devices = ["", *devices]
            self.comp_device_label.setVisible(bool(devices))
            self.comp_list.setVisible(bool(devices))
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
            for spin in (self.x_min_spin, self.x_max_spin, self.y_min_spin, self.y_max_spin):
                spin.setValue(0.0)
            return
        self.x_min_spin.setValue(_range_lower_bound(min(pin.pin_x for pin in self.all_pins)))
        self.x_max_spin.setValue(_range_upper_bound(max(pin.pin_x for pin in self.all_pins)))
        self.y_min_spin.setValue(_range_lower_bound(min(pin.pin_y for pin in self.all_pins)))
        self.y_max_spin.setValue(_range_upper_bound(max(pin.pin_y for pin in self.all_pins)))

    def _on_load_failed(self, message: str) -> None:
        self._loading_input = False
        self._restore_loaded_path()
        self._log(f"Input error: {message}")
        self._set_controls_enabled(True)
        self._request_selection_update()
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
        if self._loading_controls or self._loading_input:
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
        if self._loading_controls or self._loading_input:
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
        worker = self.sender()
        if isinstance(worker, SelectionThread) and (worker._pins is not self.all_pins or self._loading_input):
            return
        self.selected_pins = selected
        self._apply_current_table_sort()
        self._refresh_table()
        self.plot.set_data(self.all_pins, self.selected_pins, (x_min, x_max, y_min, y_max))
        displayed = min(len(self.selected_pins), self.MAX_TABLE_ROWS)
        self._log(f"Selection updated: {len(self.selected_pins)} rows selected, {displayed} rows displayed.")

    def _on_selection_failed(self, message: str) -> None:
        worker = self.sender()
        if isinstance(worker, SelectionThread) and (worker._pins is not self.all_pins or self._loading_input):
            return
        self._log(f"Selection update failed: {message}")
        QMessageBox.critical(self, "Selection update failed", message)

    def _on_selection_finished(self) -> None:
        self._selection_worker = None
        if self._loading_input:
            return
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
        self._ensure_auto_sides()
        self._picked_ids.intersection_update(id(pin) for pin in self.selected_pins)
        self._table_start = min(self._table_start, max(0, len(self.selected_pins) - self.MAX_TABLE_ROWS))
        display_pins = self.selected_pins[self._table_start : self._table_start + self.MAX_TABLE_ROWS]
        if self._picked_ids and not any(id(pin) in self._picked_ids for pin in display_pins):
            index = next(index for index, pin in enumerate(self.selected_pins) if id(pin) in self._picked_ids)
            self._table_start = min(index, max(0, len(self.selected_pins) - self.MAX_TABLE_ROWS))
            display_pins = self.selected_pins[self._table_start : self._table_start + self.MAX_TABLE_ROWS]
        sides = [self._resolved_side(pin) for pin in display_pins]
        self._visible_pins = list(display_pins)
        self._sync_plot_styles()
        self.selected_table.blockSignals(True)
        self.selected_table.setUpdatesEnabled(False)
        try:
            self.selected_table.clearSelection()
            self.selected_table.setRowCount(len(display_pins))
            for row, pin in enumerate(display_pins):
                header = QTableWidgetItem(pin.pin_number)
                header.setToolTip(f"{pin.refdes} | Pin {pin.pin_number}")
                self.selected_table.setVerticalHeaderItem(row, header)
                values = [
                    _format_coordinate(pin.pin_x),
                    _format_coordinate(pin.pin_y),
                    pin.net_name,
                    self._effective_source_group_for_pin(pin),
                    sides[row],
                ]
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    if column == 3:
                        item.setData(Qt.ItemDataRole.DecorationRole, QColor(self.plot.group_color(value)))
                    item.setToolTip(f"Pin {pin.pin_number} | NET {pin.net_name} | Source {values[3]} | CIS side {values[4]}"
                                    f" | Predicted probe: {self._predicted_probe_type(pin)}")
                    self.selected_table.setItem(row, column, item)
            self.selected_table.resizeColumnsToContents()
        finally:
            self.selected_table.setUpdatesEnabled(True)
            self.selected_table.blockSignals(False)
        self._sync_picked_pins()
        self._refresh_source_group_color_controls()
        counts = Counter(self._predicted_probe_type(pin) for pin in self.selected_pins)
        self.probe_type_count_label.setText("Probe type (filtered): " + " / ".join(f"{kind} {counts[kind]}" for kind in ("Long", "Short", "Undetermined")))

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
            self._ensure_auto_sides()
            return [self._resolved_side(pin) for pin in pins]
        return [""] * len(pins)

    def _effective_source_group_for_pin(self, pin: PinRecord) -> str:
        if id(pin) in self._source_group_overrides:
            return self._source_group_overrides[id(pin)]
        has_input_group = bool(pin.source_probe_name.strip() or pin.comp_device.strip())
        if self._automatic_probe_groups and (self._replace_input_groups or not has_input_group):
            probe_type = self._predicted_probe_type(pin)
            if probe_type == "Long":
                return self._long_probe_group
            if probe_type == "Short":
                return self._short_probe_group
        return source_group_name_for_pin(pin)

    def _effective_pin(self, pin: PinRecord) -> PinRecord:
        source_group = self._effective_source_group_for_pin(pin)
        return pin if source_group == source_group_name_for_pin(pin) else replace(pin, source_probe_name=source_group)

    def _effective_pins(self) -> list[PinRecord]:
        return [self._effective_pin(pin) for pin in self._generation_pins()]

    def _generation_pins(self) -> list[PinRecord]:
        return self._picked_pins() if self.picked_only_check.isChecked() else self.selected_pins

    def apply_source_group_to_selected_rows(self) -> None:
        source_group = self.source_group_edit.text().strip()
        if not source_group:
            QMessageBox.warning(self, "Missing source group", "Enter an HFSS source group name first.")
            return
        pins = self._picked_pins()
        if not pins:
            QMessageBox.warning(self, "No picked pins", "Pick one or more pins in the map or preview table first.")
            return
        for pin in pins:
            self._source_group_overrides[id(pin)] = source_group
        self._apply_current_table_sort()
        self._refresh_table()
        self._log(f"Applied source group override to {len(pins)} picked pins: {source_group}")

    def apply_source_group_to_current_coordinates(self) -> None:
        source_group = self.source_group_edit.text().strip()
        if not source_group:
            QMessageBox.warning(self, "Missing source group", "Enter an HFSS source group name first.")
            return
        for pin in self.selected_pins:
            self._source_group_overrides[id(pin)] = source_group
        self._apply_current_table_sort()
        self._refresh_table()
        self._log(f"Applied source group override to {len(self.selected_pins)} selected coordinates: {source_group}")

    def clear_source_group_overrides(self) -> None:
        count = len(self._source_group_overrides)
        self._source_group_overrides.clear()
        self._apply_current_table_sort()
        self._refresh_table()
        self._log(f"Cleared {count} source group overrides.")

    def _ensure_auto_sides(self) -> None:
        # Normal loads populate this once; direct selected_pins callers remain supported.
        pins = self.all_pins or self.selected_pins
        if any(id(pin) not in self._auto_sides for pin in pins):
            self._cache_bond_layout(pins)

    def _cache_bond_layout(self, pins: list[PinRecord]) -> None:
        sides, lanes = infer_bond_layout(pins)
        self._auto_sides = dict(zip(map(id, pins), sides))
        self._bond_lanes = dict(zip(map(id, pins), lanes))

    def _predicted_probe_type(self, pin: PinRecord) -> str:
        if self._resolved_side(pin) != self._auto_sides.get(id(pin)):
            return "Undetermined"
        lane = self._bond_lanes.get(id(pin))
        if lane not in ("outer", "inner"):
            return "Undetermined"
        return "Long" if (lane == "outer") == self._tips_toward_center else "Short"

    def apply_probe_inference(self, *, validate_groups: bool = True, show_warning: bool = True) -> None:
        enabled = self.automatic_probe_groups_check.isChecked()
        long_group = self.long_probe_group_edit.text().strip()
        short_group = self.short_probe_group_edit.text().strip()
        if validate_groups and (not long_group or not short_group or long_group == short_group):
            if show_warning:
                QMessageBox.warning(self, "Invalid probe groups", "Enter two different, nonblank HFSS group names. Previous inference settings were retained.")
            return
        self._automatic_probe_groups = enabled
        self._tips_toward_center = self.tip_orientation_combo.currentIndex() == 0
        self._replace_input_groups = self.replace_input_groups_check.isChecked()
        if validate_groups:
            self._long_probe_group, self._short_probe_group = long_group, short_group
        self._apply_current_table_sort()
        self._refresh_table()
        self._log_probe_summary()

    def _log_probe_summary(self) -> None:
        counts = Counter(self._predicted_probe_type(pin) for pin in self.all_pins)
        summary = " / ".join(f"{kind} {counts[kind]}" for kind in ("Long", "Short", "Undetermined"))
        orientation = "toward center" if self._tips_toward_center else "toward outside"
        self._log(f"Geometry probe estimate: {summary}; tips {orientation}; automatic groups {'on' if self._automatic_probe_groups else 'off'}.")

    def _resolved_side(self, pin: PinRecord) -> str:
        return self._side_overrides.get(id(pin), self._auto_sides.get(id(pin), "right"))

    def _picked_pins(self) -> list[PinRecord]:
        return [pin for pin in self.selected_pins if id(pin) in self._picked_ids]

    def _sync_picked_pins(self) -> None:
        selection = QItemSelection()
        for row, pin in enumerate(self._visible_pins):
            if id(pin) in self._picked_ids:
                selection.select(self.selected_table.model().index(row, 0), self.selected_table.model().index(row, 4))
        self.selected_table.blockSignals(True)
        try:
            self.selected_table.selectionModel().select(selection, QItemSelectionModel.SelectionFlag.ClearAndSelect)
        finally:
            self.selected_table.blockSignals(False)
        picked = self._picked_pins()
        self.plot.set_highlighted_pins(picked)
        self.picked_count_label.setText(f"Picked: {len(picked)} / Filtered: {len(self.selected_pins)}")

    def _on_map_pins_picked(self, pins: list[PinRecord], toggle: bool) -> None:
        eligible = {id(pin) for pin in self.selected_pins}
        picked = {id(pin) for pin in pins} & eligible
        if toggle:
            self._picked_ids.symmetric_difference_update(picked)
        else:
            self._picked_ids = picked
        visible_ids = {id(pin) for pin in self._visible_pins}
        if picked - visible_ids:
            index = next(index for index, pin in enumerate(self.selected_pins) if id(pin) in picked)
            self._table_start = min(index, max(0, len(self.selected_pins) - self.MAX_TABLE_ROWS))
            self._refresh_table()
        else:
            self._sync_picked_pins()
        for row, pin in enumerate(self._visible_pins):
            if id(pin) in picked:
                self.selected_table.scrollToItem(self.selected_table.item(row, 0))
                break

    def _on_table_selection_changed(self) -> None:
        if QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier:
            self._picked_ids.difference_update(id(pin) for pin in self._visible_pins)
        else:
            self._picked_ids.clear()
        rows = self.selected_table.selectionModel().selectedRows()
        self._picked_ids.update(id(self._visible_pins[index.row()]) for index in rows)
        self._sync_picked_pins()

    def apply_side_to_picked_pins(self) -> None:
        pins = self._picked_pins()
        if not pins:
            QMessageBox.warning(self, "No picked pins", "Pick one or more pins in the map or preview table first.")
            return
        side = self.side_combo.currentText()
        for pin in pins:
            if side == "Auto":
                self._side_overrides.pop(id(pin), None)
            else:
                self._side_overrides[id(pin)] = side
        self._apply_current_table_sort()
        self._refresh_table()
        self._log(f"Applied CIS side {side} to {len(pins)} picked pins.")
        self._log_probe_summary()

    def _sync_plot_styles(self) -> None:
        pins = self.all_pins or self.selected_pins
        groups = {id(pin): self._effective_source_group_for_pin(pin) for pin in pins}
        sides = {id(pin): self._resolved_side(pin) for pin in pins}
        self.plot.set_pin_styles(groups, sides, self._source_group_colors)
        self.plot.set_tip_orientation(self._tips_toward_center)
        self.plot.set_probe_types({id(pin): self._predicted_probe_type(pin) for pin in pins})

    def _refresh_source_group_color_controls(self) -> None:
        current = self.source_group_color_combo.currentText()
        groups = list(dict.fromkeys(self._effective_source_group_for_pin(pin) for pin in (self.all_pins or self.selected_pins)))
        self.source_group_color_combo.blockSignals(True)
        self.source_group_color_combo.clear()
        self.source_group_color_combo.addItems(groups)
        if current in groups:
            self.source_group_color_combo.setCurrentText(current)
        self.source_group_color_combo.blockSignals(False)
        self._refresh_source_group_color_button()

    def _refresh_source_group_color_button(self) -> None:
        group = self.source_group_color_combo.currentText()
        color = self._source_group_colors.get(group, "")
        self.choose_source_color_button.setEnabled(bool(group))
        self.reset_source_color_button.setEnabled(bool(group and color))
        self.choose_source_color_button.setStyleSheet(f"border-bottom: 4px solid {color};" if color else "")

    def _choose_source_group_color(self) -> None:
        group = self.source_group_color_combo.currentText()
        if group:
            color = QColorDialog.getColor(QColor(self._source_group_colors.get(group, "#8fc1ff")), self, f"Select color for {group}")
            if color.isValid():
                self._set_source_group_color(group, color.name())

    def _set_source_group_color(self, group: str, color: str) -> None:
        parsed = QColor(color)
        if group.strip() and parsed.isValid():
            self._source_group_colors[group] = parsed.name()
            self._refresh_table()

    def _reset_current_source_group_color(self) -> None:
        self._source_group_colors.pop(self.source_group_color_combo.currentText(), None)
        self._refresh_table()

    def generate_script(self) -> None:
        generation_pins = self._generation_pins()
        if not generation_pins:
            message = "Pick at least one pin, or turn off Place picked pins only." if self.picked_only_check.isChecked() else "Load input files and select at least one coordinate."
            QMessageBox.warning(self, "No selection", message)
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
        self._ensure_auto_sides()
        pin_sides = [self._resolved_side(pin) for pin in generation_pins]
        self._log_selection_summary(effective_pins, pin_sides)
        self._worker = GenerateThread(effective_pins, options, Path(output_path), self, pin_sides=pin_sides)
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

    def _log_selection_summary(self, pins: list[PinRecord], pin_sides: list[str] | None = None) -> None:
        side_counts = Counter(pin_sides if pin_sides is not None else classify_pin_sides(pins))
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
        self.spd_selection_button.setEnabled(
            enabled and self._spd_data is not None and self.pin_path_edit.text() == self._loaded_pin_path
        )

    def _set_controls_enabled(self, enabled: bool) -> None:
        for widget in (
            self.project_edit,
            self.design_edit,
            self.browse_pin_button,
            self.load_button,
            self.spd_selection_button,
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
            self.side_combo,
            self.apply_side_button,
            self.source_group_color_combo,
            self.choose_source_color_button,
            self.reset_source_color_button,
            self.picked_only_check,
            self.automatic_probe_groups_check,
            self.tip_orientation_combo,
            self.long_probe_group_edit,
            self.short_probe_group_edit,
            self.replace_input_groups_check,
            self.apply_probe_inference_button,
            self.reset_button,
            self.generate_button,
            self.selected_table,
            self.plot,
        ):
            widget.setEnabled(enabled)
        if enabled:
            self._update_spd_controls()
            self._refresh_source_group_color_button()


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


def _sample_spd_data() -> SpdData:
    """Small SPD inventory: a DUT part placed at three sites, and a capacitor part."""
    records: dict[str, dict[int | None, list[PinRecord]]] = {"DUT": {}, "CAP0402": {None: []}}
    for site in range(3):
        records["DUT"][site] = [
            PinRecord(f"SITE{site}", f"A{index + 1}", "DUT", "", "PAD80", pin.pin_x + site * 12.0, pin.pin_y, net)
            for index, pin in enumerate(_sample_pins())
            for net in ["DGND" if "DGND" in pin.net_name else f"{pin.net_name}/{site}"]
        ]
    for index in range(4):
        records["CAP0402"][None] += [
            PinRecord(f"C{index + 1}", "1", "CAP0402", "", "C0402", 40.0 + index, 9.0, "VDD"),
            PinRecord(f"C{index + 1}", "2", "CAP0402", "", "C0402", 40.0 + index, 9.5, "DGND"),
        ]
    return SpdData(records)


# A complete, minimal SPD file. The packaged application reads it during its
# start-up check, so a build that cannot import SPD pins is caught before release.
_SMOKE_SPD_TEXT = """\
.Package $Package
Node101!!A1::CLK/3 X = 1250um Y = 400um PadStack = PAD80
Node102!!A2::DGND X = 1.25mm Y = 0.9mm PadStack = PAD80
.EndPackage
.Connect SITE3 DUT
A1 $Package.Node101!!A1::CLK/3
A2 $Package.Node102!!A2::DGND
.EndC
"""

GUI_OVERVIEW_WIDTH = 860
GUI_OVERVIEW_WINDOW_WIDTH = 1270
SPD_CONTROLS_WIDTH = 760


def _group_title_rect(group: QGroupBox) -> QRect:
    """Area covered by the title of ``group``, in the coordinates of the group."""
    option = QStyleOptionGroupBox()
    group.initStyleOption(option)
    title = group.style().subControlRect(
        QStyle.ComplexControl.CC_GroupBox, option, QStyle.SubControl.SC_GroupBoxLabel, group
    )
    font = QFont(group.font())
    font.setBold(True)  # at least as wide as the title weight of the theme
    text_right = title.left() + QFontMetrics(font).horizontalAdvance(group.title())
    title.setRight(max(title.right(), text_right))
    return title


def _settle_layout(window: MainWindow) -> None:
    """Lay out a window that is never shown, the way showing it would.

    A scroll area shows or hides its scroll bars through a queued call after
    their range has changed, and the space this frees or takes is used at the
    next layout. Shown windows get there through the event loop; here the two
    steps are repeated until nothing moves any more.
    """
    areas = window.findChildren(QAbstractScrollArea)
    previous = None
    for _ in range(8):
        window.grab(QRect(0, 0, 1, 1))  # lays out and sends the pending resize events
        # Only the calls of these scroll areas are delivered: the picture is drawn
        # while the help is being laid out, where other events must wait.
        for area in areas:
            QApplication.sendPostedEvents(area, QEvent.Type.MetaCall)
        state = [
            (area.viewport().size(), area.horizontalScrollBar().isVisibleTo(area), area.verticalScrollBar().isVisibleTo(area))
            for area in areas
        ]
        if state == previous:
            break
        previous = state


def _show_all_table_columns(window: MainWindow) -> None:
    """Give the preview table the width of its five columns; the map keeps the rest."""
    table, splitter = window.selected_table, window.preview_splitter
    needed = (
        table.verticalHeader().width()
        + table.horizontalHeader().length()
        + table.verticalScrollBar().sizeHint().width()
        + 2 * table.frameWidth()
    )
    shortfall = needed + window.plot.minimumWidth() - sum(splitter.sizes())
    if shortfall > 0:
        # A wide font: widen the window and give all of the gain to the right-hand side.
        left, right = window.main_splitter.sizes()
        window.resize(window.width() + shortfall, window.height())
        _settle_layout(window)
        window.main_splitter.setSizes([left, right + shortfall])
        _settle_layout(window)
    total = sum(splitter.sizes())
    splitter.setSizes([needed, max(total - needed, 0)])


def _make_room_after_tabs(window: MainWindow, radius: int) -> None:
    """Widen the left panel until a marker of ``radius`` fits right of the last tab."""
    panel, tab_bar = window._left_panel, window.control_tabs.tabBar()
    last_tab = tab_bar.tabRect(tab_bar.count() - 1)
    shortage = tab_bar.mapTo(panel, QPoint(last_tab.right(), 0)).x() + 2 * radius + 4 - panel.width()
    if shortage > 0:
        left, right = window.main_splitter.sizes()
        window.resize(window.width() + shortage, window.height())
        _settle_layout(window)
        window.main_splitter.setSizes([left + shortage, right])
        _settle_layout(window)


# Radius of a marker of the main-window picture, in window coordinates. It is
# fixed there, so that a marker keeps its size against the controls it sits
# between when a wide font makes the window, and with it the scaling, larger.
GUI_OVERVIEW_MARKER_RADIUS = math.ceil(CALLOUT_RADIUS * GUI_OVERVIEW_WINDOW_WIDTH / GUI_OVERVIEW_WIDTH)


def gui_overview_markers(window: MainWindow, radius: int) -> list[QPoint]:
    """Centres of the numbered markers of the main-window picture, in window coordinates.

    They are derived from the widgets, so that a marker of ``radius`` never
    hides the caption it points at, whatever the font of the machine.
    """
    def after_title(group: QGroupBox) -> QPoint:
        title = _group_title_rect(group)
        return QPoint(title.right() + radius + 8, title.center().y())

    file_group = window.file_group
    tab_bar = window.control_tabs.tabBar()
    last_tab = tab_bar.tabRect(tab_bar.count() - 1)
    markers = [
        # Below the tabs, right of the "Coordinate file" caption.
        (file_group, QPoint(file_group.width() - radius - 12, window.pin_path_edit.y() - radius - 1)),
        (window.filter_group, after_title(window.filter_group)),
        (window.net_group, after_title(window.net_group)),
        (tab_bar, QPoint(last_tab.right() + radius + 4, last_tab.center().y())),
        (window.generate_button, QPoint(40, 12)),
        (window.selected_table, QPoint(10, 10)),
        (window.plot, QPoint(30, 30)),
        (window.log_edit, QPoint(window.log_edit.width() - 26, 20)),
    ]
    return [widget.mapTo(window, offset) for widget, offset in markers]


def prepare_gui_overview(window: MainWindow) -> None:
    """Bring ``window`` to the state shown in the main-window picture of the help."""
    window.resize(GUI_OVERVIEW_WINDOW_WIDTH, window.full_content_height())
    window.show_sample_state()
    _settle_layout(window)
    _show_all_table_columns(window)
    _settle_layout(window)
    _make_room_after_tabs(window, GUI_OVERVIEW_MARKER_RADIUS)


def render_gui_overview(dpr: float) -> QImage:
    """Picture of the main window showing the built-in example, with numbered markers."""
    window = MainWindow()
    try:
        prepare_gui_overview(window)
        shot = window.grab().toImage()
        scale = GUI_OVERVIEW_WIDTH / window.width()
        dpr = max(float(dpr), 1.0)
        image = shot.scaledToWidth(round(GUI_OVERVIEW_WIDTH * dpr), Qt.TransformationMode.SmoothTransformation)
        image = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(dpr)

        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setPen(QPen(QColor("#94a3b8"), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(0, 0, GUI_OVERVIEW_WIDTH - 1, round(window.height() * scale) - 1)
        radius = GUI_OVERVIEW_MARKER_RADIUS
        for number, position in enumerate(gui_overview_markers(window, radius), start=1):
            draw_callout(painter, QPointF(position.x() * scale, position.y() * scale), str(number), radius * scale)
        painter.end()
        return image
    finally:
        window.deleteLater()


def render_spd_controls(dpr: float) -> QImage:
    """The SPD selection window beside the Input Files area as it looks after an SPD load."""
    dpr = max(float(dpr), 1.0)
    window = MainWindow()
    dialog = SpdSelectionDialog(_sample_spd_data())
    try:
        window.resize(GUI_OVERVIEW_WINDOW_WIDTH, window.full_content_height())
        window.show_spd_sample_state()
        _settle_layout(window)
        shot = window.grab().toImage()
        ratio = shot.devicePixelRatio()
        group = window.file_group
        origin = group.mapTo(window, QPoint(0, 0))
        group_shot = shot.copy(
            QRect(
                round(origin.x() * ratio),
                round(origin.y() * ratio),
                round(group.width() * ratio),
                round(group.height() * ratio),
            )
        )
        dialog.adjustSize()
        dialog_shot = dialog.grab().toImage()

        caption_height, title_height, gap = 30, 26, 34
        dialog_rect = QRectF(1, caption_height + title_height, dialog.width(), dialog.height())
        group_left = dialog_rect.right() + gap
        group_scale = min(1.0, (SPD_CONTROLS_WIDTH - 1 - group_left) / group.width())
        group_rect = QRectF(group_left, caption_height, group.width() * group_scale, group.height() * group_scale)
        height = round(max(dialog_rect.bottom(), group_rect.bottom())) + 6

        image, painter = new_canvas(SPD_CONTROLS_WIDTH, height, dpr)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setFont(figure_font(13, bold=True))
        painter.setPen(QColor("#1f2937"))
        left_align = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        painter.drawText(QRectF(1, 0, dialog_rect.width() + gap, caption_height - 6), left_align, "Load Inputs 뒤에 열리는 선택 창")
        painter.drawText(QRectF(group_left, 0, group_rect.width(), caption_height - 6), left_align, "선택을 마친 뒤의 Input Files 영역")

        # The grab holds only the contents of the window, so draw its title bar.
        title_rect = QRectF(dialog_rect.left(), caption_height, dialog_rect.width(), title_height)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#e2e8f0"))
        painter.drawRect(title_rect)
        painter.setFont(figure_font(12))
        painter.setPen(QColor("#1f2937"))
        painter.drawText(title_rect.adjusted(10, 0, -10, 0), left_align, dialog.windowTitle())
        painter.drawImage(dialog_rect, dialog_shot)
        painter.drawImage(group_rect, group_shot)
        painter.setPen(QPen(QColor("#94a3b8"), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(title_rect.united(dialog_rect))
        painter.drawRect(group_rect)

        def in_dialog(widget: QWidget, offset: QPoint) -> QPointF:
            position = widget.mapTo(dialog, offset)
            return QPointF(dialog_rect.left() + position.x(), dialog_rect.top() + position.y())

        def in_group(widget: QWidget, offset: QPoint) -> QPointF:
            position = widget.mapTo(group, offset)
            return QPointF(group_rect.left() + position.x() * group_scale, group_rect.top() + position.y() * group_scale)

        combo = dialog.component_combo
        combo_offset = QPoint(combo.width() - 46, combo.height() // 2)
        label, button = window.spd_selection_label, window.spd_selection_button
        label_end = label.fontMetrics().horizontalAdvance(label.text())
        markers = [
            in_dialog(combo, combo_offset),
            in_dialog(dialog.site_combo, combo_offset),
            in_group(label, QPoint(label_end + 18, label.height() // 2)),
            in_group(button, QPoint(button.width() + 2, -2)),
        ]
        for number, center in enumerate(markers, start=1):
            draw_callout(painter, center, str(number))
        painter.end()
        return image
    finally:
        dialog.deleteLater()
        window.deleteLater()


HELP_EXTRA_FIGURES = {"gui-overview": render_gui_overview, "spd-controls": render_spd_controls}


def run_smoke_check() -> int:
    """Build the main window and the help without entering the event loop.

    Returns 0 when everything needed at run time is in place: the Qt plugins,
    the bundled help document, every picture it refers to, the picture used by
    the theme, and the SPD reader.
    Packaged builds are verified with this before they are published.
    """
    try:
        app = QApplication.instance() or QApplication(sys.argv)
        window = MainWindow()
        window.show_sample_state()
        dialog = HelpDialog(extra_figures=HELP_EXTRA_FIGURES)
        problems = [f"missing help picture: {name}" for name in dialog.missing_figures()]
        if QPixmap(f"{ASSET_PREFIX}:{CHECK_MARK.name}").isNull():
            problems.append(f"missing theme picture: {CHECK_MARK.name}")
        if dialog.toc.topLevelItemCount() == 0:
            problems.append("help document has no sections")
        if len(window.selected_pins) != window.selected_table.rowCount():
            problems.append("preview table does not show the sample coordinates")
        with tempfile.TemporaryDirectory() as folder:
            spd_path = Path(folder) / "start-up-check.spd"
            spd_path.write_text(_SMOKE_SPD_TEXT, encoding="utf-8")
            spd_pins = read_spd(spd_path).pins("DUT", 3)
        if [(pin.pin_number, pin.net_name) for pin in spd_pins] != [("A1", "CLK/3"), ("A2", "DGND")]:
            problems.append("SPD import does not return the sample pins")
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
