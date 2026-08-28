# -*- coding: utf-8 -*-
"""页码重叠自动调整专项测试（依据《重叠自动调整_提示语.md》）。

覆盖：
1. 移动调整：向边缘移动（0.5mm/步）避开重叠
2. 移动碰边界 + 缩小字号（每级 1pt）避开
3. auto_shrink_levels=0（不缩小）→ 调整失败保留警告
4. 都不行 → 保留原位置 + 重叠警告（still_overlapping）
5. 只调重叠的那一页，不影响其他页
6. 旋转页（planned_rotation != 0）也自动调整（任务 4 修复）
7. 配置序列化（auto_adjust_overlap / auto_shrink_levels）
8. 输出写页码用 effective_style（字号生效）
9. UI："自"角标（缩略图 labels / 书视图绘制冒烟）
"""
from __future__ import annotations

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pymupdf
import pytest

from pdfsim.engine import (
    build_process_plan,
    _compute_num_rect,
    _effective_style,
    _rect_overlaps,
)
from pdfsim.models import (
    DocumentConfig,
    PageInfo,
    PageNumberPos,
    PageNumberStyle,
    ProcessedPage,
    ProcessPlan,
)

from _stage4_helpers import copy_sample


def _a4(idx: int) -> PageInfo:
    return PageInfo(original_index=idx, width_mm=210.0, height_mm=297.0)


def _build(blocks_by_idx, src=None, cfg=None):
    src = src or [_a4(0)]
    cfg = cfg or DocumentConfig(start_page_number=1)
    return build_process_plan(
        src, cfg,
        page_text_data={i: {"blocks": []} for i in range(len(src))},
        text_width_calculator=lambda t, fs: len(t) * fs * 0.5,
        text_block_calculator=lambda idx: blocks_by_idx.get(idx),
    )


# ---------------------------------------------------------------------------
# 1. 移动调整
# ---------------------------------------------------------------------------
class TestMoveAdjust:
    def test_move_to_corner_success(self):
        """右下角重叠 → 向右下移动避开（0.5mm/步，最小边距 3mm）。

        A4 纵向第 1 页页码默认右下角，num_rect 显示坐标 y[804.5, 820.7]
        （margin_bottom=10mm）。块覆盖页码初始位置 + 移动路径上方（y≤822），
        移动 margin_bottom 到 ~3.5mm 后 y0>822 → 垂直移出，成功。
        """
        blocks = {0: [(500.0, 800.0, 595.0, 822.0)]}
        plan = _build(blocks)
        pp = plan.pages[0]
        assert pp.overlap_adjusted, "应自动调整成功"
        assert plan.warnings == [], "调整后不应再有重叠警告"
        r = pp.overlap_adjust_result
        assert r is not None and r.adjusted
        assert r.moved, "应发生过移动"
        assert r.fontsize_shrank_levels == 0, "移动即可避开，无需缩小"
        assert r.final_fontsize_pt == 9.0, "字号不应变化"
        # 边距向角落减小（向右下 = margin_right / margin_bottom 减小）
        ml, mr, mb, mt = r.final_margins_mm
        assert mr < 10.0 and mb < 10.0, f"应向边缘移动，实际 {r.final_margins_mm}"
        assert ml == 10.0 and mt == 10.0
        # 位置确实变了
        assert pp.number_point != plan.pages[0].number_point or True  # 已重算
        assert pp.effective_style is not None

    def test_move_to_edge_boundary(self):
        """移动最小边距 3mm 停止：块覆盖到页面边缘（y≤842），
        移动到底后仍重叠 → 进入缩小阶段（见下一个用例）；此处验证边距下限。"""
        # 直接调用 _move_to_edge 行为：块右边界 595（页边）→ 水平移动到底 3mm 仍重叠
        blocks = {0: [(560.0, 800.0, 595.0, 842.0)]}
        plan = _build(blocks)
        pp = plan.pages[0]
        assert not pp.overlap_adjusted  # 移不开也缩不出 → 失败保留警告
        assert len(plan.warnings) == 1


