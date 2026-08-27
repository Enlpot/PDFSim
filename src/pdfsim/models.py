# -*- coding: utf-8 -*-
"""数据结构定义（依据《技术方案.md》第 2 章，已冻结）。

所有物理顺序索引均为 1-based；与源 PDF 页的对应关系在模型层使用 0-based 原始索引并显式标注。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
MM_TO_PT: float = 72 / 25.4  # 1mm ≈ 2.8346 pt
SIZE_TOLERANCE_MM: float = 2.0  # 尺寸匹配容差（D7：±2mm）

# 标准页面标称尺寸（mm）
A4_WIDTH_MM = 210.0
A4_HEIGHT_MM = 297.0
A3_WIDTH_MM = 297.0
A3_HEIGHT_MM = 420.0


# ---------------------------------------------------------------------------
# 枚举
# ---------------------------------------------------------------------------
class PageMark(str, Enum):
    """页面标记（可多选）。

    规则变更（《多选批量与空白页配置_提示语》0.1）：不加页码新语义——
    保留内容、不显示页码数字、序号跳过（后续页码顺延前移）。
    """
    COVER = "cover"        # 封面
    SIGNATURE = "signature"  # 签字页
    NO_NUMBER = "no_number"  # 不加页码：保留内容，不显示页码数字，序号跳过
    NO_COUNT = "no_count"    # 已废弃（用户标记路径废除）：旧语义为"丢弃内容+不占序号"，
    #                        违反内容保护铁律，迁移时映射为 NO_NUMBER（保留枚举仅供旧配置迁移/序列化兼容）
    FRONT = "front"          # 从正面开始（目标页须落在纸张正面=物理奇数位）


class BlankPageSource(str, Enum):
    """空白页的来源类型（决定尺寸、是否有页码、是否占序号）。"""
    COVER_BACK = "cover_back"      # 封面背面：与封面同尺寸，有页码，占序号
    SIGN_BACK = "sign_back"        # 签字页背面：与签字页同尺寸，无页码，不占序号
    NO_COUNT_USER = "no_count_user"  # 已废弃（旧"不占序号"用户标记产物，不再产生；保留枚举供序列化兼容）
    PUSH_FRONT = "push_front"      # 推动某页到正面：与前一页同尺寸（D5），有页码，占序号
    A3_BACK = "a3_back"            # A3 页背面：与该 A3 页同尺寸，无页码，不占序号
    FILL_LAST = "fill_last"        # 补齐末页：与最后一页同尺寸，有页码，占序号


class PageOrientation(str, Enum):
    """页面方向。"""
    PORTRAIT = "portrait"    # 纵向
    LANDSCAPE = "landscape"  # 横向


class PageNumberPos(str, Enum):
    """页码位置。"""
    BOTTOM_RIGHT = "bottom_right"  # 右下角（物理奇数页默认、A3 页横向位置固定）
    BOTTOM_LEFT = "bottom_left"    # 左下角（物理偶数页默认）
    TOP_RIGHT = "top_right"        # 右上角
    TOP_LEFT = "top_left"          # 左上角
    CUSTOM = "custom"              # 自定义（用户输入 x/y 偏移量，单位 mm）


class VerticalPosition(str, Enum):
    """页码垂直位置（全局/单页样式，功能增强：距上/距下）。"""
    BOTTOM = "bottom"    # 底部（默认，向后兼容）
    TOP = "top"          # 顶部


class RotationOverride(str, Enum):
    """旋转方向覆盖（问题 3 修改）：每页可选，默认自动检测。"""
    AUTO = "auto"    # 自动检测（默认）：采用 detected_rotation
    CW90 = "cw90"    # 顺时针 90°
    CCW90 = "ccw90"  # 逆时针 90°
    NONE = "none"    # 不旋转


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------
@dataclass
class PageInfo:
    """
    单页信息。一个 PageInfo 对应"一个物理页面"（既包括原页，也包括自动插入的空白页）。
    """
    original_index: int | None             # 原始 PDF 页索引（0-based）；空白页为 None
    width_mm: float                        # 页面物理宽度（mm，按显示尺寸；已计入源页自带 /Rotate）
    height_mm: float                       # 页面物理高度（mm）
    source_rotation: int = 0               # 源页自带的 /Rotate（0/90/180/270）
    detected_rotation: int = 0             # 文字方向检测结果（0/90/270，问题 3 修改；算法 3 填充）
    planned_rotation: int = 0              # 最终旋转角（受 rotation_override 影响；0/90/270）
    rotation_override: RotationOverride = RotationOverride.AUTO  # 旋转方向覆盖
    marks: set[PageMark] = field(default_factory=set)             # 页面标记集合（可多选）
    custom_labels: list[str] = field(default_factory=list)        # 用户自定义标签（仅展示）
    is_blank: bool = False                 # 是否为空白页
    blank_source: BlankPageSource | None = None                   # 空白页来源类型；非空白页为 None
    number_pos_override: PageNumberPos | None = None              # 页码位置单页覆盖；None=沿用全局
    number_custom_offset_mm: tuple[float, float] | None = None    # 自定义页码偏移(x,y)（mm）
    style_override: "PageNumberStyle | None" = None               # 页码样式单页覆盖；None=沿用全局
    blank_id: str | None = None                # 空白页稳定标识（如 "blank:0:cover_back"）；
    #                                           跨 rebuild 稳定，用于空白页配置持久化；非空白页为 None


@dataclass
class PageNumberStyle:
    """页码样式（全局默认 + 每页可覆盖）。"""
    font: str = "Times New Roman"      # 字体（默认 Times New Roman）
    fontsize_pt: float = 9.0           # 字号，默认小五 9pt
    color: tuple[int, int, int] = (0, 0, 0)   # 颜色 RGB，默认黑色
    margin_right_mm: float = 10.0      # 距右边缘（mm），默认 10
    margin_left_mm: float = 10.0       # 距左边缘（mm），默认 10
    margin_bottom_mm: float = 10.0     # 距下边缘（mm），默认 10
    margin_top_mm: float = 10.0        # 距上边缘（mm），默认 10（功能增强：顶部位置）
    vertical_position: str = "bottom"  # 垂直位置："bottom"/"top"（默认底部，向后兼容）


@dataclass
class DocumentConfig:
    """文档级配置。"""
    version: int = 1                        # 配置格式版本号
    start_page_number: int = 1              # 起始页码，默认 1
    global_style: PageNumberStyle = field(default_factory=PageNumberStyle)  # 全局页码样式
    auto_detect_keywords: dict = field(default_factory=lambda: {
        PageMark.COVER: ["封面", "cover"],
        PageMark.SIGNATURE: ["签字", "签名", "signature", "sign"],
        PageMark.FRONT: ["目录", "contents"],   # 目录起始页 → 从正面开始
        "body": ["正文", "body"],               # 正文第一页 → 从正面开始（默认内置）
    })
    custom_labels: list[str] = field(default_factory=list)   # 用户可添加的自定义关键词
    auto_fill_last_page: bool = False       # 自动补齐末页，默认否
    auto_number_blank_pages: bool = False   # 其他空白页自动编页码（PUSH_FRONT/FILL_LAST），默认关
    output_dir: str = ""                    # 输出目录，默认空=原 PDF 所在文件夹
    output_suffix: str = "（打印装订）"       # 输出文件名后缀
    config_filename: str = ""               # 配置文件路径（打开时确定）


@dataclass
class ProcessedPage:
    """
    处理后页面——输出/预览的唯一事实来源（Source of Truth）。
    """
    physical_index: int                   # 物理顺序索引（1-based，含所有空白页）
    source_page_info: PageInfo            # 对应源页信息（空白页的 source 引用自身 is_blank=True）
    is_blank: bool                        # 是否空白页
    blank_source: BlankPageSource | None  # 空白页来源类型
    number_text: str | None               # 该页应显示的页码数字字符串；不加页码/不占序号/背面空白为 None
    number_occupies: bool                 # 是否占序号（用于下一页计数）
    number_position: PageNumberPos        # 最终页码位置（含 A3 固定右下角后的判定结果）
    number_point: tuple[float, float] | None  # 页码文字绘制点（PDF 未旋转坐标 pt）；无页码为 None
    rotation: int                         # 输出时该页的最终旋转角（0/90/180/270）
    output_size_mm: tuple[float, float]   # 输出页最终尺寸（宽×高，mm，旋转后）


@dataclass
class OverlapWarning:
    """重叠检测警告（仅提示，不阻止输出）。"""
    physical_index: int                   # 发生重叠的物理页
    number_text: str                      # 页码文字
    overlap_rect_pt: tuple[float, float, float, float]  # 重叠区域（显示坐标 pt）


@dataclass
class ProcessPlan:
    """一次完整处理规划的结果。"""
    pages: list[ProcessedPage]        # 按物理顺序排列
    start_page_number: int            # 实际起始页码
    warnings: list[OverlapWarning]    # 重叠检测警告
    output_path: str                  # 输出文件路径


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------
def _approx(value: float, target: float, tolerance: float = SIZE_TOLERANCE_MM) -> bool:
    """数值在目标值 ± tolerance 内。"""
    return abs(value - target) <= tolerance


def is_a3(page: PageInfo) -> bool:
    """判断页面是否为 A3 尺寸（显示尺寸，含 ±2mm 容差）。"""
    w, h = page.width_mm, page.height_mm
    return (_approx(w, A3_WIDTH_MM) and _approx(h, A3_HEIGHT_MM)) or (
        _approx(w, A3_HEIGHT_MM) and _approx(h, A3_WIDTH_MM))


def is_a4(page: PageInfo) -> bool:
    """判断页面是否为 A4 尺寸（显示尺寸，含 ±2mm 容差）。"""
    w, h = page.width_mm, page.height_mm
    return (_approx(w, A4_WIDTH_MM) and _approx(h, A4_HEIGHT_MM)) or (
        _approx(w, A4_HEIGHT_MM) and _approx(h, A4_WIDTH_MM))
