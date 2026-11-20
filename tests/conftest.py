import os

import pytest


@pytest.fixture
def digit_width():
    """Lay the text of the application out with digits at least so many pixels wide.

    The fonts of machines differ: under Qt's offscreen platform the Windows
    build machine needs about one and a half times the width for the same
    controls as a Linux desktop, where a digit of the window font is 8 pixels
    wide. Naming the width makes a test run on comparable text everywhere.
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QFont, QFontMetrics
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    original = QFont(app.font())

    def widen(pixels: int | None) -> None:
        if pixels is None:
            return
        probe = QFont(original)
        probe.setPointSize(10)  # the size the theme gives the windows
        spacing = max(0, pixels - QFontMetrics(probe).horizontalAdvance("0"))
        font = QFont(original)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
        app.setFont(font)

    yield widen
    app.setFont(original)
