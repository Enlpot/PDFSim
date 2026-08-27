# -*- coding: utf-8 -*-
"""缩略图列表面板（依据《Stage3_提示语.md》5.4 与《UI原型说明.md》第 3 章）。

按物理页面顺序排列（含空白页）；每项：缩略图 + 物理序号 + 页码预览 + 标记徽标。
点击缩略图 → 书视图跳转高亮；与书视图双向同步。

性能优化 P1-4（缩略图虚拟化）：QListWidget + 自定义 delegate，
只创建轻量 QListWidgetItem（800 页不再实例化 800 个 QWidget），
delegate 仅绘制可见项；缩略图 PNG 仍按需懒加载并缓存于 delegate。
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QListView,
    QListWidget,
    QListWidgetItem,
    QStyle,
    QStyledItemDelegate,
    QWidget,
)

from pdfsim.models import PageMark
from pdfsim.ui.styles import (
    COLOR_BLANK_BADGE,
    COLOR_MARK_COVER,
    COLOR_MARK_CUSTOM,
    COLOR_MARK_FRONT,
    COLOR_MARK_NO_COUNT,
    COLOR_MARK_NO_NUMBER,
    COLOR_MARK_SIGN,
    COLOR_ROTATE_BADGE,
    COLOR_SELECTED_ITEM,
    FONT_DEFAULT,
    PADDING_THUMBNAIL_ITEM,
    SPACING_THUMBNAIL,
    THUMBNAIL_MAX_HEIGHT,
    THUMBNAIL_WIDTH,
)

# 徽标定义：(文字, 颜色, 是否斜杠, 是否虚线)
_BADGES = [
    (PageMark.COVER, "封", COLOR_MARK_COVER, False, False),
    (PageMark.SIGNATURE, "签", COLOR_MARK_SIGN, False, False),
    (PageMark.NO_NUMBER, "无", COLOR_MARK_NO_NUMBER, False, False),
    (PageMark.NO_COUNT, "弃", COLOR_MARK_NO_COUNT, True, False),
    (PageMark.FRONT, "正", COLOR_MARK_FRONT, False, False),
]

_ITEM_HEIGHT = THUMBNAIL_MAX_HEIGHT + 28 + PADDING_THUMBNAIL_ITEM * 2


class _ThumbDelegate(QStyledItemDelegate):
    """缩略图绘制委托（只绘制可见项；缩略图 PNG 懒加载缓存）。"""

    def __init__(self, panel: "ThumbnailPanel") -> None:
        super().__init__(panel)
        self._panel = panel
        self._pix_cache: dict[int, QPixmap] = {}

    def reset_cache(self) -> None:
        self._pix_cache.clear()

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        return QSize(THUMBNAIL_WIDTH + PADDING_THUMBNAIL_ITEM * 2, _ITEM_HEIGHT)

    # ------------------------------------------------------------------
    def _pixmap(self, phys: int) -> QPixmap:
        cached = self._pix_cache.get(phys)
        if cached is not None:
            return cached
        data = self._panel.controller.get_thumbnail(phys)
        pix = QPixmap()
        if data:
            pix.loadFromData(data)
        else:
            pix = QPixmap(1, 1)
            pix.fill(QColor("white"))
        # 缩略图宽度适配（与旧 ThumbnailItem 一致）
        if pix.width() > THUMBNAIL_WIDTH:
            h = max(1, int(pix.height() * THUMBNAIL_WIDTH / pix.width()))
            if h > THUMBNAIL_MAX_HEIGHT:
                w = int(pix.width() * THUMBNAIL_MAX_HEIGHT / pix.height())
                pix = pix.scaled(w, THUMBNAIL_MAX_HEIGHT,
                                 Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
            else:
                pix = pix.scaled(THUMBNAIL_WIDTH, h,
                                 Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
        self._pix_cache[phys] = pix
        return pix

    def paint(self, painter, option, index) -> None:  # noqa: N802
        phys = index.data(Qt.ItemDataRole.UserRole)
        if phys is None:
            return
        controller = self._panel.controller
        pp = controller.processed_page(phys)
        if pp is None:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = option.rect

        # 选中高亮
        if option.state & QStyle.StateFlag.State_Selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(COLOR_SELECTED_ITEM))
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 4, 4)

        # 缩略图
        pix = self._pixmap(phys)
        img_w, img_h = pix.width(), pix.height()
        x = rect.left() + (rect.width() - img_w) / 2
        y = rect.top() + PADDING_THUMBNAIL_ITEM
        painter.drawPixmap(int(x), int(y), pix)
        painter.setPen(QPen(QColor("#D0D0D0"), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(int(x), int(y), int(img_w), int(img_h))

        font = QFont(FONT_DEFAULT, 8)
        painter.setFont(font)
        fm = painter.fontMetrics()
        base_y = y + img_h

        # 物理序号（左下）
        painter.setPen(QColor("#333333"))
        painter.drawText(rect.left() + 4, base_y + 16, str(phys))

        # 页码预览（右下）
        num_text = self._number_preview(pp, phys)
        tw = fm.horizontalAdvance(num_text)
        painter.setPen(QColor("#555555"))
        painter.drawText(rect.right() - 4 - tw, base_y + 16, num_text)

        # 标记徽标（右上）
        self._paint_badges(painter, x, y, img_w, pp, phys)

        painter.restore()

    # ------------------------------------------------------------------
    def _number_preview(self, pp, phys: int) -> str:
        if pp.number_text is not None:
            return pp.number_text
        if pp.source_page_info is not None and PageMark.NO_NUMBER in pp.source_page_info.marks:
            return f"({phys})"
        return "—"

    def _paint_badges(self, painter, x, y, img_w, pp, phys) -> None:
        marks = pp.source_page_info.marks if pp.source_page_info is not None else set()
        labels = []
        for mark, text, color, slash, dash in _BADGES:
            if mark in marks:
                labels.append((text, color, slash, dash))
        if pp.is_blank:
            labels.append(("空", COLOR_BLANK_BADGE, False, False))
        if not pp.is_blank and pp.rotation in (90, 270):
            labels.append(("旋", COLOR_ROTATE_BADGE, False, True))
        custom = list(pp.source_page_info.custom_labels) if pp.source_page_info else []

        font = QFont(FONT_DEFAULT, 8)
        painter.setFont(font)
        fm = painter.fontMetrics()
        badge_h = 18
        shown = labels[:4]
        overflow = len(labels) - 4
        bx = x + img_w
        for text, color, slash, dash in shown:
            tw = fm.horizontalAdvance(text) + 8
            bx -= tw + 2
            if dash:
                pen = QPen(QColor(color), 1, Qt.PenStyle.DashLine)
                painter.setPen(pen)
                painter.setBrush(QColor(color).lighter(185))
            elif slash:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(color))
            else:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(color))
            painter.drawRoundedRect(int(bx), int(y), int(tw), badge_h, 3, 3)
            if slash:
                painter.setPen(QPen(QColor("white"), 1))
                painter.drawLine(int(bx + 3), int(y + badge_h - 3),
                                 int(bx + tw - 3), int(y + 3))
            painter.setPen(QColor("white"))
            painter.drawText(int(bx + 4), int(y + fm.ascent() + 4), text)
        if overflow > 0:
            tw = fm.horizontalAdvance(f"+{overflow}") + 6
            bx -= tw + 2
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#616161"))
            painter.drawRoundedRect(int(bx), int(y), int(tw), badge_h, 3, 3)
            painter.setPen(QColor("white"))
            painter.drawText(int(bx + 3), int(y + fm.ascent() + 4), f"+{overflow}")

        # 自定义标签（黑色小字，右对齐徽标下方）
        if custom:
            painter.setPen(QColor(COLOR_MARK_CUSTOM))
            py = y + badge_h + 2
            for label in custom[:2]:
                tw = fm.horizontalAdvance(label) + 6
                bx2 = x + img_w - tw
                painter.drawText(int(bx2), int(py + fm.ascent()), label)
                py += fm.height() + 1


class ThumbnailPanel(QListWidget):
    """缩略图列表面板（QListWidget 虚拟化，仅创建轻量 item）。

    多选批量（任务 3）：ExtendedSelection（Ctrl 点选 / Shift 范围选 / 拖框选），
    多选集合同步到 controller（set_selected_pages）；单选走 select_physical。
    """

    def __init__(self, controller=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._items: dict[int, QListWidgetItem] = {}
        self._updating = False
        self.setViewMode(QListView.ViewMode.ListMode)
        # 功能增强（双列）：LeftToRight 流 + 换行 + GridSize，
        # 面板拖宽自动多列、拖窄自动回单列（TopToBottom 流在 wrapping 下不换行，
        # 会导致布局单列且滚动失效，故不用）
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setGridSize(QSize(THUMBNAIL_WIDTH + PADDING_THUMBNAIL_ITEM * 2, _ITEM_HEIGHT))
        self.setUniformItemSizes(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMinimumWidth(160)
        # 功能增强（滚动平滑）：每格滚轮滚动固定小步长，不再"一滚好几行"
        self.verticalScrollBar().setSingleStep(20)
        self.setItemDelegate(_ThumbDelegate(self))
        self.itemSelectionChanged.connect(self._on_view_selection_changed)

    # ------------------------------------------------------------------
    def wheelEvent(self, event) -> None:  # noqa: N802
        """平滑滚动：每格滚轮固定滚动 step px（不随视口高度缩放）。

        键盘 PageUp/PageDown 由 QAbstractItemView 处理，不受影响；
        scrollToItem(EnsureVisible) 定位也不受影响。
        """
        step = 24  # px per notch
        delta = event.angleDelta().y()
        if delta == 0:
            super().wheelEvent(event)
            return
        bar = self.verticalScrollBar()
        bar.setValue(bar.value() - delta * step // 120)
        event.accept()

    # ------------------------------------------------------------------
    def _on_view_selection_changed(self) -> None:
        """用户交互（点击/Ctrl/Shift/拖框）改变选择 → 同步 controller。"""
        if self._updating or self.controller is None:
            return
        selected = sorted(
            it.data(Qt.ItemDataRole.UserRole) for it in self.selectedItems()
            if it.data(Qt.ItemDataRole.UserRole) is not None
        )
        current = self.controller.selected_physical_pages()
        if selected == current:
            return
        if len(selected) <= 1:
            self.controller.select_physical(selected[0] if selected else 1)
        else:
            self.controller.set_selected_pages(selected)

    def rebuild(self) -> None:
        """按当前规划重建列表（只创建轻量 QListWidgetItem，800 页不建 Widget）。"""
        self._updating = True
        try:
            self._items = {}
            self.clear()
            delegate = self.itemDelegate()
            if isinstance(delegate, _ThumbDelegate):
                delegate.reset_cache()
            if self.controller is None:
                return
            count = self.controller.plan_page_count()
            for phys in range(1, count + 1):
                item = QListWidgetItem()
                item.setSizeHint(QSize(THUMBNAIL_WIDTH + PADDING_THUMBNAIL_ITEM * 2,
                                       _ITEM_HEIGHT))
                item.setData(Qt.ItemDataRole.UserRole, phys)
                self.addItem(item)
                self._items[phys] = item
            # 恢复当前多选集合
            for phys in self.controller.selected_physical_pages():
                item = self._items.get(phys)
                if item is not None:
                    item.setSelected(True)
            if count and self.controller.selected_physical_index:
                self._ensure_visible(self.controller.selected_physical_index)
        finally:
            self._updating = False

    def select(self, physical_index: int) -> None:
        """主选中页高亮并滚动到可见（书视图驱动；不破坏多选集合）。"""
        item = self._items.get(physical_index)
        if item is None:
            return
        self._updating = True
        try:
            item.setSelected(True)
            self._ensure_visible(physical_index)
        finally:
            self._updating = False

    def _ensure_visible(self, physical_index: int) -> None:
        item = self._items.get(physical_index)
        if item is not None:
            self.scrollToItem(item, QAbstractItemView.ScrollHint.EnsureVisible)

    def on_plan_changed(self) -> None:
        self.rebuild()

    def on_selection_changed(self, physical_index: int) -> None:
        self.select(physical_index)
