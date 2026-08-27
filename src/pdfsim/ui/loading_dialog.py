# -*- coding: utf-8 -*-
"""加载进度对话框（性能优化 P0-1）。

打开大文档时由后台线程驱动进度：
  标题 "正在处理"，步骤文字 + 进度条（百分比）。
模态显示，主线程事件循环保持运行（可响应信号/进度刷新），
后台工作完成后由调用方 accept() 关闭。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QProgressBar,
    QVBoxLayout,
)

from pdfsim.ui.styles import FONT_DEFAULT


class LoadingDialog(QDialog):
    """加载进度对话框（模态，标题"正在处理"）。"""

    def __init__(self, parent=None, title: str = "正在处理") -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(380)
        self.setWindowFlags(
            Qt.Dialog | Qt.CustomizeWindowHint | Qt.WindowTitleHint
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        self._label = QLabel("准备中…")
        self._label.setFont(self.font())
        self._label.setWordWrap(True)
        layout.addWidget(self._label)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setTextVisible(True)
        layout.addWidget(self._progress)

    # ------------------------------------------------------------------
    # 供主线程信号槽调用
    # ------------------------------------------------------------------
    def set_progress(self, percent: int, text: str) -> None:
        """更新进度（百分比 0-100 与步骤文字）。"""
        self._progress.setValue(int(percent))
        self._label.setText(text)
