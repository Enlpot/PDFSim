# -*- coding: utf-8 -*-
"""Stage 4 旋转可读性专项验证。

对应《测试矩阵.md》第 2 节：用方向标记样本（四角'顶/底/左/右' + 中心水平箭头）
实证旋转方向正确，不能用"看起来对"代替。

验证方法（测试矩阵 2.2）：
1. 输入带方向标记样本 → 输出（含旋转决策）；
2. 用 PyMuPDF 渲染输出页（get_pixmap，应用 /Rotate）；
3. 把渲染图逆时针旋转 90°（模拟读者站书右侧逆时针转书 90°）；
4. 检查中心箭头是否水平朝右、"顶"在上"底"在下、正文正立可读。

程序化判定：
- 方向标记位置：rotation_matrix 把未旋转坐标→显示坐标，检查"顶在上、底在下、左在左、右在右"；
- 渲染箭头方向：渲染图逆时针转 90° 后，中心带状区域黑色像素呈水平延伸（宽>高）。
"""
from __future__ import annotations

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # 供导入 _stage4_helpers

import pymupdf
import pytest
from PIL import Image

from pdfsim.models import A3_HEIGHT_MM, A3_WIDTH_MM, RotationOverride

from _stage4_helpers import (
    Pipeline,
    assert_marks_upright,
    copy_sample,
)


def render_page(out_path: str, phys_index: int, dpi: int = 72) -> Image.Image:
    """渲染输出页为 PIL 图（get_pixmap 已应用 /Rotate）。"""
    doc = pymupdf.open(out_path)
    try:
        pix = doc[phys_index - 1].get_pixmap(dpi=dpi)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        return img
    finally:
        doc.close()


def arrow_is_horizontal(img: Image.Image) -> bool:
    """检查图像中心带状区域黑色像素是否呈水平延伸（宽>高）。

    箭头为黑色粗线段；检测中心 40%–60% 高度带的深色像素分布。
    """
    gray = img.convert("L")
    w, h = gray.size
    band = gray.crop((0, int(h * 0.40), w, int(h * 0.60)))
    pix = band.load()
    bw, bh = band.size
    xs: list[int] = []
    ys: list[int] = []
    for yy in range(bh):
        for xx in range(bw):
            if pix[xx, yy] < 128:
                xs.append(xx)
                ys.append(yy)
    if len(xs) < 20:
        return False
    spread_w = max(xs) - min(xs)
    spread_h = max(ys) - min(ys)
    return spread_w > spread_h * 2 and spread_w > 0.1 * w


class TestRotationReadability:
    def test_a4_landscape_rotated_readable(self, samples_dir, tmp_path):
        """A4 横向页：输出旋转 90°→210×297 纵向，逆时针转书 90° 后正立可读。

        样本文字本为水平正向（AUTO 检测=0），故显式强制旋转以验证
        "旋转→输出→转书后可读" 链路（检测逻辑由 test_engine 专项覆盖）。
        """
        src = copy_sample("sample_direction_markers.pdf", str(tmp_path))
        p = Pipeline(src, str(tmp_path))
        try:
            p.result.pages[0].rotation_override = RotationOverride.CW90
            p.rebuild()
            # 定位 A4 横向源页（idx0）的物理页（phys1）
            pp = p.plan.pages[0]
            assert pp.source_page_info.original_index == 0
            assert pp.rotation == 90
            assert pp.output_size_mm == pytest.approx((210.0, 297.0), abs=0.2)
            res = p.output()
            assert res.success
            # 方向标记位置（显示画面）→ 顶在上底在下
            assert_marks_upright(res.output_path, pp.physical_index)
            # 渲染图逆时针转 90° 后中心箭头水平朝右
            img = render_page(res.output_path, pp.physical_index)
            rotated = img.transpose(Image.Transpose.ROTATE_90)  # 逆时针 90°
            assert arrow_is_horizontal(rotated), "逆时针转 90° 后箭头未水平朝右"
        finally:
            p.close()

    def test_a3_portrait_rotated_readable(self, samples_dir, tmp_path):
        """A3 纵向页：输出旋转 90°→420×297 横向，逆时针转书 90° 后正立可读（显式强制旋转）。"""
        src = copy_sample("sample_a3_portrait.pdf", str(tmp_path))
        p = Pipeline(src, str(tmp_path))
        try:
            p.result.pages[1].rotation_override = RotationOverride.CW90
            p.rebuild()
            a3 = [pp for pp in p.plan.pages
                  if not pp.is_blank and pp.source_page_info.original_index == 1]
            assert a3 and a3[0].rotation == 90
            assert a3[0].output_size_mm == pytest.approx(
                (A3_HEIGHT_MM, A3_WIDTH_MM), abs=0.2)
            res = p.output()
            assert res.success
            assert_marks_upright(res.output_path, a3[0].physical_index)
            img = render_page(res.output_path, a3[0].physical_index)
            rotated = img.transpose(Image.Transpose.ROTATE_90)
            assert arrow_is_horizontal(rotated), "A3 纵向转书后箭头未水平"
        finally:
            p.close()

    def test_a3_landscape_no_rotation_readable(self, samples_dir, tmp_path):
        """A3 横向页：不旋转（420×297），展开跨页直接正立可读。"""
        src = copy_sample("sample_a3_landscape.pdf", str(tmp_path))
        p = Pipeline(src, str(tmp_path))
        try:
            a3 = [pp for pp in p.plan.pages
                  if not pp.is_blank and pp.source_page_info.original_index == 1]
            assert a3 and a3[0].rotation == 0
            assert a3[0].output_size_mm == pytest.approx(
                (A3_HEIGHT_MM, A3_WIDTH_MM), abs=0.2)
            res = p.output()
            assert res.success
            assert_marks_upright(res.output_path, a3[0].physical_index)
            # 不旋转 → 渲染图直接正立，无需转书
            img = render_page(res.output_path, a3[0].physical_index)
            assert arrow_is_horizontal(img), "A3 横向直接应正立（箭头水平）"
        finally:
            p.close()

    def test_a4_portrait_control_readable(self, samples_dir, tmp_path):
        """A4 纵向页（对照组）：不旋转，直接正立可读。"""
        src = copy_sample("sample_a4_portrait.pdf", str(tmp_path))
        p = Pipeline(src, str(tmp_path))
        try:
            pp = p.plan.pages[0]
            assert pp.rotation == 0
            assert pp.output_size_mm == pytest.approx((210.0, 297.0), abs=0.2)
            res = p.output()
            assert res.success
            # 正文文字直接正立可读（get_text 取到标题）
            with pymupdf.open(res.output_path) as doc:
                text = doc[0].get_text()
                assert "第1页标题" in text
        finally:
            p.close()
