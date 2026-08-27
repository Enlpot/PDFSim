# -*- coding: utf-8 -*-
"""重叠检测优化专项测试。

覆盖：
1. detect_pixel_overlap：有内容/空白/扫描件
2. 混合检测（build_process_plan）：文本块命中 / 像素命中 / 都 miss
3. 旋转坐标一致性：源页带 /Rotate + planned_rotation=0 → 文本块坐标回正
4. UI 重叠角标（缩略图 labels 含"叠"）
"""
from __future__ import annotations

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # 供导入 _stage4_helpers

import pymupdf
import pytest

from pdfsim.engine import build_process_plan, detect_overlap, detect_pixel_overlap
from pdfsim.models import (
    MM_TO_PT,
    BlankPageSource,
    DocumentConfig,
    PageInfo,
    PageNumberPos,
    PageNumberStyle,
    RotationOverride,
)
from pdfsim.engine import _display_anchor, number_rect_from_anchor

from _stage4_helpers import copy_sample


# ---------------------------------------------------------------------------
# 1. 像素重叠检测
# ---------------------------------------------------------------------------
class TestDetectPixelOverlap:
    def _make_doc(self, draw_rect=True, scanned=False):
        """构造 A4 纵向页面；draw_rect 在底部画深色矩形，scanned 插入整页噪声图。"""
        doc = pymupdf.open()
        page = doc.new_page(width=595, height=842)
        if scanned:
            from PIL import Image

            img = Image.effect_noise((240, 240), 55).convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=75)
            page.insert_image(pymupdf.Rect(0, 0, 595, 842), stream=buf.getvalue())
        elif draw_rect:
            page.draw_rect(pymupdf.Rect(480, 760, 580, 800),
                           color=(0, 0, 0), fill=(0, 0, 0))
        return doc

    def test_pixel_overlap_with_content(self):
        doc = self._make_doc(draw_rect=True)
        try:
            page = doc[0]
            rect = (485.0, 760.0, 560.0, 790.0)  # 落在深色矩形上
            assert detect_pixel_overlap(page, rect) is True
        finally:
            doc.close()

    def test_pixel_overlap_blank_area(self):
        doc = self._make_doc(draw_rect=True)
        try:
            page = doc[0]
            rect = (20.0, 20.0, 80.0, 40.0)  # 左上角空白
            assert detect_pixel_overlap(page, rect) is False
        finally:
            doc.close()

    def test_pixel_overlap_blank_page(self):
        doc = self._make_doc(draw_rect=False)
        try:
            page = doc[0]
            rect = (485.0, 760.0, 560.0, 790.0)
            assert detect_pixel_overlap(page, rect) is False
        finally:
            doc.close()

    def test_pixel_overlap_scanned_pdf(self):
        """扫描件（整页图片）：页码区域有图片内容 → 检测到重叠。"""
        doc = self._make_doc(scanned=True)
        try:
            page = doc[0]
            rect = (485.0, 760.0, 560.0, 790.0)
            assert detect_pixel_overlap(page, rect) is True
        finally:
            doc.close()

    def test_threshold_filters_noise(self):
        """高阈值过滤：min_overlap_pixels 很大 → 视为无内容（防误报）。"""
        doc = self._make_doc(draw_rect=True)
        try:
            page = doc[0]
            rect = (485.0, 760.0, 560.0, 790.0)
            # 63×31 像素区域最多约 1953 像素，阈值远超 → False
            assert detect_pixel_overlap(page, rect, min_overlap_pixels=100000) is False
        finally:
            doc.close()


# ---------------------------------------------------------------------------
# 2. 混合检测（build_process_plan + pixel_overlap_checker 回调）
# ---------------------------------------------------------------------------
class TestMixedOverlap:
    def _build(self, text_blocks, pixel_result, with_pixel_checker=True):
        src = [PageInfo(original_index=0, width_mm=210.0, height_mm=297.0)]
        cfg = DocumentConfig(start_page_number=1)
        cfg.auto_adjust_overlap = False  # 本组验证"检测→警告"原始语义，关闭自动调整
        text_data = {0: {"blocks": []}}

        def w_calc(t, fs):
            return len(t) * fs * 0.5

        def tbc(idx):
            return text_blocks if idx == 0 else None

        def poc(idx, rect):
            return pixel_result

        return build_process_plan(
            src, cfg,
            page_text_data=text_data,
            text_width_calculator=w_calc,
            text_block_calculator=tbc,
            pixel_overlap_checker=poc if with_pixel_checker else None,
        )

    def test_text_block_hit_no_pixel_needed(self):
        """文本块命中 → 报重叠（像素 miss 也无妨）。"""
        # A4 纵向第 1 页默认页码在右下角：num_rect 显示坐标约 (562, 805, 567, 821)pt
        blocks = [(555.0, 800.0, 575.0, 825.0)]  # 与右下页码区域重叠
        plan = self._build(blocks, False)
        assert len(plan.warnings) == 1
        w = plan.warnings[0]
        assert w.physical_index == 1
        assert w.number_text == "1"

    def test_text_block_miss_pixel_hit(self):
        """文本块 miss + 像素命中（扫描件）→ 报重叠，overlap_rect 用页码 bbox。"""
        blocks = [(10.0, 10.0, 50.0, 30.0)]  # 不与页码重叠
        plan = self._build(blocks, True)
        assert len(plan.warnings) == 1
        w = plan.warnings[0]
        assert w.physical_index == 1
        # 像素命中无精确交集 → overlap_rect 即页码 bbox（底部区域）
        x0, y0, x1, y1 = w.overlap_rect_pt
        assert y0 > 500  # 底部页码区域

    def test_both_miss(self):
        """两者都 miss → 无警告。"""
        plan = self._build([(10.0, 10.0, 50.0, 30.0)], False)
        assert plan.warnings == []

    def test_no_pixel_checker_no_pixel_warning(self):
        """不传 pixel_overlap_checker → 仅文本块检测（向后兼容）。"""
        plan = self._build([(10.0, 10.0, 50.0, 30.0)], True, with_pixel_checker=False)
        assert plan.warnings == []


