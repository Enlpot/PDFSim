# -*- coding: utf-8 -*-
"""PDFSim 程序入口（Stage 3）。

用法：`python src/main.py`
"""
from __future__ import annotations

import sys


def main() -> int:
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication

    from pdfsim.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("PDFSim")
    # 显式加载系统中文字体（Qt 不再自带字体；保证中文界面正常显示）
    for font_path in (
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simsun.ttc",
    ):
        try:
            QFontDatabase.addApplicationFont(font_path)
        except Exception:  # pragma: no cover
            pass
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
