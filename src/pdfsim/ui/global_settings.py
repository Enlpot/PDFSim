# -*- coding: utf-8 -*-
"""全局设置对话框（依据《Stage3_提示语.md》5.6 与《UI原型说明.md》第 5 章）。

模态对话框；确定 → 应用并保存配置，取消 → 不生效。
"""
from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from pdfsim.models import DocumentConfig, PageMark, PageNumberStyle

_FONTS = ["Times New Roman", "SimSun", "SimHei", "KaiTi", "Microsoft YaHei", "Arial"]


class GlobalSettingsDialog(QDialog):
    """全局设置对话框。构造后 accept() 时将结果应用到 controller。"""

    def __init__(self, controller=None, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._color_rgb = (0, 0, 0)
        self.setWindowTitle("全局设置")
        self.setMinimumWidth(460)
        self._build_ui()
        self._load_current()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # -- 页码 --
        page_group = QGroupBox("页码")
        page_form = QFormLayout(page_group)
        self._start_spin = QSpinBox()
        self._start_spin.setRange(1, 99999)
        page_form.addRow("起始页码", self._start_spin)
        self._blank_num_check = QCheckBox("其他空白页自动编页码")
        self._blank_num_check.setToolTip(
            "推正面空白页（PUSH_FRONT）与补齐末页空白页（FILL_LAST）是否显示页码、占序号。\n"
            "关（默认）：不显示页码、不占序号，后续页码顺延；封面/签字/A3 背面不受影响。")
        page_form.addRow(self._blank_num_check)

        # -- 重叠自动调整 --
        self._auto_adj_check = QCheckBox("检测到页码重叠自动调整")
        self._auto_adj_check.setToolTip(
            "检测到页码与内容重叠时，自动向页面边缘移动页码避开；\n"
            "移动到边界仍重叠则缩小字号。只调整重叠的那一页。")
        page_form.addRow(self._auto_adj_check)

        shrink_row = QWidget()
        shrink_layout = QHBoxLayout(shrink_row)
        shrink_layout.setContentsMargins(0, 0, 0, 0)
        shrink_layout.addWidget(QLabel("自动缩小字号最多"))
        self._shrink_combo = QComboBox()
        self._shrink_combo.addItems(["0 级", "1 级", "2 级", "3 级", "4 级"])
        self._shrink_combo.setCurrentIndex(2)  # 默认 2
        shrink_layout.addWidget(self._shrink_combo)
        shrink_layout.addWidget(QLabel("（每级 1pt）"))
        shrink_layout.addStretch()
        shrink_row.setStyleSheet("margin-left: 20px;")  # 缩进到开关下面
        page_form.addRow(shrink_row)
        self._shrink_row = shrink_row
        self._auto_adj_check.stateChanged.connect(self._on_auto_adj_changed)
        root.addWidget(page_group)

        # -- 页码样式 --
        style_group = QGroupBox("页码样式")
        style_form = QFormLayout(style_group)
        self._font_combo = QComboBox()
        self._font_combo.addItems(_FONTS)
        self._size_spin = QDoubleSpinBox()
        self._size_spin.setRange(4, 72)
        self._size_spin.setSuffix(" pt")
        self._color_btn = QPushButton("选择颜色")
        self._color_btn.setFixedWidth(90)
        self._margin_spin = QDoubleSpinBox()
        self._margin_spin.setRange(0, 100)
        self._margin_spin.setSuffix(" mm")
        self._vert_pos_combo = QComboBox()
        self._vert_pos_combo.addItem("底部", "bottom")
        self._vert_pos_combo.addItem("顶部", "top")
        self._margin_v_label = QLabel("距下边缘")
        self._margin_v = QDoubleSpinBox()
        self._margin_v.setRange(0, 100)
        self._margin_v.setSuffix(" mm")
        style_form.addRow("字体", self._font_combo)
        style_form.addRow("字号", self._size_spin)
        style_form.addRow("颜色", self._color_btn)
        style_form.addRow("距右/左边缘", self._margin_spin)
        style_form.addRow("垂直位置", self._vert_pos_combo)
        style_form.addRow(self._margin_v_label, self._margin_v)
        self._color_btn.clicked.connect(self._on_pick_color)
        self._vert_pos_combo.currentIndexChanged.connect(self._on_vert_pos_changed)
        root.addWidget(style_group)

        # -- 自动识别 --
        auto_group = QGroupBox("自动识别")
        auto_form = QFormLayout(auto_group)
        self._kw_cover = QLineEdit()
        self._kw_sign = QLineEdit()
        self._kw_toc = QLineEdit()
        self._kw_body = QLineEdit()
        auto_form.addRow("封面关键词", self._kw_cover)
        auto_form.addRow("签字关键词", self._kw_sign)
        auto_form.addRow("目录关键词", self._kw_toc)
        auto_form.addRow("正文关键词", self._kw_body)
        hint = QLabel("多个关键词用英文逗号分隔")
        hint.setStyleSheet("color:#909090;")
        auto_form.addRow(hint)
        root.addWidget(auto_group)

        # -- 输出 --
        out_group = QGroupBox("输出")
        out_form = QFormLayout(out_group)
        self._fill_check = QCheckBox("自动补齐末页")
        self._suffix_edit = QLineEdit()
        self._suffix_edit.setPlaceholderText("（打印装订）")
        out_form.addRow(self._fill_check)
        out_form.addRow("输出后缀", self._suffix_edit)
        root.addWidget(out_group)

        # -- 按钮 --
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        # 应用级全局默认：保存后新 PDF 打开自动应用（独立按钮，不影响当前文档）
        self._save_default_btn = buttons.addButton(
            "保存为默认", QDialogButtonBox.ButtonRole.ActionRole)
        self._save_default_btn.setToolTip(
            "将当前设置保存为应用级默认配置。\n"
            "之后打开没有专属配置的新 PDF 会自动应用；当前文档不受影响。")
        self._save_default_btn.clicked.connect(self._on_save_default)
        root.addWidget(buttons)

    # ------------------------------------------------------------------
    def _load_current(self) -> None:
        """从 controller.config 回填当前值。"""
        if self.controller is None:
            return
        cfg = self.controller.config
        self._start_spin.setValue(cfg.start_page_number)
        self._blank_num_check.setChecked(cfg.auto_number_blank_pages)
        self._auto_adj_check.setChecked(cfg.auto_adjust_overlap)
        self._shrink_combo.setCurrentIndex(max(0, min(4, cfg.auto_shrink_levels)))
        self._on_auto_adj_changed(self._auto_adj_check.isChecked())
        style = cfg.global_style
        self._font_combo.setCurrentText(style.font)
        self._size_spin.setValue(style.fontsize_pt)
        self._color_rgb = tuple(style.color)
        self._set_color_button(self._color_rgb)
        self._margin_spin.setValue(style.margin_right_mm)
        vert = style.vertical_position if style.vertical_position == "top" else "bottom"
        self._vert_pos_combo.setCurrentIndex(0 if vert == "bottom" else 1)
        self._margin_v_label.setText("距上边缘" if vert == "top" else "距下边缘")
        self._margin_v.setValue(style.margin_top_mm if vert == "top" else style.margin_bottom_mm)
        kw = cfg.auto_detect_keywords or {}
        self._kw_cover.setText(", ".join(kw.get(PageMark.COVER, [])))
        self._kw_sign.setText(", ".join(kw.get(PageMark.SIGNATURE, [])))
        self._kw_toc.setText(", ".join(kw.get(PageMark.FRONT, [])))
        self._kw_body.setText(", ".join(kw.get("body", [])))
        self._fill_check.setChecked(cfg.auto_fill_last_page)
        self._suffix_edit.setText(cfg.output_suffix)

    def _on_auto_adj_changed(self, checked) -> None:
        """自动调整开关联动：未勾选时缩小级别下拉置灰。"""
        enabled = bool(checked)
        self._shrink_row.setEnabled(enabled)

    def _split_kw(self, text: str) -> list[str]:
        return [s.strip() for s in text.split(",") if s.strip()]

    def _current_style(self) -> PageNumberStyle:
        margin = self._margin_spin.value()
        vert = "top" if self._vert_pos_combo.currentIndex() == 1 else "bottom"
        return PageNumberStyle(
            font=self._font_combo.currentText() or "Times New Roman",
            fontsize_pt=float(self._size_spin.value()),
            color=tuple(self._color_rgb),
            margin_right_mm=margin,
            margin_left_mm=margin,
            margin_bottom_mm=float(self._margin_v.value()),
            margin_top_mm=float(self._margin_v.value()),
            vertical_position=vert,
        )

    def _on_vert_pos_changed(self, _index: int) -> None:
        """垂直位置切换：更新"距上/距下边缘"标签。"""
        vert = "top" if self._vert_pos_combo.currentIndex() == 1 else "bottom"
        self._margin_v_label.setText("距上边缘" if vert == "top" else "距下边缘")

    def _set_color_button(self, color) -> None:
        self._color_btn.setStyleSheet(
            "QPushButton{background:%s;color:%s;border:1px solid #ccc;}"
            % (QColor(*color).name(), "#ffffff" if sum(color) < 384 else "#000000")
        )

    def _on_pick_color(self) -> None:
        color = QColorDialog.getColor(QColor(*self._color_rgb), self, "选择页码颜色")
        if color.isValid():
            self._color_rgb = (color.red(), color.green(), color.blue())
            self._set_color_button(self._color_rgb)

    def _current_config(self) -> DocumentConfig:
        """按当前 UI 值构造 DocumentConfig（不触碰 controller 状态）。"""
        cfg = DocumentConfig()
        cfg.start_page_number = self._start_spin.value()
        cfg.auto_number_blank_pages = self._blank_num_check.isChecked()
        cfg.auto_adjust_overlap = self._auto_adj_check.isChecked()
        cfg.auto_shrink_levels = self._shrink_combo.currentIndex()
        cfg.global_style = self._current_style()
        cfg.auto_detect_keywords = {
            PageMark.COVER: self._split_kw(self._kw_cover.text()),
            PageMark.SIGNATURE: self._split_kw(self._kw_sign.text()),
            PageMark.FRONT: self._split_kw(self._kw_toc.text()),
            "body": self._split_kw(self._kw_body.text()),
        }
        cfg.auto_fill_last_page = self._fill_check.isChecked()
        cfg.output_suffix = self._suffix_edit.text().strip()
        return cfg

    def _on_save_default(self) -> None:
        """保存为默认：写应用级全局默认配置，不影响当前文档。"""
        from pdfsim.config import ConfigManager

        cfg_mgr = (
            self.controller.config_mgr
            if self.controller is not None
            else ConfigManager()
        )
        try:
            cfg_mgr.save_global_default(self._current_config())
        except OSError as e:  # pragma: no cover
            QMessageBox.warning(self, "保存失败", f"写入默认配置失败：{e}")
            return
        QMessageBox.information(
            self,
            "已保存默认配置",
            "已将当前设置保存为应用级默认配置。\n"
            "之后打开没有专属配置的新 PDF 会自动应用。",
        )

    def accept(self) -> None:
        """确定：应用到 controller（触发重建 + 防抖保存）。"""
        if self.controller is not None:
            self.controller.set_start_page_number(self._start_spin.value())
            self.controller.set_auto_number_blank_pages(self._blank_num_check.isChecked())
            self.controller.set_auto_adjust_overlap(self._auto_adj_check.isChecked())
            self.controller.set_auto_shrink_levels(self._shrink_combo.currentIndex())
            self.controller.set_global_style(self._current_style())
            self.controller.set_keywords(
                {
                    PageMark.COVER: self._split_kw(self._kw_cover.text()),
                    PageMark.SIGNATURE: self._split_kw(self._kw_sign.text()),
                    PageMark.FRONT: self._split_kw(self._kw_toc.text()),
                    "body": self._split_kw(self._kw_body.text()),
                }
            )
            self.controller.set_auto_fill_last(self._fill_check.isChecked())
            self.controller.set_output_suffix(self._suffix_edit.text().strip())
        super().accept()
