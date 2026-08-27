# -*- coding: utf-8 -*-
"""pytest 公共 fixtures。"""
import os
import sys
from pathlib import Path

import pytest

# UI 测试：无头平台（必须在 QApplication 创建前设置）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# 确保 src 在导入路径上
SRC_DIR = Path(__file__).resolve().parent.parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

SAMPLES_DIR = Path(__file__).resolve().parent / "samples"


@pytest.fixture(scope="session")
def samples_dir() -> Path:
    """测试样本目录。"""
    return SAMPLES_DIR


@pytest.fixture(scope="session")
def gen_samples_script() -> Path:
    """样本生成脚本路径。"""
    return SAMPLES_DIR / "gen_samples.py"


# ---------------------------------------------------------------------------
# Stage 3 UI 测试 fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def ui_fonts():
    """加载系统中文字体，保证 UI 截图/渲染正常。

    先确保 QApplication 存在再加载字体：无 app 时调用
    QFontDatabase.addApplicationFont 在无桌面会话环境（CI runner）会触发
    Qt native crash（access violation，try/except 无法捕获）。
    """
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    for fp in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simsun.ttc"):
        try:
            QFontDatabase.addApplicationFont(fp)
        except Exception:
            pass
    return True


@pytest.fixture
def make_window(qtbot, ui_fonts):
    """创建 MainWindow（带 controller）。"""
    from pdfsim.ui.main_window import MainWindow

    windows = []

    def _make():
        w = MainWindow()
        w.show()
        windows.append(w)
        return w

    yield _make
    for w in windows:
        try:
            w.close()
        except Exception:
            pass


@pytest.fixture
def open_sample(make_window):
    """打开指定样本并返回 (window, controller)。"""
    def _open(rel_name: str):
        w = make_window()
        path = str(SAMPLES_DIR / rel_name)
        w.controller.open_pdf(path, "")
        return w, w.controller
    return _open
