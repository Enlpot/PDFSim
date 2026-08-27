# -*- coding: utf-8 -*-
"""PDF 输出模块（依据《技术方案.md》5.1 协作流程 + Stage2 提示语 5.5）。

流程：
  1. 结构阶段（pikepdf）：按 ProcessPlan 重组页面（复制原页 / 插空白 / 旋转），存内存字节流；
  2. 内容阶段（PyMuPDF）：用 insert_text 以内容流文字绘制页码（坐标来自算法 4），字体嵌入；
  3. 校验：输出后重开确认页数一致；原文件 SHA-256 前后对比（未修改）。

输出规则：输出到原文件夹，文件名 `原文件名（打印装订）.pdf`；已存在则跳过不覆盖。
"""
from __future__ import annotations

import hashlib
import io
import os
from dataclasses import dataclass, field

import pikepdf
import pymupdf

from pdfsim.models import (
    MM_TO_PT,
    DocumentConfig,
    ProcessPlan,
)

_DEFAULT_FONT = r"C:\Windows\Fonts\times.ttf"
_FONTNAME_EMBED = "F0"      # 嵌入字体名（非保留名）
_FONTNAME_BASE14 = "tiro"   # 回退 Base-14 Times-Roman


@dataclass
class OutputResult:
    success: bool
    output_path: str
    message: str
    page_count: int = 0
    source_hash_verified: bool = False


class PDFOutput:
    def __init__(self, font_path: str = _DEFAULT_FONT) -> None:
        self.font_path = font_path

    # -- 输出路径 -----------------------------------------------------------
    def _output_path(self, source_pdf_path: str, config: DocumentConfig) -> str:
        base = os.path.basename(source_pdf_path)
        stem, ext = os.path.splitext(base)
        fname = f"{stem}{config.output_suffix}{ext}"
        out_dir = config.output_dir or os.path.dirname(os.path.abspath(source_pdf_path))
        return os.path.join(out_dir, fname)

    # -- 主入口 -------------------------------------------------------------
    def output(
        self,
        source_pdf_path: str,
        plan: ProcessPlan,
        config: DocumentConfig,
        font_path: str | None = None,
    ) -> OutputResult:
        font_path = font_path or self.font_path
        out_path = self._output_path(source_pdf_path, config)

        if os.path.exists(out_path):
            return OutputResult(
                success=False,
                output_path=out_path,
                message=f"输出文件已存在，跳过不覆盖: {os.path.basename(out_path)}",
            )

        src_hash_before = self._sha256(source_pdf_path)

        # 1. 结构阶段（pikepdf）
        bytes_pdf = self._build_structure(source_pdf_path, plan)

        # 2. 内容阶段（PyMuPDF 绘制页码）
        self._draw_page_numbers(bytes_pdf, plan, config, out_path, font_path)

        # 3. 校验
        page_count = self._verify_output(out_path, len(plan.pages))
        src_hash_after = self._sha256(source_pdf_path)
        hash_ok = src_hash_before == src_hash_after

        if page_count != len(plan.pages):
            return OutputResult(
                success=False,
                output_path=out_path,
                message=f"输出页数校验失败: 期望 {len(plan.pages)}，实际 {page_count}",
                page_count=page_count,
                source_hash_verified=hash_ok,
            )
        return OutputResult(
            success=True,
            output_path=out_path,
            message=f"已输出: {os.path.basename(out_path)}",
            page_count=page_count,
            source_hash_verified=hash_ok,
        )

    # -- 结构阶段 -----------------------------------------------------------
    def _build_structure(self, source_pdf_path: str, plan: ProcessPlan) -> bytes:
        src = pikepdf.open(source_pdf_path)
        dst = pikepdf.Pdf.new()
        try:
            for pp in plan.pages:
                if pp.is_blank:
                    # 空白页 MediaBox = 原始尺寸（与同纸正面页一致，不随旋转交换）；
                    # 方向由下方旋转阶段加 /Rotate 实现（Bug 修复：空白页方向与正面一致）
                    w_pt = pp.source_page_info.width_mm * MM_TO_PT
                    h_pt = pp.source_page_info.height_mm * MM_TO_PT
                    dst.add_blank_page(page_size=(w_pt, h_pt))
                else:
                    idx = pp.source_page_info.original_index
                    dst.pages.append(src.pages[idx])

            # 旋转（含空白页：继承同纸正面方向，与正面 MediaBox 相同 + 相同 /Rotate）
            for pp in plan.pages:
                if not pp.rotation:
                    continue
                dst.pages[pp.physical_index - 1].rotate(pp.rotation, relative=True)

            buf = io.BytesIO()
            dst.save(buf)
            return buf.getvalue()
        finally:
            dst.close()
            src.close()

    # -- 内容阶段 -----------------------------------------------------------
    def _setup_font(self, page, style, font_path: str) -> tuple[str, tuple]:
        """注册页码字体，返回 (fontname, color(0-1))。"""
        color = tuple(c / 255.0 for c in style.color)
        if os.path.exists(font_path):
            page.insert_font(fontname=_FONTNAME_EMBED, fontfile=font_path)
            return _FONTNAME_EMBED, color
        return _FONTNAME_BASE14, color

    def _draw_page_numbers(
        self,
        bytes_pdf: bytes,
        plan: ProcessPlan,
        config: DocumentConfig,
        out_path: str,
        font_path: str,
    ) -> None:
        out = pymupdf.open(stream=bytes_pdf, filetype="pdf")
        try:
            for pp in plan.pages:
                if pp.number_text is None or pp.number_point is None:
                    continue
                page = out[pp.physical_index - 1]
                style = pp.source_page_info.style_override or config.global_style
                fontname, color = self._setup_font(page, style, font_path)
                x, y = pp.number_point
                # insert_text 使用 MediaBox（未旋转）坐标；page.rect 是 /Rotate 旋转后的
                # 显示矩形（旋转页宽高已交换），因此必须用 page.mediabox 的宽高。
                mb = page.mediabox
                # 坐标语义：number_point 由算法 4 计算，已按"总旋转角"
                # （源页自带 /Rotate + 规划旋转）derotate 到 MediaBox 未旋转坐标系，
                # 即 PDF 规范坐标系（原点左下、y 向上）。此处仅需把 y 翻转为
                # PyMuPDF insert_text 的左上原点（y 向下），否则距下 10mm 的页码
                # 会视觉上翻转到页面顶部。
                y_insert = mb.height - y
                # 页码文字方向：页面总 /Rotate 会把内容平面的文字一起旋转显示。
                # 为保证输出后页码视觉正立（阅读方向与页面一致），内容平面的页码
                # 文字需按总 /Rotate 反向旋转写入（insert_text rotate 为逆时针）。
                rot_total = int(page.rotation or 0) % 360
                if rot_total in (90, 180, 270):
                    page.insert_text(
                        (x, y_insert),
                        pp.number_text,
                        fontname=fontname,
                        fontsize=style.fontsize_pt,
                        color=color,
                        rotate=rot_total,
                    )
                else:
                    page.insert_text(
                        (x, y_insert),
                        pp.number_text,
                        fontname=fontname,
                        fontsize=style.fontsize_pt,
                        color=color,
                    )
            out.save(out_path)
        finally:
            out.close()

    # -- 校验 ---------------------------------------------------------------
    def _verify_output(self, out_path: str, expected: int) -> int:
        doc = pymupdf.open(out_path)
        try:
            return doc.page_count
        finally:
            doc.close()

    @staticmethod
    def _sha256(path: str) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
