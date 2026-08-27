# -*- coding: utf-8 -*-
"""renderer.py 测试（依据 Stage2 提示语 5.6）。"""
import pymupdf
import pytest

from pdfsim.renderer import PDFRenderer


@pytest.fixture()
def renderer():
    return PDFRenderer()


@pytest.fixture(scope="module")
def doc():
    d = pymupdf.open()
    page = d.new_page(width=595.28, height=841.89)
    page.insert_text((72, 100), "Hello World", fontsize=24)
    page.insert_text((72, 150), "第二行文字", fontsize=18, fontname="china-s")
    return d


class TestRenderer:
    def test_thumbnail_png(self, renderer, doc):
        data = renderer.render_thumbnail(doc[0], dpi=72)
        assert isinstance(data, bytes)
        assert data[:8] == b"\x89PNG\r\n\x1a\n"  # PNG 魔数

    def test_full_png(self, renderer, doc):
        data = renderer.render_page_full(doc[0], dpi=150)
        assert isinstance(data, bytes)
        assert data[:8] == b"\x89PNG\r\n\x1a\n"

    def test_extract_text_blocks(self, renderer, doc):
        blocks = renderer.extract_text_blocks(doc[0])
        assert isinstance(blocks, list)
        assert len(blocks) > 0
        texts = " ".join(
            span["text"]
            for b in blocks
            if b.get("type") == 0
            for line in b.get("lines", [])
            for span in line.get("spans", [])
        )
        assert "Hello World" in texts
        assert "第二行文字" in texts

    def test_get_text_width(self, renderer):
        w = renderer.get_text_width("1234", 9.0)
        assert w > 0
        # 宽度随字号线性增长
        w2 = renderer.get_text_width("1234", 18.0)
        assert w2 == pytest.approx(w * 2, rel=0.1)

    def test_get_text_width_fallback_font(self, renderer):
        # 不存在的字体路径 → 回退内置字体
        w = renderer.get_text_width("abc", 10.0, font_path=r"D:\no\such.ttf")
        assert w > 0
