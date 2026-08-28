# -*- coding: utf-8 -*-
"""PDF 输出模块（依据《技术方案.md》5.1 协作流程 + Stage2 提示语 5.5）。

流程：
  1. 结构阶段（pikepdf）：按 ProcessPlan 重组页面（复制原页 / 插空白 / 旋转），
     保存到**临时文件**（大 PDF 修复方案 A：BytesIO 整包序列化导致内存峰值
     ~400-600MB，改为磁盘中转，两库不再同时持有完整 PDF）；
  2. 内容阶段（PyMuPDF）：用 insert_text 以内容流文字绘制页码（坐标来自算法 4），
     字体嵌入；out.save(garbage=4, deflate=True) 压缩 + GC 减小体积；
  3. 校验：输出后重开确认页数一致；原文件 SHA-256 前后对比（未修改）。

输出规则：输出到原文件夹，文件名 `原文件名（打印装订）.pdf`；已存在则跳过不覆盖。
"""
from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass, field

import pikepdf
import pymupdf

from pdfsim.models import (
    MM_TO_PT,
    DocumentConfig,
    ProcessPlan,
)

_DEFAULT_FONT = r"C:\Windows\Fonts\times.ttf"
# 嵌入字体名：必须避开源 PDF 页面已有的字体名（通常为 F0-Fn）。
# Bug 修复：原硬编码 "F0" 与源 PDF 内 62 页自带的 /F0 字体冲突，
# PyMuPDF insert_font 检测到页面已有同名 F0 时走复用分支 get_char_widths，
# 但该 F0 继承自源 PDF、无 FontFile 流，导致 'NoneType' object has no attribute 'm_internal'。
# "PDFSimFont" 不匹配 F\d+ 模式，源 PDF 不可能存在，永远走"新建嵌入"分支。
_FONTNAME_EMBED = "PDFSimFont"
_FONTNAME_BASE14 = "times-roman"  # 回退 Base-14 Times-Roman（标准名）


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
        progress_cb: callable = None,  # noqa: F821  # 可选进度回调 (pct, step_text)
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
        out_dir = config.output_dir or os.path.dirname(os.path.abspath(source_pdf_path))
        tmp_path: str | None = None

        if progress_cb:
            progress_cb(10, "构建页面结构…")
        try:
            # 1. 结构阶段（pikepdf）→ 临时文件（不再整包进内存）
            tmp_path = self._build_structure(source_pdf_path, plan, out_dir)
            if progress_cb:
                progress_cb(50, "绘制页码…")
            # 2. 内容阶段（PyMuPDF 绘制页码）
            self._draw_page_numbers(tmp_path, plan, config, out_path, font_path)
        finally:
            # 无论成功/异常都清理临时文件（异常时 _draw_page_numbers 内已关闭 out）
            if tmp_path is not None and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

        if progress_cb:
            progress_cb(90, "校验输出…")
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
    def _build_structure(
        self, source_pdf_path: str, plan: ProcessPlan, out_dir: str
    ) -> str:
        """结构阶段：pikepdf 重组页面，保存到临时文件（不再用 BytesIO）。

        返回临时文件路径，调用方（output() 的 finally）负责清理。
        临时文件放 out_dir（输出目录）内，确保同盘避免跨盘拷贝。
        大 PDF 修复方案 A：dst.save 直接落盘，避免整个 PDF 序列化到内存。
        """
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

            fd, tmp_path = tempfile.mkstemp(suffix=".pdf", dir=out_dir or ".")
            os.close(fd)
            dst.save(tmp_path)
            return tmp_path
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
        tmp_path: str,
        plan: ProcessPlan,
        config: DocumentConfig,
        out_path: str,
        font_path: str,
    ) -> None:
        out = pymupdf.open(tmp_path)  # 从文件打开（不再 open(stream=bytes)）
        try:
            for pp in plan.pages:
                if pp.number_text is None or pp.number_point is None:
                    continue
                page = out[pp.physical_index - 1]
                # 有效样式优先：重叠自动调整后的副本 > 单页覆盖 > 全局
                style = (
                    pp.effective_style
                    or pp.source_page_info.style_override
                    or config.global_style
                )
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
            # 大 PDF 修复方案 A：压缩 + GC 减小输出体积（不改变页面内容）
            out.save(out_path, garbage=4, deflate=True)
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
