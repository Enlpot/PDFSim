# -*- coding: utf-8 -*-
"""算法引擎（依据《技术方案.md》第 3 章 + Stage2 提示语 5.3）。

纯 Python 实现，不直接依赖 pikepdf / PyMuPDF；通过参数传入数据，可独立单元测试。
5 大算法：
  算法 1  plan_physical_order   物理顺序规划
  算法 2  plan_page_numbers     页码数字规划
  算法 3  detect_text_rotation / plan_rotation / final_rotation  页面旋转
  算法 4  calculate_number_position  页码坐标计算
  算法 5  detect_overlap        重叠检测
统一入口 build_process_plan 串联 1→3→2→4→5。
"""
from __future__ import annotations

import math

from pdfsim.models import (
    A4_HEIGHT_MM,
    A4_WIDTH_MM,
    A3_HEIGHT_MM,
    A3_WIDTH_MM,
    MM_TO_PT,
    SIZE_TOLERANCE_MM,
    BlankPageSource,
    DocumentConfig,
    OverlapWarning,
    PageInfo,
    PageMark,
    PageNumberPos,
    PageNumberStyle,
    ProcessedPage,
    ProcessPlan,
    RotationOverride,
    is_a3,
)

# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------
def _approx(value: float, target: float, tol: float = SIZE_TOLERANCE_MM) -> bool:
    return abs(value - target) <= tol


def make_blank_page(
    width_mm: float,
    height_mm: float,
    source: BlankPageSource,
    original_index: int | None = None,
    blank_id: str | None = None,
) -> PageInfo:
    """构造一张空白页 PageInfo（blank_id 为跨 rebuild 稳定的配置标识）。"""
    return PageInfo(
        original_index=original_index,
        width_mm=width_mm,
        height_mm=height_mm,
        is_blank=True,
        blank_source=source,
        blank_id=blank_id,
    )


def make_blank_id(trigger: int | str, source: BlankPageSource) -> str:
    """空白页稳定标识：f"blank:{触发源标识}:{来源类型}"。

    触发源标识 = 来源页 original_index（0-based）或固定 "last"（末页补齐）。
    基于源页索引 + 来源类型，与物理位置无关，故插入/删除空白页后 rebuild 不变。
    """
    return f"blank:{trigger}:{source.value}"


def _adjacent_size(plan: list[PageInfo], cur: PageInfo) -> tuple[float, float]:
    """“推正面”空白页尺寸：取前一页（plan[-1]），无前页取当前页（D5）。"""
    if plan:
        last = plan[-1]
        return (last.width_mm, last.height_mm)
    return (cur.width_mm, cur.height_mm)


def _rotated_size(page: PageInfo, rotation: int) -> tuple[float, float]:
    """旋转后的物理尺寸（mm）。90/270 交换宽高；0/180 不变。"""
    if rotation in (90, 270):
        return (page.height_mm, page.width_mm)
    return (page.width_mm, page.height_mm)


def _derotate(
    x: float, y: float, rotation: int, display_w_pt: float, display_h_pt: float
) -> tuple[float, float]:
    """显示坐标 → 未旋转坐标（PDF 坐标系，原点左下，y 向上）。

    依据 PDF 规范 + 实测渲染验证（/Rotate=90/270/180 页面上 insert_text 后
    用 PyMuPDF rotation_matrix 反推得到，详见 docs/页码位置Bug修复报告.md）：
      r=0:   (x, y)
      r=90:  (Hd - y, x)         ← 修复：y 分量应为显示坐标 x（原实现误用 Wd - x）
      r=270: (y, Wd - x)
      r=180: (Wd - x, Hd - y)
    Wd/Hd 为旋转后显示尺寸（pt）。
    """
    if rotation == 0:
        return (x, y)
    if rotation == 90:
        return (display_h_pt - y, x)
    if rotation == 270:
        return (y, display_w_pt - x)
    if rotation == 180:
        return (display_w_pt - x, display_h_pt - y)
    raise ValueError(f"无效旋转角: {rotation}")


