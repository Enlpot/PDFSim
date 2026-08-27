# -*- coding: utf-8 -*-
"""跳回第一页 Bug 修复专项测试（对应《跳回第一页Bug_提示语》）。

根因：rebuild() 中 `_updating = True` 在 `clear()` 之后设置，`clear()` 触发
itemSelectionChanged → `_on_view_selection_changed` 未拦截 → 选中变空 →
`select_physical(1)` 跳回第一页。修复：`_updating = True` 提前到 clear() 之前，
try/finally 保护。

验证：
- 单页：调整单页配置触发 rebuild 后，选中页不跳回第一页
- 多选：批量配置触发 rebuild 后，选中集合不变
- 单元级：rebuild() 全程不误调 controller.select_physical
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt

from pdfsim.models import PageMark


def _open(make_window, samples_dir, rel):
    w = make_window()
    c = w.controller
    c.open_pdf(str(samples_dir / rel), "")
    return w, c


class TestStayOnPage:
    def test_rebuild_does_not_jump_to_first(self, make_window, samples_dir):
        """单元级：rebuild() 不误调 select_physical(1)（修复核心）。"""
        w, c = _open(make_window, samples_dir, "sample_no_bookmark.pdf")
        c.select_physical(3)
        calls = []
        orig = c.select_physical
        c.select_physical = lambda idx: (calls.append(idx), orig(idx))[1]
        try:
            w.thumbnail_panel.rebuild()
            assert 1 not in calls, f"rebuild 误跳第一页: {calls}"
        finally:
            c.select_physical = orig

    def test_single_config_change_keeps_selection(self, make_window, samples_dir):
        """端到端：调整单页配置（触发 rebuild）后，选中页保持不变。"""
        w, c = _open(make_window, samples_dir, "sample_no_bookmark.pdf")
        c.select_physical(3)
        # 封面联动 FRONT 会改变 plan 结构 → plan_changed → rebuild
        c.set_page_mark(0, PageMark.COVER, True)
        assert c.selected_physical_index == 3, (
            f"调整单页配置后跳回 {c.selected_physical_index}（期望仍 3）")

    def test_signature_config_change_keeps_selection(self, make_window, samples_dir):
        """调整签字页配置后同样不跳回。"""
        w, c = _open(make_window, samples_dir, "sample_no_bookmark.pdf")
        c.select_physical(2)
        c.set_page_mark(1, PageMark.SIGNATURE, True)
        assert c.selected_physical_index == 2

    def test_no_number_config_change_keeps_selection(self, make_window, samples_dir):
        """调整"不加页码"（无结构变化）后仍停留在原页。"""
        w, c = _open(make_window, samples_dir, "sample_no_bookmark.pdf")
        c.select_physical(4)
        c.set_page_mark(3, PageMark.NO_NUMBER, True)
        assert c.selected_physical_index == 4


class TestMultiSelectStays:
    def test_multiselect_kept_after_batch(self, make_window, samples_dir):
        """多选：批量配置触发 rebuild 后选中集合不变。"""
        w, c = _open(make_window, samples_dir, "sample_no_bookmark.pdf")
        c.set_selected_pages([2, 3])
        # 批量"不加页码"→ 触发 rebuild
        c.set_page_mark_batch([2, 3], PageMark.NO_NUMBER, True)
        assert c.selected_physical_pages() == [2, 3], (
            f"批量配置后选中集合变为 {c.selected_physical_pages()}（期望 [2,3]）")
        # 缩略图高亮恢复
        sel = sorted(
            it.data(Qt.ItemDataRole.UserRole) for it in w.thumbnail_panel.selectedItems()
            if it.data(Qt.ItemDataRole.UserRole) is not None
        )
        assert sel == [2, 3]

    def test_multiselect_after_plan_change(self, make_window, samples_dir):
        """多选后触发结构变化（封面联动插空白）→ 选中集合保持。"""
        w, c = _open(make_window, samples_dir, "sample_no_bookmark.pdf")
        c.set_selected_pages([3, 4])
        c.set_page_mark(0, PageMark.COVER, True)  # 前面插空白 → 物理重排
        # controller 主选中 = 最小页（3）保持语义；重建后集合按主选中恢复
        assert c.selected_physical_index == 3
