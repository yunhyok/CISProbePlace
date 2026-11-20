import os
import re
import sys
from pathlib import Path

import pytest

from cisprobeplace import __version__
from cisprobeplace.data_io import HEADER_ALIASES, PIN_COLUMNS, DataValidationError, load_pin_records
from cisprobeplace.help_viewer import (
    HELP_FILE,
    VERSION_PLACEHOLDER,
    extract_figure_names,
    extract_table_of_contents,
    load_help_html,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _application():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication(sys.argv)


def _plain_text(document_html: str) -> str:
    import html

    return html.unescape(re.sub(r"<[^>]+>", "", document_html))


def test_help_document_is_an_html_file_with_the_running_version():
    assert HELP_FILE.suffix == ".html"
    assert VERSION_PLACEHOLDER in HELP_FILE.read_text(encoding="utf-8")

    document_html = load_help_html()

    assert VERSION_PLACEHOLDER not in document_html
    assert f"v{__version__}" in document_html
    # The page must stand on its own: nothing is fetched from outside the application.
    assert "http://" not in document_html
    assert "https://" not in document_html
    assert "<script" not in document_html.lower()


def test_help_contents_and_internal_links_are_consistent():
    document_html = load_help_html()
    anchors = re.findall(r'<a name="([^"]+)"></a>', document_html)
    contents = extract_table_of_contents(document_html)

    assert len(anchors) == len(set(anchors))
    assert [title for level, _, title in contents if level == 2][:3] == [
        "1. \ud55c\ub208\uc5d0 \ubcf4\uae30",
        "2. \ube60\ub978 \uc2dc\uc791",
        "3. \uc785\ub825 \ud30c\uc77c \uc591\uc2dd",
    ]
    # Sections and subsections are listed in the contents; smaller headings may
    # carry link targets of their own.
    listed = {anchor for _, anchor, _ in contents}
    assert listed <= set(anchors)
    assert set(anchors) - listed == {"spd-sites", "spd-errors"}
    assert all(title for _, _, title in contents)
    for target in re.findall(r'href="#([^"]+)"', document_html):
        assert target in anchors, target
    # Every link stays inside the document.
    assert all(link.startswith("#") for link in re.findall(r'href="([^"]+)"', document_html))


def test_help_documents_every_accepted_header_name():
    text = _plain_text(load_help_html())

    for column in PIN_COLUMNS:
        assert column in text, column
    for column, names in HEADER_ALIASES.items():
        for name in names:
            assert name in text, (column, name)


def test_help_lists_the_messages_raised_for_bad_input_files(tmp_path: Path):
    text = _plain_text(load_help_html())
    cases = {
        "notes.txt": "X,Y,NET\n1,2,N1\n",
        "no_header.csv": "A,B,C\n1,2,N1\n",
        "missing_value.csv": "X,Y,NET\n,2,N1\n",
        "bad_value.csv": "X,Y,NET\n1.5mm,2,N1\n",
        "no_rows.csv": "X,Y,NET\n",
    }
    documented = [
        "Unsupported file format for",
        "Could not find required header.",
        "Missing X\uc88c\ud45c at row",
        "Invalid X\uc88c\ud45c at row",
        "No pin records found in",
    ]

    for (file_name, content), message in zip(cases.items(), documented):
        path = tmp_path / file_name
        path.write_text(content, encoding="utf-8")
        with pytest.raises(DataValidationError) as error:
            load_pin_records(path)
        assert str(error.value).startswith(message), (file_name, str(error.value))
        assert message in text, message
    assert "Could not decode CSV file" in text


def test_help_lists_the_messages_raised_for_bad_spd_files(tmp_path: Path):
    from cisprobeplace.spd import _TO_MM, read_spd

    text = _plain_text(load_help_html())
    node = "Node1!!A1::CLK/3 X = 1mm Y = 2mm\n"
    connect = ".Connect SITE3 DUT\nA1 $Package.Node1\n.EndC\n"
    # (file content, the raised message, how the guide prints it)
    cases = [
        ("binary\x00data", "SPD must be a text file, not binary or UTF-16.", "SPD must be a text file, not binary or UTF-16."),
        (
            "* nothing but a comment\n",
            "No component pin coordinates found in SPD file case_1.spd.",
            "No component pin coordinates found in SPD file",
        ),
        (
            node + ".Connect SITE3 DUT\nA1 $Package.Node9\n.EndC\n",
            "SPD pin SITE3.A1 refers to a missing physical node.",
            "refers to a missing physical node.",
        ),
        (
            "Node1!!A1::CLK/3 X = 1 Y = 2mm\n" + connect,
            "Invalid or unsupported SPD coordinate unit for Node1: '1'.",
            "Invalid or unsupported SPD coordinate unit for",
        ),
        ("Node1!!A1::CLK/3 X = 1mm\n" + connect, "Missing SPD X/Y coordinate for Node1.", "Missing SPD X/Y coordinate for"),
        (
            "Node1!!A1::CLK/3 X = 1e999mm Y = 2mm\n" + connect,
            "SPD coordinate for Node1 must be finite: '1e999mm'.",
            "must be finite:",
        ),
        (
            node + "Node1!!A1::CLK/3 X = 5mm Y = 2mm\n" + connect,
            "Conflicting SPD physical node: Node1.",
            "Conflicting SPD physical node:",
        ),
        (
            node + ".Connect SITE3 DUT\n.Connect \tSITE4\n" + connect,
            "Malformed SPD .Connect header at line 3.",
            "Malformed SPD .Connect header at line",
        ),
        (
            node + ".Connect SITE3 DUT\nA1 B2 $Package.Node1\n.EndC\n",
            "Malformed SPD pin connection for 'SITE3' at line 3.",
            "Malformed SPD pin connection for",
        ),
        (
            "Node1!! X = 1mm Y = 2mm\n" + connect,
            "Malformed SPD physical node record: 'Node1!! X = 1mm Y = 2mm'.",
            "Malformed SPD physical node record:",
        ),
    ]

    for index, (content, message, documented) in enumerate(cases):
        path = tmp_path / f"case_{index}.spd"
        path.write_text(content, encoding="utf-8")
        with pytest.raises(DataValidationError) as error:
            read_spd(path)
        assert str(error.value) == message, content
        assert documented in text, documented
    with pytest.raises(DataValidationError, match="Could not read SPD file"):
        read_spd(tmp_path / "missing.spd")
    assert "Could not read SPD file" in text
    assert "Could not decode SPD pin data as UTF-8 or CP949." in text

    # Every unit the reader converts is named in the guide.
    for unit in _TO_MM:
        assert unit.replace("\u03bc", "\u00b5") in text, unit


def test_every_help_figure_is_drawn_at_any_screen_scale():
    _application()
    from cisprobeplace.gui import GUI_OVERVIEW_WIDTH, HELP_EXTRA_FIGURES, SPD_CONTROLS_WIDTH, render_gui_overview
    from cisprobeplace.help_figures import FIGURE_RENDERERS

    renderers = {**FIGURE_RENDERERS, **HELP_EXTRA_FIGURES}
    figure_names = extract_figure_names(load_help_html())

    assert sorted(set(figure_names)) == sorted(renderers)
    for name in figure_names:
        normal = renderers[name](1.0)
        sharp = renderers[name](2.0)
        assert not normal.isNull(), name
        assert sharp.devicePixelRatio() == 2.0, name
        # Same size on the page, twice the pixels on a high-DPI screen.
        assert sharp.width() == pytest.approx(normal.width() * 2, abs=2), name
        assert sharp.height() == pytest.approx(normal.height() * 2, abs=2), name
    overview = render_gui_overview(1.0)
    assert overview.width() == GUI_OVERVIEW_WIDTH
    assert renderers["spd-controls"](1.0).width() == SPD_CONTROLS_WIDTH


def _scroll_state(window, scroll) -> str:
    """Sizes behind the scroll bars of a scroll area, for a failing assertion."""
    content = scroll.widget()
    horizontal, vertical = scroll.horizontalScrollBar(), scroll.verticalScrollBar()
    font = window.font()
    groups = ", ".join(
        f"{child.title()}={child.minimumSizeHint().width()}x{child.minimumSizeHint().height()}"
        for child in content.children() if hasattr(child, "title")
    )
    return (
        f"window {window.width()}x{window.height()}, scroll area {scroll.width()}x{scroll.height()}, "
        f"viewport {scroll.viewport().width()}x{scroll.viewport().height()}, content {content.width()}x{content.height()}, "
        f"content minimum {content.minimumSizeHint().width()}x{content.minimumSizeHint().height()} ({groups}), "
        f"horizontal range {horizontal.maximum()} shown {horizontal.isVisibleTo(scroll)}, "
        f"vertical range {vertical.maximum()} shown {vertical.isVisibleTo(scroll)}, "
        f"bar extent {vertical.sizeHint().width()}, font {font.family()} {font.pointSizeF()}pt"
    )


@pytest.mark.parametrize("spacing", [0, 6])
def test_main_window_picture_keeps_every_caption_readable(letter_spacing, spacing):
    from PySide6.QtCore import QPoint, QRect
    from PySide6.QtWidgets import QLabel

    letter_spacing(spacing)
    import cisprobeplace.gui as gui

    window = gui.MainWindow()
    try:
        gui.prepare_gui_overview(window)
        radius = gui.gui_overview_marker_radius(window)
        markers = gui.gui_overview_markers(window, radius)
        assert len(markers) == 8  # the rows of the table below the picture in the help

        tab_bar = window.control_tabs.tabBar()
        captions = {
            f"tab {tab_bar.tabText(index)}": QRect(tab_bar.mapTo(window, tab_bar.tabRect(index).topLeft()), tab_bar.tabRect(index).size())
            for index in range(tab_bar.count())
        }
        for group in (window.file_group, window.filter_group, window.net_group):
            title = gui._group_title_rect(group)
            captions[f"title {group.title()}"] = QRect(group.mapTo(window, title.topLeft()), title.size())
        for label in window.file_group.findChildren(QLabel) + window.filter_group.findChildren(QLabel):
            if label.isVisibleTo(window) and label.text():
                width = min(label.width(), label.fontMetrics().horizontalAdvance(label.text()))
                captions[f"label {label.text()}"] = QRect(label.mapTo(window, QPoint(0, 0)), label.size()).adjusted(0, 0, width - label.width(), 0)
        assert {"tab Input and filters", "tab Pin editing", "title Input Files", "label Coordinate file"} <= set(captions)

        panel = window._left_panel
        left_panel = QRect(panel.mapTo(window, QPoint(0, 0)), panel.size())
        for number, center in enumerate(markers, start=1):
            disc = QRect(center.x() - radius, center.y() - radius, 2 * radius, 2 * radius)
            assert window.rect().contains(disc), number
            covered = [name for name, rect in captions.items() if disc.intersects(rect)]
            assert not covered, (number, covered)
            if number <= 5:  # the markers of the left panel stay off the right-hand side
                assert left_panel.left() <= disc.left() and disc.right() <= left_panel.right(), (number, disc, left_panel)

        # The picture shows the whole left panel and all five columns of the table.
        scroll = window._left_scroll
        state = _scroll_state(window, scroll)
        assert scroll.verticalScrollBar().maximum() == 0, state
        assert scroll.horizontalScrollBar().maximum() == 0, state
        assert not scroll.verticalScrollBar().isVisibleTo(scroll), state
        assert not scroll.horizontalScrollBar().isVisibleTo(scroll), state
        table = window.selected_table
        columns = f"table {table.width()}, columns {table.horizontalHeader().length()}, window {window.width()}"
        assert table.horizontalScrollBar().maximum() == 0, columns
        assert not table.horizontalScrollBar().isVisibleTo(table), columns
    finally:
        window.close()


def test_help_dialog_shows_pictures_contents_and_search():
    app = _application()
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QTextDocument

    from cisprobeplace.gui import MainWindow

    window = MainWindow()
    window.show_help()
    dialog = window._help_dialog
    app.processEvents()

    assert dialog.missing_figures() == []
    for name in extract_figure_names(load_help_html()):
        image = dialog.browser.document().resource(QTextDocument.ResourceType.ImageResource, QUrl(f"figure:{name}"))
        assert image is not None and not image.isNull(), name

    assert dialog.toc.topLevelItemCount() == 10
    scroll_bar = dialog.browser.verticalScrollBar()
    assert scroll_bar.value() == 0
    input_section = dialog.toc.topLevelItem(2)
    assert input_section.text(0).startswith("3.")
    dialog.toc.setCurrentItem(input_section.child(5))
    app.processEvents()
    assert scroll_bar.value() > 0
    assert dialog.toc.currentItem() is input_section.child(5)

    # A section too short to reach the top of the page stays highlighted when chosen.
    last_section = dialog.toc.topLevelItem(9)
    dialog.toc.setCurrentItem(last_section)
    app.processEvents()
    assert dialog.toc.currentItem() is last_section
    scroll_bar.setValue(0)
    app.processEvents()
    assert dialog.toc.currentItem().text(0).startswith("1.")

    # Scrolling the page moves the highlight in the contents list with it.
    scroll_bar.setValue(scroll_bar.maximum())
    app.processEvents()
    assert dialog.toc.currentItem().text(0).startswith("10.")

    dialog.search_edit.setText("PIX_X")
    assert dialog.find_next()
    assert dialog.browser.textCursor().selectedText() == "PIX_X"
    dialog.search_edit.setText("no such words in the help")
    assert not dialog.find_next()
    assert dialog.search_status.text() != ""

    dialog.close()
    window.close()
    app.quit()


def test_help_browser_never_leaves_the_document():
    app = _application()
    from PySide6.QtCore import QUrl

    from cisprobeplace.help_viewer import HelpDialog

    dialog = HelpDialog()
    dialog.show()
    app.processEvents()
    before = dialog.browser.toPlainText()

    dialog.browser.anchorClicked.emit(QUrl("https://example.com/"))
    dialog.browser.anchorClicked.emit(QUrl("file:///C:/Windows/notepad.exe"))
    app.processEvents()

    assert dialog.browser.toPlainText() == before
    assert not dialog.browser.openExternalLinks()
    assert not dialog.browser.openLinks()

    dialog.browser.anchorClicked.emit(QUrl("#troubleshooting"))
    app.processEvents()
    assert dialog.browser.verticalScrollBar().value() > 0
    dialog.close()
    app.quit()


def test_a_figure_that_cannot_be_drawn_does_not_break_the_help():
    app = _application()
    from cisprobeplace.help_viewer import HelpDialog

    def broken(_dpr):
        raise RuntimeError("no picture")

    from cisprobeplace.gui import HELP_EXTRA_FIGURES

    dialog = HelpDialog(extra_figures={**HELP_EXTRA_FIGURES, "gui-overview": broken})
    app.processEvents()

    assert dialog.missing_figures() == ["gui-overview"]
    assert "CISRotAng_Right" in dialog.browser.toPlainText()
    dialog.close()
    app.quit()


def test_packaged_build_includes_the_help_and_checks_it_on_smoke_run(monkeypatch):
    _application()
    import cisprobeplace.gui as gui
    import cisprobeplace.help_viewer as help_viewer

    spec = (REPOSITORY_ROOT / "CISProbePlacementScriptor.spec").read_text(encoding="utf-8")
    assert "('cisprobeplace/help', 'cisprobeplace/help')" in spec

    assert gui.run_smoke_check() == 0

    monkeypatch.setattr(help_viewer, "HELP_FILE", REPOSITORY_ROOT / "missing" / "help_ko.html")
    monkeypatch.setattr(sys, "stderr", None)
    assert gui.run_smoke_check() == 1
