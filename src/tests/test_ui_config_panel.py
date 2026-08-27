# -*- coding: utf-8 -*-
"""页面配置面板 UI 测试（Stage 3 交付物 2 的一部分）。

覆盖：标签联动（封面→FRONT）/ A3 置灰 / 页码位置切换 / 旋转方向切换 /
样式覆盖 / 重叠警告显示与隐藏。
"""
from __future__ import annotations

import pytest

from pdfsim.models import (
    PageMark,
    PageNumberPos,
    RotationOverride,
    is_a3,
)


def _load_first_page(c, panel):
    """选中物理第 1 页并加载面板。"""
    c.select_physical(1)
    panel.load_page(1)
    return panel


def test_mark_cover_linkage(make_window, samples_dir):
    """勾选封面 → 自动联动勾选"从正面开始"。"""
    w, c = _open(make_window, samples_dir, "sample_single.pdf")
    panel = _load_first_page(c, w.config_panel)
    oi = c.source_pages[0].original_index

    # 先清空封面
    c.set_page_mark(oi, PageMark.COVER, False)
    panel.load_page(1)

    panel._chk_cover.setChecked(True)
    assert PageMark.COVER in c.source_page(oi).marks
    assert PageMark.FRONT in c.source_page(oi).marks
    assert panel._chk_front.isChecked()


def test_mark_sign_linkage(make_window, samples_dir):
    """勾选签字页 → 自动联动勾选"从正面开始"。"""
    w, c = _open(make_window, samples_dir, "sample_single.pdf")
    panel = _load_first_page(c, w.config_panel)
    oi = c.source_pages[0].original_index
    c.set_page_mark(oi, PageMark.SIGNATURE, False)
    panel.load_page(1)

    panel._chk_sign.setChecked(True)
    assert PageMark.SIGNATURE in c.source_page(oi).marks
    assert PageMark.FRONT in c.source_page(oi).marks


def test_a3_front_disabled(make_window, samples_dir):
    """A3 页"从正面开始"置灰勾选、不可取消。"""
    w, c = _open(make_window, samples_dir, "sample_a3_portrait.pdf")
    a3_idx = next(p.original_index for p in c.source_pages if is_a3(p))
    # 定位 A3 页对应的物理页
    phys = None
    for pp in c.current_plan.pages:
        if not pp.is_blank and pp.source_page_info.original_index == a3_idx:
            phys = pp.physical_index
            break
    assert phys is not None
    c.select_physical(phys)
    panel = w.config_panel
    panel.load_page(phys)
    assert not panel._chk_front.isEnabled()
    assert panel._chk_front.isChecked()
    # 通过 controller 尝试取消 → 被强制保留
    c.set_page_mark(a3_idx, PageMark.FRONT, False)
    assert PageMark.FRONT in c.source_page(a3_idx).marks


def test_number_pos_switch(make_window, samples_dir):
    """页码位置下拉切换 → 单页覆盖生效。"""
    w, c = _open(make_window, samples_dir, "sample_a4_portrait.pdf")
    panel = _load_first_page(c, w.config_panel)
    oi = c.source_pages[0].original_index

    # 切到"左下角"（index 2）
    panel._pos_combo.setCurrentIndex(2)
    assert c.source_page(oi).number_pos_override is PageNumberPos.BOTTOM_LEFT

    # 切到"左上角"（index 4）→ 单页覆盖生效
    panel._pos_combo.setCurrentIndex(4)
    assert c.source_page(oi).number_pos_override is PageNumberPos.TOP_LEFT

    # 切到"自定义"（index 5）→ 偏移框出现
    panel._pos_combo.setCurrentIndex(5)
    assert c.source_page(oi).number_pos_override is PageNumberPos.CUSTOM
    assert panel._custom_row.isVisible()
    panel._off_x.setValue(5.0)
    assert c.source_page(oi).number_custom_offset_mm[0] == 5.0

    # 切回"自动"（index 0）→ 清除覆盖
    panel._pos_combo.setCurrentIndex(0)
    assert c.source_page(oi).number_pos_override is None