# ---------------------------------------------------------------------------
# 算法 1：物理顺序规划
# ---------------------------------------------------------------------------
def plan_physical_order(
    source_pages: list[PageInfo], config: DocumentConfig
) -> list[PageInfo]:
    """按源页顺序单趟正向累加（D4），产出物理顺序列表（含插入的空白页）。

    规则变更（《多选批量与空白页配置_提示语》0.1）：删除"不占序号"替换分支——
    原页一律保留内容（内容保护铁律），不再有用户 NO_COUNT 空白页。
    步骤：
      ① “从正面开始”检查（need_front：FRONT 标记或 A3），偶数位时插空白页推动到奇数位；
      ② 放入原页；
      ③ 封面/签字页/A3 背面空白（A3 背面优先，D6）；
      ④ 补齐末页（可选）。
    每张空白页生成 blank_id（f"blank:{触发源标识}:{来源类型}"），跨 rebuild 稳定。
    """
    plan: list[PageInfo] = []

    def need_front(p: PageInfo) -> bool:
        return (PageMark.FRONT in p.marks) or is_a3(p)

    for p in source_pages:
        # ① 从正面开始检查（物理序号 = len(plan)+1；偶数位=背面）
        if need_front(p) and (len(plan) + 1) % 2 == 0:
            w, h = _adjacent_size(plan, p)
            plan.append(
                make_blank_page(
                    w, h, BlankPageSource.PUSH_FRONT,
                    blank_id=make_blank_id(p.original_index, BlankPageSource.PUSH_FRONT),
                )
            )

        # ② 放入原页
        plan.append(p)

        # ③ 封面/签字/A3 背面空白（A3 背面优先；同页多背面只插一张）
        if is_a3(p):
            plan.append(
                make_blank_page(
                    p.width_mm, p.height_mm, BlankPageSource.A3_BACK,
                    blank_id=make_blank_id(p.original_index, BlankPageSource.A3_BACK),
                )
            )
        elif PageMark.COVER in p.marks:
            plan.append(
                make_blank_page(
                    p.width_mm, p.height_mm, BlankPageSource.COVER_BACK,
                    blank_id=make_blank_id(p.original_index, BlankPageSource.COVER_BACK),
                )
            )
        elif PageMark.SIGNATURE in p.marks:
            plan.append(
                make_blank_page(
                    p.width_mm, p.height_mm, BlankPageSource.SIGN_BACK,
                    blank_id=make_blank_id(p.original_index, BlankPageSource.SIGN_BACK),
                )
            )

    # ④ 补齐末页
    if config.auto_fill_last_page and len(plan) % 2 == 1:
        last = plan[-1]
        plan.append(
            make_blank_page(
                last.width_mm, last.height_mm, BlankPageSource.FILL_LAST,
                blank_id=make_blank_id("last", BlankPageSource.FILL_LAST),
            )
        )

    return plan


