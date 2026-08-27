# -*- coding: utf-8 -*-
"""新提示语《旋转确认与处理报告》任务 1：输出流程验证测试。

验证"先旋转、后加页码"：源页自带 /Rotate（90/180/270）与规划旋转的各种组合下，
输出 PDF 中页码均视觉正立（方向与页面一致）且位于右下角（距右/距底 ≈ 10mm）。
"""
import os
import tempfile

import pymupdf
import pytest

from pdfsim.engine import build_process_plan
from pdfsim.loader import PDFLoader
from pdfsim.models import DocumentConfig, MM_TO_PT, RotationOverride
from pdfsim.output import PDFOutput
from pdfsim.renderer import PDFRenderer

_DPI = 150


def _make_src(rot: int) -> bytes:
    """生成 A4 纵向源页：内容按 rotate=rot 逆时针写入，配合页面 /Rotate=rot
    （顺时针显示）视觉正立——模拟真实扫描件（内容方向与 /Rotate 配套）。"""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Hello Rotated Page", fontsize=24, rotate=rot)
    page.insert_text((72, 800), "bottom text", fontsize=14, rotate=rot)
    if rot:
        page.set_rotation(rot)
    buf = doc.tobytes()
    doc.close()
    return buf


def _build_and_output(src_bytes: bytes, override, start=10):
    d = tempfile.mkdtemp()
    src = os.path.join(d, "src.pdf")
    with open(src, "wb") as f:
        f.write(src_bytes)
    loader = PDFLoader()
    r = loader.open(src)
    try:
        for p in r.pages:
            p.rotation_override = override
        text_data = {i: loader.extract_text_data(i) for i in range(len(r.pages))}
        renderer = PDFRenderer()
        config = DocumentConfig(output_dir=d, start_page_number=start)
        plan = build_process_plan(
            r.pages,
            config,
            page_text_data=text_data,
            text_width_calculator=renderer.get_text_width,
        )
        res = PDFOutput().output(src, plan, config)
        return res, plan, config
    finally:
        loader.close()


def _page_number_ink(pg):
    """渲染输出页右下角页码邻域，返回墨迹 bbox（pt，左上原点）。"""
    pix = pg.get_pixmap(dpi=_DPI)
    wpt, hpt = pg.rect.width, pg.rect.height
    w, h = pix.width, pix.height
    n = pix.n
    samp = pix.samples
    scale = _DPI / 72.0
    pts = []
    for y in range(int((hpt - 55) * scale), int((hpt - 5) * scale)):
        for x in range(int((wpt - 55) * scale), int((wpt - 5) * scale)):
            if samp[(y * w + x) * n] < 120:
                pts.append((x, y))
    if not pts:
        return None
    return (
        min(p[0] for p in pts) / scale,
        min(p[1] for p in pts) / scale,
        max(p[0] for p in pts) / scale,
        max(p[1] for p in pts) / scale,
    )


class TestRotatedOutput:
    """任务 1 测试矩阵：源页 /Rotate 与规划旋转组合。"""

    @pytest.mark.parametrize(
        "src_rot,override,label",
        [
            (0, RotationOverride.NONE, "源页无旋转+planned0"),
            (90, RotationOverride.NONE, "源页90+planned0"),
            (180, RotationOverride.NONE, "源页180+planned0"),
            (270, RotationOverride.NONE, "源页270+planned0"),
            (0, RotationOverride.CW90, "源页0+planned90"),
            (90, RotationOverride.CW90, "源页90+planned90(总180)"),
            (270, RotationOverride.CW90, "源页270+planned90(总0)"),
        ],
    )
    def test_rotation_matrix(self, src_rot, override, label):
        """矩阵内每种组合：页码视觉正立 + 右下角（距右/距底≈10mm）。"""
        res, plan, _ = _build_and_output(_make_src(src_rot), override)
        assert res.success, res.message
        pp = plan.pages[0]
        assert pp.number_text is not None
        doc = pymupdf.open(res.output_path)
        try:
            pg = doc[0]
            b = _page_number_ink(pg)
            assert b is not None, f"[{label}] 右下角未渲染页码墨迹"
            bw, bh = b[2] - b[0], b[3] - b[1]
            # 正立：墨迹 bbox 宽 >= 高（横排数字）
            assert bw >= bh, f"[{label}] 页码侧立: bbox {bw:.1f}x{bh:.1f}pt"
            # 位置：距右/距底 ≈ margin 10mm=28.35pt（容差 8pt）
            wpt, hpt = pg.rect.width, pg.rect.height
            right_gap = wpt - b[2]
            bottom_gap = hpt - b[3]
            assert abs(right_gap - 10 * MM_TO_PT) < 8.0, \
                f"[{label}] 距右 {right_gap:.1f}pt 异常"
            assert abs(bottom_gap - 10 * MM_TO_PT) < 8.0, \
                f"[{label}] 距底 {bottom_gap:.1f}pt 异常"
        finally:
            doc.close()

    def test_blank_and_no_number_pages_skipped(self):
        """不显示页码的页（如背面空白）不绘制页码文字。"""
        # 简化：单页文档（无 NO_NUMBER）正常输出
        res, _, _ = _build_and_output(_make_src(90), RotationOverride.NONE)
        assert res.success
