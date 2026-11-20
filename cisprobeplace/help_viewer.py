"""Built-in help viewer.

The help is an HTML document rendered inside the application by QTextBrowser,
so it needs neither a web browser nor any additional process.
"""

from __future__ import annotations

import html as html_lib
import re
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QFont, QImage, QKeySequence, QPalette, QShortcut, QTextCursor, QTextDocument
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .help_figures import FIGURE_RENDERERS, FigureRenderer, render_unavailable
from .theme import apply_theme


HELP_FILE = Path(__file__).resolve().parent / "help" / "help_ko.html"
HELP_WINDOW_TITLE = "CIS Probe Placement Scriptor Help"
FIGURE_SCHEME = "figure"
VERSION_PLACEHOLDER = "{{APP_VERSION}}"
TEXT_FONT_FAMILIES = ["Malgun Gothic", "Segoe UI", "Apple SD Gothic Neo", "Noto Sans CJK KR", "NanumGothic"]

_HEADING_PATTERN = re.compile(r'<h([23])[^>]*>\s*<a name="([^"]+)"></a>(.*?)</h\1>', re.DOTALL)
_FIGURE_PATTERN = re.compile(r'src="figure:([^"]+)"')
_TAG_PATTERN = re.compile(r"<[^>]+>")
_ANCHOR_ROLE = Qt.ItemDataRole.UserRole


def load_help_html() -> str:
    """Return the help document with the application version filled in."""
    return HELP_FILE.read_text(encoding="utf-8").replace(VERSION_PLACEHOLDER, __version__)


def extract_table_of_contents(document_html: str) -> list[tuple[int, str, str]]:
    """List the ``(level, anchor, title)`` of every numbered section heading."""
    entries: list[tuple[int, str, str]] = []
    for match in _HEADING_PATTERN.finditer(document_html):
        title = html_lib.unescape(_TAG_PATTERN.sub("", match.group(3)))
        entries.append((int(match.group(1)), match.group(2), " ".join(title.split())))
    return entries


def extract_figure_names(document_html: str) -> list[str]:
    """Names of the ``figure:<name>`` pictures the document refers to."""
    return _FIGURE_PATTERN.findall(document_html)