# ---------------------------------------------------------------------------
# 算法 2：页码数字规划
# ---------------------------------------------------------------------------
def plan_page_numbers(
    plan: list[PageInfo], start_number: int, auto_number_blank_pages: bool = False
) -> list[ProcessedPage]:
    """遍历物理顺序列表，按 blank_source / marks 决定页码数字与是否占序号。

    规则（技术方案 3.2 + 规则变更《多选批量与空白页配置_提示语》0.1）：
      SIGN_BACK / A3_BACK：不显示、不占序号（来源驱动，不变）；
      COVER_BACK / PUSH_FRONT / FILL_LAST：显示、占序号（来源驱动，不变）；
      空白页编页码开关（功能增强：auto_number_blank_pages，默认关）：
        关 → PUSH_FRONT / FILL_LAST 也不显示、不占序号（后续顺延）；开 → 当前行为；
      COVER_BACK 不受开关控制（始终显示、占序号）；
      空白页用户显式标记 NO_NUMBER：覆盖来源默认 → 无数字、不占序号（覆盖优先级：
        用户显式标记 > 开关 > 来源默认；空白页无 original_index，marks 即用户显式配置）；
      NO_NUMBER（原页）：保留内容、不显示、**跳过序号**（新语义：不占序号，后续顺延前移）；
      其余原页：显示、占序号。
    """
    seq = start_number
    out: list[ProcessedPage] = []
    no_number_sources = {
        BlankPageSource.SIGN_BACK,
        BlankPageSource.A3_BACK,
    }
    # 开关关（默认）：PUSH_FRONT / FILL_LAST 也不编页码、不占序号
    if not auto_number_blank_pages:
        no_number_sources.add(BlankPageSource.PUSH_FRONT)
        no_number_sources.add(BlankPageSource.FILL_LAST)

    for physical_index, page in enumerate(plan, start=1):
        is_blank = page.is_blank
        blank_source = page.blank_source
        # NO_COUNT 已废弃（迁移为 NO_NUMBER）：残留时按 NO_NUMBER 处理
        # （内容保留 + 跳过序号，旧"丢弃内容"路径已删除，行为等价）
        user_no_number = (
            PageMark.NO_NUMBER in page.marks or PageMark.NO_COUNT in page.marks
        )
        number_text: str | None = None
        number_occupies: bool = False

        if is_blank:
            if user_no_number or blank_source in no_number_sources:
                number_text = None
                number_occupies = False
            else:  # COVER_BACK / PUSH_FRONT / FILL_LAST（用户未显式覆盖）
                number_text = str(seq)
                number_occupies = True
                seq += 1
        elif user_no_number:  # 原页"不加页码"：跳过序号（后续页码顺延前移）
            number_text = None
            number_occupies = False
        else:
            number_text = str(seq)
            number_occupies = True
            seq += 1

        out.append(
            ProcessedPage(
                physical_index=physical_index,
                source_page_info=page,
                is_blank=is_blank,
                blank_source=blank_source,
                number_text=number_text,
                number_occupies=number_occupies,
                number_position=PageNumberPos.BOTTOM_RIGHT,  # 算法 4 阶段修正
                number_point=None,
                rotation=page.planned_rotation,
                output_size_mm=_rotated_size(page, page.planned_rotation),
            )
        )
    return out


# ---------------------------------------------------------------------------
# 算法 3：页面旋转
# ---------------------------------------------------------------------------
def detect_text_rotation(page_text_data: dict) -> int:
    """文字方向检测：返回让主导文字朝右所需的旋转角（0/90/180/270）。

    原理：统计页面上各 line 的 dir 向量（按字符数加权），把方向量化到
    4 个主方向（PDF 文本 dir 可能有微小浮点误差，直接比较 exact match 不可靠，
    用"水平/垂直哪个分量大"归类），找到占主导地位的文字方向，返回需要旋转的
    角度使旋转后文字水平正向可读（dir=(1,0)，朝右）。

    对应关系：
      dir=(1, 0)   → 已朝右，不旋转 → 0
      dir=(0, 1)   → 文字向上，顺时针 90° 后朝右 → 90
      dir=(-1, 0)  → 文字反向，旋转 180° 后朝右 → 180
      dir=(0, -1)  → 文字向下，逆时针 90° 后朝右 → 270

    无文字时返回 90（回退默认，UI 提示用户确认）。
    输入：PyMuPDF `get_text("dict")` 的返回。
    """
    blocks = page_text_data.get("blocks", []) if isinstance(page_text_data, dict) else []
    # 统计各 line 方向（量化到 4 主方向），按文本量（字符数）加权
    dir_weight: dict[tuple, float] = {}
    for block in blocks:
        if not isinstance(block, dict) or block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            chars = sum(len(span.get("text", "")) for span in spans)
            if chars <= 0:
                continue
            d = line.get("dir")
            if d is None:
                continue
            dx, dy = float(d[0]), float(d[1])
            if abs(dx) > abs(dy):
                quantized = (1.0 if dx > 0 else -1.0, 0.0)
            else:
                quantized = (0.0, 1.0 if dy > 0 else -1.0)
            dir_weight[quantized] = dir_weight.get(quantized, 0.0) + chars

    if not dir_weight:
        return 90  # 无文字 → 回退默认 90

    dominant = max(dir_weight, key=dir_weight.get)

    if dominant == (1.0, 0.0):
        return 0
    if dominant == (0.0, 1.0):
        return 90
    if dominant == (-1.0, 0.0):
        return 180
    if dominant == (0.0, -1.0):
        return 270
    return 90  # fallback


