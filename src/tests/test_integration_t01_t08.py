# -*- coding: utf-8 -*-
"""Stage 4 集成测试：T01–T08 端到端（标准场景 + 边界）。

对应《测试矩阵.md》T01–T08。只新增测试，不修改 Stage 2/3 代码。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # 供导入 _stage4_helpers

import pikepdf
import pymupdf
import pytest

from pdfsim.loader import PDFLoader, PDFLoadError, PDFPasswordError
from pdfsim.models import (
    A3_HEIGHT_MM,
    A3_WIDTH_MM,
    A4_HEIGHT_MM,
    A4_WIDTH_MM,
    BlankPageSource,
    PageMark,
    PageNumberPos,
    RotationOverride,
)

from _stage4_helpers import (
    Pipeline,
    assert_physical_table,
    blank,
    copy_sample,
    original,
    sha256,
)


class TestT01_BookmarkA4:
    """T01：标准 A4 纵向多页含书签（封面/目录/正文/签字）。"""

    def test_auto_detect_and_plan(self, samples_dir, tmp_path):
        src = copy_sample("sample_a4_portrait.pdf", str(tmp_path))
        p = Pipeline(src, str(tmp_path))
        try:
            p.config.auto_number_blank_pages = True  # 保留 PUSH_FRONT 编页码行为
            p.rebuild()
            # 自动识别：书签 → 标记
            pages = p.result.pages
            assert PageMark.COVER in pages[0].marks
            assert PageMark.FRONT in pages[0].marks
            assert PageMark.FRONT in pages[1].marks        # 目录起始 → FRONT
            assert PageMark.FRONT in pages[2].marks        # 正文起始 → FRONT
            assert PageMark.SIGNATURE in pages[4].marks
            assert PageMark.FRONT in pages[4].marks        # 签字 → 联动 FRONT

            expected = [
                original(1, PageNumberPos.BOTTOM_RIGHT, 0, True),
                blank("cover_back", "2", True, PageNumberPos.BOTTOM_LEFT),
                original(3, PageNumberPos.BOTTOM_RIGHT, 0, True),
                blank("push_front", "4", True, PageNumberPos.BOTTOM_LEFT),
                original(5, PageNumberPos.BOTTOM_RIGHT, 0, True),
                original(6, PageNumberPos.BOTTOM_LEFT, 0, True),
                original(7, PageNumberPos.BOTTOM_RIGHT, 0, True),
                blank("sign_back", None, False, PageNumberPos.BOTTOM_RIGHT),
                original(8, PageNumberPos.BOTTOM_RIGHT, 0, True),
            ]
            for i, row in enumerate(expected, start=1):
                row["phys"] = i
                if not row["blank"]:
                    row["src_index"] = i - 1 if i <= 9 else None
            # 修正 src_index（按物理顺序对应源页）
            src_idx = [0, None, 1, None, 2, 3, 4, None, 5]
            for i, row in enumerate(expected):
                row["src_index"] = src_idx[i]
            assert_physical_table(p.plan, expected)
        finally:
            p.close()

    def test_output_and_integrity(self, samples_dir, tmp_path):
        src = copy_sample("sample_a4_portrait.pdf", str(tmp_path))
        before = sha256(src)
        p = Pipeline(src, str(tmp_path))
        try:
            res = p.output()
            assert res.success
            assert res.page_count == len(p.plan.pages) == 9
            assert res.source_hash_verified
            # 输出可打开、页码为文字
            with pymupdf.open(res.output_path) as doc:
                assert doc.page_count == 9
                text = doc[0].get_text()
                assert "1" in text
            assert sha256(src) == before  # 原文件字节级未变
        finally:
            p.close()


class TestT02_NoBookmark:
    """T02：无书签文档。"""

    def test_no_auto_mark(self, samples_dir, tmp_path):
        src = copy_sample("sample_no_bookmark.pdf", str(tmp_path))
        p = Pipeline(src, str(tmp_path))
        try:
            for pg in p.result.pages:
                assert not pg.marks  # 无书签 → 无自动标记
            assert len(p.plan.pages) == 4
            # 手工标记生效：加封面 → 插封背空白
            p.result.pages[0].marks.add(PageMark.COVER)
            p.result.pages[0].marks.add(PageMark.FRONT)
            p.rebuild()
            bs = [pp.blank_source.value if pp.blank_source else None
                  for pp in p.plan.pages]
            assert bs == [None, "cover_back", None, None, None]
            res = p.output()
            assert res.success and res.page_count == 5
        finally:
            p.close()


class TestT03_A3PortraitMix:
    """T03：含 A3 纵向页的混合文档。"""

    def test_a3_portrait_rotation_and_back(self, samples_dir, tmp_path):
        src = copy_sample("sample_a3_portrait.pdf", str(tmp_path))
        p = Pipeline(src, str(tmp_path))
        try:
            # 样本文字水平 → AUTO 检测为 0，显式强制旋转以验证 A3 旋转+背面
            p.result.pages[1].rotation_override = RotationOverride.CW90
            p.rebuild()
            # 找到 A3 纵向源页（idx1）
            a3_pp = [pp for pp in p.plan.pages
                     if pp.source_page_info.original_index == 1]
            assert len(a3_pp) == 1
            pp = a3_pp[0]
            assert pp.is_blank is False
            assert pp.rotation == 90                       # 显式强制旋转 → 90
            assert pp.output_size_mm == pytest.approx(
                (A3_HEIGHT_MM, A3_WIDTH_MM), abs=0.2)     # 420×297 横向
            assert pp.number_position == PageNumberPos.BOTTOM_RIGHT
            # A3 在奇数位（正面）
            assert pp.physical_index % 2 == 1
            # 其背面为 A3_BACK 空白
            back = p.plan.pages[pp.physical_index]        # 0-based 下一个
            assert back.is_blank and back.blank_source is BlankPageSource.A3_BACK
            assert back.number_text is None and not back.number_occupies
            res = p.output()
            assert res.success
        finally:
            p.close()


class TestT04_A3LandscapeMix:
    """T04：含 A3 横向页的混合文档（不旋转）。"""

    def test_a3_landscape_no_rotation(self, samples_dir, tmp_path):
        src = copy_sample("sample_a3_landscape.pdf", str(tmp_path))
        p = Pipeline(src, str(tmp_path))
        try:
            a3_pp = [pp for pp in p.plan.pages
                     if pp.source_page_info.original_index == 1]
            assert len(a3_pp) == 1
            pp = a3_pp[0]
            assert pp.rotation == 0
            assert pp.output_size_mm == pytest.approx(
                (A3_HEIGHT_MM, A3_WIDTH_MM), abs=0.2)     # 420×297 保持横向
            assert pp.physical_index % 2 == 1
            back = p.plan.pages[pp.physical_index]
            assert back.is_blank and back.blank_source is BlankPageSource.A3_BACK
            res = p.output()
            assert res.success
        finally:
            p.close()


class TestT05_Single:
    """T05：单页文档。"""

    def test_single_page(self, samples_dir, tmp_path):
        src = copy_sample("sample_single.pdf", str(tmp_path))
        p = Pipeline(src, str(tmp_path))
        try:
            assert len(p.plan.pages) == 1
            pp = p.plan.pages[0]
            assert pp.number_text == "1"
            assert pp.number_position == PageNumberPos.BOTTOM_RIGHT
            res = p.output()
            assert res.success and res.page_count == 1
        finally:
            p.close()


class TestT06_OddLast:
    """T06：末页奇数（3 页）。"""

    def test_default_no_fill(self, samples_dir, tmp_path):
        src = copy_sample("sample_odd_last.pdf", str(tmp_path))
        p = Pipeline(src, str(tmp_path))
        try:
            assert len(p.plan.pages) == 3
            assert [pp.number_text for pp in p.plan.pages] == ["1", "2", "3"]
            res = p.output()
            assert res.success and res.page_count == 3
        finally:
            p.close()

    def test_auto_fill_last(self, samples_dir, tmp_path):
        src = copy_sample("sample_odd_last.pdf", str(tmp_path))
        p = Pipeline(src, str(tmp_path))
        try:
            p.config.auto_fill_last_page = True
            p.config.auto_number_blank_pages = True  # 保留 FILL_LAST 编页码行为
            p.rebuild()
            assert len(p.plan.pages) == 4
            last = p.plan.pages[-1]
            assert last.is_blank
            assert last.blank_source is BlankPageSource.FILL_LAST
            assert last.number_text == "4"
            assert last.number_occupies
            res = p.output()
            assert res.success and res.page_count == 4
        finally:
            p.close()


class TestT07_Encrypted:
    """T07：加密 PDF 全流程。"""

    def test_password_flow_and_output(self, samples_dir, tmp_path):
        src = copy_sample("sample_encrypted.pdf", str(tmp_path))
        before = sha256(src)
        loader = PDFLoader()
        # 无密码 → 需密码
        with pytest.raises(PDFPasswordError):
            loader.open(src, "")
        # 错误密码 → 仍失败
        with pytest.raises(PDFPasswordError):
            loader.open(src, "wrong")
        # 正确密码 → 打开
        assert loader.try_password(src, "testpass")
        res = loader.open(src, "testpass")
        assert res.is_encrypted
        assert len(res.pages) == 1
        loader.close()
        # 全流程：打开（带密码）→ 规划 → 输出
        p = Pipeline(src, str(tmp_path), password="testpass")
        try:
            out = p.output()
            assert out.success
            # 输出为未加密新文件
            with pikepdf.open(out.output_path) as pdf:
                assert not pdf.is_encrypted
            assert sha256(src) == before  # 原文件不变
        finally:
            p.close()


class TestT08_Corrupted:
    """T08：损坏 PDF。"""

    def test_corrupted_raises(self, samples_dir, tmp_path):
        src = copy_sample("sample_corrupted.pdf", str(tmp_path))
        loader = PDFLoader()
        with pytest.raises(PDFLoadError):
            loader.open(src, "")
        loader.close()
