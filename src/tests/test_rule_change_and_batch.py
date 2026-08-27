# -*- coding: utf-8 -*-
"""规则变更 + 空白页可配置 + 多选批量 + tooltip 专项测试（对应《多选批量与空白页配置_提示语》第六节）。

- 任务 1：NO_NUMBER 跳过序号、NO_COUNT 迁移、自动空白页回归、原文件完整性、报告语义
- 任务 2：空白页标识稳定、设"不加页码"、持久化、旧配置兼容、UI 置灰
- 任务 3：多选集合、三态、批量应用、A3 FRONT 强制、书视图提示、单页区禁用、混合多选
- 任务 4：4 个 tooltip 非空

样本说明：
  sample_no_bookmark：4 页纯 A4（无封面/签字自动识别）→ 页码规则精确断言
  sample_no_count：封面/附件/正文 3 页（封面 → 自动插 COVER_BACK）
  sample_a4_portrait：6 页带书签（封面/目录/正文/签字）→ 含 COVER_BACK 与 SIGN_BACK
  sample_mixed：A4+A3 混合 → 含 A3_BACK
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # 供导入 _stage4_helpers

import pytest

from _stage4_helpers import Pipeline, copy_sample

from pdfsim.models import BlankPageSource, PageMark


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _cfg_path(src: str) -> str:
    """配置路径：原 PDF 同名 + .pagerconfig.json。"""
    return os.path.splitext(src)[0] + ".pagerconfig.json"


def open_sample_ui(make_window, samples_dir, rel):
    w = make_window()
    c = w.controller
    cfg = os.path.join(str(samples_dir), rel + ".pagerconfig.json")
    if os.path.exists(cfg):
        os.remove(cfg)
    c.open_pdf(str(samples_dir / rel), "")
    return w, c


def _non_blank_phys(plan) -> list[int]:
    return [pp.physical_index for pp in plan.pages if not pp.is_blank]


# ---------------------------------------------------------------------------
# 任务 1：规则变更
# ---------------------------------------------------------------------------
class TestRuleChange:
    def test_no_number_skip_sequence(self, tmp_path, samples_dir):
        """提示语示例：页1"1"、页2不加页码（无数字）、页3"2"（顺延前移）。"""
        from pdfsim.ui.app_controller import AppController

        src = copy_sample("sample_no_bookmark.pdf", str(tmp_path))
        c = AppController()
        try:
            c.open_pdf(src, "")
            c.set_page_mark(1, PageMark.NO_NUMBER, True)  # 源页 2（0-based 1）
            texts = [pp.number_text for pp in c.current_plan.pages]
            assert texts == ["1", None, "2", "3"]
        finally:
            c.close()

    def test_mixed_no_number_and_blank(self, tmp_path):
        """混合 NO_NUMBER 源页 + 自动空白页：序号跳过累计正确、序号连续无洞。"""
        from pdfsim.ui.app_controller import AppController

        src = copy_sample("sample_a4_portrait.pdf", str(tmp_path))
        c = AppController()
        try:
            c.open_pdf(src, "")
            c.set_page_mark(2, PageMark.NO_NUMBER, True)  # 源页 3
            plan = c.current_plan
            # 含自动空白页（封面背面/签字背面）
            assert any(pp.is_blank for pp in plan.pages)
            nums = [int(pp.number_text) for pp in plan.pages
                    if pp.number_text is not None]
            assert nums == list(range(1, len(nums) + 1))
        finally:
            c.close()

    def test_old_config_migration(self, tmp_path):
        """旧配置 v1（含 no_count）→ 迁移为 NO_NUMBER，不报错，新语义生效。"""
        from pdfsim.ui.app_controller import AppController

        src = copy_sample("sample_no_count.pdf", str(tmp_path))
        with open(_cfg_path(src), "w", encoding="utf-8") as f:
            json.dump({
                "version": 1,
                "source_file": os.path.abspath(src),
                "global": {"start_page_number": 1, "auto_fill_last_page": False},
                "pages": [{"original_index": 1, "marks": ["no_count"]}],
            }, f)
        c = AppController()
        try:
            c.open_pdf(src, "")
            assert PageMark.NO_COUNT not in c.source_page(1).marks
            assert PageMark.NO_NUMBER in c.source_page(1).marks
            # 新语义：保留内容 + 无数字 + 跳过序号
            pp = next(p for p in c.current_plan.pages
                      if p.source_page_info.original_index == 1)
            assert pp.is_blank is False
            assert pp.number_text is None and not pp.number_occupies
        finally:
            c.close()

    def test_old_no_number_config_new_semantics(self, tmp_path):
        """旧 NO_NUMBER 配置按新语义（跳过序号）生效。"""
        from pdfsim.ui.app_controller import AppController

        src = copy_sample("sample_no_bookmark.pdf", str(tmp_path))
        with open(_cfg_path(src), "w", encoding="utf-8") as f:
            json.dump({
                "version": 2,
                "source_file": os.path.abspath(src),
                "global": {"start_page_number": 1, "auto_fill_last_page": False},
                "pages": [{"original_index": 0, "marks": ["no_number"]}],
            }, f)
        c = AppController()
        try:
            c.open_pdf(src, "")
            plan = c.current_plan
            assert plan.pages[0].number_text is None
            assert plan.pages[0].number_occupies is False  # 跳过序号（新语义）
            assert plan.pages[1].number_text == "1"
        finally:
            c.close()

    def test_auto_blank_regression(self, tmp_path):
        """自动空白页回归：封面背面有页码占序号、签字背面无页码不占序号。"""
        from pdfsim.ui.app_controller import AppController

        src = copy_sample("sample_a4_portrait.pdf", str(tmp_path))
        c = AppController()
        try:
            c.open_pdf(src, "")
            for pp in c.current_plan.pages:
                if pp.blank_source is BlankPageSource.COVER_BACK:
                    assert pp.number_text is not None and pp.number_occupies
                if pp.blank_source is BlankPageSource.SIGN_BACK:
                    assert pp.number_text is None and not pp.number_occupies
                if pp.blank_source is BlankPageSource.A3_BACK:
                    assert pp.number_text is None and not pp.number_occupies
        finally:
            c.close()

    def test_source_file_integrity(self, samples_dir, tmp_path):
        """原文件完整性：output 前后 SHA-256 一致（内容保护铁律）。"""
        p = Pipeline(copy_sample("sample_no_count.pdf", str(tmp_path)),
                     str(tmp_path))
        try:
            h1 = _sha256(p.src)
            res = p.output()
            assert res.success
            h2 = _sha256(p.src)
            assert h1 == h2
        finally:
            p.close()

    def test_report_new_semantics(self, make_window, samples_dir):
        """报告"页面标记"列反映新语义（不加页码；无"不占序号"）。"""
        w, c = open_sample_ui(make_window, samples_dir, "sample_no_bookmark.pdf")
        c.set_page_mark(1, PageMark.NO_NUMBER, True)
        rows = c.get_report_data()
        row = next(r for r in rows if r["源文件页号"] == 2)
        assert "不加页码" in row["页面标记"]
        assert "不占序号" not in row["页面标记"]


# ---------------------------------------------------------------------------
# 任务 2：空白页可配置
# ---------------------------------------------------------------------------
class TestBlankConfig:
    def test_blank_id_stable(self, tmp_path):
        """空白页标识跨 rebuild 稳定（级联插入后不变）。"""
        from pdfsim.ui.app_controller import AppController

        src = copy_sample("sample_mixed.pdf", str(tmp_path))
        c = AppController()
        try:
            c.open_pdf(src, "")
            a3backs = [pp for pp in c.current_plan.pages
                       if pp.blank_source is BlankPageSource.A3_BACK]
            assert a3backs
            bid = a3backs[0].source_page_info.blank_id
            assert bid and bid.startswith("blank:")
            # 修改第 1 页标记 → 级联插入空白 → rebuild
            c.set_page_mark(0, PageMark.COVER, True)
            a3backs2 = [pp for pp in c.current_plan.pages
                        if pp.blank_source is BlankPageSource.A3_BACK]
            assert a3backs2
            assert a3backs2[0].source_page_info.blank_id == bid
        finally:
            c.close()

    def test_blank_no_number_override(self, tmp_path):
        """空白页设"不加页码"：无数字、序号跳过、后续页码连续前移（覆盖来源默认）。"""
        from pdfsim.ui.app_controller import AppController

        src = copy_sample("sample_a4_portrait.pdf", str(tmp_path))
        c = AppController()
        try:
            c.open_pdf(src, "")
            cb = next(pp for pp in c.current_plan.pages
                      if pp.blank_source is BlankPageSource.COVER_BACK)
            assert cb.number_text is not None  # 默认有页码
            c.set_page_mark_physical(cb.physical_index, PageMark.NO_NUMBER, True)
            pp = c.current_plan.pages[cb.physical_index - 1]
            assert pp.number_text is None and not pp.number_occupies
            nums = [int(pp.number_text) for pp in c.current_plan.pages
                    if pp.number_text is not None]
            assert nums == list(range(1, len(nums) + 1))  # 后续顺延无洞
        finally:
            c.close()

    def test_blank_default_unchanged(self, tmp_path):
        """未配置时空白页行为与现状完全一致。"""
        from pdfsim.ui.app_controller import AppController

        src = copy_sample("sample_a4_portrait.pdf", str(tmp_path))
        c = AppController()
        try:
            c.open_pdf(src, "")
            cb = next(pp for pp in c.current_plan.pages
                      if pp.blank_source is BlankPageSource.COVER_BACK)
            assert cb.number_text is not None and cb.number_occupies
        finally:
            c.close()

    def test_blank_config_persist(self, tmp_path):
        """空白页配置持久化：保存后重开恢复。"""
        from pdfsim.ui.app_controller import AppController

        src = copy_sample("sample_a4_portrait.pdf", str(tmp_path))
        c = AppController()
        try:
            c.open_pdf(src, "")
            cb = next(pp for pp in c.current_plan.pages
                      if pp.blank_source is BlankPageSource.COVER_BACK)
            c.set_page_mark_physical(cb.physical_index, PageMark.NO_NUMBER, True)
            c._do_save_config()
            assert os.path.exists(_cfg_path(src))
        finally:
            c.close()
        c2 = AppController()
        try:
            c2.open_pdf(src, "")
            cb2 = next(pp for pp in c2.current_plan.pages
                       if pp.blank_source is BlankPageSource.COVER_BACK)
            assert cb2.number_text is None and not cb2.number_occupies
        finally:
            c2.close()

    def test_old_config_without_blank(self, tmp_path):
        """无空白页配置的旧 JSON 正常加载。"""
        from pdfsim.ui.app_controller import AppController

        src = copy_sample("sample_a4_portrait.pdf", str(tmp_path))
        with open(_cfg_path(src), "w", encoding="utf-8") as f:
            json.dump({
                "version": 1,
                "source_file": os.path.abspath(src),
                "pages": [{"original_index": 0, "marks": ["cover"]}],
            }, f)
        c = AppController()
        try:
            c.open_pdf(src, "")  # 不报错
            assert PageMark.COVER in c.source_page(0).marks
        finally:
            c.close()

    def test_blank_ui_disabled(self, make_window, samples_dir):
        """空白页选中时：封面/签字页/从正面开始置灰，自定义标签禁用；不加页码可用。"""
        w, c = open_sample_ui(make_window, samples_dir, "sample_a4_portrait.pdf")
        blank_pp = next(pp for pp in c.current_plan.pages if pp.is_blank)
        c.select_physical(blank_pp.physical_index)
        w.config_panel.load_page(blank_pp.physical_index)
        assert not w.config_panel._chk_cover.isEnabled()
        assert not w.config_panel._chk_sign.isEnabled()
        assert not w.config_panel._chk_front.isEnabled()
        assert not w.config_panel._label_input.isEnabled()
        assert w.config_panel._chk_no_number.isEnabled()


# ---------------------------------------------------------------------------
# 任务 3：多选批量
# ---------------------------------------------------------------------------
class TestMultiSelectBatch:
    def test_multiselect_set(self, make_window, samples_dir):
        """缩略图多选（ExtendedSelection）→ 选中集正确同步 controller。"""
        w, c = open_sample_ui(make_window, samples_dir, "sample_no_bookmark.pdf")
        items = w.thumbnail_panel._items
        items[2].setSelected(True)
        items[3].setSelected(True)
        assert c.selected_physical_pages() == [2, 3]
        assert c.selected_physical_index == 2  # 主选中=最小页

    def test_batch_mark(self, make_window, samples_dir):
        """批量勾选/取消：所有选中页标记正确增删。"""
        w, c = open_sample_ui(make_window, samples_dir, "sample_no_bookmark.pdf")
        c.set_selected_pages([2, 3, 4])
        c.set_page_mark_batch([2, 3, 4], PageMark.NO_NUMBER, True)
        for phys in (2, 3, 4):
            assert PageMark.NO_NUMBER in c.processed_page(phys).source_page_info.marks
        c.set_page_mark_batch([2, 3, 4], PageMark.NO_NUMBER, False)
        for phys in (2, 3, 4):
            assert PageMark.NO_NUMBER not in c.processed_page(phys).source_page_info.marks

    def test_tristate(self, tmp_path):
        """三态：全勾 / 半勾 / 空态。"""
        from pdfsim.ui.app_controller import AppController

        src = copy_sample("sample_no_bookmark.pdf", str(tmp_path))
        c = AppController()
        try:
            c.open_pdf(src, "")
            # NO_NUMBER 不改变物理结构 → 物理页号稳定
            c.set_page_mark(0, PageMark.NO_NUMBER, True)  # 物理1
            c.set_page_mark(1, PageMark.NO_NUMBER, True)  # 物理2
            assert c.mark_state_for_pages([1, 2], PageMark.NO_NUMBER) is True
            c.set_page_mark(1, PageMark.NO_NUMBER, False)
            assert c.mark_state_for_pages([1, 2], PageMark.NO_NUMBER) is None
            c.set_page_mark(0, PageMark.NO_NUMBER, False)
            assert c.mark_state_for_pages([1, 2], PageMark.NO_NUMBER) is False
        finally:
            c.close()

    def test_batch_front_forced_a3(self, tmp_path):
        """批量取消"从正面开始"：A3 页 FRONT 保留（强制）。"""
        from pdfsim.models import is_a3
        from pdfsim.ui.app_controller import AppController

        src = copy_sample("sample_mixed.pdf", str(tmp_path))
        c = AppController()
        try:
            c.open_pdf(src, "")
            a3_pp = next(pp for pp in c.current_plan.pages
                         if not pp.is_blank and is_a3(pp.source_page_info))
            assert PageMark.FRONT in a3_pp.source_page_info.marks
            c.set_page_mark_batch([a3_pp.physical_index], PageMark.FRONT, False)
            assert PageMark.FRONT in a3_pp.source_page_info.marks
        finally:
            c.close()

    def test_all_a3_front_disabled(self, tmp_path):
        """全 A3 选中 → "从正面开始"置灰只读。"""
        from pdfsim.models import is_a3
        from pdfsim.ui.app_controller import AppController

        src = copy_sample("sample_mixed.pdf", str(tmp_path))
        c = AppController()
        try:
            c.open_pdf(src, "")
            a3_phys = [pp.physical_index for pp in c.current_plan.pages
                       if not pp.is_blank and is_a3(pp.source_page_info)]
            assert a3_phys
            c.set_selected_pages(a3_phys)
            from pdfsim.ui.config_panel import ConfigPanel
            panel = ConfigPanel(controller=c)
            panel.on_selection_set_changed(a3_phys)
            assert panel._chk_front.isEnabled() is False
        finally:
            c.close()

    def test_batch_rebuild(self, tmp_path):
        """批量操作后 plan 正确重算（结构不变、标记生效）。"""
        from pdfsim.ui.app_controller import AppController

        src = copy_sample("sample_mixed.pdf", str(tmp_path))
        c = AppController()
        try:
            c.open_pdf(src, "")
            n0 = c.plan_page_count()
            a3_pp = next(pp for pp in c.current_plan.pages
                         if pp.is_blank and pp.blank_source is BlankPageSource.A3_BACK)
            c.set_page_mark_batch([a3_pp.physical_index], PageMark.NO_NUMBER, True)
            assert c.plan_page_count() == n0
            assert a3_pp.number_text is None
        finally:
            c.close()

    def test_bookview_hint(self, make_window, samples_dir):
        """多选时书视图显示最前选中页 + 已选 N 页提示（可渲染）。"""
        w, c = open_sample_ui(make_window, samples_dir, "sample_no_bookmark.pdf")
        c.set_selected_pages([3, 4])
        assert c.selected_physical_index == 3  # 最小页驱动状态机
        w.book_view.update()
        img = w.book_view.grab().toImage()
        assert not img.isNull()

    def test_single_page_disabled(self, make_window, samples_dir):
        """多选时：页码位置/自定义标签仍禁用；旋转与页码样式已解锁可批量；标签可用。"""
        w, c = open_sample_ui(make_window, samples_dir, "sample_no_bookmark.pdf")
        c.set_selected_pages([2, 3])
        w.config_panel.on_selection_set_changed([2, 3])
        assert w.config_panel._batch_pages == [2, 3]
        # 页码位置保持禁用
        assert not w.config_panel._pos_combo.isEnabled()
        assert not w.config_panel._custom_row.isEnabled()
        # 旋转方向 / 页码样式已解锁（功能增强）
        assert w.config_panel._rot_combo.isEnabled()
        assert w.config_panel._style_font.isEnabled()
        assert w.config_panel._chk_no_number.isEnabled()

    def test_batch_save_restore(self, tmp_path):
        """批量标记保存后重开恢复。"""
        from pdfsim.ui.app_controller import AppController

        src = copy_sample("sample_no_bookmark.pdf", str(tmp_path))
        c = AppController()
        try:
            c.open_pdf(src, "")
            c.set_page_mark_batch([2, 3], PageMark.NO_NUMBER, True)
            c._do_save_config()
        finally:
            c.close()
        c2 = AppController()
        try:
            c2.open_pdf(src, "")
            for phys in (2, 3):
                assert PageMark.NO_NUMBER in c2.processed_page(phys).source_page_info.marks
        finally:
            c2.close()

    def test_mixed_source_blank_batch(self, tmp_path):
        """混合多选：源页 + 空白页批量"不加页码"，各自生效。"""
        from pdfsim.ui.app_controller import AppController

        src = copy_sample("sample_a4_portrait.pdf", str(tmp_path))
        c = AppController()
        try:
            c.open_pdf(src, "")
            blank_pp = next(pp for pp in c.current_plan.pages if pp.is_blank)
            src_pp = next(pp for pp in c.current_plan.pages if not pp.is_blank)
            c.set_page_mark_batch(
                [src_pp.physical_index, blank_pp.physical_index],
                PageMark.NO_NUMBER, True)
            assert PageMark.NO_NUMBER in src_pp.source_page_info.marks
            assert PageMark.NO_NUMBER in blank_pp.source_page_info.marks
        finally:
            c.close()


# ---------------------------------------------------------------------------
# 任务 4：tooltip
# ---------------------------------------------------------------------------
class TestTooltip:
    def test_four_checkbox_tooltips(self, make_window, samples_dir):
        """4 个属性标签复选框 tooltip 非空且反映新语义。"""
        w, c = open_sample_ui(make_window, samples_dir, "sample_no_bookmark.pdf")
        p = w.config_panel
        tips = {
            "封面": p._chk_cover.toolTip(),
            "签字页": p._chk_sign.toolTip(),
            "不加页码": p._chk_no_number.toolTip(),
            "从正面开始": p._chk_front.toolTip(),
        }
        for name, tip in tips.items():
            assert tip and tip.strip(), f"{name} tooltip 为空"
        assert "前移" in tips["不加页码"]
        assert "空白" in tips["签字页"]

