# -*- coding: utf-8 -*-
"""集成测试：样本 PDF 端到端验证（加载 → 规划 → 输出）。

对应 Stage2 提示语步骤 8：用测试样本验证算法 → 加载 → 输出全链路。
"""
import shutil

import pymupdf
import pytest

from pdfsim.engine import build_process_plan
from pdfsim.loader import PDFLoader, PDFPasswordError
from pdfsim.models import (
    BlankPageSource,
    DocumentConfig,
    PageMark,
    RotationOverride,
    A4_WIDTH_MM,
    A4_HEIGHT_MM,
    A3_WIDTH_MM,
    A3_HEIGHT_MM,
)
from pdfsim.output import PDFOutput
from pdfsim.renderer import PDFRenderer


class Pipeline:
    """端到端流水线（真实文本检测 + 真实字体宽度）。"""

    def __init__(self, sample_name, samples_dir, out_dir, **cfg_kw):
        self.sample_name = sample_name
        self.src = str(samples_dir / sample_name)
        self.loader = PDFLoader()
        cfg_kw.setdefault("output_dir", str(out_dir))
        self.config = DocumentConfig(**cfg_kw)
        self.result = self.loader.open(self.src)
        self.text_data = {
            i: self.loader.extract_text_data(i)
            for i in range(len(self.result.pages))
        }
        self.renderer = PDFRenderer()
        self.plan = build_process_plan(
            self.result.pages,
            self.config,
            page_text_data=self.text_data,
            text_width_calculator=self.renderer.get_text_width,
        )

    def output(self):
        return PDFOutput().output(self.src, self.plan, self.config)

    def close(self):
        self.loader.close()

    def text_block_calculator(self):
        """构造文本块回调（显示坐标；无旋转样本可直接用 bbox）。"""
        def calc(idx):
            if idx is None:
                return None
            blocks = self.text_data.get(idx, {}).get("blocks", [])
            rects = []
            for b in blocks:
                if b.get("type") != 0:
                    continue
                x0, y0, x1, y1 = b["bbox"]
                rects.append((x0, y0, x1, y1))
            return rects
        return calc


def _blank_counts(plan):
    from collections import Counter
    return Counter(pp.blank_source for pp in plan.pages if pp.is_blank)