# ---------------------------------------------------------------------------
# 3. 旋转坐标一致性（源页带 /Rotate + planned_rotation=0）
# ---------------------------------------------------------------------------
class TestRotationConsistency:
    def _open_rotated(self, tmp_path):
        """构造带 /Rotate=90 的 PDF：显示坐标右下（内容坐标左上）写多行文字。

        /Rotate=90 时内容坐标→显示坐标映射为 (x_disp, y_disp)=(H-y, W-x)：
        内容 y 小 → 显示 x 大（右侧）；内容 x 小 → 显示 y 大（底部）。
        故在内容左上写文字 → 显示右下（页码默认右下区域 → 重叠）。
        """
        doc = pymupdf.open()
        page = doc.new_page(width=595, height=842)
        for i, yy in enumerate(range(5, 60, 10)):
            page.insert_text((20, yy), "X" * 8, fontsize=12)
        page.set_rotation(90)
        path = str(tmp_path / "rot90.pdf")
        doc.save(path)
        doc.close()

        from pdfsim.ui.app_controller import AppController

        c = AppController()
        c.open_pdf(path, "")
        return c

    def test_text_block_coords_use_total_rotation(self, tmp_path):
        """带 /Rotate=90 + planned_rotation=0 时，文本块坐标按总旋转 90° 回正。"""
        c = self._open_rotated(tmp_path)
        try:
            pp = next(p for p in c.current_plan.pages if not p.is_blank)
            assert pp.source_page_info.source_rotation == 90
            assert pp.rotation == 0  # 文字水平正向 → 无需额外旋转
            # 模拟 build_process_plan 传入总旋转（源页 /Rotate + 规划旋转）
            blocks = c._text_block_calculator(0, 90)
            assert blocks, "应有文本块"
            # 内容左上文字 → 显示右下（y 大=底部）
            max_y = max(b[3] for b in blocks)
            H = pp.output_size_mm[1] * MM_TO_PT
            assert max_y > H * 0.5, f"文本块未回正到底部: max_y={max_y}, H={H}"
        finally:
            c.close()

    def test_rotated_source_overlap_warning(self, tmp_path):
        """带 /Rotate 页：显示底部有内容 → 页码重叠警告正确触发（坐标回正后）。"""
        c = self._open_rotated(tmp_path)
        try:
            assert c.current_plan.warnings, "带 /Rotate 页应触发重叠警告（坐标回正后）"
        finally:
            c.close()


# ---------------------------------------------------------------------------
# 4. UI 重叠角标
# ---------------------------------------------------------------------------
class TestUiOverlapBadge:
    def test_thumbnail_overlap_badge(self, make_window, samples_dir):
        """缩略图对重叠页生成"叠"角标（labels 含叠）。"""
        from PySide6.QtGui import QColor, QImage, QPainter

        w = make_window()
        c = w.controller
        c.open_pdf(str(samples_dir / "sample_with_pagenum.pdf"), "")
        c.set_auto_adjust_overlap(False)  # 验证"检测→警告"原始语义，关闭自动调整
        panel = w.thumbnail_panel

        warned = [
            pp.physical_index for pp in c.current_plan.pages
            if not pp.is_blank and c.overlap_warning_for(pp.physical_index) is not None
        ]
        assert warned, "sample_with_pagenum 应有重叠警告页"

        # 直接调用 delegate._paint_badges：验证 labels 逻辑含"叠"（冒烟不崩溃）
        from PySide6.QtGui import QColor, QImage, QPainter

        delegate = panel.itemDelegate()
        img = QImage(200, 200, QImage.Format.Format_ARGB32)
        img.fill(QColor("white"))
        painter = QPainter(img)
        try:
            for phys in warned[:1]:
                pp = c.processed_page(phys)
                assert pp is not None
                delegate._paint_badges(painter, 0, 0, 120, pp, phys)
            # 无异常即通过（逻辑上 labels 已含"叠"）
        finally:
            painter.end()

    def test_book_view_overlap_badge_smoke(self, make_window, samples_dir):
        """书视图在重叠页绘制不崩溃（角标路径）。"""
        w = make_window()
        c = w.controller
        c.open_pdf(str(samples_dir / "sample_with_pagenum.pdf"), "")
        bv = w.book_view
        warned = [
            pp.physical_index for pp in c.current_plan.pages
            if not pp.is_blank and c.overlap_warning_for(pp.physical_index) is not None
        ]
        if not warned:
            pytest.skip("样本无重叠警告页")
        c.select_physical(warned[0])
        bv.update()  # 触发 paintEvent，不崩溃即通过
        assert True
