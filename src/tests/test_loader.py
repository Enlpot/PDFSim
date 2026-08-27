# -*- coding: utf-8 -*-
"""loader.py 测试（依据 Stage2 提示语 5.4）。"""
import os

import pikepdf
import pytest

from pdfsim.loader import (
    PDFLoadError,
    PDFLoader,
    PDFPasswordError,
    Bookmark,
)
from pdfsim.models import A4_HEIGHT_MM, A4_WIDTH_MM, A3_HEIGHT_MM, A3_WIDTH_MM, PageMark


@pytest.fixture()
def loader():
    return PDFLoader()


# ---------------------------------------------------------------------------
# 打开 / 加密 / 损坏
# ---------------------------------------------------------------------------
class TestOpen:
    def test_open_normal(self, loader, samples_dir):
        r = loader.open(str(samples_dir / "sample_a4_portrait.pdf"))
        assert len(r.pages) == 6
        assert not r.is_encrypted
        assert r.pdf_handle is not None
        loader.close()

    def test_open_missing(self, loader):
        with pytest.raises(PDFLoadError):
            loader.open(r"D:\no_such_file_xyz.pdf")

    def test_corrupted(self, loader, samples_dir):
        """损坏 PDF → PDFLoadError。"""
        with pytest.raises(PDFLoadError):
            loader.open(str(samples_dir / "sample_corrupted.pdf"))

    def test_encrypted_detection(self, loader, samples_dir):
        """加密 PDF 正确检测。"""
        assert loader.is_encrypted(str(samples_dir / "sample_encrypted.pdf")) is True
        assert loader.is_encrypted(str(samples_dir / "sample_a4_portrait.pdf")) is False

    def test_password_correct(self, loader, samples_dir):
        assert loader.try_password(str(samples_dir / "sample_encrypted.pdf"), "testpass") is True

    def test_password_wrong(self, loader, samples_dir):
        assert loader.try_password(str(samples_dir / "sample_encrypted.pdf"), "wrongpass") is False

    def test_open_encrypted_no_password(self, loader, samples_dir):
        with pytest.raises(PDFPasswordError):
            loader.open(str(samples_dir / "sample_encrypted.pdf"))

    def test_open_encrypted_with_password(self, loader, samples_dir):
        r = loader.open(str(samples_dir / "sample_encrypted.pdf"), password="testpass")
        assert r.is_encrypted
        assert len(r.pages) == 1
        loader.close()

    def test_is_encrypted_corrupted(self, loader, samples_dir):
        """损坏文件 is_encrypted → False（PdfError 分支）。"""
        assert loader.is_encrypted(str(samples_dir / "sample_corrupted.pdf")) is False

    def test_try_password_corrupted(self, loader, samples_dir):
        """损坏文件 try_password → False。"""
        assert loader.try_password(str(samples_dir / "sample_corrupted.pdf"), "x") is False

    def test_fitz_open_failure_raises(self, loader, samples_dir, monkeypatch):
        """pikepdf 可打开但 PyMuPDF 打开失败 → PDFLoadError。"""
        import pymupdf
        real_open = pymupdf.open

        def fake_open(*a, **k):
            raise RuntimeError("fitz broken")

        monkeypatch.setattr(pymupdf, "open", fake_open)
        with pytest.raises(PDFLoadError):
            loader.open(str(samples_dir / "sample_single.pdf"))

    def test_fitz_needs_pass_no_password(self, loader, samples_dir, monkeypatch):
        """PyMuPDF needs_pass 但未提供密码 → PDFPasswordError。"""
        import pymupdf

        class FakeDoc:
            needs_pass = True
            is_encrypted = True

            def authenticate(self, pw):
                return False

            def close(self):
                pass

        monkeypatch.setattr(pymupdf, "open", lambda *a, **k: FakeDoc())
        with pytest.raises(PDFPasswordError):
            loader.open(str(samples_dir / "sample_encrypted.pdf"))

    def test_fitz_needs_pass_auth_fail(self, loader, samples_dir, monkeypatch):
        """PyMuPDF needs_pass 且密码错误 → PDFPasswordError。"""
        import pymupdf

        class FakeDoc:
            needs_pass = True
            is_encrypted = True

            def authenticate(self, pw):
                return False

            def close(self):
                pass

        monkeypatch.setattr(pymupdf, "open", lambda *a, **k: FakeDoc())
        with pytest.raises(PDFPasswordError):
            loader.open(str(samples_dir / "sample_encrypted.pdf"), password="wrong")


class TestEmptyDocument:
    def test_empty_detection(self, loader, samples_dir, tmp_path):
        """空文档 → PDFLoadError。"""
        p = tmp_path / "empty.pdf"
        with pikepdf.Pdf.new() as pdf:
            pdf.save(p)
        with pytest.raises(PDFLoadError):
            loader.open(str(p))