def plan_rotation(
    page: PageInfo, page_text_data: dict | None = None
) -> tuple[int, tuple[float, float]]:
    """按判定表（技术方案 3.3.1）决定是否需要旋转与旋转后尺寸。

    对需旋转页（A4 横向、A3 纵向）调用 detect_text_rotation 填充 detected_rotation。
    返回 (detected_rotation, 旋转后尺寸 mm)；180° 与 0° 一样不交换宽高
    （由 _rotated_size 统一处理）。
    """
    w, h = page.width_mm, page.height_mm
    if _approx(w, A3_WIDTH_MM) and _approx(h, A3_HEIGHT_MM):  # A3 纵向 → 需旋转
        r = detect_text_rotation(page_text_data) if page_text_data is not None else 90
        page.detected_rotation = r
        return r, _rotated_size(page, r)
    if _approx(w, A3_HEIGHT_MM) and _approx(h, A3_WIDTH_MM):  # A3 横向 → 不旋转
        page.detected_rotation = 0
        return 0, (A3_WIDTH_MM, A3_HEIGHT_MM)
    if _approx(w, A4_HEIGHT_MM) and _approx(h, A4_WIDTH_MM):  # A4 横向 → 需旋转
        r = detect_text_rotation(page_text_data) if page_text_data is not None else 90
        page.detected_rotation = r
        return r, _rotated_size(page, r)
    if _approx(w, A4_WIDTH_MM) and _approx(h, A4_HEIGHT_MM):  # A4 纵向 → 不旋转
        page.detected_rotation = 0
        return 0, (A4_WIDTH_MM, A4_HEIGHT_MM)
    # 其他尺寸（D3）：不旋转
    page.detected_rotation = 0
    return 0, (w, h)


def final_rotation(page: PageInfo) -> int:
    """最终旋转角（问题 3 修改）：用户可用 rotation_override 覆盖自动检测结果。"""
    o = page.rotation_override
    if o is RotationOverride.AUTO:
        return page.detected_rotation
    if o is RotationOverride.CW90:
        return 90
    if o is RotationOverride.CCW90:
        return 270
    if o is RotationOverride.ROT180:
        return 180
    if o is RotationOverride.NONE:
        return 0
    return page.detected_rotation


# ---------------------------------------------------------------------------
# 算法 4：页码坐标计算
# ---------------------------------------------------------------------------
def _base_position(
    page: ProcessedPage, style: PageNumberStyle | None = None
) -> PageNumberPos:
    """确定该页的基准页码位置（不含 CUSTOM 偏移）。

    水平方向：单页覆盖优先；A3 固定右；物理奇页右、偶页左。
    垂直方向：由样式 vertical_position 决定（top/bottom，功能增强）；
    CUSTOM 保持历史行为（奇偶决定左下/右下基准）。
    """
    ov = page.source_page_info.number_pos_override
    if ov is not None and ov is not PageNumberPos.CUSTOM:
        return ov
    if ov is PageNumberPos.CUSTOM:
        # 自定义：保持历史行为（奇偶决定左下/右下基准，垂直底部）
        if page.physical_index % 2 == 1:
            return PageNumberPos.BOTTOM_RIGHT
        return PageNumberPos.BOTTOM_LEFT
    is_top = bool(style is not None and style.vertical_position == "top")
    right = PageNumberPos.TOP_RIGHT if is_top else PageNumberPos.BOTTOM_RIGHT
    left = PageNumberPos.TOP_LEFT if is_top else PageNumberPos.BOTTOM_LEFT
    if is_a3(page.source_page_info):
        return right  # A3 横向位置固定右，垂直跟随全局
    if page.physical_index % 2 == 1:
        return right  # 物理奇数页（正面）
    return left      # 物理偶数页（背面）


