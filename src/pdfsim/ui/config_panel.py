# -*- coding: utf-8 -*-
"""页面配置面板（依据《Stage3_提示语.md》5.5 与《UI原型说明.md》第 4 章）。

6 个子区：4.1 页面属性标签 / 4.2 页码位置 / 4.3 旋转方向 / 4.4 页码样式 /
4.5 重叠警告 / 4.6 起始页码（全局）。无选中页时折叠为提示栏。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from pdfsim.models import (
    PageMark,
    PageNumberPos,
    PageNumberStyle,
    RotationOverride,
    is_a3,
)
from pdfsim.ui.styles import (
    COLOR_OVERLAP_TEXT,
    COLOR_OVERLAP_WARN,
    FONT_DEFAULT,
    PADDING_PANEL,
)

_FONTS = ["Times New Roman", "SimSun", "SimHei", "KaiTi", "Microsoft YaHei", "Arial"]

# 旋转方向下拉项的固定顺序（与 _rot_combo.addItem 一一对应）
_ROT_OVERRIDE_ORDER = [
    RotationOverride.AUTO,
    RotationOverride.CW90,
    RotationOverride.CCW90,
    RotationOverride.ROT180,
    RotationOverride.NONE,
]


class ConfigPanel(QWidget):
    """底部页面配置面板。"""

    def __init__(self, controller=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._loading = False
        self._batch_pages: list[int] | None = None  # 批量多选模式（None=单页）

        self._build_ui()

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(PADDING_PANEL, 6, PADDING_PANEL, 6)
        self._root.setSpacing(6)

        # 重叠警告条（顶部，默认隐藏）
        self._warn_label = QLabel("⚠ 页码位置可能与原有内容重叠，请调整")
        self._warn_label.setStyleSheet(
            f"background:{COLOR_OVERLAP_WARN};color:{COLOR_OVERLAP_TEXT};"
            "border-radius:4px;padding:5px 8px;"
        )
        self._warn_label.setVisible(False)
        self._root.addWidget(self._warn_label)

        # 主体区域（6 子区）
        self._body = QWidget()
        body_layout = QHBoxLayout(self._body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(8)
        self._root.addWidget(self._body, 1)

        self._mark_group = self._build_mark_group()
        self._pos_group = self._build_pos_group()
        self._rot_group = self._build_rot_group()
        self._style_group = self._build_style_group()
        self._start_group = self._build_start_group()

        body_layout.addWidget(self._mark_group)
        body_layout.addWidget(self._pos_group)
        body_layout.addWidget(self._rot_group)
        body_layout.addWidget(self._style_group)
        body_layout.addWidget(self._start_group)
        body_layout.addStretch(1)

        # 无选中页提示栏
        self._empty_label = QLabel("请选择页面")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet(
            f"color:#909090;font-size:14px;background:#FAFAFA;border-radius:4px;"
        )
        self._root.addWidget(self._empty_label)
        self._empty_label.setVisible(False)

        self.setMinimumHeight(180)

    # -- 4.1 页面属性标签 ------------------------------------------------
    def _build_mark_group(self) -> QGroupBox:
        box = QGroupBox("页面属性标签")
        lay = QVBoxLayout(box)
        self._chk_cover = QCheckBox("封面")
        self._chk_sign = QCheckBox("签字页")
        self._chk_no_number = QCheckBox("不加页码")
        self._chk_front = QCheckBox("从正面开始")
        # tooltip（任务 4，文案参考提示语）
        self._chk_cover.setToolTip(
            "该页从正面开始（物理奇数位）；背面自动插入同尺寸空白页，空白页有页码")
        self._chk_sign.setToolTip(
            "该页从正面开始（物理奇数位）；背面自动插入同尺寸空白页，"
            "完全空白、无页码、不占序号")
        self._chk_no_number.setToolTip(
            "该页保留原内容，不显示页码数字，且序号跳过——"
            "后续页页码顺延前移（如页1“1”、页2无、页3“2”）")
        self._chk_front.setToolTip(
            "该页强制落在物理奇数位（打印正面）；若当前在偶数位则前面自动插入空白页推动")
        for chk in (self._chk_cover, self._chk_sign, self._chk_no_number,
                    self._chk_front):
            lay.addWidget(chk)
        # 自定义标签
        row = QHBoxLayout()
        self._label_input = QLineEdit()
        self._label_input.setPlaceholderText("自定义标签")
        self._label_add = QPushButton("添加")
        row.addWidget(self._label_input)
        row.addWidget(self._label_add)
        lay.addLayout(row)
        self._labels_display = QLabel("")
        self._labels_display.setStyleSheet("color:#424242;")
        self._labels_display.setWordWrap(True)
        lay.addWidget(self._labels_display)

        self._chk_cover.toggled.connect(self._on_mark_cover)
        self._chk_sign.toggled.connect(self._on_mark_sign)
        self._chk_no_number.toggled.connect(
            lambda v: self._on_mark(PageMark.NO_NUMBER, v))
        self._chk_front.toggled.connect(self._on_mark_front)
        self._label_add.clicked.connect(self._on_add_label)
        self._label_input.returnPressed.connect(self._on_add_label)
        return box

    # -- 4.2 页码位置 ----------------------------------------------------
    def _build_pos_group(self) -> QGroupBox:
        box = QGroupBox("页码位置")
        lay = QVBoxLayout(box)
        self._pos_combo = QComboBox()
        self._pos_combo.addItem("自动（按物理奇偶）", None)
        self._pos_combo.addItem("右下角", PageNumberPos.BOTTOM_RIGHT)
        self._pos_combo.addItem("左下角", PageNumberPos.BOTTOM_LEFT)
        self._pos_combo.addItem("右上角", PageNumberPos.TOP_RIGHT)
        self._pos_combo.addItem("左上角", PageNumberPos.TOP_LEFT)
        self._pos_combo.addItem("自定义", PageNumberPos.CUSTOM)
        lay.addWidget(self._pos_combo)

        self._custom_row = QWidget()
        custom_lay = QFormLayout(self._custom_row)
        self._off_x = QDoubleSpinBox()
        self._off_x.setRange(-100, 100)
        self._off_x.setSuffix(" mm")
        self._off_y = QDoubleSpinBox()
        self._off_y.setRange(-100, 100)
        self._off_y.setSuffix(" mm")
        custom_lay.addRow("X 偏移", self._off_x)
        custom_lay.addRow("Y 偏移", self._off_y)
        lay.addWidget(self._custom_row)
        self._custom_row.setVisible(False)

        self._pos_combo.currentIndexChanged.connect(self._on_pos_changed)
        self._off_x.valueChanged.connect(self._on_custom_offset)
        self._off_y.valueChanged.connect(self._on_custom_offset)
        return box

    # -- 4.3 旋转方向 ----------------------------------------------------
    def _build_rot_group(self) -> QGroupBox:
        box = QGroupBox("旋转方向")
        lay = QVBoxLayout(box)
        self._rot_detect_label = QLabel("")
        self._rot_detect_label.setWordWrap(True)
        self._rot_detect_label.setStyleSheet("color:#5B9BD5;")
        lay.addWidget(self._rot_detect_label)
        self._rot_combo = QComboBox()
        self._rot_combo.addItem("自动检测", RotationOverride.AUTO)
        self._rot_combo.addItem("顺时针 90°", RotationOverride.CW90)
        self._rot_combo.addItem("逆时针 90°", RotationOverride.CCW90)
        self._rot_combo.addItem("旋转 180°", RotationOverride.ROT180)
        self._rot_combo.addItem("不旋转", RotationOverride.NONE)
        lay.addWidget(self._rot_combo)
        self._rot_combo.currentIndexChanged.connect(self._on_rot_changed)
        return box

    # -- 4.4 页码样式 ----------------------------------------------------
    def _build_style_group(self) -> QGroupBox:
        box = QGroupBox("页码样式")
        lay = QFormLayout(box)
        self._style_font = QComboBox()
        self._style_font.addItems(_FONTS)
        self._style_size = QDoubleSpinBox()
        self._style_size.setRange(4, 72)
        self._style_size.setSuffix(" pt")
        self._style_size.setValue(9.0)
        self._style_color = QPushButton("选择颜色")
        self._style_color.setFixedWidth(90)
        self._style_margin_r = QDoubleSpinBox()
        self._style_margin_r.setRange(0, 100)
        self._style_margin_r.setSuffix(" mm")
        self._style_vert_pos = QComboBox()
        self._style_vert_pos.addItem("底部", "bottom")
        self._style_vert_pos.addItem("顶部", "top")
        self._margin_v_label = QLabel("距下")
        self._style_margin_v = QDoubleSpinBox()
        self._style_margin_v.setRange(0, 100)
        self._style_margin_v.setSuffix(" mm")
        lay.addRow("字体", self._style_font)
        lay.addRow("字号", self._style_size)
        lay.addRow("颜色", self._style_color)
        lay.addRow("距右/左", self._style_margin_r)
        lay.addRow("垂直位置", self._style_vert_pos)
        lay.addRow(self._margin_v_label, self._style_margin_v)
        self._restore_btn = QPushButton("恢复全局样式")
        lay.addRow(self._restore_btn)

        self._style_color.setStyleSheet(
            "QPushButton{background:#000000;color:#ffffff;border:1px solid #ccc;}"
        )
        self._style_color.clicked.connect(self._on_pick_color)
        self._style_font.currentTextChanged.connect(self._on_style_changed)
        self._style_size.valueChanged.connect(self._on_style_changed)
        self._style_margin_r.valueChanged.connect(self._on_style_changed)
        self._style_margin_v.valueChanged.connect(self._on_style_changed)
        self._style_vert_pos.currentIndexChanged.connect(self._on_vert_pos_changed)
        self._restore_btn.clicked.connect(self._on_restore_style)
        return box

    # -- 4.6 起始页码（全局） --------------------------------------------
    def _build_start_group(self) -> QGroupBox:
        box = QGroupBox("起始页码")
        lay = QVBoxLayout(box)
        self._start_spin = QSpinBox()
        self._start_spin.setRange(1, 99999)
        lay.addWidget(self._start_spin)
        self._start_spin.valueChanged.connect(self._on_start_changed)
        return box

    # ------------------------------------------------------------------
    # 数据加载（选中页变化时）
    # ------------------------------------------------------------------
    def load_page(self, physical_index: int) -> None:
        """根据选中页填充控件（批量多选模式下忽略，由 _refresh_batch 维护）。"""
        if self._batch_pages:
            return
        self._loading = True
        try:
            if self.controller is None:
                self._show_empty(True)
                return
            pp = self.controller.processed_page(physical_index)
            if pp is None:
                self._show_empty(True)
                return
            self._show_empty(False)
            # 恢复单页设置区控件可用（批量置灰后切回单页需恢复）
            for w in self._single_page_widgets():
                w.setEnabled(True)
            src = pp.source_page_info
            marks = src.marks if src is not None else set()

            # 4.1 标签
            self._chk_cover.blockSignals(True)
            self._chk_sign.blockSignals(True)
            self._chk_no_number.blockSignals(True)
            self._chk_front.blockSignals(True)
            self._chk_cover.setChecked(PageMark.COVER in marks)
            self._chk_sign.setChecked(PageMark.SIGNATURE in marks)
            self._chk_no_number.setChecked(PageMark.NO_NUMBER in marks)
            self._chk_front.setChecked(PageMark.FRONT in marks)
            self._chk_cover.blockSignals(False)
            self._chk_sign.blockSignals(False)
            self._chk_no_number.blockSignals(False)
            self._chk_front.blockSignals(False)
            # 空白页（任务 2）：封面/签字页/从正面开始无语义 → 置灰；自定义标签禁用
            is_blank = bool(getattr(src, "is_blank", False))
            a3 = src is not None and not is_blank and is_a3(src)
            if is_blank:
                self._chk_cover.setEnabled(False)
                self._chk_sign.setEnabled(False)
                self._chk_front.setEnabled(False)
                self._chk_front.setChecked(False)
                self._label_input.setEnabled(False)
                self._label_add.setEnabled(False)
            else:
                self._chk_cover.setEnabled(True)
                self._chk_sign.setEnabled(True)
                self._label_input.setEnabled(True)
                self._label_add.setEnabled(True)
                # A3 页 front 置灰不可取消
                self._chk_front.setEnabled(not a3)
                if a3:
                    self._chk_front.setChecked(True)
            labels = list(src.custom_labels) if src is not None else []
            self._labels_display.setText("、".join(labels))
            self._label_input.clear()

            # 4.2 页码位置
            ov = src.number_pos_override if src is not None else None
            self._pos_combo.blockSignals(True)
            idx = 0
            if ov is not None:
                idx = {PageNumberPos.BOTTOM_RIGHT: 1, PageNumberPos.BOTTOM_LEFT: 2,
                       PageNumberPos.TOP_RIGHT: 3, PageNumberPos.TOP_LEFT: 4,
                       PageNumberPos.CUSTOM: 5}.get(ov, 0)
            self._pos_combo.setCurrentIndex(idx)
            # A3 页"自动"只读
            if a3:
                self._pos_combo.setEnabled(False)
            else:
                self._pos_combo.setEnabled(True)
            self._pos_combo.blockSignals(False)
            custom_on = ov is PageNumberPos.CUSTOM
            self._custom_row.setVisible(custom_on)
            off = src.number_custom_offset_mm if src is not None else None
            self._off_x.blockSignals(True)
            self._off_y.blockSignals(True)
            if off is not None:
                self._off_x.setValue(off[0])
                self._off_y.setValue(off[1])
            else:
                self._off_x.setValue(0.0)
                self._off_y.setValue(0.0)
            self._off_x.blockSignals(False)
            self._off_y.blockSignals(False)

            # 4.3 旋转方向
            oi = src.original_index if src is not None else None
            need_rot = oi is not None and self.controller.needs_rotation(oi)
            if need_rot:
                self._rot_combo.setEnabled(True)
                self._rot_detect_label.setEnabled(True)
                det_text = self.controller.rotation_detection_text(oi) if oi is not None else ""
                self._rot_detect_label.setText(det_text)
                rot_ov = src.rotation_override if src is not None else RotationOverride.AUTO
                self._rot_combo.blockSignals(True)
                self._rot_combo.setCurrentIndex(
                    _ROT_OVERRIDE_ORDER.index(rot_ov) if rot_ov in _ROT_OVERRIDE_ORDER else 0)
                self._rot_combo.blockSignals(False)
            else:
                self._rot_combo.setEnabled(False)
                self._rot_detect_label.setText("无需旋转")

            # 4.4 样式（单页覆盖优先；否则回显全局）
            style = src.style_override if src is not None else None
            global_style = self.controller.config.global_style
            eff = style or global_style
            self._apply_style_to_widgets(eff)

            # 4.6 起始页码（全局）
            self._start_spin.blockSignals(True)
            self._start_spin.setValue(self.controller.config.start_page_number)
            self._start_spin.blockSignals(False)

            # 4.5 重叠警告
            warning = self.controller.overlap_warning_for(physical_index)
            self._warn_label.setVisible(warning is not None)
        finally:
            self._loading = False

    def _show_empty(self, empty: bool) -> None:
        self._body.setVisible(not empty)
        self._empty_label.setVisible(empty)
        self._warn_label.setVisible(False)

    def _set_color_button(self, color) -> None:
        self._style_color.setStyleSheet(
            "QPushButton{background:%s;color:%s;border:1px solid #ccc;}"
            % (QColor(*color).name(), "#ffffff" if sum(color) < 384 else "#000000")
        )

    # ------------------------------------------------------------------
    # 信号处理
    # ------------------------------------------------------------------
    def _current_physical_index(self) -> int | None:
        pp = self.controller.current_processed_page() if self.controller else None
        return pp.physical_index if pp else None

    def _current_original_index(self) -> int | None:
        pp = self.controller.current_processed_page() if self.controller else None
        if pp is None or pp.source_page_info is None:
            return None
        return pp.source_page_info.original_index

    # -- 批量多选模式（任务 3 + 功能增强：多选可批量调旋转/样式） ----------
    def _single_page_widgets(self) -> list:
        """单页专属设置控件（批量多选时禁用置灰）。

        功能增强：旋转方向与页码样式已移出——多选时可批量调整。
        """
        return [
            self._pos_combo, self._custom_row,  # 页码位置（保持禁用）
            self._label_input, self._label_add, self._labels_display,  # 标签（保持禁用）
        ]

    def on_selection_set_changed(self, pages: list[int]) -> None:
        """多选集合变化：>1 页进入批量模式（三态标签 + 单页区置灰）。"""
        if self.controller is None:
            self._batch_pages = None
            return
        if len(pages) <= 1:
            self._batch_pages = None
            return
        self._batch_pages = pages
        self._refresh_batch(pages)

    def _refresh_batch(self, pages: list[int]) -> None:
        self._show_empty(False)
        self._set_tristate(self._chk_cover, PageMark.COVER, pages)
        self._set_tristate(self._chk_sign, PageMark.SIGNATURE, pages)
        self._set_tristate(self._chk_no_number, PageMark.NO_NUMBER, pages)
        self._set_tristate(self._chk_front, PageMark.FRONT, pages)
        # 全 A3 选中 → "从正面开始"置灰只读（A3 FRONT 强制不可取消）
        if pages and all(self._phys_is_a3_original(p) for p in pages):
            self._chk_front.setEnabled(False)
        else:
            self._chk_front.setEnabled(True)
        for w in self._single_page_widgets():
            w.setEnabled(False)
        # 旋转方向 / 页码样式批量回显（多选可调，功能增强）
        self._refresh_batch_rotation(pages)
        self._refresh_batch_style(pages)
        self._warn_label.setVisible(False)

    def _refresh_batch_rotation(self, pages: list[int]) -> None:
        """旋转方向批量回显：全部一致显示该值；不一致显示"自动检测"占位。

        全空白页 → 禁用（空白页旋转由同纸正面继承、不可手动覆盖）。
        """
        vals = []
        for phys in pages:
            pp = self.controller.processed_page(phys) if self.controller else None
            if pp is None or pp.source_page_info is None:
                continue
            src = pp.source_page_info
            if not src.is_blank:
                vals.append(src.rotation_override)
        if not vals:  # 全空白页
            self._rot_combo.setEnabled(False)
            self._rot_detect_label.setEnabled(False)
            self._rot_detect_label.setText("空白页不可调旋转")
            return
        self._rot_combo.setEnabled(True)
        self._rot_detect_label.setEnabled(True)
        if len(set(vals)) == 1:
            override = vals[0]
            self._rot_detect_label.setText(f"批量旋转（{len(vals)} 页一致）")
        else:
            override = RotationOverride.AUTO
            self._rot_detect_label.setText(f"批量旋转（{len(vals)} 页值不一致，将统一覆盖）")
        self._rot_combo.blockSignals(True)
        self._rot_combo.setCurrentIndex(
            _ROT_OVERRIDE_ORDER.index(override) if override in _ROT_OVERRIDE_ORDER else 0)
        self._rot_combo.blockSignals(False)

    def _refresh_batch_style(self, pages: list[int]) -> None:
        """页码样式批量回显：覆盖全部一致且非 None → 显示该覆盖；否则显示全局样式。

        控件保持可选，用户调整即统一覆盖全部选中页。
        """
        for w in (self._style_font, self._style_size, self._style_color,
                  self._style_margin_r, self._style_vert_pos, self._style_margin_v,
                  self._restore_btn):
            w.setEnabled(True)
        if self.controller is None:
            return
        global_style = self.controller.config.global_style
        overrides = []
        for phys in pages:
            pp = self.controller.processed_page(phys)
            if pp is None or pp.source_page_info is None:
                continue
            overrides.append(pp.source_page_info.style_override)
        if (overrides and len(overrides) == len(pages)
                and all(o is not None and o == overrides[0] for o in overrides)):
            eff = overrides[0]
        else:
            eff = global_style  # 有差异 / 无覆盖 → 显示全局样式，调整后统一覆盖
        self._apply_style_to_widgets(eff)

    def _apply_style_to_widgets(self, eff: PageNumberStyle) -> None:
        """把样式回显到样式控件（单页 load_page 与批量 _refresh_batch 共用）。"""
        self._style_font.blockSignals(True)
        self._style_font.setCurrentText(eff.font)
        self._style_font.blockSignals(False)
        self._style_size.blockSignals(True)
        self._style_size.setValue(eff.fontsize_pt)
        self._style_size.blockSignals(False)
        self._set_color_button(eff.color)
        self._color_rgb = tuple(eff.color)
        self._style_margin_r.blockSignals(True)
        self._style_margin_v.blockSignals(True)
        self._style_vert_pos.blockSignals(True)
        self._style_margin_r.setValue(eff.margin_right_mm)
        # 垂直位置（顶部/底部）→ 切换"距下/距上"标签与对应边距值
        vert = eff.vertical_position if eff.vertical_position == "top" else "bottom"
        self._style_vert_pos.setCurrentIndex(0 if vert == "bottom" else 1)
        self._margin_v_label.setText("距下" if vert == "bottom" else "距上")
        self._style_margin_v.setValue(
            eff.margin_top_mm if vert == "top" else eff.margin_bottom_mm)
        self._style_margin_r.blockSignals(False)
        self._style_margin_v.blockSignals(False)
        self._style_vert_pos.blockSignals(False)

    def _phys_is_a3_original(self, phys: int) -> bool:
        pp = self.controller.processed_page(phys) if self.controller else None
        if pp is None or pp.source_page_info is None:
            return False
        info = pp.source_page_info
        return not info.is_blank and is_a3(info)

    def _set_tristate(self, chk: QCheckBox, mark: PageMark, pages: list[int]) -> None:
        """三态：全有=勾选、全无=不勾、部分=半选。"""
        st = self.controller.mark_state_for_pages(pages, mark)
        chk.blockSignals(True)
        chk.setTristate(st is None)
        if st is None:
            chk.setCheckState(Qt.CheckState.PartiallyChecked)
        else:
            chk.setCheckState(
                Qt.CheckState.Checked if st else Qt.CheckState.Unchecked)
        chk.blockSignals(False)

    # ------------------------------------------------------------------
    def _on_mark(self, mark: PageMark, value: bool) -> None:
        if self._loading or self.controller is None:
            return
        if self._batch_pages:
            self.controller.set_page_mark_batch(self._batch_pages, mark, value)
            self._refresh_batch(self._batch_pages)
            return
        phys = self._current_physical_index()
        if phys is None:
            return
        self.controller.set_page_mark_physical(phys, mark, value)

    def _on_mark_cover(self, value: bool) -> None:
        if self._loading or self.controller is None:
            return
        if self._batch_pages:
            self.controller.set_page_mark_batch(
                self._batch_pages, PageMark.COVER, value)
            if value:  # 联动：封面 → 自动从正面开始
                self.controller.set_page_mark_batch(
                    self._batch_pages, PageMark.FRONT, True)
            self._refresh_batch(self._batch_pages)
            return
        phys = self._current_physical_index()
        if phys is None:
            return
        self.controller.set_page_mark_physical(phys, PageMark.COVER, value)
        # 联动：勾选封面 → 自动勾选"从正面开始"
        if value:
            self._chk_front.blockSignals(True)
            self._chk_front.setChecked(True)
            self._chk_front.blockSignals(False)
            self.controller.set_page_mark_physical(phys, PageMark.FRONT, True)

    def _on_mark_sign(self, value: bool) -> None:
        if self._loading or self.controller is None:
            return
        if self._batch_pages:
            self.controller.set_page_mark_batch(
                self._batch_pages, PageMark.SIGNATURE, value)
            if value:  # 联动：签字页 → 自动从正面开始
                self.controller.set_page_mark_batch(
                    self._batch_pages, PageMark.FRONT, True)
            self._refresh_batch(self._batch_pages)
            return
        phys = self._current_physical_index()
        if phys is None:
            return
        self.controller.set_page_mark_physical(phys, PageMark.SIGNATURE, value)
        if value:
            self._chk_front.blockSignals(True)
            self._chk_front.setChecked(True)
            self._chk_front.blockSignals(False)
            self.controller.set_page_mark_physical(phys, PageMark.FRONT, True)

    def _on_mark_front(self, value: bool) -> None:
        if self._loading or self.controller is None:
            return
        if self._batch_pages:
            self.controller.set_page_mark_batch(
                self._batch_pages, PageMark.FRONT, value)
            self._refresh_batch(self._batch_pages)
            return
        phys = self._current_physical_index()
        if phys is None:
            return
        self.controller.set_page_mark_physical(phys, PageMark.FRONT, value)

    def _on_add_label(self) -> None:
        if self.controller is None:
            return
        oi = self._current_original_index()
        text = self._label_input.text().strip()
        if oi is None or not text:
            return
        self.controller.set_custom_label(oi, text)
        self._label_input.clear()

    def _on_pos_changed(self, index: int) -> None:
        if self._loading or self.controller is None:
            return
        oi = self._current_original_index()
        if oi is None:
            return
        # Qt 会把 str 枚举降级为字符串，这里显式映射回枚举
        pos = [None, PageNumberPos.BOTTOM_RIGHT, PageNumberPos.BOTTOM_LEFT,
               PageNumberPos.TOP_RIGHT, PageNumberPos.TOP_LEFT,
               PageNumberPos.CUSTOM][index]
        self._custom_row.setVisible(pos is PageNumberPos.CUSTOM)
        if pos is PageNumberPos.CUSTOM:
            offset = (self._off_x.value(), self._off_y.value())
        else:
            offset = None
        self.controller.set_page_number_pos(oi, pos, offset)

    def _on_custom_offset(self, _value) -> None:
        if self._loading or self.controller is None:
            return
        oi = self._current_original_index()
        if oi is None or self._pos_combo.currentIndex() != 5:
            return
        self.controller.set_page_number_pos(
            oi, PageNumberPos.CUSTOM, (self._off_x.value(), self._off_y.value()))

    def _on_rot_changed(self, index: int) -> None:
        if self._loading or self.controller is None:
            return
        override = _ROT_OVERRIDE_ORDER[index] if 0 <= index < len(_ROT_OVERRIDE_ORDER) else RotationOverride.AUTO
        if self._batch_pages:
            self.controller.set_rotation_override_batch(self._batch_pages, override)
            self._refresh_batch(self._batch_pages)
            return
        oi = self._current_original_index()
        if oi is None:
            return
        self.controller.set_rotation_override(oi, override)

    def _on_style_changed(self, *_args) -> None:
        if self._loading or self.controller is None:
            return
        style = self._current_style()
        if self._batch_pages:
            self.controller.set_page_style_override_batch(self._batch_pages, style)
            self._refresh_batch(self._batch_pages)
            return
        oi = self._current_original_index()
        if oi is None:
            return
        self.controller.set_page_style_override(oi, style)

    def _current_style(self) -> PageNumberStyle:
        margin = float(self._style_margin_r.value())
        vert = "top" if self._style_vert_pos.currentIndex() == 1 else "bottom"
        style = PageNumberStyle(
            font=self._style_font.currentText() or "Times New Roman",
            fontsize_pt=float(self._style_size.value()),
            color=tuple(self._color_rgb),
            margin_right_mm=margin,
            margin_left_mm=margin,
            margin_bottom_mm=float(self._style_margin_v.value()),
            margin_top_mm=float(self._style_margin_v.value()),
            vertical_position=vert,
        )
        return style

    def _on_vert_pos_changed(self, _index: int) -> None:
        """垂直位置切换：更新"距上/距下"标签并重载当前页边距值。"""
        if self._loading:
            return
        vert = "top" if self._style_vert_pos.currentIndex() == 1 else "bottom"
        self._margin_v_label.setText("距上" if vert == "top" else "距下")
        if self._batch_pages:
            # 批量模式：直接走批量样式更新（不做单页值回显）
            self._on_style_changed()
            return
        if self.controller is not None:
            pp = self.controller.current_processed_page()
            if pp is not None and pp.source_page_info is not None:
                eff = pp.source_page_info.style_override or self.controller.config.global_style
                self._style_margin_v.blockSignals(True)
                self._style_margin_v.setValue(
                    eff.margin_top_mm if vert == "top" else eff.margin_bottom_mm)
                self._style_margin_v.blockSignals(False)
        self._on_style_changed()

    def _on_pick_color(self) -> None:
        if self.controller is None:
            return
        current = QColor(*self._color_rgb)
        color = QColorDialog.getColor(current, self, "选择页码颜色")
        if color.isValid():
            self._color_rgb = (color.red(), color.green(), color.blue())
            self._set_color_button(self._color_rgb)
            if self._batch_pages:
                self.controller.set_page_style_override_batch(
                    self._batch_pages, self._current_style())
                self._refresh_batch(self._batch_pages)
                return
            oi = self._current_original_index()
            if oi is None:
                return
            self.controller.set_page_style_override(oi, self._current_style())

    def _on_restore_style(self) -> None:
        if self.controller is None:
            return
        if self._batch_pages:
            self.controller.set_page_style_override_batch(self._batch_pages, None)
            self._refresh_batch(self._batch_pages)
            return
        oi = self._current_original_index()
        if oi is None:
            return
        self.controller.set_page_style_override(oi, None)

    def _on_start_changed(self, value: int) -> None:
        if self._loading or self.controller is None:
            return
        self.controller.set_start_page_number(value)

    # ------------------------------------------------------------------
    # 控制器信号桥接
    # ------------------------------------------------------------------
    def on_plan_changed(self) -> None:
        if self.controller is not None:
            self.load_page(self.controller.selected_physical_index)

    def on_selection_changed(self, physical_index: int) -> None:
        self.load_page(physical_index)

    @property
    def _color_rgb(self) -> tuple[int, int, int]:
        return getattr(self, "_color_rgb_val", (0, 0, 0))

    @_color_rgb.setter
    def _color_rgb(self, value: tuple[int, int, int]) -> None:
        self._color_rgb_val = value
