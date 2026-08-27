# -*- coding: utf-8 -*-
"""书视图页码预览测试（页码位置 Bug 修复任务 2）。

验证 AppController.get_page_number_info 返回的页码显示坐标：
  - 与输出 PDF 的页码位置一致（右下/左下/顶部，距边 10mm）；
  - 旋转页（A3 纵向→90°）页码仍在显示坐标右下角；
  - 无页码页（A3 背面）返回 None。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # 供导入 _stage4_helpers

import pytest

from pdfsim.models import MM_TO_PT, PageNumberPos, PageNumberStyle, RotationOverride

from _stage4_helpers import copy_sample

TOL = 2.5  # mm


def _open(tmp_path, name):
    from pdfsim.ui.app_controller import AppController

    src = copy_sample(name, str(tmp_path))
    c = AppController()
    c.open_pdf(src, "")
    return c


def _anchor_mm(c, phys):
    """返回 (anchor_x_pt, anchor_y_pt, out_w_mm, out_h_mm)。"""
    info = c.get_page_number_info(phys)
    assert info is not None, f"phys{phys} 应有页码"
    out = c.processed_page(phys).output_size_mm
    return info["anchor"][0], info["anchor"][1], out[0], out[1]


class TestPageNumberPreview:
    def test_bottom_right_10mm(self, tmp_path):
        """物理 1 页（A4 纵向）：页码距右/距底 ≈10mm（显示坐标）。"""
        c = _open(tmp_path, "sample_a4_portrait.pdf")
        try:
            ax, ay, wmm, hmm = _anchor_mm(c, 1)
            right_mm = wmm - ax / MM_TO_PT - 1.0  # 数字"1"宽约1mm
            bottom_mm = hmm - ay / MM_TO_PT
            assert abs(right_mm - 10) <= TOL, f"距右 {right_mm:.1f}mm"
            assert abs(bottom_mm - 10) <= TOL, f"距底 {bottom_mm:.1f}mm"
        finally:
            c.close()

    def test_even_page_bottom_left(self, tmp_path):
        """物理 2 页（偶数）：页码在左下角。"""
        c = _open(tmp_path, "sample_a4_portrait.pdf")
        try:
            ax, ay, _, hmm = _anchor_mm(c, 2)
            assert ax / MM_TO_PT <= 11.5, f"距左 {ax/MM_TO_PT:.1f}mm 应≈10mm"
            assert abs(hmm - ay / MM_TO_PT - 10) <= TOL, "应距底 10mm"
        finally:
            c.close()

    def test_top_position(self, tmp_path):
        """垂直位置=顶部：页码文字顶部距页顶 ≈10mm（anchor 为基线，含字高）。"""
        c = _open(tmp_path, "sample_a4_portrait.pdf")
        try:
            c.set_page_style_override(
                0, PageNumberStyle(vertical_position="top", margin_top_mm=10))
            _, ay, _, _ = _anchor_mm(c, 1)
            # 顶部语义：margin_top 使文字 bbox 顶部距页顶 = 10mm；
            # 基线 y = top_mm + ascent(≈0.8*fontsize)。显示坐标 y 向下。
            ascent_mm = 0.8 * 9.0 / MM_TO_PT
            top_mm = ay / MM_TO_PT - ascent_mm
            assert abs(top_mm - 10) <= TOL, f"距顶 {top_mm:.1f}mm"
        finally:
            c.close()

    def test_rotated_a3_page_right(self, tmp_path):
        """A3 纵向（规划旋转 90°）：显示坐标中页码仍在右下角（显式强制旋转）。"""
        c = _open(tmp_path, "sample_a3_portrait.pdf")
        try:
            c.set_rotation_override(1, RotationOverride.CW90)  # 样本文字水平 → 强制旋转
            pp = c.processed_page(3)
            assert pp.rotation == 90
            ax, ay, wmm, hmm = _anchor_mm(c, 3)
            right_mm = wmm - ax / MM_TO_PT - 1.0
            bottom_mm = hmm - ay / MM_TO_PT
            assert abs(right_mm - 10) <= TOL, f"旋转页距右 {right_mm:.1f}mm"
            assert abs(bottom_mm - 10) <= TOL, f"旋转页距底 {bottom_mm:.1f}mm"
        finally:
            c.close()

    def test_no_number_page_returns_none(self, tmp_path):
        """A3 背面（无页码不占序号）：返回 None。"""
        c = _open(tmp_path, "sample_mixed.pdf")
        try:
            assert c.get_page_number_info(4) is None
        finally:
            c.close()

    def test_book_view_paint_smoke(self, qtbot, tmp_path):
        """书视图渲染页码不崩溃（预览绘制路径）。"""
        c = _open(tmp_path, "sample_a4_portrait.pdf")
        try:
            from PySide6.QtWidgets import QApplication

            app = QApplication.instance() or QApplication([])
            from pdfsim.ui.book_view import BookView

            bv = BookView(c)
            bv.resize(600, 500)
            bv.show()
            app.processEvents()
            pix = bv.grab()
            assert not pix.isNull()
            bv.close()
        finally:
            c.close()
