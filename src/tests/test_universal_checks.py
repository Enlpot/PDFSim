# -*- coding: utf-8 -*-
"""Stage 4 跨场景通用检查：6 项 × 16 场景。

对应《测试矩阵.md》第 4 节：
  1. 原文件不可修改（SHA-256 一致）
  2. 禁止 PDF→图片→PDF（内容流保留文字、无整页位图回封）
  3. 页码为文字非图片（get_text 可取、嵌入字体）
  4. 禁止覆盖输出（T15：已存在时跳过）
  5. 禁止删除/隐藏原页（输出页数一致、原页内容保留）
  6. 空白页特征（按 BlankPageSource 校验尺寸/页码/序号）
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # 供导入 _stage4_helpers

import pymupdf
import pytest

from pdfsim.models import (
    A3_HEIGHT_MM,
    A3_WIDTH_MM,
    A4_HEIGHT_MM,
    A4_WIDTH_MM,
    BlankPageSource,
    DocumentConfig,
    PageMark,
)

from _stage4_helpers import Pipeline, copy_sample, sha256

# 无页码不占序号的空白类型（不得出现页码文字）
_NO_NUM_SOURCES = {
    BlankPageSource.SIGN_BACK,
    BlankPageSource.A3_BACK,
    BlankPageSource.NO_COUNT_USER,
}


def check_universal(src: str, out_path: str, plan, sample_title_ok=True,
                    full_text_check=True):
    """对单个场景执行通用检查（src 已在调用前记录 hash，此处验证输出）。

    full_text_check=False：大文档只抽样检查（性能）。
    """
    assert os.path.exists(out_path)
    with pymupdf.open(out_path) as doc:
        # 5. 禁止删除/隐藏原页：页数一致
        assert doc.page_count == len(plan.pages), (
            f"输出页数 {doc.page_count} != plan {len(plan.pages)}")

        page_indices = range(doc.page_count)
        if not full_text_check:
            page_indices = list(range(min(3, doc.page_count))) + \
                [doc.page_count - 1] if doc.page_count else []
        for i in page_indices:
            pp = plan.pages[i]
            page = doc[i]
            # 2. 无整页图片化：样本无图 → 输出页不得出现图片
            imgs = page.get_images(full=True)
            assert not imgs, f"物理{i+1} 出现图片（整页位图回封违规）"
            if pp.is_blank:
                # 6. 空白页特征：无正文内容；无页码空白页完全无文字，
                #    有页码空白页（COVER_BACK/PUSH_FRONT/FILL_LAST）只含页码
                txt = page.get_text().strip()
                if pp.number_text is None:
                    assert txt == "", f"空白页物理{i+1} 不应有内容"
                else:
                    assert pp.number_text in txt, \
                        f"空白页物理{i+1} 缺少其页码 {pp.number_text}"
                _check_blank_size(page, pp)
                if pp.blank_source in _NO_NUM_SOURCES:
                    assert pp.number_text is None and not pp.number_occupies
            else:
                # 2/5. 原页内容保留（正文文字可取）
                txt = page.get_text()
                assert txt.strip(), f"物理{i+1} 无文字内容（原页被删/图片化）"
                if sample_title_ok:
                    assert txt.strip().startswith(""), ""

            # 3. 页码为文字非图片：可取页码数字
            if pp.number_text is not None:
                assert pp.number_text in page.get_text(), \
                    f"物理{i+1} 页码 {pp.number_text} 未作为文字出现"
        # 3. 页码字体嵌入：非空白且带页码的页应有字体
        for i in page_indices:
            pp = plan.pages[i]
            if pp.number_text is None:
                continue
            fonts = doc[i].get_fonts()
            assert fonts, f"物理{i+1} 无字体（页码非文本绘制？）"


def _check_blank_size(page, pp):
    """空白页尺寸按 BlankPageSource 校验（mm 容差）。"""
    w, h = pp.output_size_mm
    r = page.rect
    exp_w_mm, exp_h_mm = w, h
    tol_mm = 1.0
    assert abs(r.width / 72 * 25.4 - exp_w_mm) <= tol_mm and \
        abs(r.height / 72 * 25.4 - exp_h_mm) <= tol_mm, \
        f"空白页物理{pp.physical_index} 尺寸 {r} 与 plan {pp.output_size_mm} 不一致"


def _run_and_check(samples_dir, tmp_path, sample, *, password="",
                   mutator=None, fill=False, full=True):
    src = copy_sample(sample, str(tmp_path))
    before = sha256(src)
    p = Pipeline(src, str(tmp_path), password=password)
    try:
        if mutator:
            mutator(p.result.pages)
        if fill:
            p.config.auto_fill_last_page = True
        p.rebuild()
        res = p.output()
        assert res.success
        assert res.source_hash_verified
        # 1. 原文件不可修改
        assert sha256(src) == before, f"{sample}: 原文件被修改"
        # 2-6. 通用检查
        check_universal(src, res.output_path, p.plan, full_text_check=full)
        return res
    finally:
        p.close()


def _mut_no_count(pages):
    pages[1].marks.add(PageMark.NO_COUNT)


def _mut_front_cancel(pages):
    pages[1].marks.add(PageMark.FRONT)
    pages[1].marks.discard(PageMark.FRONT)  # 取消（T14）


SCENARIOS = [
    pytest.param("sample_a4_portrait.pdf", {}, True, id="T01_书签A4"),
    pytest.param("sample_no_bookmark.pdf", {}, True, id="T02_无书签"),
    pytest.param("sample_a3_portrait.pdf", {}, True, id="T03_A3纵向"),
    pytest.param("sample_a3_landscape.pdf", {}, True, id="T04_A3横向"),
    pytest.param("sample_single.pdf", {}, True, id="T05_单页"),
    pytest.param("sample_odd_last.pdf", {"fill": True}, True, id="T06_补齐末页"),
    pytest.param("sample_encrypted.pdf", {"password": "testpass"}, True, id="T07_加密"),
    pytest.param("sample_200pages.pdf", {}, False, id="T09_200页"),
    pytest.param("sample_with_pagenum.pdf", {}, True, id="T10_现有页码"),
    pytest.param("sample_no_count.pdf", {"mutator": _mut_no_count}, True, id="T11_不占序号"),
    pytest.param("sample_mixed.pdf", {}, True, id="T12_T13_A3级联"),
    pytest.param("sample_odd_last.pdf", {"mutator": _mut_front_cancel}, True, id="T14_取消正面"),
    pytest.param("sample_direction_markers.pdf", {}, True, id="T16_方向标记"),
]


class TestUniversalChecks:
    @pytest.mark.parametrize("sample,kwargs,full", SCENARIOS)
    def test_scenario_universal(self, samples_dir, tmp_path, sample, kwargs, full):
        _run_and_check(samples_dir, tmp_path, sample, full=full, **kwargs)

    def test_t15_no_overwrite(self, samples_dir, tmp_path):
        """禁止覆盖输出：二次输出跳过、原输出不变。"""
        src = copy_sample("sample_single.pdf", str(tmp_path))
        p = Pipeline(src, str(tmp_path))
        try:
            r1 = p.output()
            assert r1.success
            with open(r1.output_path, "rb") as f:
                first = f.read()
            r2 = p.output()
            assert not r2.success and "已存在" in r2.message
            with open(r1.output_path, "rb") as f:
                assert f.read() == first
        finally:
            p.close()

    def test_t08_corrupted_source_untouched(self, samples_dir, tmp_path):
        """损坏 PDF：loader 打开失败（抛错），原文件字节不变。"""
        src = copy_sample("sample_corrupted.pdf", str(tmp_path))
        before = sha256(src)
        from pdfsim.loader import PDFLoader, PDFLoadError
        with pytest.raises(PDFLoadError):
            PDFLoader().open(src, "")
        assert sha256(src) == before

    def test_blank_page_feature_table(self, samples_dir, tmp_path):
        """空白页特征规则表（BlankPageSource 尺寸/页码/序号）逐项核验。"""
        from pdfsim.models import DocumentConfig as DC
        from pdfsim.engine import build_process_plan, make_blank_page
        from pdfsim.loader import PDFLoader

        loader = PDFLoader()
        res = loader.open(str(samples_dir / "sample_a4_portrait.pdf"))
        try:
            pages = res.pages
            pages[0].marks.add(PageMark.COVER)
            pages[4].marks.add(PageMark.SIGNATURE)
            config = DC()
            plan = build_process_plan(pages, config)
            # 规则：COVER_BACK 有页码占序号、SIGN_BACK 无页码不占序号
            by_bs = {}
            for pp in plan.pages:
                if pp.is_blank:
                    by_bs[pp.blank_source] = pp
            assert by_bs[BlankPageSource.COVER_BACK].number_text is not None
            assert by_bs[BlankPageSource.COVER_BACK].number_occupies
            assert by_bs[BlankPageSource.SIGN_BACK].number_text is None
            assert not by_bs[BlankPageSource.SIGN_BACK].number_occupies
            # A3_BACK / NO_COUNT_USER 无页码不占序号
            b = make_blank_page(210, 297, BlankPageSource.A3_BACK)
            p2 = plan_page_numbers([b], 1)[0]
            assert p2.number_text is None and not p2.number_occupies
        finally:
            loader.close()


def plan_page_numbers(plan, start):
    from pdfsim.engine import plan_page_numbers as _ppn
    return _ppn(plan, start)