class TestE2E:
    def test_basic_pipeline(self, samples_dir, tmp_path):
        """基础端到端：sample_a4_portrait → 输出成功、页数一致、空白页正确。"""
        p = Pipeline("sample_a4_portrait.pdf", samples_dir, tmp_path)
        try:
            res = p.output()
            assert res.success
            assert res.page_count == len(p.plan.pages)
            assert res.source_hash_verified
            # 空白页类型正确
            cnt = _blank_counts(p.plan)
            assert cnt[BlankPageSource.COVER_BACK] == 1
            assert cnt[BlankPageSource.PUSH_FRONT] == 1
            assert cnt[BlankPageSource.SIGN_BACK] == 1
            # 物理顺序：奇数位全是正面（有页码且非空白）
            for pp in p.plan.pages:
                if pp.physical_index % 2 == 1:
                    assert not pp.is_blank, f"物理奇数页 {pp.physical_index} 应为正面"
        finally:
            p.close()

    def test_a3_portrait_rotation(self, samples_dir, tmp_path):
        """A3 纵向页端到端旋转 90（样本文字水平 → 显式强制旋转）。"""
        p = Pipeline("sample_a3_portrait.pdf", samples_dir, tmp_path)
        try:
            # 样本文字水平 → AUTO 检测为 0；显式强制旋转以验证 A3 旋转+输出
            p.result.pages[1].rotation_override = RotationOverride.CW90
            p.plan = build_process_plan(
                p.result.pages, p.config,
                page_text_data=p.text_data,
                text_width_calculator=p.renderer.get_text_width,
            )
            a3_pages = [
                pp for pp in p.plan.pages
                if not pp.is_blank and pp.source_page_info.original_index == 1
            ]
            assert a3_pages and a3_pages[0].rotation == 90
            assert a3_pages[0].output_size_mm == pytest.approx((A3_HEIGHT_MM, A3_WIDTH_MM), abs=0.1)
            res = p.output()
            assert res.success
            with pymupdf.open(res.output_path) as doc:
                r = doc[a3_pages[0].physical_index - 1].rect
                assert r.width == pytest.approx(1190.55, abs=1)
                assert r.height == pytest.approx(841.89, abs=1)
        finally:
            p.close()

    def test_mixed_sizes(self, samples_dir, tmp_path):
        """混合尺寸：A4 + A3 纵 + A3 横 各页旋转正确（A3 纵向显式强制旋转）。"""
        p = Pipeline("sample_mixed.pdf", samples_dir, tmp_path)
        try:
            # 样本文字水平 → AUTO 检测为 0；强制 A3 纵向页旋转
            p.result.pages[1].rotation_override = RotationOverride.CW90
            p.plan = build_process_plan(
                p.result.pages, p.config,
                page_text_data=p.text_data,
                text_width_calculator=p.renderer.get_text_width,
            )
            by_idx = {pp.source_page_info.original_index: pp for pp in p.plan.pages if not pp.is_blank}
            # 0:A4纵 → 不旋转; 1:A3纵 → 90; 2:A3横 → 0; 3:A4纵 → 0
            assert by_idx[0].rotation == 0
            assert by_idx[1].rotation == 90
            assert by_idx[2].rotation == 0
            assert by_idx[3].rotation == 0
            res = p.output()
            assert res.success
        finally:
            p.close()

    def test_no_count_deprecated_keeps_content(self, samples_dir, tmp_path):
        """规则变更（0.1）：NO_COUNT 用户标记路径废除——原页保留内容、无页码、跳过序号。"""
        # 手动给第 2 页（附件）打 NO_COUNT 标记（旧配置迁移语义）
        p = Pipeline("sample_no_count.pdf", samples_dir, tmp_path)
        try:
            p.result.pages[1].marks.add(PageMark.NO_COUNT)
            p.plan = build_process_plan(
                p.result.pages, p.config,
                page_text_data=p.text_data,
                text_width_calculator=p.renderer.get_text_width,
            )
            # 不再产生 NO_COUNT_USER 空白页
            no_count = [pp for pp in p.plan.pages
                        if pp.blank_source is BlankPageSource.NO_COUNT_USER]
            assert no_count == []
            # 附件页保留为原页、无页码、跳过序号
            pp = p.plan.pages[1]
            assert pp.is_blank is False
            assert pp.number_text is None
            assert pp.number_occupies is False
            res = p.output()
            assert res.success
            # 输出后该页内容保留（内容保护铁律）
            idx = pp.physical_index - 1
            with pymupdf.open(res.output_path) as doc:
                assert doc[idx].get_text().strip() != ""
        finally:
            p.close()

    def test_overlap_detection(self, samples_dir, tmp_path):
        """重叠检测：已有页码样本 → 检测到与新增页码重叠。"""
        p = Pipeline("sample_with_pagenum.pdf", samples_dir, tmp_path)
        try:
            plan2 = build_process_plan(
                p.result.pages, p.config,
                page_text_data=p.text_data,
                text_width_calculator=p.renderer.get_text_width,
                text_block_calculator=p.text_block_calculator(),
            )
            assert len(plan2.warnings) >= 1, "应检测到页码重叠"
        finally:
            p.close()

    def test_encrypted_pipeline(self, samples_dir, tmp_path):
        """加密样本：无密码失败、正确密码端到端成功。"""
        loader = PDFLoader()
        with pytest.raises(PDFPasswordError):
            loader.open(str(samples_dir / "sample_encrypted.pdf"))
        r = loader.open(str(samples_dir / "sample_encrypted.pdf"), password="testpass")
        try:
            text_data = {0: loader.extract_text_data(0)}
            renderer = PDFRenderer()
            config = DocumentConfig(output_dir=str(tmp_path))
            plan = build_process_plan(r.pages, config, page_text_data=text_data,
                                      text_width_calculator=renderer.get_text_width)
            res = PDFOutput().output(str(samples_dir / "sample_encrypted.pdf"), plan, config)
            assert res.success
            assert res.page_count == 1
        finally:
            loader.close()

    def test_200pages_performance(self, samples_dir, tmp_path):
        """200 页性能样本端到端完成。"""
        p = Pipeline("sample_200pages.pdf", samples_dir, tmp_path)
        try:
            res = p.output()
            assert res.success
            assert res.page_count == 200
        finally:
            p.close()

    def test_single_page(self, samples_dir, tmp_path):
        """单页样本端到端。"""
        p = Pipeline("sample_single.pdf", samples_dir, tmp_path)
        try:
            res = p.output()
            assert res.success
            assert res.page_count == 1
        finally:
            p.close()

    def test_rotation_markers_output(self, samples_dir, tmp_path):
        """方向标记样本端到端：A4 横向 + A3 纵向页输出旋转正确（显式强制旋转）。"""
        p = Pipeline("sample_direction_markers.pdf", samples_dir, tmp_path)
        try:
            # 样本文字水平 → AUTO 检测为 0；强制两页旋转以验证输出旋转正确
            p.result.pages[0].rotation_override = RotationOverride.CW90
            p.result.pages[1].rotation_override = RotationOverride.CW90
            p.plan = build_process_plan(
                p.result.pages, p.config,
                page_text_data=p.text_data,
                text_width_calculator=p.renderer.get_text_width,
            )
            for pp in p.plan.pages:
                if pp.is_blank:
                    continue
                idx = pp.source_page_info.original_index
                if idx == 0:  # A4 横向 → 90
                    assert pp.rotation == 90
                elif idx == 1:  # A3 纵向 → 90
                    assert pp.rotation == 90
            res = p.output()
            assert res.success
            with pymupdf.open(res.output_path) as doc:
                # 输出页 0（A4横向）显示尺寸应为 210×297 mm（pt: 595.28×841.89）
                r = doc[0].rect
                assert r.width == pytest.approx(A4_WIDTH_MM * 72 / 25.4, abs=1)
                assert r.height == pytest.approx(A4_HEIGHT_MM * 72 / 25.4, abs=1)
                # 方向标记文字仍可提取（内容未被破坏）
                text = doc[0].get_text()
                for mark in ["顶", "右", "底", "左"]:
                    assert mark in text
        finally:
            p.close()
