# -*- coding: utf-8 -*-
"""多选批量调整旋转方向与页码样式专项测试（对应《多选批量旋转与样式_提示语》）。

- 批量旋转：所有选中页（非空白）rotation_override 统一应用；空白页跳过
- 批量样式：所有选中页 style_override 统一应用（含空白页）；恢复全局样式清除
- UI：多选时旋转/样式控件可选、页码位置/自定义标签仍禁用；单选行为不变
"""
from __future__ import annotations

import os

from pdfsim.models import PageMark, PageNumberStyle, RotationOverride
from pdfsim.ui.config_panel import ConfigPanel


def _open(make_window, samples_dir, rel):
    w = make_window()
    c = w.controller
    c.open_pdf(str(samples_dir / rel), "")
    return w, c


def _src(c, phys: int):
    return c.processed_page(phys).source_page_info


def _style(color=(10, 20, 30), size=12.0):
    return PageNumberStyle(
        font="Arial", fontsize_pt=size, color=color,
        margin_right_mm=15.0, margin_left_mm=15.0,
        margin_bottom_mm=16.0, margin_top_mm=16.0,
        vertical_position="bottom",
    )


class TestBatchRotation:
    def test_batch_rotation_override(self, make_window, samples_dir):
        """批量设置旋转 → 所有选中页（非空白）rotation_override 统一。"""
        w, c = _open(make_window, samples_dir, "sample_no_bookmark.pdf")
        c.set_rotation_override_batch([2, 3, 4], RotationOverride.CW90)
        for phys in (2, 3, 4):
            assert _src(c, phys).rotation_override is RotationOverride.CW90
        # 单选页（未选）不受影响
        assert _src(c, 1).rotation_override is RotationOverride.AUTO

    def test_batch_rotation_skips_blank(self, make_window, samples_dir):
        """批量旋转跳过空白页（空白页旋转由同纸正面继承）。"""
        w, c = _open(make_window, samples_dir, "sample_a4_portrait.pdf")
        blank = next(pp for pp in c.current_plan.pages if pp.is_blank)
        src_page = next(pp for pp in c.current_plan.pages
                        if not pp.is_blank and pp.physical_index != blank.physical_index)
        c.set_rotation_override_batch(
            [blank.physical_index, src_page.physical_index], RotationOverride.CCW90)
        # 空白页 rotation_override 不变（AUTO）
        assert blank.source_page_info.rotation_override is RotationOverride.AUTO
        assert src_page.source_page_info.rotation_override is RotationOverride.CCW90

    def test_batch_rotation_mixed_state(self, make_window, samples_dir):
        """批量回显：值不一致显示占位（自动检测），选择后统一覆盖。"""
        w, c = _open(make_window, samples_dir, "sample_no_bookmark.pdf")
        c.set_rotation_override_batch([2], RotationOverride.CW90)
        c.set_rotation_override_batch([3], RotationOverride.NONE)
        panel = w.config_panel
        panel.on_selection_set_changed([2, 3])
        assert panel._batch_pages == [2, 3]
        # 混合 → 回显 AUTO 占位、下拉可选
        assert panel._rot_combo.currentIndex() == 0
        assert panel._rot_combo.isEnabled()
        # 选择 CW90 → 统一覆盖
        panel._on_rot_changed(1)
        assert _src(c, 2).rotation_override is RotationOverride.CW90
        assert _src(c, 3).rotation_override is RotationOverride.CW90