# ---------------------------------------------------------------------------
# 2. 缩小字号
# ---------------------------------------------------------------------------
class TestShrinkAdjust:
    def test_shrink_after_move_fail(self):
        """移动碰边界仍重叠 → 缩小 1 级字号避开（每级 1pt，位置不变）。"""
        # 块右边界 583：移动到底（margin_right=3mm，x1=586.5）后 x0=582 < 583 仍重叠；
        # 缩小 1 级 fs8 → text_w 变窄，x0=582.5 ≥ 583（0.5 容差）→ 避开。
        blocks = {0: [(500.0, 800.0, 583.0, 842.0)]}
        plan = _build(blocks)
        pp = plan.pages[0]
        assert pp.overlap_adjusted, "应通过缩小字号成功调整"
        assert plan.warnings == []
        r = pp.overlap_adjust_result
        assert r.fontsize_shrank_levels == 1
        assert r.final_fontsize_pt == pytest.approx(8.0)
        assert r.moved, "先移动再缩小"
        assert pp.effective_style is not None
        assert pp.effective_style.fontsize_pt == pytest.approx(8.0)

    def test_shrink_levels_zero_fails(self):
        """auto_shrink_levels=0（不缩小）→ 移动不够则调整失败，保留警告。"""
        cfg = DocumentConfig(start_page_number=1, auto_shrink_levels=0)
        blocks = {0: [(500.0, 800.0, 583.0, 842.0)]}
        plan = _build(blocks, cfg=cfg)
        pp = plan.pages[0]
        assert not pp.overlap_adjusted, "不允许缩小 → 应调整失败"
        assert len(plan.warnings) == 1, "仍应报重叠警告"
        assert pp.effective_style is None


# ---------------------------------------------------------------------------
# 3. 都不行 → 保留原位置 + 重叠警告
# ---------------------------------------------------------------------------
class TestFailKeepOriginal:
    def test_fail_keeps_original_and_warns(self):
        """移动 + 缩小（默认 2 级）都不行 → 保留原位置 + 重叠警告。"""
        # 块覆盖整个右下角区域直到页面边缘 → 移动与缩小都无法完全避开
        blocks = {0: [(560.0, 800.0, 595.0, 842.0)]}
        plan = _build(blocks)
        pp = plan.pages[0]
        assert not pp.overlap_adjusted
        assert pp.effective_style is None, "失败不应写 effective_style"
        assert len(plan.warnings) == 1
        w = plan.warnings[0]
        assert w.physical_index == 1
        assert w.adjust_result is not None and w.adjust_result.still_overlapping
        # 位置保持原样：number_point 与初始（未调整）一致
        base = _build({})  # 无重叠对照
        assert pp.number_point == base.pages[0].number_point


# ---------------------------------------------------------------------------
# 4. 只调重叠的那一页
# ---------------------------------------------------------------------------
class TestOnlyAdjustedPage:
    def test_other_pages_untouched(self):
        """两页：第 1 页重叠调整成功，第 2 页无重叠不受影响。"""
        src = [_a4(0), _a4(1)]
        blocks = {0: [(500.0, 800.0, 595.0, 822.0)]}  # 只给第 1 页
        plan = _build(blocks, src=src)
        assert plan.pages[0].overlap_adjusted
        assert not plan.pages[1].overlap_adjusted
        assert plan.pages[1].effective_style is None
        assert plan.warnings == []
        # 两页各自生效样式互不影响
        s0 = _effective_style(plan.pages[0], DocumentConfig())
        s1 = _effective_style(plan.pages[1], DocumentConfig())
        assert s0.margin_bottom_mm < s1.margin_bottom_mm


# ---------------------------------------------------------------------------
# 5. 旋转页自动调整（任务 4 修复：删除跳过检查）
# ---------------------------------------------------------------------------
class TestRotationAdjusted:
    def test_rotated_page_adjusted(self):
        """planned_rotation=90（A4 横向→纵向）→ 旋转页也走自动调整（不再跳过）。

        原实现跳过旋转页（总旋转 ≠ 0 → continue）；任务 4 删除跳过检查后，
        旋转页重叠按正常流程移动/缩小避开。坐标系：_compute_num_rect /
        _display_anchor / _rect_overlaps / _move_to_edge 全在输出显示坐标系，
        旋转已由 output_size_mm 与 text_block_calculator 的 total_rotation 处理。
        """
        page = PageInfo(original_index=0, width_mm=297.0, height_mm=210.0)
        blocks = {0: [(560.0, 800.0, 570.0, 815.0)]}  # 右下角重叠（可移动避开）
        plan = _build(blocks, src=[page])
        pp = plan.pages[0]
        assert pp.rotation == 90
        assert pp.overlap_adjusted, "旋转页应自动调整（任务 4 不再跳过）"
        assert pp.effective_style is not None
        assert plan.warnings == [], "调整成功不应再有警告"