class HelpBrowser(QTextBrowser):
    """Text browser that draws ``figure:<name>`` images itself and never leaves the document."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._figure_renderers: dict[str, FigureRenderer] = dict(FIGURE_RENDERERS)
        self._figure_cache: dict[str, QImage] = {}
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.anchorClicked.connect(self._follow_link)

        # The document carries its own light colours, so keep the page light even
        # when the desktop uses a dark theme.
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.Text, QColor("#1f2937"))
        # A search hit is selected while the keyboard focus stays in the search
        # field, so the unfocused selection must be as visible as a focused one.
        for role in (QPalette.ColorRole.Highlight, QPalette.ColorRole.HighlightedText):
            palette.setColor(QPalette.ColorGroup.Inactive, role, palette.color(QPalette.ColorGroup.Active, role))
        self.setPalette(palette)
        font = QFont(self.font())
        font.setFamilies(TEXT_FONT_FAMILIES)
        font.setPointSize(10)
        self.document().setDefaultFont(font)
        self.document().setDocumentMargin(18)

    def set_figure_renderer(self, name: str, renderer: FigureRenderer) -> None:
        self._figure_renderers[name] = renderer
        self._figure_cache.pop(name, None)

    def prepare_figures(self, names: list[str]) -> None:
        """Draw the given pictures now, before the document is laid out or painted."""
        for name in names:
            self._figure(name)

    def has_figure(self, name: str) -> bool:
        """Whether ``name`` can actually be drawn (rather than replaced by a notice)."""
        renderer = self._figure_renderers.get(name)
        if renderer is None:
            return False
        try:
            image = renderer(self.devicePixelRatioF())
        except Exception:
            return False
        return image is not None and not image.isNull()

    def loadResource(self, kind: int, url: QUrl):  # noqa: N802 - Qt API
        if url.scheme() == FIGURE_SCHEME:
            return self._figure(url.path())
        return super().loadResource(kind, url)

    def _figure(self, name: str) -> QImage:
        if name not in self._figure_cache:
            dpr = self.devicePixelRatioF()
            renderer = self._figure_renderers.get(name)
            image: QImage | None = None
            if renderer is not None:
                try:
                    image = renderer(dpr)
                except Exception:  # A missing picture must never keep the help from opening.
                    image = None
            if image is None or image.isNull():
                image = render_unavailable(dpr)
            self._figure_cache[name] = image
        return self._figure_cache[name]

    def _follow_link(self, url: QUrl) -> None:
        # Only links to a section of this document are followed.
        if url.hasFragment() and not url.scheme() and not url.path():
            self.scrollToAnchor(url.fragment())


class HelpDialog(QDialog):
    """Help window: contents on the left, the document on the right, search on top."""

    def __init__(self, parent: QWidget | None = None, extra_figures: dict[str, FigureRenderer] | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(HELP_WINDOW_TITLE)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        width, height = 1240, 860
        screen = self.screen()
        if screen is not None:
            available = screen.availableGeometry()
            width = min(width, available.width() - 40)
            height = min(height, available.height() - 80)
        self.resize(width, height)
        apply_theme(self)
        self._anchor_tops_cache: tuple[tuple[float, float], list[tuple[float, str]]] | None = None
        self._following_contents_click = False

        self.browser = HelpBrowser(self)
        self.browser.setObjectName("help_browser")
        for name, renderer in (extra_figures or {}).items():
            self.browser.set_figure_renderer(name, renderer)

        self.toc = QTreeWidget(self)
        self.toc.setObjectName("help_toc")
        self.toc.setHeaderHidden(True)
        self.toc.setIndentation(14)
        self.toc.setMinimumWidth(200)

        self.search_edit = QLineEdit(self)
        self.search_edit.setObjectName("help_search")
        self.search_edit.setPlaceholderText("도움말에서 찾기 (Enter: 다음 찾기)")
        self.search_edit.setClearButtonEnabled(True)
        self.find_previous_button = QPushButton("이전", self)
        self.find_next_button = QPushButton("다음", self)
        self.search_status = QLabel(self)
        self.search_status.setMinimumWidth(170)
        close_button = QPushButton("닫기", self)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("찾기", self))
        search_row.addWidget(self.search_edit, 1)
        search_row.addWidget(self.find_previous_button)
        search_row.addWidget(self.find_next_button)
        search_row.addWidget(self.search_status)

        contents = QWidget(self)
        contents_layout = QVBoxLayout(contents)
        contents_layout.setContentsMargins(0, 0, 0, 0)
        contents_layout.addWidget(QLabel("목차", contents))
        contents_layout.addWidget(self.toc, 1)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.addWidget(contents)
        splitter.addWidget(self.browser)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([250, 990])

        layout = QVBoxLayout(self)
        layout.addLayout(search_row)
        layout.addWidget(splitter, 1)
        layout.addWidget(close_button, 0, alignment=Qt.AlignmentFlag.AlignRight)

        document_html = load_help_html()
        self._figure_names = extract_figure_names(document_html)
        # One picture is a rendering of the main window; doing that up front keeps
        # it out of this document's own layout and paint passes.
        self.browser.prepare_figures(self._figure_names)
        self.browser.setHtml(document_html)
        self._populate_contents(extract_table_of_contents(document_html))

        self.toc.currentItemChanged.connect(self._on_contents_item_changed)
        self.toc.itemClicked.connect(lambda item, _column: self._on_contents_item_changed(item, None))
        self.browser.verticalScrollBar().valueChanged.connect(self._sync_contents_to_scroll)
        self.search_edit.returnPressed.connect(self.find_next)
        self.search_edit.textChanged.connect(lambda _: self.search_status.clear())
        self.find_next_button.clicked.connect(self.find_next)
        self.find_previous_button.clicked.connect(self.find_previous)
        close_button.clicked.connect(self.close)
        for button in (self.find_previous_button, self.find_next_button, close_button):
            button.setAutoDefault(False)
        QShortcut(QKeySequence.StandardKey.Find, self, activated=self._focus_search)

    def missing_figures(self) -> list[str]:
        """Pictures the document refers to that cannot be drawn."""
        return [name for name in self._figure_names if not self.browser.has_figure(name)]

    # ------------------------------------------------------------------ contents

    def _populate_contents(self, entries: list[tuple[int, str, str]]) -> None:
        self.toc.clear()
        section: QTreeWidgetItem | None = None
        for level, anchor, title in entries:
            if level == 2 or section is None:
                item = QTreeWidgetItem(self.toc, [title])
                section = item
            else:
                item = QTreeWidgetItem(section, [title])
            item.setData(0, _ANCHOR_ROLE, anchor)
        self.toc.expandAll()

    def scroll_to(self, anchor: str) -> None:
        self.browser.scrollToAnchor(anchor)

    def _on_contents_item_changed(self, current: QTreeWidgetItem | None, _previous: QTreeWidgetItem | None) -> None:
        if current is None:
            return
        # Keep the clicked entry highlighted even when its section is too short
        # to reach the top of the page.
        self._following_contents_click = True
        try:
            self.scroll_to(str(current.data(0, _ANCHOR_ROLE)))
        finally:
            self._following_contents_click = False

    def _anchor_tops(self) -> list[tuple[float, str]]:
        document = self.browser.document()
        size = document.size()
        key = (size.width(), size.height())
        if self._anchor_tops_cache is not None and self._anchor_tops_cache[0] == key:
            return self._anchor_tops_cache[1]
        layout = document.documentLayout()
        tops: list[tuple[float, str]] = []
        block = document.begin()
        while block.isValid():
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.isValid():
                    for name in fragment.charFormat().anchorNames():
                        tops.append((layout.blockBoundingRect(block).top(), name))
                iterator += 1
            block = block.next()
        self._anchor_tops_cache = (key, tops)
        return tops

    def _sync_contents_to_scroll(self, value: int) -> None:
        """Highlight the section that is currently at the top of the page."""
        if self._following_contents_click:
            return
        # Only headings listed in the contents can be highlighted; the document
        # also has link targets on smaller headings.
        listed = {item.data(0, _ANCHOR_ROLE) for item in self._contents_items()}
        tops = [entry for entry in self._anchor_tops() if entry[1] in listed]
        if not tops:
            return
        # Above the first heading (the title block) the first section is current.
        current_anchor = tops[0][1]
        scroll_bar = self.browser.verticalScrollBar()
        if scroll_bar.maximum() > 0 and value >= scroll_bar.maximum():
            # At the very end the last section is on screen but cannot reach the top.
            current_anchor = tops[-1][1]
        else:
            for top, name in tops:
                if top > value + 24:
                    break
                current_anchor = name
        for item in self._contents_items():
            if item.data(0, _ANCHOR_ROLE) == current_anchor:
                if item is not self.toc.currentItem():
                    self.toc.blockSignals(True)
                    self.toc.setCurrentItem(item)
                    self.toc.blockSignals(False)
                return

    def _contents_items(self) -> list[QTreeWidgetItem]:
        items: list[QTreeWidgetItem] = []
        for index in range(self.toc.topLevelItemCount()):
            section = self.toc.topLevelItem(index)
            items.append(section)
            items.extend(section.child(child_index) for child_index in range(section.childCount()))
        return items

    # -------------------------------------------------------------------- search

    def _focus_search(self) -> None:
        self.search_edit.setFocus()
        self.search_edit.selectAll()

    def find_next(self) -> bool:
        return self._find(backward=False)

    def find_previous(self) -> bool:
        return self._find(backward=True)

    def _bring_match_into_view(self) -> None:
        """Scroll so the match sits in the upper part of the page, not on its edge."""
        scroll_bar = self.browser.verticalScrollBar()
        match_top = self.browser.cursorRect().top()
        scroll_bar.setValue(scroll_bar.value() + match_top - self.browser.viewport().height() // 3)

    def _find(self, backward: bool) -> bool:
        text = self.search_edit.text()
        if not text:
            self.search_status.clear()
            return False
        flags = QTextDocument.FindFlag.FindBackward if backward else QTextDocument.FindFlag(0)
        if self.browser.find(text, flags):
            self.search_status.clear()
            self._bring_match_into_view()
            return True
        # Nothing further in this direction: wrap around once.
        cursor = self.browser.textCursor()
        previous = QTextCursor(cursor)
        cursor.movePosition(QTextCursor.MoveOperation.End if backward else QTextCursor.MoveOperation.Start)
        self.browser.setTextCursor(cursor)
        if self.browser.find(text, flags):
            self.search_status.setText("처음부터 다시 찾았습니다" if not backward else "끝에서부터 다시 찾았습니다")
            self._bring_match_into_view()
            return True
        self.browser.setTextCursor(previous)
        self.search_status.setText("찾는 내용이 없습니다")
        return False
