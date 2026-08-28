# -*- coding: utf-8 -*-
"""书视图（依据《Stage3_提示语.md》5.3 与《UI原型说明.md》第 2 章）。

状态机：CLOSED（选中第1页）/ OPEN_LEFT（选中偶数页）/ OPEN_RIGHT（选中奇数页≥3）。
偶数页在左、奇数页在右（物理顺序，含空白页）。
"""
from __future__ import annotations

from enum import Enum

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QRubberBand, QWidget

from pdfsim.ui import dialogs
from pdfsim.ui.styles import (
    COLOR_BLANK_BADGE,
    COLOR_BOOK_BG,
    COLOR_BOOK_BG_EDGE,
    COLOR_HIGHLIGHT,
    COLOR_HIGHLIGHT_GLOW,
    COLOR_OVERLAP_BADGE,
    COLOR_AUTO_ADJUST,
    COLOR_PAGE_BORDER,
    COLOR_ROTATE_BADGE,
    FONT_DEFAULT,
)


class BookViewState(Enum):
    CLOSED = "closed"         # 选中第 1 页：单页居右
    OPEN_LEFT = "open_left"   # 选中偶数页：左=选中(高亮)，右=选中+1
    OPEN_RIGHT = "open_right"  # 选中奇数页(≥3)：左=选中-1，右=选中(高亮)


