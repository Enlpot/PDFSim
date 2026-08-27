# -*- coding: utf-8 -*-
"""处理报告对话框（新提示语《旋转确认与处理报告》任务 2）。

表格展示每页处理信息（数据来自 controller.get_report_data()），
支持导出 CSV（UTF-8 with BOM，Excel 打开不乱码）。
"""
from __future__ import annotations

import csv
import os

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from pdfsim.ui.styles import FONT_DEFAULT


def export_report_csv(data: list[dict], path: str) -> None:
    """导出报告数据为 CSV（UTF-8 with BOM，Excel 打开不乱码）。"""
    if not data:
        raise ValueError("报告数据为空")
    columns = list(data[0].keys())
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        for row in data:
            writer.writerow([row.get(c, "") for c in columns])


class ReportDialog(QDialog):
    """处理报告对话框。"""

    def __init__(self, controller=None, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._data: list[dict] = []
        self.setWindowTitle("处理报告")
        self.resize(860, 560)
        self._build_ui()
        self._load_data()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        hint = QLabel("以下为输出 PDF 每一页的处理信息（只读，不影响规划与输出结果）。")
        hint.setStyleSheet("color:#606060;")
        hint.setFont(FONT_DEFAULT)
        root.addWidget(hint)

        self._table = QTableWidget()
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        root.addWidget(self._table, 1)

        btn_row = QHBoxLayout()
        self._export_btn = QPushButton("导出 CSV")
        self._export_btn.clicked.connect(self._on_export)
        btn_row.addWidget(self._export_btn)
        btn_row.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.clicked.connect(lambda _: self.reject())
        btn_row.addWidget(buttons)
        root.addLayout(btn_row)

    def _load_data(self) -> None:
        """从控制器实时取数据并填充表格。"""
        if self.controller is None:
            return
        self._data = self.controller.get_report_data()
        if not self._data:
            self._table.setRowCount(0)
            self._table.setColumnCount(0)
            return
        columns = list(self._data[0].keys())
        self._table.setColumnCount(len(columns))
        self._table.setHorizontalHeaderLabels(columns)
        self._table.setRowCount(len(self._data))
        for r, row in enumerate(self._data):
            for c, col in enumerate(columns):
                item = QTableWidgetItem(str(row.get(col, "")))
                self._table.setItem(r, c, item)

    # ------------------------------------------------------------------
    def _on_export(self) -> None:
        """导出 CSV（UTF-8 with BOM）。"""
        if self.controller is None or not self._data:
            QMessageBox.information(self, "处理报告", "暂无报告数据可导出。")
            return
        default_name = "处理报告.csv"
        base = os.path.basename(self.controller.pdf_path or "")
        if base:
            stem = os.path.splitext(base)[0]
            default_name = f"{stem}_处理报告.csv"
        default_dir = self.controller.config.output_dir or (
            os.path.dirname(self.controller.pdf_path or "") if self.controller.pdf_path else "")
        path, _ = QFileDialog.getSaveFileName(
            self, "导出处理报告", os.path.join(default_dir or "", default_name),
            "CSV 文件 (*.csv)")
        if not path:
            return
        try:
            export_report_csv(self._data, path)
        except OSError as e:
            QMessageBox.warning(self, "导出失败", f"写入文件失败：{e}")
            return
        QMessageBox.information(self, "处理报告", f"已导出：{path}")
