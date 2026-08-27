# -*- coding: utf-8 -*-
"""Stage 4 物理顺序专项验证。

对应《测试矩阵.md》第 3 节：对含插入空白页的场景构造期望"最终物理顺序表"，
逐项断言正背面、左右位置、页码位置、页码数字、级联正确性。

至少覆盖一次"插入点导致后续页奇偶翻转"的级联场景（sample_mixed 天然覆盖）。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # 供导入 _stage4_helpers

import pytest

from pdfsim.engine import plan_page_numbers
from pdfsim.loader import PDFLoader
from pdfsim.models import (
    BlankPageSource,
    DocumentConfig,
    PageMark,
    PageNumberPos,
    RotationOverride,
)

from _stage4_helpers import Pipeline, assert_physical_table, blank, copy_sample, original

# 参与"正/背"定位的空白类型（应落在偶数位=背面；NO_COUNT_USER 是原页替换，除外）
_BACK_BLANKS = {
    BlankPageSource.COVER_BACK,
    BlankPageSource.SIGN_BACK,
    BlankPageSource.PUSH_FRONT,
    BlankPageSource.A3_BACK,
    BlankPageSource.FILL_LAST,
}


def _make_pipeline(src_name, samples_dir, tmp_path, mutator=None):
    src = copy_sample(src_name, str(tmp_path))
    p = Pipeline(src, str(tmp_path))
    if mutator:
        mutator(p.result.pages)
        p.rebuild()
    return p


def assert_front_back_invariant(plan):
    """正背面：FRONT/A3 原页必须在奇数位（正面）；back/push/fill 空白在偶数位（背面）。

    无标记原页可自然落在偶数位（打印时的背面），不做强制。
    """
    from pdfsim.models import is_a3
    for pp in plan.pages:
        if pp.is_blank and pp.blank_source in _BACK_BLANKS:
            assert pp.physical_index % 2 == 0, (
                f"背面空白 {pp.blank_source.value} 在物理{pp.physical_index}（应为偶数）")
        elif not pp.is_blank:
            marks = pp.source_page_info.marks
            if PageMark.FRONT in marks or is_a3(pp.source_page_info):
                assert pp.physical_index % 2 == 1, (
                    f"FRONT/A3 原页在物理{pp.physical_index}（应为奇数=正面）")


def assert_number_position_invariant(plan):
    """页码位置：物理奇数→右下、偶数→左下（A3 固定右下）。"""
    from pdfsim.models import is_a3
    for pp in plan.pages:
        if pp.number_text is None:
            continue
        if is_a3(pp.source_page_info):
            assert pp.number_position == PageNumberPos.BOTTOM_RIGHT
            continue
        if pp.physical_index % 2 == 1:
            assert pp.number_position == PageNumberPos.BOTTOM_RIGHT
        else:
            assert pp.number_position == PageNumberPos.BOTTOM_LEFT


class TestFrontBack:
    def test_a4_bookmark_front_back(self, samples_dir, tmp_path):
        p = _make_pipeline("sample_a4_portrait.pdf", samples_dir, tmp_path)
        try:
            assert_front_back_invariant(p.plan)
        finally:
            p.close()

    def test_mixed_front_back(self, samples_dir, tmp_path):
        p = _make_pipeline("sample_mixed.pdf", samples_dir, tmp_path)
        try:
            assert_front_back_invariant(p.plan)
        finally:
            p.close()

    def test_odd_last_fill_front_back(self, samples_dir, tmp_path):
        def mut(pages):
            pass
        p = _make_pipeline("sample_odd_last.pdf", samples_dir, tmp_path)
        try:
            p.config.auto_fill_last_page = True
            p.rebuild()
            assert_front_back_invariant(p.plan)
        finally:
            p.close()


class TestNumberPosition:
    def test_a4_bookmark_position(self, samples_dir, tmp_path):
        p = _make_pipeline("sample_a4_portrait.pdf", samples_dir, tmp_path)
        try:
            assert_number_position_invariant(p.plan)
            # 抽样：phys1 奇→右下、phys2 偶→左下、phys3 奇→右下、phys8 签字背（无页码）
            rows = {pp.physical_index: pp for pp in p.plan.pages}
            assert rows[1].number_position is PageNumberPos.BOTTOM_RIGHT
            assert rows[2].number_position is PageNumberPos.BOTTOM_LEFT
            assert rows[3].number_position is PageNumberPos.BOTTOM_RIGHT
            assert rows[8].number_text is None
        finally:
            p.close()

    def test_mixed_a3_fixed_right(self, samples_dir, tmp_path):
        p = _make_pipeline("sample_mixed.pdf", samples_dir, tmp_path)
        try:
            assert_number_position_invariant(p.plan)
            # A3 页（phys3/phys5）固定右下
            assert p.plan.pages[2].number_position is PageNumberPos.BOTTOM_RIGHT
            assert p.plan.pages[4].number_position is PageNumberPos.BOTTOM_RIGHT
        finally:
            p.close()


class TestExpectedTables:
    """构造期望物理顺序表逐项断言（页码数字 + 级联）。"""

    def test_t06_fill_last_table(self, samples_dir, tmp_path):
        p = _make_pipeline("sample_odd_last.pdf", samples_dir, tmp_path)
        try:
            p.config.auto_fill_last_page = True
            p.config.auto_number_blank_pages = True  # 保留 FILL_LAST 编页码行为
            p.rebuild()
            expected = [
                original(1, PageNumberPos.BOTTOM_RIGHT),
                original(2, PageNumberPos.BOTTOM_LEFT),
                original(3, PageNumberPos.BOTTOM_RIGHT),
                blank("fill_last", "4", True, PageNumberPos.BOTTOM_LEFT),
            ]
            for i, row in enumerate(expected):
                row["phys"] = i + 1
                row["src_index"] = i if i < 3 else None
            assert_physical_table(p.plan, expected)
        finally:
            p.close()

    def test_t11_no_count_table(self, samples_dir, tmp_path):
        """规则变更（0.1）：NO_COUNT 迁移为 NO_NUMBER → 原页保留内容、无页码、跳过序号。"""
        def mut(pages):
            pages[1].marks.add(PageMark.NO_COUNT)  # 旧标记（迁移语义）
        p = _make_pipeline("sample_no_count.pdf", samples_dir, tmp_path, mut)
        try:
            expected = [
                original(1, PageNumberPos.BOTTOM_RIGHT),
                {"blank": False, "blank_source": None, "number_text": None,
                 "number_occupies": False, "number_position": PageNumberPos.BOTTOM_RIGHT,
                 "rotation": 0},
                original(2, PageNumberPos.BOTTOM_RIGHT),
            ]
            src_idx = [0, 1, 2]
            for i, row in enumerate(expected):
                row["phys"] = i + 1
                row["src_index"] = src_idx[i]
            assert_physical_table(p.plan, expected)
            # 原页保留内容（内容保护铁律）：不是空白页
            assert p.plan.pages[1].is_blank is False
            assert_front_back_invariant(p.plan)
        finally:
            p.close()

    def test_t12_t13_cascade_table(self, samples_dir, tmp_path):
        """级联翻转：A3 落偶数位 → 前插空白推动 → 后续奇偶重排（sample_mixed）。"""
        def _force_a3_rot(pages):
            pages[1].rotation_override = RotationOverride.CW90  # A3 纵向样本文字水平 → 强制旋转

        p = _make_pipeline("sample_mixed.pdf", samples_dir, tmp_path,
                           mutator=_force_a3_rot)
        try:
            p.config.auto_number_blank_pages = True  # 保留 PUSH_FRONT 编页码行为
            p.rebuild()
            expected = [
                original(1, PageNumberPos.BOTTOM_RIGHT),
                blank("push_front", "2", True, PageNumberPos.BOTTOM_LEFT),
                original(3, PageNumberPos.BOTTOM_RIGHT, 90),
                blank("a3_back", None, False, PageNumberPos.BOTTOM_RIGHT, rot=90),
                original(4, PageNumberPos.BOTTOM_RIGHT, 0),
                blank("a3_back", None, False, PageNumberPos.BOTTOM_RIGHT, rot=0),
                original(5, PageNumberPos.BOTTOM_RIGHT, 0),
            ]
            src_idx = [0, None, 1, None, 2, None, 3]
            for i, row in enumerate(expected):
                row["phys"] = i + 1
                row["src_index"] = src_idx[i]
            assert_physical_table(p.plan, expected)
            assert_front_back_invariant(p.plan)
            assert_number_position_invariant(p.plan)
        finally:
            p.close()


class TestCascadeInvariant:
    """级联正确性：插入空白后，其后每一页的 4 项均基于新序号成立。"""

    def test_page_numbers_sequential_after_insert(self, samples_dir, tmp_path):
        """规则变更（0.1）：NO_COUNT 迁移为 NO_NUMBER，附件页保留内容但跳过序号，正文=2。"""
        def mut(pages):
            pages[1].marks.add(PageMark.NO_COUNT)
        p = _make_pipeline("sample_no_count.pdf", samples_dir, tmp_path, mut)
        try:
            seq = [pp.number_text for pp in p.plan.pages
                   if pp.number_text is not None]
            assert seq == ["1", "2"]  # 封面=1、正文=2（附件页跳过序号）
            # 附件页保留内容（非空白页）
            assert p.plan.pages[1].is_blank is False
        finally:
            p.close()

    def test_a3_push_sequential(self, samples_dir, tmp_path):
        """T12 级联：A3 前插空白后，A3 与其后页码连续（1,2,3,4,5）。"""
        p = _make_pipeline("sample_mixed.pdf", samples_dir, tmp_path)
        try:
            p.config.auto_number_blank_pages = True  # 保留 PUSH_FRONT 编页码行为
            p.rebuild()
            seq = [pp.number_text for pp in p.plan.pages
                   if pp.number_text is not None]
            assert seq == ["1", "2", "3", "4", "5"]
        finally:
            p.close()
