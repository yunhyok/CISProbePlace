import os

import pytest


@pytest.fixture
def letter_spacing():
    """Widen every character of the application font by a number of pixels.

    The fonts of machines differ. Under Qt's offscreen platform the Windows
    build machine lays text out about one and a half times as wide as here.
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    original = QFont(app.font())

    def widen(pixels: int) -> None:
        font = QFont(original)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, pixels)
        app.setFont(font)

    yield widen
    app.setFont(original)