def test_rotation_switch(make_window, samples_dir):
    """旋转方向下拉切换 → override 生效。"""
    w, c = _open(make_window, samples_dir, "sample_direction_markers.pdf")
    rot_idx = next(p.original_index for p in c.source_pages
                   if c.needs_rotation(p.original_index))
    phys = next(pp.physical_index for pp in c.current_plan.pages
                if not pp.is_blank and pp.source_page_info.original_index == rot_idx)
    c.select_physical(phys)
    panel = w.config_panel
    panel.load_page(phys)

    assert panel._rot_combo.isEnabled()
    # 切到"顺时针 90°"（index 1）
    panel._rot_combo.setCurrentIndex(1)
    assert c.source_page(rot_idx).rotation_override is RotationOverride.CW90
    # plan 中该页 rotation=90
    pp = next(pp for pp in c.current_plan.pages
              if not pp.is_blank and pp.source_page_info.original_index == rot_idx)
    assert pp.rotation == 90
    # 切到"不旋转"（index 4，新增"旋转 180°"后顺延）
    panel._rot_combo.setCurrentIndex(4)
    pp = next(pp for pp in c.current_plan.pages
              if not pp.is_blank and pp.source_page_info.original_index == rot_idx)
    assert pp.rotation == 0


def test_rotation_detect_text(make_window, samples_dir):
    """需旋转页显示自动检测文案；不旋转页显示"无需旋转"。"""
    w, c = _open(make_window, samples_dir, "sample_direction_markers.pdf")
    rot_idx = next(p.original_index for p in c.source_pages
                   if c.needs_rotation(p.original_index))
    phys = next(pp.physical_index for pp in c.current_plan.pages
                if not pp.is_blank and pp.source_page_info.original_index == rot_idx)
    panel = w.config_panel
    panel.load_page(phys)
    assert "自动检测" in panel._rot_detect_label.text()
    assert panel._rot_combo.isEnabled()
    # 非旋转页：打开 A4 纵向样本验证"无需旋转"置灰
    w2, c2 = _open(make_window, samples_dir, "sample_a4_portrait.pdf")
    no_rot_idx = next(p.original_index for p in c2.source_pages
                      if not c2.needs_rotation(p.original_index))
    phys2 = next(pp.physical_index for pp in c2.current_plan.pages
                 if not pp.is_blank and pp.source_page_info.original_index == no_rot_idx)
    w2.config_panel.load_page(phys2)
    assert not w2.config_panel._rot_combo.isEnabled()
    assert "无需旋转" in w2.config_panel._rot_detect_label.text()


def test_style_override(make_window, samples_dir):
    """修改样式 → 单页 style_override 生效；恢复全局 → 清除覆盖。"""
    w, c = _open(make_window, samples_dir, "sample_single.pdf")
    panel = _load_first_page(c, w.config_panel)
    oi = c.source_pages[0].original_index

    panel._style_size.setValue(12.0)
    assert c.source_page(oi).style_override is not None
    assert c.source_page(oi).style_override.fontsize_pt == 12.0

    panel._on_restore_style()
    assert c.source_page(oi).style_override is None


def test_overlap_warning_visible(make_window, samples_dir):
    """重叠警告条显示/隐藏。"""
    w, c = _open(make_window, samples_dir, "sample_with_pagenum.pdf")
    c.set_auto_adjust_overlap(False)  # 验证"检测→警告"原始语义，关闭自动调整
    panel = w.config_panel
    # 打开时 select=1 已触发 load_page（经信号），直接检查
    panel.load_page(1)
    # 找到有重叠的页（若存在）或验证逻辑正确性
    any_warn = bool(c.current_plan.warnings)
    for pp in c.current_plan.pages:
        panel.load_page(pp.physical_index)
        ww = c.overlap_warning_for(pp.physical_index)
        assert panel._warn_label.isVisible() == (ww is not None)
    assert any_warn  # 样本应至少有一页重叠（带页码样本）

def _open(make_window, samples_dir, rel):
    w = make_window()
    c = w.controller
    c.open_pdf(str(samples_dir / rel), "")
    return w, c