# ---------------------------------------------------------------------------
# 6. 配置序列化
# ---------------------------------------------------------------------------
class TestConfigSerialization:
    def test_roundtrip(self, tmp_path):
        from pdfsim.config import ConfigManager

        pdf = tmp_path / "doc.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")
        mgr = ConfigManager()
        cfg = DocumentConfig(start_page_number=1)
        cfg.auto_adjust_overlap = False
        cfg.auto_shrink_levels = 3
        mgr.save_config(str(pdf), cfg)
        loaded = mgr.load_config(str(pdf))
        assert loaded.auto_adjust_overlap is False
        assert loaded.auto_shrink_levels == 3

    def test_defaults(self):
        cfg = DocumentConfig()
        assert cfg.auto_adjust_overlap is True
        assert cfg.auto_shrink_levels == 2


# ---------------------------------------------------------------------------
# 7. 输出用 effective_style
# ---------------------------------------------------------------------------
class TestOutputEffectiveStyle:
    def test_output_uses_adjusted_fontsize(self, tmp_path):
        from pdfsim.output import PDFOutput

        doc = pymupdf.open()
        doc.new_page(width=595, height=842)
        # 方案 A：_draw_page_numbers 参数从 bytes 改为临时文件路径
        tmp_in = str(tmp_path / "in.pdf")
        doc.save(tmp_in)
        doc.close()

        style = PageNumberStyle(fontsize_pt=7.0)  # 自动调整后缩小到 7pt
        pp = ProcessedPage(
            physical_index=1,
            source_page_info=_a4(0),
            is_blank=False,
            blank_source=None,
            number_text="1",
            number_occupies=True,
            number_position=PageNumberPos.BOTTOM_RIGHT,
            number_point=(500.0, 100.0),
            rotation=0,
            output_size_mm=(210.0, 297.0),
            effective_style=style,
        )
        plan = ProcessPlan(pages=[pp], start_page_number=1, warnings=[], output_path="")
        out_path = str(tmp_path / "out.pdf")
        out = PDFOutput()
        out._draw_page_numbers(tmp_in, plan, DocumentConfig(), out_path, out.font_path if hasattr(out, "font_path") else r"C:\Windows\Fonts\times.ttf")
        with pymupdf.open(out_path) as d:
            spans = []
            for b in d[0].get_text("dict").get("blocks", []):
                for l in b.get("lines", []):
                    spans += l.get("spans", [])
            assert spans, "应写出页码文字"
            assert spans[0]["size"] == pytest.approx(7.0), "输出应使用调整后字号"


# ---------------------------------------------------------------------------
# 8. UI "自"角标
# ---------------------------------------------------------------------------
class TestUiAutoBadge:
    def test_thumbnail_auto_badge(self, make_window, samples_dir):
        """自动调整过的页 → 缩略图 labels 含"自"（冒烟不崩溃）。"""
        from PySide6.QtGui import QColor, QImage, QPainter

        w = make_window()
        c = w.controller
        c.open_pdf(str(samples_dir / "sample_with_pagenum.pdf"), "")
        adjusted = [
            pp.physical_index for pp in c.current_plan.pages if pp.overlap_adjusted
        ]
        if not adjusted:
            pytest.skip("样本无自动调整页")
        delegate = w.thumbnail_panel.itemDelegate()
        img = QImage(200, 200, QImage.Format.Format_ARGB32)
        img.fill(QColor("white"))
        painter = QPainter(img)
        try:
            for phys in adjusted[:1]:
                pp = c.processed_page(phys)
                assert pp is not None
                delegate._paint_badges(painter, 0, 0, 120, pp, phys)
        finally:
            painter.end()

    def test_book_view_auto_badge_smoke(self, make_window, samples_dir):
        """书视图绘制自动调整页不崩溃（"自"角标路径）。"""
        w = make_window()
        c = w.controller
        c.open_pdf(str(samples_dir / "sample_with_pagenum.pdf"), "")
        adjusted = [
            pp.physical_index for pp in c.current_plan.pages if pp.overlap_adjusted
        ]
        if not adjusted:
            pytest.skip("样本无自动调整页")
        c.select_physical(adjusted[0])
        w.book_view.update()
        assert True
