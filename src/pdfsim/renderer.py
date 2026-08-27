# -*- coding: utf-8 -*-
"""渲染模块（依据 Stage2 提示语 5.6）。

本模块只读，永不保存文件：
  - 缩略图 / 全页渲染为 PNG bytes（Stage 3 UI 使用，接口预留）；
  - 文本块提取（get_text("dict")，供文字方向检测与重叠检测）；
  - 文字宽度计算（fitz.Font.text_length）。
"""
from __future__ import annotations

import os

import pymupdf

# 内置 Times 字体备用路径（get_text_width 默认字体）
_DEFAULT_FONT = r"C:\Windows\Fonts\times.ttf"


class PDFRenderer:
    # Font 对象缓存（P0-3 优化：800 页时避免每页重复创建 pymupdf.Font）
    _FONT_CACHE: dict[str, "pymupdf.Font"] = {}

    def render_thumbnail(self, page, dpi: int = 72) -> bytes:
        """渲染指定页缩略图为 PNG bytes。"""
        pix = page.get_pixmap(dpi=dpi)
        return pix.tobytes("png")

    def render_page_full(self, page, dpi: int = 150) -> bytes:
        """渲染指定页全尺寸图为 PNG bytes。"""
        pix = page.get_pixmap(dpi=dpi)
        return pix.tobytes("png")

    def extract_text_blocks(self, page) -> list[dict]:
        """提取页文本块结构（get_text("dict") 的 blocks 列表）。"""
        data = page.get_text("dict")
        return data.get("blocks", [])

    def get_text_width(
        self,
        text: str,
        fontsize: float,
        font_path: str | None = None,
    ) -> float:
        """用指定字体计算文字宽度（pt）。

        Font 对象按路径缓存复用（text_length 为只读计算，可安全复用），
        避免每次调用都创建 pymupdf.Font（P0-3 优化）。
        """
        path = font_path or _DEFAULT_FONT
        font = self._FONT_CACHE.get(path)
        if font is None:
            if os.path.exists(path):
                font = pymupdf.Font(fontfile=path)
            else:
                font = pymupdf.Font("times-roman")
            self._FONT_CACHE[path] = font
        return font.text_length(text, fontsize=fontsize)
