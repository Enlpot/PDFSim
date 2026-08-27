# -*- coding: utf-8 -*-
"""主窗口 UI 测试（Stage 3 交付物 2 的一部分）。

覆盖：窗口创建 / 布局比例 / 菜单栏 / 工具栏 / 打开文件对话框。
"""
from __future__ import annotations

import os

import pytest

from pdfsim.ui.styles import (
    BOTTOM_PANEL_MIN,
    LEFT_PANEL_MAX,
    LEFT_PANEL_MIN,
    WINDOW_DEFAULT_H,
    WINDOW_DEFAULT_W,
    WINDOW_MIN_H,
    WINDOW_MIN_W,
)


def test_window_created(make_window, ui_fonts):
    """窗口创建：标题 / 默认尺寸 / 最小尺寸。"""
    w = make_window()
    assert "PDFSim" in w.windowTitle()
    assert w.width() >= WINDOW_MIN_W
    assert w.height() >= WINDOW_MIN_H
    assert w.minimumWidth() == WINDOW_MIN_W
    assert w.minimumHeight() == WINDOW_MIN_H


def test_three_panel_layout(make_window):
    """三段式布局：左侧缩略图 + 右上书视图 + 右下配置面板。"""
    w = make_window()
    assert w.thumbnail_panel is not None
    assert w.book_view is not None
    assert w.config_panel is not None
    # 左侧面板宽度范围
    assert LEFT_PANEL_MIN <= w.thumbnail_panel.minimumWidth() <= LEFT_PANEL_MAX
    # 配置面板最小高度
    assert w.config_panel.minimumHeight() >= BOTTOM_PANEL_MIN
    # 左侧面板是 QScrollArea，书视图是 QWidget
    assert w.thumbnail_panel.__class__.__name__ == "ThumbnailPanel"
    assert w.book_view.__class__.__name__ == "BookView"


def test_menus_and_toolbar(make_window):
    """菜单栏 / 工具栏动作齐全。"""
    w = make_window()
    assert w.act_open is not None
    assert w.act_reopen is not None
    assert w.act_auto is not None
    assert w.act_settings is not None
    assert w.act_output is not None
    # 工具栏按钮
    assert w.tb_open is not None
    assert w.tb_auto is not None
    assert w.tb_settings is not None
    assert w.tb_output is not None
    # 未打开文档时：打开可用，其余禁用
    assert w.act_open.isEnabled()
    assert not w.act_output.isEnabled()
    assert not w.act_settings.isEnabled()


def test_open_pdf_updates_title(make_window, samples_dir):
    """打开 PDF 后窗口标题含文件名，动作启用。"""
    w = make_window()
    w._open_pdf_flow(str(samples_dir / "sample_single.pdf"))
    assert os.path.basename("sample_single.pdf") in w.windowTitle()
    assert w.act_output.isEnabled()
    assert w.act_settings.isEnabled()


def test_open_dialog_called(make_window, monkeypatch, samples_dir):
    """打开文件对话框路径选择流程。"""
    w = make_window()
    calls = {}

    class FakeDialog:
        @staticmethod
        def getOpenFileName(*args, **kwargs):
            calls["called"] = True
            return (str(samples_dir / "sample_single.pdf"), "PDF 文件 (*.pdf)")

    monkeypatch.setattr("pdfsim.ui.main_window.QFileDialog", FakeDialog)
    w.on_open()
    assert calls.get("called")
    assert w.controller.pdf_path is not None


def test_auto_detect_flow(make_window, samples_dir):
    """自动识别按钮流程。"""
    w = make_window()
    w.controller.open_pdf(str(samples_dir / "sample_mixed.pdf"), "")
    before = w.controller.selected_physical_index
    w.on_auto_detect()
    assert w.controller.selected_physical_index == 1
    assert w.controller.current_plan is not None
    assert before >= 1


def test_output_button_enabled_after_open(make_window, samples_dir):
    """打开后输出动作可用。"""
    w = make_window()
    assert not w.act_output.isEnabled()
    w.controller.open_pdf(str(samples_dir / "sample_single.pdf"), "")
    assert w.act_output.isEnabled()