# ---------------------------------------------------------------------------
# 页面尺寸
# ---------------------------------------------------------------------------
class TestPageSize:
    def test_a4_portrait(self, loader, samples_dir):
        r = loader.open(str(samples_dir / "sample_single.pdf"))
        p = r.pages[0]
        assert p.width_mm == pytest.approx(A4_WIDTH_MM, abs=0.5)
        assert p.height_mm == pytest.approx(A4_HEIGHT_MM, abs=0.5)
        loader.close()

    def test_a3_portrait_and_landscape(self, loader, samples_dir):
        r = loader.open(str(samples_dir / "sample_mixed.pdf"))
        sizes = [(p.width_mm, p.height_mm) for p in r.pages]
        # 页0 A4纵向；页1 A3纵向(841.89×1190.55 pt)；页2 A3横向(1190.55×841.89)
        assert sizes[0] == pytest.approx((A4_WIDTH_MM, A4_HEIGHT_MM), abs=0.5)
        assert sizes[1] == pytest.approx((A3_WIDTH_MM, A3_HEIGHT_MM), abs=0.5)
        assert sizes[2] == pytest.approx((A3_HEIGHT_MM, A3_WIDTH_MM), abs=0.5)
        loader.close()

    def test_page_count_matches(self, loader, samples_dir):
        r = loader.open(str(samples_dir / "sample_200pages.pdf"))
        assert len(r.pages) == 200
        loader.close()


# ---------------------------------------------------------------------------
# 书签读取与关键词匹配
# ---------------------------------------------------------------------------
class TestBookmarks:
    def test_read_bookmarks(self, loader, samples_dir):
        r = loader.open(str(samples_dir / "sample_a4_portrait.pdf"))
        titles = [b.title for b in r.bookmarks]
        assert "封面" in titles
        assert "目录" in titles
        assert "正文" in titles
        assert "签字" in titles
        loader.close()

    def test_no_bookmark(self, loader, samples_dir):
        r = loader.open(str(samples_dir / "sample_no_bookmark.pdf"))
        assert r.bookmarks == []
        loader.close()

    def test_keyword_mark_cover(self, loader, samples_dir):
        """书签"封面" → COVER + FRONT（标记联动）。"""
        r = loader.open(str(samples_dir / "sample_a4_portrait.pdf"))
        cover = [p for p in r.pages if PageMark.COVER in p.marks]
        assert len(cover) == 1
        assert PageMark.FRONT in cover[0].marks

    def test_keyword_mark_signature(self, loader, samples_dir):
        r = loader.open(str(samples_dir / "sample_a4_portrait.pdf"))
        sig = [p for p in r.pages if PageMark.SIGNATURE in p.marks]
        assert len(sig) == 1
        assert PageMark.FRONT in sig[0].marks

    def test_keyword_mark_front(self, loader, samples_dir):
        """书签"目录" → FRONT（从正面开始）。"""
        r = loader.open(str(samples_dir / "sample_a4_portrait.pdf"))
        front = [p for p in r.pages if PageMark.FRONT in p.marks]
        # 封面、目录、正文、签字页都会打 FRONT
        assert len(front) >= 3

    def test_keyword_case_insensitive(self):
        l = PDFLoader()
        hits = l._match_keywords("CONTENTS Page", {
            PageMark.FRONT: ["目录", "contents"],
        })
        assert PageMark.FRONT in hits

    def test_keyword_body_front(self):
        """正文/body 关键词 → FRONT。"""
        l = PDFLoader()
        hits = l._match_keywords("正文", {
            "body": ["正文", "body"],
        })
        assert PageMark.FRONT in hits

    def test_nested_bookmarks(self, samples_dir, tmp_path):
        """嵌套书签遍历（children 递归）。"""
        import pymupdf
        path = tmp_path / "nested.pdf"
        doc = pymupdf.open()
        doc.new_page(width=595, height=842)
        doc.new_page(width=595, height=842)
        doc.set_toc([
            [1, "第1章", 1],
            [2, "第1章-1节", 2],
        ])
        doc.save(path)
        doc.close()
        loader = PDFLoader()
        r = loader.open(str(path))
        assert len(r.bookmarks) == 2
        assert r.bookmarks[1].title == "第1章-1节"
        assert r.bookmarks[1].page_index == 1
        loader.close()

    def test_read_bookmarks_exception(self, loader, samples_dir, monkeypatch):
        """open_outline 异常 → 返回空列表。"""
        import pikepdf

        def boom(*a, **k):
            raise RuntimeError("outline broken")

        monkeypatch.setattr(pikepdf.Pdf, "open_outline", boom)
        r = loader.open(str(samples_dir / "sample_a4_portrait.pdf"))
        assert r.bookmarks == []
        loader.close()

    def test_read_page_info_default_args(self, loader, samples_dir):
        """read_page_info 默认参数（不传 bookmarks/keywords）。"""
        import pikepdf
        with pikepdf.open(str(samples_dir / "sample_a4_portrait.pdf")) as pdf:
            pages = loader.read_page_info(pdf)
        assert len(pages) == 6
        # 书签命中封面 → COVER 标记
        assert any(PageMark.COVER in p.marks for p in pages)

    def test_read_page_info_no_bookmarks(self, loader, samples_dir):
        """无书签样本 → marks 全空。"""
        import pikepdf
        with pikepdf.open(str(samples_dir / "sample_no_bookmark.pdf")) as pdf:
            pages = loader.read_page_info(pdf, bookmarks=[])
        assert all(not p.marks for p in pages)


# ---------------------------------------------------------------------------
# 文本数据提取
# ---------------------------------------------------------------------------
class TestTextData:
    def test_extract_text_data(self, loader, samples_dir):
        r = loader.open(str(samples_dir / "sample_single.pdf"))
        data = loader.extract_text_data(0)
        assert "blocks" in data
        assert len(data["blocks"]) > 0
        loader.close()

    def test_extract_after_close_raises(self, loader, samples_dir):
        loader.open(str(samples_dir / "sample_single.pdf"))
        loader.close()
        with pytest.raises(PDFLoadError):
            loader.extract_text_data(0)
