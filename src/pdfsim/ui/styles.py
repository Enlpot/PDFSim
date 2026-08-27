# -*- coding: utf-8 -*-
"""UI 样式常量（依据《Stage3_提示语.md》5.8 与《UI原型说明.md》）。

集中定义颜色、间距、字体、尺寸，保证全界面风格统一。
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# 颜色
# ---------------------------------------------------------------------------
COLOR_HIGHLIGHT = "#4A90D9"         # 高亮光晕（主色）
COLOR_HIGHLIGHT_GLOW = "#7AB8E8"    # 光晕渐变（浅蓝）
COLOR_BLANK_BADGE = "#999999"       # 空白页角标（灰）
COLOR_ROTATE_BADGE = "#5B9BD5"      # 旋转角标（蓝）
COLOR_OVERLAP_WARN = "#FFF3CD"      # 重叠警告背景（浅黄）
COLOR_OVERLAP_TEXT = "#856404"      # 重叠警告文字（深黄）
COLOR_OVERLAP_BADGE = "#E74C3C"     # 重叠警告角标（红）
COLOR_MARK_COVER = "#4A90D9"        # 封面徽标底（蓝）
COLOR_MARK_SIGN = "#E8912D"         # 签字页徽标底（橙）
COLOR_MARK_NO_NUMBER = "#9E9E9E"    # 不加页码徽标底（灰）
COLOR_MARK_NO_COUNT = "#757575"     # 不占序号徽标底（深灰）
COLOR_MARK_FRONT = "#4CAF50"        # 从正面开始徽标底（绿）
COLOR_MARK_CUSTOM = "#424242"       # 自定义标签文字（黑）
COLOR_BLANK_PAGE = "#FFFFFF"        # 空白页纸面
COLOR_PAGE_BORDER = "#D0D0D0"       # 页边框
COLOR_EMPTY_HINT = "#909090"        # 空状态提示文字
COLOR_SELECTED_ITEM = "#E3F0FA"     # 缩略图选中背景
COLOR_BOOK_BG = "#C8C8C8"           # 书视图背景（灰）
COLOR_BOOK_BG_EDGE = "#B0B0B0"      # 书脊阴影
COLOR_BOTTOM_BG = "#FAFAFA"         # 配置面板背景

# ---------------------------------------------------------------------------
# 间距
# ---------------------------------------------------------------------------
SPACING_THUMBNAIL = 8               # 缩略图间距
PADDING_PANEL = 12                  # 面板内边距
PADDING_THUMBNAIL_ITEM = 6          # 缩略图项内边距

# ---------------------------------------------------------------------------
# 字体
# ---------------------------------------------------------------------------
FONT_DEFAULT = "Microsoft YaHei UI"  # 界面字体（中文友好）
FONT_MONO = "Consolas"

# ---------------------------------------------------------------------------
# 尺寸
# ---------------------------------------------------------------------------
THUMBNAIL_WIDTH = 120               # 缩略图宽度 px
THUMBNAIL_MAX_HEIGHT = 170          # 缩略图最大高度 px
BADGE_SIZE = 20                     # 角标大小 px
BOOK_BG_RADIUS = 4                  # 书视图背景圆角

# ---------------------------------------------------------------------------
# 布局比例（依据 UI 原型 1.2）
# ---------------------------------------------------------------------------
LEFT_PANEL_RATIO = 0.18             # 左侧缩略图面板宽度占比
LEFT_PANEL_MIN = 200
LEFT_PANEL_MAX = 480                # 允许拖宽到双列/多列（功能增强：缩略图双列）
BOTTOM_PANEL_RATIO = 0.26           # 底部配置面板高度占比
BOTTOM_PANEL_MIN = 180
WINDOW_DEFAULT_W = 1280
WINDOW_DEFAULT_H = 800
WINDOW_MIN_W = 960
WINDOW_MIN_H = 640

# ---------------------------------------------------------------------------
# 其他
# ---------------------------------------------------------------------------
CONFIG_SAVE_DEBOUNCE_MS = 500       # 配置自动保存防抖
THUMBNAIL_DPI = 96                  # 缩略图渲染 DPI
BOOK_VIEW_DPI = 150                 # 书视图渲染 DPI