class TestBatchStyle:
    def test_batch_style_override(self, make_window, samples_dir):
        """批量设置页码样式 → 所有选中页 style_override 一致（含空白页）。"""
        w, c = _open(make_window, samples_dir, "sample_no_bookmark.pdf")
        st = _style()
        c.set_page_style_override_batch([2, 3, 4], st)
        for phys in (2, 3, 4):
            assert _src(c, phys).style_override == st
        assert _src(c, 1).style_override is None

    def test_batch_style_on_blank(self, make_window, samples_dir):
        """样式批量覆盖对空白页生效（空白页有页码也显示样式）。"""
        w, c = _open(make_window, samples_dir, "sample_a4_portrait.pdf")
        blank = next(pp for pp in c.current_plan.pages if pp.is_blank)
        st = _style()
        c.set_page_style_override_batch([blank.physical_index], st)
        assert blank.source_page_info.style_override == st

    def test_batch_restore_global_style(self, make_window, samples_dir):
        """批量恢复全局样式 → 所有选中页 style_override = None。"""
        w, c = _open(make_window, samples_dir, "sample_no_bookmark.pdf")
        c.set_page_style_override_batch([2, 3], _style())
        c.set_page_style_override_batch([2, 3], None)
        for phys in (2, 3):
            assert _src(c, phys).style_override is None

    def test_batch_style_via_panel(self, make_window, samples_dir):
        """面板批量样式：回调 _on_style_changed 在批量模式下统一应用。"""
        w, c = _open(make_window, samples_dir, "sample_no_bookmark.pdf")
        panel = w.config_panel
        panel.on_selection_set_changed([2, 3])
        # 修改字号控件 → 触发批量样式
        panel._style_size.setValue(14.0)
        panel._on_style_changed()
        for phys in (2, 3):
            assert _src(c, phys).style_override is not None
            assert _src(c, phys).style_override.fontsize_pt == 14.0

    def test_batch_restore_via_panel(self, make_window, samples_dir):
        """面板批量"恢复全局样式"按钮 → 清除覆盖。"""
        w, c = _open(make_window, samples_dir, "sample_no_bookmark.pdf")
        c.set_page_style_override_batch([2, 3], _style())
        panel = w.config_panel
        panel.on_selection_set_changed([2, 3])
        panel._on_restore_style()
        for phys in (2, 3):
            assert _src(c, phys).style_override is None


class TestBatchUI:
    def test_rotation_style_enabled_position_disabled(self, make_window, samples_dir):
        """多选时：旋转/样式控件可选；页码位置/自定义标签仍禁用。"""
        w, c = _open(make_window, samples_dir, "sample_no_bookmark.pdf")
        panel = w.config_panel
        panel.on_selection_set_changed([2, 3, 4])
        assert panel._rot_combo.isEnabled()
        assert panel._rot_detect_label.isEnabled()
        for widget in (panel._style_font, panel._style_size, panel._style_color,
                       panel._style_margin_r, panel._style_vert_pos,
                       panel._style_margin_v, panel._restore_btn):
            assert widget.isEnabled(), f"{widget} 应可选"
        assert not panel._pos_combo.isEnabled()
        assert not panel._custom_row.isEnabled()
        assert not panel._label_input.isEnabled()
        assert not panel._label_add.isEnabled()
        assert not panel._labels_display.isEnabled()

    def test_all_blank_rotation_disabled(self, make_window, samples_dir):
        """全空白页多选：旋转下拉禁用。"""
        w, c = _open(make_window, samples_dir, "sample_a4_portrait.pdf")
        blanks = [pp.physical_index for pp in c.current_plan.pages if pp.is_blank]
        assert len(blanks) >= 2
        panel = w.config_panel
        panel.on_selection_set_changed(blanks)
        assert not panel._rot_combo.isEnabled()

    def test_single_page_unchanged(self, make_window, samples_dir):
        """单选行为不变：旋转/样式回调走单页路径。"""
        w, c = _open(make_window, samples_dir, "sample_no_bookmark.pdf")
        panel = w.config_panel
        c.select_physical(2)
        panel.on_selection_changed(2)
        assert panel._batch_pages is None
        panel._on_rot_changed(1)
        assert _src(c, 2).rotation_override is RotationOverride.CW90
        panel._on_restore_style()
        assert _src(c, 2).style_override is None
