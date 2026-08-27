# -*- coding: utf-8 -*-
"""主窗口（依据《Stage3_提示语.md》5.2 与《UI原型说明.md》第 1、6、7 章）。

三段式布局：左侧缩略图 + 右上书视图 + 右下配置面板。
菜单 / 工具栏：文件（打开PDF…/重新打开/退出）、工具（自动识别/全局设置…/输出）、帮助（关于）。
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QFont
from PySide6.QtWidgets import (
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QToolBar,
)

from pdfsim.loader import PDFLoadError, PDFPasswordError
from pdfsim.ui import dialogs
from pdfsim.ui.app_controller import AppController
from pdfsim.ui.book_view import BookView
from pdfsim.ui.config_panel import ConfigPanel
from pdfsim.ui.global_settings import GlobalSettingsDialog
from pdfsim.ui.loading_dialog import LoadingDialog
from pdfsim.ui.report_dialog import ReportDialog
from pdfsim.ui.styles import (
    BOTTOM_PANEL_MIN,
    FONT_DEFAULT,
    LEFT_PANEL_MAX,
    LEFT_PANEL_MIN,
    WINDOW_DEFAULT_H,
    WINDOW_DEFAULT_W,
    WINDOW_MIN_H,
    WINDOW_MIN_W,
)
from pdfsim.ui.thumbnail_panel import ThumbnailPanel

VERSION = "3.0.0"


class MainWindow(QMainWindow):
    """PDFSim 主窗口。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.controller = AppController(self)
        self._doc_open = False
        self._loading: LoadingDialog | None = None
        self.setWindowTitle("PDFSim — PDF 双面打印页码编排")
        self.resize(WINDOW_DEFAULT_W, WINDOW_DEFAULT_H)
        self.setMinimumSize(WINDOW_MIN_W, WINDOW_MIN_H)
        self.setFont(QFont(FONT_DEFAULT, 9))

        self._build_menus()
        self._build_central()
        self._build_toolbar()
        self._connect_signals()
        self._update_actions()

        self.statusBar().showMessage("就绪 — 请打开 PDF 文件")

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------
    def _build_central(self) -> None:
        self.thumbnail_panel = ThumbnailPanel(self.controller)
        self.thumbnail_panel.setMinimumWidth(LEFT_PANEL_MIN)
        self.thumbnail_panel.setMaximumWidth(LEFT_PANEL_MAX)

        self.book_view = BookView(self.controller)
        self.config_panel = ConfigPanel(self.controller)
        self.config_panel.setMinimumHeight(BOTTOM_PANEL_MIN)

        right_split = QSplitter(Qt.Orientation.Vertical)
        right_split.addWidget(self.book_view)
        right_split.addWidget(self.config_panel)
        right_split.setStretchFactor(0, 1)
        right_split.setStretchFactor(1, 0)
        right_split.setSizes([520, 200])

        self.main_split = QSplitter(Qt.Orientation.Horizontal)
        self.main_split.addWidget(self.thumbnail_panel)
        self.main_split.addWidget(right_split)
        self.main_split.setStretchFactor(0, 0)
        self.main_split.setStretchFactor(1, 1)
        self.main_split.setSizes([230, 1050])

        self.setCentralWidget(self.main_split)

    def _build_menus(self) -> None:
        menubar = self.menuBar()

        # 文件
        file_menu = menubar.addMenu("文件")
        self.act_open = QAction("打开 PDF…", self)
        self.act_open.setShortcut("Ctrl+O")
        self.act_open.triggered.connect(self.on_open)
        file_menu.addAction(self.act_open)
        self.act_reopen = QAction("重新打开", self)
        self.act_reopen.triggered.connect(self.on_reopen)
        file_menu.addAction(self.act_reopen)
        file_menu.addSeparator()
        act_exit = QAction("退出", self)
        act_exit.triggered.connect(self.close)
        file_menu.addAction(act_exit)

        # 工具
        tool_menu = menubar.addMenu("工具")
        self.act_auto = QAction("自动识别", self)
        self.act_auto.triggered.connect(self.on_auto_detect)
        tool_menu.addAction(self.act_auto)
        self.act_settings = QAction("全局设置…", self)
        self.act_settings.triggered.connect(self.on_global_settings)
        tool_menu.addAction(self.act_settings)
        tool_menu.addSeparator()
        self.act_output = QAction("输出", self)
        self.act_output.setShortcut("Ctrl+S")
        self.act_output.triggered.connect(self.on_output)
        tool_menu.addAction(self.act_output)
        self.act_report = QAction("查看处理报告…", self)
        self.act_report.triggered.connect(self.on_report)
        tool_menu.addAction(self.act_report)

        # 帮助
        help_menu = menubar.addMenu("帮助")
        act_about = QAction("关于", self)
        act_about.triggered.connect(self.on_about)
        help_menu.addAction(act_about)

    def _build_toolbar(self) -> None:
        tb = QToolBar("主工具栏")
        tb.setMovable(False)
        self.addToolBar(tb)
        self.tb_open = tb.addAction("打开")
        self.tb_open.triggered.connect(self.on_open)
        self.tb_auto = tb.addAction("自动识别")
        self.tb_auto.triggered.connect(self.on_auto_detect)
        self.tb_settings = tb.addAction("全局设置")
        self.tb_settings.triggered.connect(self.on_global_settings)
        tb.addSeparator()
        self.tb_prev = tb.addAction("◀ 上一页")
        self.tb_prev.triggered.connect(self.book_view.page_prev)
        self.tb_next = tb.addAction("下一页 ▶")
        self.tb_next.triggered.connect(self.book_view.page_next)
        tb.addSeparator()
        self.tb_output = tb.addAction("输出")
        self.tb_output.triggered.connect(self.on_output)
        self.tb_report = tb.addAction("报告")
        self.tb_report.triggered.connect(self.on_report)

    # ------------------------------------------------------------------
    # 信号连接
    # ------------------------------------------------------------------
    def _connect_signals(self) -> None:
        c = self.controller
        c.plan_changed.connect(self._on_plan_changed)
        c.selection_changed.connect(self._on_selection_changed)
        c.selection_set_changed.connect(self._on_selection_set_changed)
        c.status_message.connect(self.statusBar().showMessage)
        c.load_progress.connect(self._on_load_progress)

    def _on_selection_set_changed(self, pages: list) -> None:
        """多选集合变化：缩略图高亮 + 配置面板批量模式 + 书视图刷新。"""
        self.book_view.update()
        self.config_panel.on_selection_set_changed(list(pages))

    def _on_plan_changed(self) -> None:
        self.thumbnail_panel.on_plan_changed()
        self.book_view.on_plan_changed()
        self.config_panel.on_plan_changed()
        self._update_actions()
        self._update_status()

    def _on_selection_changed(self, phys: int) -> None:
        self.thumbnail_panel.on_selection_changed(phys)
        self.book_view.on_selection_changed(phys)
        self.config_panel.on_selection_changed(phys)

    def _update_actions(self) -> None:
        enabled = self.controller.pdf_path is not None
        for a in (self.act_reopen, self.act_auto, self.act_settings,
                  self.act_output, self.act_report, self.tb_auto,
                  self.tb_settings, self.tb_output, self.tb_report,
                  self.tb_prev, self.tb_next):
            a.setEnabled(enabled)

    def _update_status(self) -> None:
        if self.controller.current_plan is None:
            return
        n_src = len(self.controller.source_pages)
        n_phys = self.controller.plan_page_count()
        sel = self.controller.selected_physical_index
        name = os.path.basename(self.controller.pdf_path or "")
        self.statusBar().showMessage(
            f"{name} — 源页 {n_src} 页 / 物理 {n_phys} 页 / 当前第 {sel} 页"
        )

    # ------------------------------------------------------------------
    # 打开流程（UI 原型 7.1 + 6 异常弹窗）
    # ------------------------------------------------------------------
    def on_open(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "打开 PDF 文件", "", "PDF 文件 (*.pdf);;所有文件 (*.*)"
        )
        if path:
            self._open_pdf_flow(path)

    def on_reopen(self) -> None:
        if self.controller.pdf_path:
            self._open_pdf_flow(self.controller.pdf_path)

    def _open_pdf_flow(self, path: str, password: str = "") -> None:
        """后台线程打开 PDF（性能优化 P0-1）：显示进度对话框，主线程不阻塞。"""
        self.setWindowTitle(f"{os.path.basename(path)} — PDFSim")
        ok, kind, detail = self._do_async_open_blocking(path, password)
        if ok:
            self._doc_open = True
            self._on_plan_changed()
        elif kind == "password":
            self._password_flow(path)
        elif kind == "load":
            if "无页面" in detail:
                dialogs.show_empty_document(self)
            else:
                dialogs.show_corrupted(self)
        else:
            dialogs.show_load_error(self, detail)

    def _do_async_open_blocking(self, path: str, password: str):
        """阻塞等待一次后台打开完成，返回 (ok, kind, detail)。"""
        result: dict = {}
        c = self.controller

        def _ok():
            if self._loading is not None:
                self._loading.accept()
            result["ok"] = True

        def _fail(kind, detail):
            if self._loading is not None:
                self._loading.accept()
            result["kind"] = kind
            result["detail"] = detail

        c.set_async_callbacks(_ok, _fail)
        self._loading = LoadingDialog(self, "正在处理")
        c.open_pdf_async(path, password)
        self._loading.exec()
        self._loading = None
        return (result.get("ok", False), result.get("kind"), result.get("detail", ""))

    def _on_load_progress(self, percent: int, text: str) -> None:
        """后台打开进度 → 进度对话框。"""
        if self._loading is not None:
            self._loading.set_progress(percent, text)

    def _password_flow(self, path: str) -> None:
        """加密 PDF：询问密码 → 后台重试（无嵌套阻塞）。"""
        while True:
            pwd = dialogs.ask_password(self)
            if pwd is None:
                break  # 取消 → 停留空界面
            ok, kind, detail = self._do_async_open_blocking(path, pwd)
            if ok:
                self._doc_open = True
                self._on_plan_changed()
                return
            if kind == "password":
                if not dialogs.show_password_error(self):
                    break
            elif kind == "load":
                dialogs.show_corrupted(self)
                return
            else:
                dialogs.show_load_error(self, detail)
                return

    def _busy(self, busy: bool) -> None:
        if busy:
            self.setCursor(Qt.CursorShape.WaitCursor)
            for a in (self.act_open, self.act_output, self.tb_output):
                a.setEnabled(False)
        else:
            self.unsetCursor()
            self._update_actions()

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------
    def on_auto_detect(self) -> None:
        self.controller.auto_detect()

    def on_global_settings(self) -> None:
        dlg = GlobalSettingsDialog(self.controller, self)
        dlg.exec()

    def on_output(self) -> None:
        """调用输出模块并处理结果弹窗（已存在 / 成功 / 失败）。"""
        if self.controller.current_plan is None:
            return
        self._busy(True)
        try:
            result = self.controller.output()
        finally:
            self._busy(False)
        if result is None:
            return
        if result.success:
            choice = dialogs.show_output_success(
                self, result.output_path, has_report=True)
            if choice == "open":
                dialogs.open_folder(result.output_path)
            elif choice == "report":
                self.on_report()
        elif "已存在" in result.message:
            dialogs.show_output_exists(self, result.output_path)
        else:
            dialogs.show_output_failed(self, result.message)

    def on_report(self) -> None:
        """打开处理报告对话框。"""
        dlg = ReportDialog(self.controller, self)
        dlg.exec()

    def on_about(self) -> None:
        QMessageBox.about(
            self,
            "关于 PDFSim",
            f"<b>PDFSim</b> v{VERSION}<br><br>"
            "PDF 双面打印页码编排与装订准备工具。<br><br>"
            "依赖：PySide6 / PyMuPDF / pikepdf",
        )

    def closeEvent(self, event):  # noqa: N802
        self.controller.close()
        super().closeEvent(event)