class BookView(QWidget):
    """书视图。通过 controller 读取规划结果并渲染。"""

    # 框选放大模式切换信号（main_window 工具栏按钮同步用，避免双向死循环）
    zoom_mode_changed = Signal(bool)

    def __init__(self, controller=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.setMinimumSize(200, 200)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAutoFillBackground(False)

        # 框选放大模式（任务：书视图放大）
        self._zoom_mode = False            # 框选放大模式是否开启
        self._rubber_band: QRubberBand | None = None
        self._rubber_origin: QRect | None = None
        self._zoom_rect_widget: QRect | None = None  # 框选区域（widget 坐标）

    # ------------------------------------------------------------------
    # 状态机计算
    # ------------------------------------------------------------------
    def state(self) -> BookViewState:
        if self.controller is None or self.controller.current_plan is None:
            return BookViewState.CLOSED
        sel = self.controller.selected_physical_index
        if sel <= 1:
            return BookViewState.CLOSED
        if sel % 2 == 0:
            return BookViewState.OPEN_LEFT
        return BookViewState.OPEN_RIGHT

    def layout_pages(self) -> tuple[list[int], int]:
        """返回 (可见物理页列表, 高亮物理页)。

        CLOSED：       [1]，高亮 1
        OPEN_LEFT：    [sel, sel+1]，高亮 sel（右页可能超界则不显示）
        OPEN_RIGHT：   [sel-1, sel]，高亮 sel
        """
        if self.controller is None or self.controller.current_plan is None:
            return [], 0
        total = self.controller.plan_page_count()
        sel = self.controller.selected_physical_index
        st = self.state()
        if st is BookViewState.CLOSED:
            return [1], 1
        if st is BookViewState.OPEN_LEFT:
            right = sel + 1 if sel + 1 <= total else 0
            pages = [sel] + ([right] if right else [])
            return pages, sel
        left = sel - 1 if sel - 1 >= 1 else 0
        pages = ([left] if left else []) + [sel]
        return pages, sel

    # ------------------------------------------------------------------
    # 绘制
    # ------------------------------------------------------------------
    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(COLOR_BOOK_BG))

        zr = self._zoom_rect_widget
        if zr is not None and not zr.isEmpty():
            # 框选放大：把 zr（widget 坐标）区域放大填满整个 widget。
            # 内容绘制逻辑完全复用（角标/页码预览一并放大），仅套 painter 变换。
            painter.save()
            scale = min(self.width() / zr.width(), self.height() / zr.height())
            painter.translate(-zr.x() * scale, -zr.y() * scale)
            painter.scale(scale, scale)
            painter.setClipRect(zr)  # 世界坐标 clip（随变换映射到 widget 全区域）
            self._paint_content(painter)
            painter.restore()
        else:
            self._paint_content(painter)

    def _paint_content(self, painter: QPainter) -> None:
        """绘制书视图内容（布局 + 页面 + 角标 + 页码预览 + 选择提示）。"""
        pages, highlighted = self.layout_pages()
        if not pages:
            self._paint_empty(painter)
            return

        st = self.state()
        rect = self.rect().adjusted(16, 16, -16, -16)

        if st is BookViewState.CLOSED:
            # 单页居右（模拟合上的封面）
            self._paint_closed(painter, rect, pages[0], highlighted)
        else:
            self._paint_opened(painter, rect, pages, highlighted)

        # 多选批量（任务 3）：角落提示"已选 N 页"
        self._paint_selection_hint(painter)

    def _paint_selection_hint(self, painter: QPainter) -> None:
        if self.controller is None:
            return
        pages = self.controller.selected_physical_pages()
        if len(pages) <= 1:
            return
        painter.save()
        font = QFont(FONT_DEFAULT, 9)
        painter.setFont(font)
        painter.setPen(QColor("#8A6D00"))
        painter.drawText(
            self.rect().adjusted(10, 8, -10, -8),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
            f"已选 {len(pages)} 页",
        )
        painter.restore()

    def _paint_empty(self, painter: QPainter) -> None:
        painter.setPen(QColor(COLOR_BLANK_BADGE))
        font = QFont(FONT_DEFAULT, 11)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "请打开 PDF 文件")

    def _page_pixmap(self, phys: int, target_h: int) -> tuple[QPixmap, float, float]:
        """加载并缩放到目标高度，返回 (pixmap, 宽, 高)。"""
        data = self.controller.get_book_view_page(phys)
        pix = QPixmap()
        if data:
            pix.loadFromData(data)
        else:
            pix = QPixmap(1, 1)
            pix.fill(QColor("white"))
        if pix.height() <= 0:
            pix = QPixmap(1, 1)
            pix.fill(QColor("white"))
        ratio = target_h / pix.height()
        w = max(1, int(pix.width() * ratio))
        h = max(1, int(pix.height() * ratio))
        return pix.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation), float(w), float(h)

    def _page_size_mm(self, phys: int) -> tuple[float, float]:
        pp = self.controller.processed_page(phys)
        if pp is None:
            return (210.0, 297.0)
        return pp.output_size_mm

    def _is_a3(self, phys: int) -> bool:
        w, h = self._page_size_mm(phys)
        return max(w, h) >= 297.0 and min(w, h) >= 210.0 and max(w, h) >= 400.0

    def _draw_page(self, painter, x, y, w, h, phys, highlighted, st, gap=0):
        """绘制单页（含图、边框、角标、光晕）。x/y 为页面左上角。"""
        # 高亮光晕（选中页）
        if highlighted:
            glow = QLinearGradient(x - 6, y - 6, x + w + 6, y + h + 6)
            glow.setColorAt(0.0, QColor(COLOR_HIGHLIGHT_GLOW))
            glow.setColorAt(1.0, QColor(COLOR_HIGHLIGHT))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(glow)
            painter.drawRoundedRect(x - 7, y - 7, w + 14, h + 14, 8, 8)

        # 页面图
        pix, pw, ph = self._page_pixmap(phys, h)
        painter.drawPixmap(int(x + (w - pw) / 2), int(y + (h - ph) / 2), pix)
        # 边框
        painter.setPen(QPen(QColor(COLOR_PAGE_BORDER), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(int(x), int(y), int(w), int(h))

        pp = self.controller.processed_page(phys)
        if pp is None:
            return
        # 角标
        if pp.is_blank:
            self._paint_badge(painter, x, y, "空", COLOR_BLANK_BADGE, solid=True, top=False)
        if self._is_a3(phys):
            self._paint_badge(painter, x + w, y, "横", COLOR_BLANK_BADGE, solid=False, top=True, anchor_right=True)
        if not pp.is_blank and pp.rotation != 0:
            if pp.rotation == 90:
                label = "旋↻90°"
            elif pp.rotation == 180:
                label = "旋180°"
            elif pp.rotation == 270:
                label = "旋↺90°"
            else:
                label = "旋"
            self._paint_badge(painter, x, y, label, COLOR_ROTATE_BADGE, solid=False, top=True)

        # 重叠警告角标（红色"叠"）：页面顶部外侧（top=False），不与旋转角标（页内）冲突
        if (
            not pp.is_blank
            and self.controller.overlap_warning_for(phys) is not None
        ):
            self._paint_badge(painter, x, y, "叠", COLOR_OVERLAP_BADGE, solid=True, top=False)
        # 自动调整过（原本重叠已成功避开）→ 同排显示"叠"+"自"（"自"右移一个角标位）
        if pp.overlap_adjusted:
            self._paint_badge(painter, x, y, "叠", COLOR_OVERLAP_BADGE, solid=True, top=False)
            self._paint_badge(painter, x + 30, y, "自", COLOR_AUTO_ADJUST, solid=True, top=False)

        # 页码预览（页码位置 Bug 任务 2）：按规划位置/样式叠加绘制，与输出一致
        info = self.controller.get_page_number_info(phys)
        if info:
            self._paint_page_number(painter, x, y, w, h, phys, info)

    def _paint_closed(self, painter, rect, phys, highlighted):
        """CLOSED：单页居右竖排。"""
        h_target = rect.height()
        w_mm, h_mm = self._page_size_mm(phys)
        ratio = h_mm / w_mm if w_mm else 1.0
        w = min(rect.width() * 0.72, int(h_target / ratio))
        h = int(w * ratio)
        if h > h_target:
            h = h_target
            w = int(h / ratio)
        x = rect.right() - w - 20
        y = rect.top() + (rect.height() - h) / 2
        self._draw_page(painter, x, y, w, h, phys, highlighted, BookViewState.CLOSED)

    def _paint_opened(self, painter, rect, pages, highlighted):
        """OPEN_LEFT / OPEN_RIGHT：左右两页并排，中间书脊。"""
        h_target = rect.height()
        gap = 12
        left_phys = pages[0]
        right_phys = pages[1] if len(pages) > 1 else 0

        # 计算两页并排时的可用宽度，按比例分配高度
        ratio_l = self._aspect_ratio(left_phys)
        ratio_r = self._aspect_ratio(right_phys) if right_phys else ratio_l
        total_w = rect.width() - gap
        # 初始按高度适配
        w_l = int(h_target / ratio_l)
        w_r = int(h_target / ratio_r)
        if w_l + w_r + gap > rect.width():
            scale = (rect.width() - gap) / (w_l + w_r)
            w_l = int(w_l * scale)
            w_r = int(w_r * scale)
        h_l = int(w_l * ratio_l)
        h_r = int(w_r * ratio_r)
        h = max(h_l, h_r)
        # 重新约束高度一致（两页底部对齐）
        if h > h_target:
            h = h_target
            w_l = int(h / ratio_l)
            w_r = int(h / ratio_r)

        y = rect.top() + (rect.height() - h) / 2
        x_l = rect.left() + (rect.width() - (w_l + w_r + gap)) / 2
        x_r = x_l + w_l + gap

        if left_phys:
            self._draw_page(painter, x_l, y, w_l, h, left_phys,
                            highlighted == left_phys, BookViewState.OPEN_LEFT)
        if right_phys:
            self._draw_page(painter, x_r, y, w_r, h, right_phys,
                            highlighted == right_phys, BookViewState.OPEN_RIGHT)
        # 书脊阴影
        spine_x = x_l + w_l + gap / 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(COLOR_BOOK_BG_EDGE))
        painter.drawRect(int(spine_x - 2), int(y), 4, int(h))

    def _aspect_ratio(self, phys: int) -> float:
        w, h = self._page_size_mm(phys)
        return h / w if w else 1.0

    def _paint_page_number(self, painter, x, y, w, h, phys, info) -> None:
        """在页面区域 (x,y,w,h) 内按规划位置绘制页码文字。

        info.anchor 为显示坐标 pt（左上原点 y 向下，页码左下基线）。
        缩放：页面显示尺寸 mm→pt 与 widget 区域 (w,h) 的比值换算。
        """
        out_w_mm, out_h_mm = self._page_size_mm(phys)
        ax, ay = info["anchor"]
        sx = w / (out_w_mm * 72.0 / 25.4)
        sy = h / (out_h_mm * 72.0 / 25.4)
        px = x + ax * sx
        py = y + ay * sy
        r, g, b = info["color"]
        painter.save()
        painter.setPen(QColor(r, g, b))
        font = QFont("Times New Roman")
        font.setPixelSize(max(1, int(info["fontsize"] * sx)))
        painter.setFont(font)
        painter.drawText(int(px), int(py), info["text"])
        painter.restore()

    def _paint_badge(self, painter, x, y, text, color, solid, top, anchor_right=False):
        """绘制小角标。"""
        painter.save()
        font = QFont(FONT_DEFAULT, 8)
        painter.setFont(font)
        fm = painter.fontMetrics()
        tw = fm.horizontalAdvance(text) + 8
        th = fm.height() + 4
        bx = (x - tw) if anchor_right else x
        by = y if top else (y - th)
        if solid:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(color))
            painter.drawRoundedRect(int(bx), int(by), int(tw), int(th), 3, 3)
            painter.setPen(QColor("white"))
            painter.drawText(int(bx + 4), int(by + fm.ascent() + 2), text)
        else:
            pen = QPen(QColor(color), 1, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(QColor(color).lighter(185))
            painter.drawRoundedRect(int(bx), int(by), int(tw), int(th), 3, 3)
            painter.setPen(QColor(color).darker(120))
            painter.drawText(int(bx + 4), int(by + fm.ascent() + 2), text)
        painter.restore()

    # ------------------------------------------------------------------
    # 交互
    # ------------------------------------------------------------------
    def _move(self, delta: int) -> None:
        if self.controller is None:
            return
        self.controller.select_physical(
            self.controller.selected_physical_index + delta
        )

    def wheelEvent(self, event):  # noqa: N802
        delta = 1 if event.angleDelta().y() < 0 else -1
        self._move(delta)
        event.accept()

    # ------------------------------------------------------------------
    # 框选放大
    # ------------------------------------------------------------------
    def set_zoom_mode(self, checked: bool) -> None:
        """开启/关闭框选放大模式（工具栏"放大"按钮切换）。"""
        self._zoom_mode = bool(checked)
        if not checked:
            self._zoom_rect_widget = None
            if self._rubber_band is not None:
                self._rubber_band.hide()
            self.update()
        self.zoom_mode_changed.emit(self._zoom_mode)

    def zoom_rect(self) -> QRect | None:
        """当前放大区域（widget 坐标）；None=未放大。"""
        return self._zoom_rect_widget

    def mousePressEvent(self, event):  # noqa: N802
        if self._zoom_mode and event.button() == Qt.MouseButton.LeftButton:
            self._rubber_origin = event.position().toPoint()
            if self._rubber_band is None:
                self._rubber_band = QRubberBand(QRubberBand.Shape.Rectangle, self)
            self._rubber_band.setGeometry(QRect(self._rubber_origin, QSize()))
            self._rubber_band.show()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._zoom_mode and self._rubber_band is not None:
            self._rubber_band.setGeometry(
                QRect(self._rubber_origin, event.position().toPoint()).normalized()
            )
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        if self._zoom_mode and self._rubber_band is not None:
            rect = self._rubber_band.geometry()
            self._rubber_band.hide()
            # 框选太小（<10px）忽略，不当放大处理
            if rect.width() > 10 and rect.height() > 10:
                self._zoom_rect_widget = rect
                self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key.Key_Escape and self._zoom_mode:
            self._zoom_mode = False
            self._zoom_rect_widget = None
            if self._rubber_band is not None:
                self._rubber_band.hide()
            self.update()
            self.zoom_mode_changed.emit(False)
            event.accept()
            return
        if event.key() == Qt.Key.Key_Right or event.key() == Qt.Key.Key_Down:
            self._move(1)
            event.accept()
        elif event.key() == Qt.Key.Key_Left or event.key() == Qt.Key.Key_Up:
            self._move(-1)
            event.accept()
        else:
            super().keyPressEvent(event)

    def page_next(self) -> None:
        self._move(1)

    def page_prev(self) -> None:
        self._move(-1)

    def on_plan_changed(self) -> None:
        self.update()

    def on_selection_changed(self, physical_index: int) -> None:
        self.update()

    def open_output_folder(self) -> None:
        path = self.controller.expected_output_path() if self.controller else ""
        if path:
            dialogs.open_folder(path)