def calculate_number_position(
    page: ProcessedPage,
    style: PageNumberStyle,
    physical_index: int,
    text_width_pt: float,
) -> tuple[float, float] | None:
    """计算页码文字在 PDF 未旋转坐标系中的绘制点 (x, y)（pt）。

    page: 已含 output_size_mm / rotation 的 ProcessedPage。
    style: 页码样式（全局或单页覆盖）。
    physical_index: 物理顺序（1-based）。
    text_width_pt: 页码文字宽度（pt），由调用方计算后传入（引擎保持纯计算）。
    """
    if page.number_text is None:
        return None

    # 显示坐标系（旋转后页面）尺寸 pt
    out_w_mm, out_h_mm = page.output_size_mm
    W = out_w_mm * MM_TO_PT
    H = out_h_mm * MM_TO_PT

    right_pt = style.margin_right_mm * MM_TO_PT
    left_pt = style.margin_left_mm * MM_TO_PT
    bottom_pt = style.margin_bottom_mm * MM_TO_PT
    top_pt = style.margin_top_mm * MM_TO_PT

    ov = page.source_page_info.number_pos_override
    base = _base_position(page, style)

    # 自定义偏移（mm→pt；相对基准角向内为正，D8）
    custom_dx = custom_dy = 0.0
    if ov is PageNumberPos.CUSTOM and page.source_page_info.number_custom_offset_mm:
        custom_dx, custom_dy = page.source_page_info.number_custom_offset_mm
        custom_dx *= MM_TO_PT
        custom_dy *= MM_TO_PT

    if base is PageNumberPos.BOTTOM_LEFT:
        anchor_x = left_pt + custom_dx
        anchor_y = bottom_pt + custom_dy
    elif base is PageNumberPos.BOTTOM_RIGHT:
        anchor_x = W - right_pt - text_width_pt - custom_dx
        anchor_y = bottom_pt + custom_dy
    elif base is PageNumberPos.TOP_LEFT:
        anchor_x = left_pt + custom_dx
        # 顶部：anchor 为文字基线，须向上让出字高 ascent，
        # 使"页码文字顶部"距页顶 = margin_top（与底部 bbox 底距页底对称）。
        anchor_y = H - top_pt - style.fontsize_pt * 0.8 - custom_dy
    elif base is PageNumberPos.TOP_RIGHT:
        anchor_x = W - right_pt - text_width_pt - custom_dx
        anchor_y = H - top_pt - style.fontsize_pt * 0.8 - custom_dy
    else:  # 兜底（不应发生）
        anchor_x = W - right_pt - text_width_pt
        anchor_y = bottom_pt

    # 若该页总旋转角 ≠ 0，则把显示坐标经 derotation 变换为未旋转坐标。
    # 总旋转 = 源页自带 /Rotate + 规划旋转（二者都会反映在输出页 /Rotate 上）；
    # 仅用 planned_rotation 会在源页带 /Rotate 时（扫描件常见）导致页码坐标
    # 与输出页 MediaBox 坐标系错位（如页码越界/跑到顶部）。
    total_rotation = (page.source_page_info.source_rotation + page.rotation) % 360
    if total_rotation != 0:
        x0, y0 = _derotate(anchor_x, anchor_y, total_rotation, W, H)
    else:
        x0, y0 = anchor_x, anchor_y

    return (x0, y0)


# ---------------------------------------------------------------------------
# 算法 5：重叠检测
# ---------------------------------------------------------------------------
OVERLAP_TOLERANCE_PT = 0.5  # 相交判定容差，避免像素级擦边误报


