# -*- coding: utf-8 -*-
"""PDF 加载模块（依据《技术方案.md》第 6 章 + Stage2 提示语 5.4）。

职责：
  - 打开 PDF（pikepdf），处理加密 / 损坏 / 空文档；
  - 读取页面尺寸（含源页自带 /Rotate，显示尺寸为准，D7）；
  - 读取书签（Outline），按关键词自动识别页面标记（含标记联动：封面/签字 → +FRONT）；
  - 用 PyMuPDF 提取每页文本数据（get_text("dict")），供算法 3 文字方向检测。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import pikepdf
import pymupdf

from pdfsim.models import (
    MM_TO_PT,
    PageInfo,
    PageMark,
)

PT_TO_MM = 1.0 / MM_TO_PT


class PDFLoadError(Exception):
    """PDF 打开失败（损坏 / IO）。"""


class PDFPasswordError(Exception):
    """PDF 需要密码或密码错误。"""


@dataclass
class Bookmark:
    title: str
    page_index: int  # 0-based（PDF 内部 page 编号）


@dataclass
class LoadResult:
    pages: list[PageInfo]
    bookmarks: list[Bookmark]
    is_encrypted: bool
    pdf_handle: pikepdf.Pdf
    path: str = ""
    text_data: dict[int, dict] = field(default_factory=dict)  # 已提取的文本数据缓存


class PDFLoader:
    """PDF 加载器。open 成功后内部持有 pikepdf 与 PyMuPDF 双只读句柄。"""

    def __init__(self) -> None:
        self._fitz_doc: pymupdf.Document | None = None

    # -- 打开 / 加密 / 损坏 -------------------------------------------------
    def is_encrypted(self, path: str) -> bool:
        """仅检测是否加密（尝试无密打开）。"""
        try:
            with pikepdf.open(path) as pdf:
                return bool(pdf.is_encrypted)
        except pikepdf.PasswordError:
            return True
        except (pikepdf.PdfError, OSError):
            return False

    def try_password(self, path: str, password: str) -> bool:
        """尝试用密码打开，成功返回 True。"""
        try:
            with pikepdf.open(path, password=password) as pdf:
                return len(pdf.pages) > 0
        except pikepdf.PasswordError:
            return False
        except (pikepdf.PdfError, OSError):
            return False

    def open(self, path: str, password: str = "") -> LoadResult:
        """打开 PDF，返回 LoadResult。

        抛 PDFPasswordError（需密码 / 密码错误）、PDFLoadError（损坏 / IO）。
        """
        if not os.path.exists(path):
            raise PDFLoadError(f"文件不存在: {path}")
        try:
            pdf = pikepdf.open(path, password=password)
        except pikepdf.PasswordError as e:
            raise PDFPasswordError(f"需要密码或密码错误: {path}") from e
        except (pikepdf.PdfError, OSError) as e:
            raise PDFLoadError(f"PDF 文件损坏或无法解析: {path}") from e

        if len(pdf.pages) == 0:
            pdf.close()
            raise PDFLoadError(f"PDF 文档无页面: {path}")

        # PyMuPDF 只读句柄（加密文件用 authenticate 解密）
        try:
            self._fitz_doc = pymupdf.open(path)
            if self._fitz_doc.needs_pass:
                if not password:
                    pdf.close()
                    self._fitz_doc = None
                    raise PDFPasswordError(f"需要密码或密码错误: {path}")
                if not self._fitz_doc.authenticate(password):
                    pdf.close()
                    self._fitz_doc = None
                    raise PDFPasswordError(f"需要密码或密码错误: {path}")
        except PDFPasswordError:
            raise
        except Exception as e:  # 渲染可用性校验失败 → 按损坏处理
            pdf.close()
            self._fitz_doc = None
            raise PDFLoadError(f"PDF 渲染校验失败: {path}") from e

        bookmarks = self.read_bookmarks(pdf)
        pages = self.read_page_info(pdf, bookmarks=bookmarks)
        return LoadResult(
            pages=pages,
            bookmarks=bookmarks,
            is_encrypted=bool(pdf.is_encrypted),
            pdf_handle=pdf,
            path=path,
        )

    def close(self) -> None:
        if self._fitz_doc is not None:
            self._fitz_doc.close()
            self._fitz_doc = None

    # -- 页面信息 -----------------------------------------------------------
    def _page_display_size_pt(self, page: pikepdf.Page) -> tuple[float, float]:
        """读取 MediaBox 并叠加 /Rotate，得到显示尺寸（宽, 高, pt）。

        D7：以显示尺寸判定 A4/A3 与方向。
        """
        mb = page.MediaBox
        w = float(mb[2]) - float(mb[0])
        h = float(mb[3]) - float(mb[1])
        rot = int(page.rotation or 0) % 360
        if rot in (90, 270):
            w, h = h, w
        return w, h

    def read_bookmarks(self, pdf: pikepdf.Pdf) -> list[Bookmark]:
        """读取 PDF Outline（书签）为扁平列表。"""
        out: list[Bookmark] = []

        def _dest_page(obj) -> int | None:
            """从 outline item 的 obj 提取目标页 0-based 编号。"""
            try:
                if "/Dest" in obj:
                    d = obj["/Dest"]
                    if isinstance(d, pikepdf.Array) and len(d) > 0:
                        return pdf.pages.index(d[0])
                if "/A" in obj:
                    a = obj["/A"]
                    if a.get("/S", "") == "/GoTo" and "/D" in a:
                        d = a["/D"]
                        if isinstance(d, pikepdf.Array) and len(d) > 0:
                            return pdf.pages.index(d[0])
            except Exception:
                return None
            return None

        def walk(items, level=0):
            for it in items:
                title = str(it.title)
                page_index = _dest_page(it.obj)
                out.append(Bookmark(title=title, page_index=page_index or 0))
                if it.children:
                    walk(it.children, level + 1)

        try:
            outline = pdf.open_outline()
            if outline is not None:
                walk(outline.root)
        except Exception:
            return out
        return out

    def _match_keywords(
        self, title: str, keywords: dict
    ) -> list[PageMark]:
        """按关键词匹配书名标题，返回命中的标记（含标记联动）。"""
        hits: set[PageMark] = set()
        title_l = title.lower()
        for mark, words in keywords.items():
            if mark == "body":  # 正文起始页 → FRONT
                if any(w.lower() in title_l for w in words):
                    hits.add(PageMark.FRONT)
                continue
            m = PageMark(mark)
            if any(w.lower() in title_l for w in words):
                hits.add(m)
                if m in (PageMark.COVER, PageMark.SIGNATURE):
                    hits.add(PageMark.FRONT)  # 标记联动（问题 1 修改）
        return list(hits)

    def read_page_info(
        self,
        pdf: pikepdf.Pdf,
        bookmarks: list[Bookmark] | None = None,
        keywords: dict | None = None,
    ) -> list[PageInfo]:
        """读取全部页面信息并应用书签关键词自动标记。"""
        from pdfsim.models import DocumentConfig

        if keywords is None:
            keywords = DocumentConfig().auto_detect_keywords
        if bookmarks is None:
            bookmarks = self.read_bookmarks(pdf)

        # 按 0-based 页索引聚合书签命中的标记
        mark_by_page: dict[int, set[PageMark]] = {}
        for bm in bookmarks:
            hits = self._match_keywords(bm.title, keywords)
            if hits:
                mark_by_page.setdefault(bm.page_index, set()).update(hits)

        pages: list[PageInfo] = []
        for i, page in enumerate(pdf.pages):
            w_pt, h_pt = self._page_display_size_pt(page)
            rot = int(page.rotation or 0) % 360
            pages.append(
                PageInfo(
                    original_index=i,
                    width_mm=w_pt * PT_TO_MM,
                    height_mm=h_pt * PT_TO_MM,
                    source_rotation=rot,  # 源页自带 /Rotate（页码坐标总旋转校正用）
                    marks=set(mark_by_page.get(i, set())),
                )
            )
        return pages

    # -- 文本数据 -----------------------------------------------------------
    def extract_text_data(self, page_index: int) -> dict:
        """提取指定页 get_text("dict")（供算法 3 文字方向检测）。"""
        if self._fitz_doc is None:
            raise PDFLoadError("尚未打开 PDF 或句柄已释放")
        page = self._fitz_doc[page_index]
        return page.get_text("dict")
