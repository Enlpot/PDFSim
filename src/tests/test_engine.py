# -*- coding: utf-8 -*-
"""算法引擎测试（依据 Stage2 提示语 5.3.6，覆盖测试矩阵 T01–T16 相关场景）。"""
import pytest

from pdfsim.engine import (
    build_process_plan,
    calculate_number_position,
    detect_overlap,
    detect_text_rotation,
    final_rotation,
    number_rect_from_anchor,
    plan_page_numbers,
    plan_physical_order,
    plan_rotation,
    rects_intersect,
)
from pdfsim.models import (
    MM_TO_PT,
    A4_HEIGHT_MM,
    A4_WIDTH_MM,
    A3_HEIGHT_MM,
    A3_WIDTH_MM,
    BlankPageSource,
    DocumentConfig,
    PageInfo,
    PageMark,
    PageNumberPos,
    PageNumberStyle,
    ProcessedPage,
    RotationOverride,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def mk(idx, w, h, marks=None, rot_override=RotationOverride.AUTO, **kw):
    return PageInfo(
        original_index=idx,
        width_mm=w,
        height_mm=h,
        marks=set(marks or []),
        rotation_override=rot_override,
        **kw,
    )


def a4(idx, **kw):
    return mk(idx, A4_WIDTH_MM, A4_HEIGHT_MM, **kw)


def a3(idx, **kw):
    return mk(idx, A3_WIDTH_MM, A3_HEIGHT_MM, **kw)


def a4_landscape(idx, **kw):
    return mk(idx, A4_HEIGHT_MM, A4_WIDTH_MM, **kw)


def a3_landscape(idx, **kw):
    return mk(idx, A3_HEIGHT_MM, A3_WIDTH_MM, **kw)


def cfg(**kw):
    return DocumentConfig(**kw)


def processed_from(plan, start=1):
    return plan_page_numbers(plan, start)


def sources_list(*pages):
    return list(pages)


# ---------------------------------------------------------------------------
# 算法 1：物理顺序
# ---------------------------------------------------------------------------
class TestPlanPhysicalOrder:
    def test_t01_basic_cover_signature_a3(self):
        """T01 基础流程：封面背面、签字页背面、A3 背面空白正确插入。"""
        src = [
            a4(0, marks=[PageMark.COVER, PageMark.FRONT]),  # 封面（同时从正面开始）
            a4(1),                                            # 普通页
            a4(2, marks=[PageMark.SIGNATURE, PageMark.FRONT]),  # 签字页
        ]
        plan = plan_physical_order(src, cfg())
        kinds = [p.blank_source.value if p.is_blank else "orig" for p in plan]
        assert kinds == ["orig", "cover_back", "orig", "push_front", "orig", "sign_back"]
        # 尺寸：封面背面=封面尺寸；签字页背面=签字页尺寸
        assert plan[1].width_mm == A4_WIDTH_MM
        assert plan[5].width_mm == A4_WIDTH_MM

    def test_t12_a3_on_even_position_pushes_front(self):
        """T12 A3 落偶数位：插入推动空白页使其从正面开始。"""
        src = [a4(0), a3(1)]
        plan = plan_physical_order(src, cfg())
        kinds = [p.blank_source.value if p.is_blank else "orig" for p in plan]
        assert kinds == ["orig", "push_front", "orig", "a3_back"]
        # 推动空白页尺寸取前一页（A4）
        assert plan[1].width_mm == A4_WIDTH_MM
        # A3 背面尺寸取 A3
        assert plan[3].width_mm == A3_WIDTH_MM
        # A3 落在物理第 3 位（正面）
        assert plan[2].original_index == 1

    def test_t13_cascade_multiple_a3(self):
        """T13 连续多个 A3：级联插入后物理顺序正确。"""
        src = [a3(0), a3(1)]
        plan = plan_physical_order(src, cfg())
        kinds = [p.blank_source.value if p.is_blank else "orig" for p in plan]
        assert kinds == ["orig", "a3_back", "orig", "a3_back"]
        # 每个 A3 都在正面（物理 1、3 位）
        assert [p.original_index for p in plan if not p.is_blank] == [0, 1]
        assert plan[0].original_index == 0
        assert plan[2].original_index == 1

    def test_t11_no_count_deprecated_keeps_content(self):
        """规则变更（0.1）：NO_COUNT 用户标记路径废除——原页保留内容、不再替换为空白页。

        旧配置迁移时 NO_COUNT → NO_NUMBER（保留内容+无页码+跳过序号）。
        """
        src = [a4(0), a3(1, marks=[PageMark.NO_COUNT])]
        plan = plan_physical_order(src, cfg())
        # 不再产生 NO_COUNT_USER 空白页（内容保护铁律）
        assert all(not (p.is_blank and p.blank_source is BlankPageSource.NO_COUNT_USER)
                   for p in plan)
        # A3(1) 落偶数位 → PUSH_FRONT 推动；A3 原页保留内容
        # plan = [a4, push_front, a3原页, a3_back]
        assert plan[1].blank_source is BlankPageSource.PUSH_FRONT
        assert plan[2].is_blank is False
        assert plan[2].original_index == 1
        assert plan[3].blank_source is BlankPageSource.A3_BACK

    def test_t06_fill_last_page(self):
        """T06 末页奇数补齐：开关打开时末尾追加空白页。"""
        src = [a4(0), a4(1), a4(2)]
        plan = plan_physical_order(src, cfg(auto_fill_last_page=False))
        assert len(plan) == 3
        plan2 = plan_physical_order(src, cfg(auto_fill_last_page=True))
        assert len(plan2) == 4
        assert plan2[-1].blank_source is BlankPageSource.FILL_LAST
        assert plan2[-1].width_mm == A4_WIDTH_MM

    def test_mark_linkage_front_pushed(self):
        """T01 标记联动：封面/签字页带 FRONT，偶数位时被推动到正面。"""
        src = [a4(0), a4(1, marks=[PageMark.COVER, PageMark.FRONT])]
        plan = plan_physical_order(src, cfg())
        # 第2页封面：len=1, +1=2 偶数 → 推 PUSH_FRONT
        kinds = [p.blank_source.value if p.is_blank else "orig" for p in plan]
        assert kinds == ["orig", "push_front", "orig", "cover_back"]
        # 封面落在物理第 3 位（正面）
        assert plan[2].original_index == 1

    def test_d6_a3_cover_conflict(self):
        """D6 标记冲突：A3+封面时 A3 背面优先（只插一张，无 COVER_BACK）。"""
        src = [a3(0, marks=[PageMark.COVER, PageMark.FRONT])]
        plan = plan_physical_order(src, cfg())
        kinds = [p.blank_source.value if p.is_blank else "orig" for p in plan]
        assert kinds == ["orig", "a3_back"]


# ---------------------------------------------------------------------------
# 算法 2：页码规划
# ---------------------------------------------------------------------------
class TestPlanPageNumbers:
    def test_t01_sequential_numbers(self):
        """T01 页码从起始值连续递增。"""
        src = [
            a4(0, marks=[PageMark.COVER, PageMark.FRONT]),
            a4(1),
        ]
        plan = plan_physical_order(src, cfg())
        proc = processed_from(plan, start=1)
        texts = [p.number_text for p in proc]
        assert texts == ["1", "2", "3"]

    def test_t11_no_count_skips_sequence(self):
        """规则变更（0.1）：NO_COUNT 迁移为 NO_NUMBER → 保留内容、无页码、跳过序号。"""
        src = [a4(0, marks=[PageMark.NO_COUNT]), a4(1)]
        plan = plan_physical_order(src, cfg())
        proc = processed_from(plan, start=1)
        assert proc[0].is_blank is False  # 原页保留内容
        assert proc[0].number_text is None
        assert proc[0].number_occupies is False  # 跳过序号
        assert proc[1].number_text == "1"  # 后续页码顺延前移

    def test_no_number_skips_sequence(self):
        """规则变更（0.1）"不加页码"新语义：无数字、跳过序号、后续顺延前移。

        例：页1"1"、页2无、页3"2"。
        """
        src = [a4(0, marks=[PageMark.NO_NUMBER]), a4(1)]
        plan = plan_physical_order(src, cfg())
        proc = processed_from(plan, start=1)
        assert proc[0].number_text is None
        assert proc[0].number_occupies is False  # 跳过序号（新语义）
        assert proc[1].number_text == "1"  # 顺延前移（不是 "2"）

    def test_no_number_consecutive_skip(self):
        """连续多页"不加页码"：全部跳过，后续顺延正确。"""
        src = [
            a4(0, marks=[PageMark.NO_NUMBER]),
            a4(1, marks=[PageMark.NO_NUMBER]),
            a4(2),
            a4(3),
        ]
        plan = plan_physical_order(src, cfg())
        proc = processed_from(plan, start=1)
        assert [p.number_text for p in proc] == [None, None, "1", "2"]

    def test_blank_sources(self):
        """各类空白页按来源类型正确处理页码与占位。"""
        src = [a4(0, marks=[PageMark.COVER, PageMark.FRONT]), a3(1)]
        plan = plan_physical_order(src, cfg())
        proc = processed_from(plan, start=5)
        # 5封面,6封面背,7PUSH(第2页A3落正面?) 实际: 封面(5) COVER_BACK(6) push(7) A3(8) A3_BACK(9)
        # 但这里封面为第1页：5封面 6COVER_BACK, 然后A3: len=2+1=3奇不需推 → A3(7) A3_BACK(8)
        by_src = {p.source_page_info.original_index: p for p in proc}
        assert proc[0].number_text == "5"  # 封面
        assert proc[1].number_text == "6"  # COVER_BACK 占序号
        assert proc[1].number_occupies is True
        # A3 及其背面
        a3p = [p for p in proc if p.source_page_info.original_index == 1][0]
        assert a3p.number_text == "7"
        a3back = [p for p in proc if p.is_blank and p.blank_source is BlankPageSource.A3_BACK][0]
        assert a3back.number_text is None
        assert a3back.number_occupies is False
        # SIGN_BACK / NO_COUNT_USER 亦不显示不占位
        src2 = [a4(0, marks=[PageMark.SIGNATURE, PageMark.FRONT])]
        plan2 = plan_physical_order(src2, cfg())
        proc2 = processed_from(plan2, start=1)
        sign_back = [p for p in proc2 if p.blank_source is BlankPageSource.SIGN_BACK][0]
        assert sign_back.number_text is None
        assert sign_back.number_occupies is False


# ---------------------------------------------------------------------------
# 算法 3：旋转
# ---------------------------------------------------------------------------
def text_data(*dirs):
    """构造 get_text("dict") 风格的 mock 数据。"""
    blocks = []
    for d in dirs:
        blocks.append(
            {"type": 0, "lines": [{"dir": d, "spans": [{"text": "x" * 20}]}]}
        )
    return {"blocks": blocks}


class TestDetectTextRotation:
    def test_horizontal(self):
        # 主导文字朝右 → 不旋转
        assert detect_text_rotation(text_data((1.0, 0.0))) == 0

    def test_vertical(self):
        # 文字向下 → 逆时针 90°；文字向上 → 顺时针 90°
        assert detect_text_rotation(text_data((0.0, -1.0))) == 270
        assert detect_text_rotation(text_data((0.0, 1.0))) == 90

    def test_no_text(self):
        assert detect_text_rotation({"blocks": []}) == 90  # 回退默认

    def test_reversed_horizontal(self):
        # 180° 倒置正文 → 旋转 180°
        assert detect_text_rotation(text_data((-1.0, 0.0))) == 180

    def test_weighted_dominant(self):
        # 大量水平正向 + 少量向下 → 按文本量取主导 → 不旋转
        data = {
            "blocks": [
                {"type": 0, "lines": [{"dir": (1.0, 0.0), "spans": [{"text": "a" * 100}]}]},
                {"type": 0, "lines": [{"dir": (0.0, -1.0), "spans": [{"text": "b" * 5}]}]},
            ]
        }
        assert detect_text_rotation(data) == 0

    def test_weighted_dominant_vertical(self):
        # 纵向向上占主导 → 顺时针 90°
        data = {
            "blocks": [
                {"type": 0, "lines": [{"dir": (1.0, 0.0), "spans": [{"text": "a" * 5}]}]},
                {"type": 0, "lines": [{"dir": (0.0, 1.0), "spans": [{"text": "b" * 80}]}]},
            ]
        }
        assert detect_text_rotation(data) == 90

    def test_small_float_error_quantized(self):
        # dir 存在微小浮点误差时按主分量量化，不误判
        assert detect_text_rotation(text_data((1.0000001, 0.0000001))) == 0
        assert detect_text_rotation(text_data((-1.0, 0.0001))) == 180

    def test_ignore_non_text_blocks(self):
        # 图片等非文字块忽略；仅文字块参与统计
        data = {
            "blocks": [
                {"type": 1, "lines": [{"dir": (1.0, 0.0), "spans": [{"text": "x" * 50}]}]},
                {"type": 0, "lines": [{"dir": (-1.0, 0.0), "spans": [{"text": "y" * 20}]}]},
            ]
        }
        assert detect_text_rotation(data) == 180


class TestPlanRotation:
    def test_a4_landscape_text_horizontal_no_rotation(self):
        # A4 横向但文字已水平正向可读 → 不旋转，尺寸不交换
        p = a4_landscape(0)
        r, size = plan_rotation(p, text_data((1.0, 0.0)))
        assert r == 0
        assert size == (A4_HEIGHT_MM, A4_WIDTH_MM)

    def test_a4_landscape_text_up_rot90(self):
        p = a4_landscape(0)
        r, size = plan_rotation(p, text_data((0.0, 1.0)))
        assert r == 90
        assert size == (A4_WIDTH_MM, A4_HEIGHT_MM)  # 90° 交换宽高

    def test_a4_landscape_text_down_rot270(self):
        p = a4_landscape(0)
        r, size = plan_rotation(p, text_data((0.0, -1.0)))
        assert r == 270
        assert size == (A4_WIDTH_MM, A4_HEIGHT_MM)

    def test_a4_landscape_text_reversed_rot180(self):
        # 180° 倒置：旋转 180°，尺寸不交换
        p = a4_landscape(0)
        r, size = plan_rotation(p, text_data((-1.0, 0.0)))
        assert r == 180
        assert size == (A4_HEIGHT_MM, A4_WIDTH_MM)

    def test_a3_portrait_needs_rotation(self):
        p = a3(0)
        r, size = plan_rotation(p, text_data((0.0, 1.0)))
        assert r == 90
        assert size == (A3_HEIGHT_MM, A3_WIDTH_MM)

    def test_a3_portrait_text_reversed_rot180(self):
        p = a3(0)
        r, size = plan_rotation(p, text_data((-1.0, 0.0)))
        assert r == 180
        assert size == (A3_WIDTH_MM, A3_HEIGHT_MM)  # 180° 不交换宽高

    def test_a4_portrait_no_rotation(self):
        p = a4(0)
        r, size = plan_rotation(p, None)
        assert r == 0
        assert size == (A4_WIDTH_MM, A4_HEIGHT_MM)

    def test_a3_landscape_no_rotation(self):
        p = a3_landscape(0)
        r, size = plan_rotation(p, None)
        assert r == 0
        assert size == (A3_WIDTH_MM, A3_HEIGHT_MM)

    def test_other_size_no_rotation(self):
        p = mk(0, 215.9, 279.4)  # Letter
        r, size = plan_rotation(p, None)
        assert r == 0
        assert size == (215.9, 279.4)

    def test_no_text_fallback(self):
        p = a4_landscape(0)
        r, _ = plan_rotation(p, {"blocks": []})
        assert r == 90  # 回退默认


class TestFinalRotation:
    def test_auto(self):
        p = a4_landscape(0)
        p.detected_rotation = 90
        assert final_rotation(p) == 90

    def test_cw90(self):
        p = a4_landscape(0, rot_override=RotationOverride.CW90)
        p.detected_rotation = 270
        assert final_rotation(p) == 90

    def test_ccw90(self):
        p = a4_landscape(0, rot_override=RotationOverride.CCW90)
        p.detected_rotation = 90
        assert final_rotation(p) == 270

    def test_rot180(self):
        p = a4_landscape(0, rot_override=RotationOverride.ROT180)
        p.detected_rotation = 90
        assert final_rotation(p) == 180

    def test_none(self):
        p = a4_landscape(0, rot_override=RotationOverride.NONE)
        p.detected_rotation = 90
        assert final_rotation(p) == 0


# ---------------------------------------------------------------------------
# 算法 4：页码坐标
# ---------------------------------------------------------------------------
def _pp(page, physical_index, number_text="1"):
    return ProcessedPage(
        physical_index=physical_index,
        source_page_info=page,
        is_blank=page.is_blank,
        blank_source=page.blank_source,
        number_text=number_text,
        number_occupies=True,
        number_position=PageNumberPos.BOTTOM_RIGHT,
        number_point=None,
        rotation=page.planned_rotation,
        output_size_mm=(page.height_mm, page.width_mm)
        if page.planned_rotation in (90, 270)
        else (page.width_mm, page.height_mm),
    )


class TestCalculateNumberPosition:
    def setup_method(self):
        self.style = PageNumberStyle()  # 默认边距 10mm，字号 9

    def test_odd_page_bottom_right(self):
        p = a4(0)  # 210×297, rot0
        pp = _pp(p, physical_index=1)
        pt = calculate_number_position(pp, self.style, 1, text_width_pt=50.0)
        assert pt is not None
        W = A4_WIDTH_MM * MM_TO_PT
        right = 10.0 * MM_TO_PT
        bottom = 10.0 * MM_TO_PT
        assert pt[0] == pytest.approx(W - right - 50.0)
        assert pt[1] == pytest.approx(bottom)

    def test_even_page_bottom_left(self):
        p = a4(0)
        pp = _pp(p, physical_index=2)
        pt = calculate_number_position(pp, self.style, 2, text_width_pt=50.0)
        left = 10.0 * MM_TO_PT
        bottom = 10.0 * MM_TO_PT
        assert pt[0] == pytest.approx(left)
        assert pt[1] == pytest.approx(bottom)

    def test_a3_always_bottom_right(self):
        # A3 横向不旋转（输出 420×297），物理偶数位也应右下
        p = a3_landscape(0)  # 420×297
        pp = _pp(p, physical_index=2)
        pt = calculate_number_position(pp, self.style, 2, text_width_pt=50.0)
        W = A3_HEIGHT_MM * MM_TO_PT  # 420mm（横向不旋转，宽=420）
        right = 10.0 * MM_TO_PT
        bottom = 10.0 * MM_TO_PT
        assert pt[0] == pytest.approx(W - right - 50.0)
        assert pt[1] == pytest.approx(bottom)

    def test_rotated_derotation(self):
        """旋转页：显示坐标经 derotation 换算为未旋转坐标。"""
        p = a4_landscape(0)  # 297×210，需旋转 90
        p.planned_rotation = 90
        p.detected_rotation = 90
        pp = _pp(p, physical_index=1)
        pt = calculate_number_position(pp, self.style, 1, text_width_pt=50.0)
        # 显示坐标右下角 anchor=(W-right-50, bottom)，W=210*MM_TO_PT
        W = A4_WIDTH_MM * MM_TO_PT
        H = A4_HEIGHT_MM * MM_TO_PT
        right = 10.0 * MM_TO_PT
        bottom = 10.0 * MM_TO_PT
        ax = W - right - 50.0
        ay = bottom
        # derotate r=90（Bug 修复后，实测渲染验证）：(x, y) → (Hd - y, x)
        assert pt[0] == pytest.approx(H - ay)
        assert pt[1] == pytest.approx(ax)

    def test_rotated_derotation_ccw(self):
        """旋转页（270°）：derotation 换算正确。"""
        p = a4_landscape(0)  # 297×210
        p.planned_rotation = 270
        p.detected_rotation = 270
        pp = _pp(p, physical_index=1)
        pt = calculate_number_position(pp, self.style, 1, text_width_pt=50.0)
        W = A4_WIDTH_MM * MM_TO_PT
        right = 10.0 * MM_TO_PT
        bottom = 10.0 * MM_TO_PT
        ax = W - right - 50.0
        ay = bottom
        # derotate r=270: (x, y) → (y, Wd - x)
        assert pt[0] == pytest.approx(ay)
        assert pt[1] == pytest.approx(W - ax)

    def test_custom_offset(self):
        """D8 自定义偏移：相对基准角向内为正。"""
        p = a4(0)
        p.number_pos_override = PageNumberPos.CUSTOM
        p.number_custom_offset_mm = (12.0, 8.0)
        pp = _pp(p, physical_index=1)  # 物理奇→右下基准
        pt = calculate_number_position(pp, self.style, 1, text_width_pt=50.0)
        W = A4_WIDTH_MM * MM_TO_PT
        right = 10.0 * MM_TO_PT
        bottom = 10.0 * MM_TO_PT
        dx = 12.0 * MM_TO_PT
        dy = 8.0 * MM_TO_PT
        # 右下基准 + 向内(x减, y加)
        assert pt[0] == pytest.approx(W - right - 50.0 - dx)
        assert pt[1] == pytest.approx(bottom + dy)

    def test_no_number_returns_none(self):
        p = a4(0)
        pp = ProcessedPage(
            physical_index=1, source_page_info=p, is_blank=False, blank_source=None,
            number_text=None, number_occupies=True, number_position=PageNumberPos.BOTTOM_RIGHT,
            number_point=None, rotation=0, output_size_mm=(210.0, 297.0))
        assert calculate_number_position(pp, self.style, 1, 50.0) is None


# ---------------------------------------------------------------------------
# 算法 5：重叠检测
# ---------------------------------------------------------------------------
class TestDetectOverlap:
    def test_t10_overlap_hit(self):
        num = (100.0, 100.0, 150.0, 130.0)
        blocks = [(120.0, 110.0, 200.0, 140.0)]  # 与 num 相交
        hits = detect_overlap(num, blocks)
        assert hits == [(120.0, 110.0, 150.0, 130.0)]  # 重叠区域 = 交集

    def test_collect_all_overlaps(self):
        """收集所有重叠文本块，不只第一个命中。"""
        num = (100.0, 100.0, 150.0, 130.0)
        blocks = [
            (120.0, 110.0, 200.0, 140.0),   # 命中 → (120,110,150,130)
            (90.0, 105.0, 140.0, 125.0),    # 命中 → (100,105,140,125)
            (300.0, 300.0, 400.0, 400.0),   # 不命中
            (100.0, 100.0, 150.0, 130.0),   # 完全包含 → 全交集
        ]
        hits = detect_overlap(num, blocks)
        assert len(hits) == 3
        assert hits[0] == (120.0, 110.0, 150.0, 130.0)
        assert hits[1] == (100.0, 105.0, 140.0, 125.0)
        assert hits[2] == (100.0, 100.0, 150.0, 130.0)

    def test_no_overlap(self):
        num = (100.0, 100.0, 150.0, 130.0)
        blocks = [(200.0, 100.0, 300.0, 130.0)]  # 相距 50pt
        assert detect_overlap(num, blocks) == []

    def test_empty_blocks(self):
        assert detect_overlap((0.0, 0.0, 10.0, 10.0), []) == []

    def test_tolerance_edges(self):
        # 贴边（重叠宽=0）→ 不误报
        num = (100.0, 100.0, 200.0, 130.0)
        assert rects_intersect(num, (200.0, 100.0, 300.0, 130.0)) is False
        # 真实重叠 1pt > 0.5pt → 判定重叠
        assert rects_intersect(num, (199.0, 100.0, 300.0, 130.0)) is True
        # 间隙 1pt → 不重叠
        assert rects_intersect(num, (201.0, 100.0, 300.0, 130.0)) is False
        # 仅 0.3pt 擦边重叠 → 容差内不算重叠
        assert rects_intersect(num, (199.7, 100.0, 300.0, 130.0)) is False

    def test_rect_from_anchor(self):
        r = number_rect_from_anchor((100.0, 50.0), 30.0, 10.0)
        assert r == (100.0, 40.0, 130.0, 58.0)


# ---------------------------------------------------------------------------
# 集成：build_process_plan
# ---------------------------------------------------------------------------
class TestBuildProcessPlan:
    def test_full_pipeline(self):
        """T01 完整流程：串联 5 个算法产出正确 ProcessPlan。"""
        src = [
            a4(0, marks=[PageMark.COVER, PageMark.FRONT]),
            a4(1),
            a4_landscape(2),  # 横向 → 需旋转
        ]
        text_data_map = {
            0: text_data((1.0, 0.0)),
            1: text_data((1.0, 0.0)),
            2: text_data((1.0, 0.0)),
        }
        plan = build_process_plan(
            src,
            cfg(start_page_number=1),
            page_text_data=text_data_map,
            text_width_calculator=lambda t, fs: len(t) * fs * 0.5,
        )
        # 物理顺序：封面 COVER_BACK 普通 A4 A4横(需推?) 旋转A4 A4背?
        # 手动推演：
        #   p0 封面(FRONT,1奇)→[封面]; COVER_BACK→[封面,COVER_BACK]
        #   p1 A4(第3奇)→[封面,COVER_BACK,A4]
        #   p2 A4横向(无FRONT,第4偶)→[封面,COVER_BACK,A4,A4横]; 无背面
        kinds = [p.blank_source.value if p.is_blank else "orig" for p in plan.pages]
        assert kinds == ["orig", "cover_back", "orig", "orig"]
        # 页码
        texts = [p.number_text for p in plan.pages]
        assert texts == ["1", "2", "3", "4"]
        # 旋转页（文字水平正向 → 新检测逻辑不再盲转 90°）
        rot_page = plan.pages[3]
        assert rot_page.rotation == 0
        assert rot_page.output_size_mm == (A4_HEIGHT_MM, A4_WIDTH_MM)
        # 每页都有坐标
        for p in plan.pages:
            assert p.number_point is not None

    def test_overlap_warning_emitted(self):
        """T10 集成：文本块与页码重叠 → 生成 OverlapWarning。"""
        src = [a4(0)]
        # 文本块在右下角（页码位置）区域：显示坐标（左上原点 y 向下），
        # A4 纵向 W=595pt、H=842pt，底部右下角 ≈ y∈[800,830]
        blocks = {
            0: [(500.0, 800.0, 595.0, 830.0)],  # 显示坐标右下角（底部）
        }
        conf = cfg()
        conf.auto_adjust_overlap = False  # 验证"检测→警告"原始语义，关闭自动调整
        plan = build_process_plan(
            src,
            conf,
            page_text_data={0: text_data((1.0, 0.0))},
            text_width_calculator=lambda t, fs: len(t) * fs * 0.5,
            text_block_calculator=lambda idx: blocks.get(idx),
        )
        assert len(plan.warnings) == 1
        assert plan.warnings[0].physical_index == 1
        assert plan.warnings[0].number_text == "1"

    def test_custom_offset_clears_overlap_warning(self):
        """B4-01 修复：CUSTOM 偏移使页码移开后，重叠警告应消除。

        回归验证：算法 5（_display_anchor）与算法 4 对 CUSTOM 偏移处理一致，
        页码实际移动后不再按未偏移位置误报重叠。
        """
        src = [a4(0)]
        src[0].number_pos_override = PageNumberPos.CUSTOM
        src[0].number_custom_offset_mm = (120.0, 0.0)  # 向右上移 120mm
        blocks = {0: [(500.0, 800.0, 595.0, 830.0)]}  # 右下角原页码位置（显示坐标，底部）
        plan = build_process_plan(
            src,
            cfg(),
            page_text_data={0: text_data((1.0, 0.0))},
            text_width_calculator=lambda t, fs: len(t) * fs * 0.5,
            text_block_calculator=lambda idx: blocks.get(idx),
        )
        # 页码已随偏移移开（算法 4），重叠检测不再报警告（算法 5 一致）
        assert len(plan.warnings) == 0, "CUSTOM 偏移后不应再报重叠警告"
        x, y = plan.pages[0].number_point
        assert x < 400.0  # 已移离原右下角文本块区域