def rects_intersect(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
    tol: float = OVERLAP_TOLERANCE_PT,
) -> bool:
    """两个轴对齐矩形是否实质重叠（含容差，避免像素级擦边误报）。

    重叠区域的宽与高都必须 > tol 才算重叠：贴边 / 间隙 ≤ tol 的擦边情况不误报。
    """
    overlap_w = min(a[2], b[2]) - max(a[0], b[0])
    overlap_h = min(a[3], b[3]) - max(a[1], b[1])
    return overlap_w > tol and overlap_h > tol


def intersection_rect(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    return (
        max(a[0], b[0]),
        max(a[1], b[1]),
        min(a[2], b[2]),
        min(a[3], b[3]),
    )


def number_rect_from_anchor(
    anchor: tuple[float, float], text_width_pt: float, fontsize_pt: float
) -> tuple[float, float, float, float]:
    """由文字左下基点估算页码文字包围盒（显示坐标 pt）。"""
    x, y = anchor
    height = fontsize_pt * 1.0  # 字体高度近似
    ascent = fontsize_pt * 0.8
    return (x, y - height, x + text_width_pt, y + ascent)


def detect_overlap(
    number_rect: tuple[float, float, float, float],
    text_bboxes: list[tuple[float, float, float, float]],
) -> OverlapWarning | None:
    """检测页码矩形与文本块列表是否重叠（仅文本块，D9）。"""
    for tb in text_bboxes:
        if rects_intersect(number_rect, tb):
            return OverlapWarning(
                physical_index=0,  # 由调用方回填
                number_text="",
                overlap_rect_pt=intersection_rect(number_rect, tb),
            )
    return None


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------
def _estimate_text_width(text: str, fontsize_pt: float) -> float:
    """无文字宽度回调时的粗略估计（引擎独立测试用）。"""
    return len(text) * fontsize_pt * 0.5


def build_process_plan(
    source_pages: list[PageInfo],
    config: DocumentConfig,
    page_text_data: dict[int, dict] | None = None,
    text_width_calculator=None,
    text_block_calculator=None,
    blank_configs: dict[str, set[PageMark]] | None = None,
) -> ProcessPlan:
    """串联算法 1→3→2→4→5，产出完整 ProcessPlan。

    page_text_data: {原始页索引(0-based): get_text("dict") 结果}，用于文字方向检测。
    text_width_calculator: f(text, fontsize) -> pt，页码文字宽度；None 时用粗略估计。
    text_block_calculator: f(原始页索引) -> [(x0,y0,x1,y1) 显示坐标文本块] | None；
        用于重叠检测；None 时跳过重叠检测。
    blank_configs: {blank_id: 用户显式标记集}，应用到自动插入的空白页
        （覆盖来源默认页码行为；blank_id 见 make_blank_id）。
    """
    # 算法 1：物理顺序
    plan = plan_physical_order(source_pages, config)

    # 空白页用户显式配置（任务 2）：把 blank_configs 中的标记应用到对应空白页
    if blank_configs:
        for p in plan:
            if p.is_blank and p.blank_id and p.blank_id in blank_configs:
                p.marks.update(blank_configs[p.blank_id])

    # 算法 3：旋转（填充 detected_rotation / planned_rotation）
    for i, p in enumerate(plan):
        if p.is_blank:
            # 空白页继承同纸正面页（前一元素 plan[i-1]）的旋转，保证正背面方向一致
            # （Bug 修复：空白页方向与同纸正面不一致——根因是空白页 rotation 固定 0；
            #  继承点放在这里而非 plan_physical_order 创建时，因为源页 planned_rotation
            #  此时才计算完成）
            p.detected_rotation = 0
            p.planned_rotation = plan[i - 1].planned_rotation if i > 0 else 0
            continue
        text = None
        if page_text_data is not None and p.original_index is not None:
            text = page_text_data.get(p.original_index)
        det, _ = plan_rotation(p, text)
        p.planned_rotation = final_rotation(p)

    # 算法 2：页码规划
    processed = plan_page_numbers(
        plan, config.start_page_number,
        auto_number_blank_pages=config.auto_number_blank_pages)

    # 算法 4：页码坐标
    warnings: list[OverlapWarning] = []
    for pp in processed:
        if pp.number_text is None:
            continue
        style = pp.source_page_info.style_override or config.global_style
        if text_width_calculator is not None:
            text_w = text_width_calculator(pp.number_text, style.fontsize_pt)
        else:
            text_w = _estimate_text_width(pp.number_text, style.fontsize_pt)
        pt = calculate_number_position(pp, style, pp.physical_index, text_w)
        pp.number_point = pt
        pp.number_position = _base_position(pp, style)

        # 算法 5：重叠检测
        if pt is not None and text_block_calculator is not None:
            src_idx = pp.source_page_info.original_index
            blocks = text_block_calculator(src_idx) if src_idx is not None else None
            if blocks:
                W = pp.output_size_mm[0] * MM_TO_PT
                anchor_disp = _display_anchor(pp, style, text_w, W)
                num_rect = number_rect_from_anchor(anchor_disp, text_w, style.fontsize_pt)
                ov = detect_overlap(num_rect, blocks)
                if ov is not None:
                    ov.physical_index = pp.physical_index
                    ov.number_text = pp.number_text
                    warnings.append(ov)

    return ProcessPlan(
        pages=processed,
        start_page_number=config.start_page_number,
        warnings=warnings,
        output_path="",
    )


def _display_anchor(
    pp: ProcessedPage, style: PageNumberStyle, text_width_pt: float, display_w_pt: float
) -> tuple[float, float]:
    """计算页码在显示坐标系中的左下基点（供重叠检测）。

    坐标系与 text_block_calculator 返回的 bbox 一致：显示坐标、左上原点、y 向下。
    （Bug 修复：原实现把"距底边距"直接当 y，导致重叠检测在页面顶部检测，
    与页码实际位置（底部）错位；现按显示坐标换算。）
    垂直位置：底部 y=H-bottom、顶部 y=top。
    """
    right_pt = style.margin_right_mm * MM_TO_PT
    left_pt = style.margin_left_mm * MM_TO_PT
    bottom_pt = style.margin_bottom_mm * MM_TO_PT
    top_pt = style.margin_top_mm * MM_TO_PT
    H = pp.output_size_mm[1] * MM_TO_PT  # 显示高度（pt）
    base = _base_position(pp, style)

    # 自定义偏移（mm→pt；相对基准角向内为正，D8）——与算法 4 一致
    custom_dx = custom_dy = 0.0
    ov = pp.source_page_info.number_pos_override
    if ov is PageNumberPos.CUSTOM and pp.source_page_info.number_custom_offset_mm:
        custom_dx, custom_dy = pp.source_page_info.number_custom_offset_mm
        custom_dx *= MM_TO_PT
        custom_dy *= MM_TO_PT

    if base is PageNumberPos.BOTTOM_LEFT:
        return (left_pt + custom_dx, H - bottom_pt - custom_dy)
    if base is PageNumberPos.BOTTOM_RIGHT:
        return (display_w_pt - right_pt - text_width_pt - custom_dx, H - bottom_pt - custom_dy)
    if base is PageNumberPos.TOP_LEFT:
        # 显示坐标 y 向下：基线 = top_pt + ascent（文字顶部距页顶 = margin_top）
        return (left_pt + custom_dx, top_pt + style.fontsize_pt * 0.8 + custom_dy)
    if base is PageNumberPos.TOP_RIGHT:
        return (display_w_pt - right_pt - text_width_pt - custom_dx,
                top_pt + style.fontsize_pt * 0.8 + custom_dy)
    return (display_w_pt - right_pt - text_width_pt, H - bottom_pt)
