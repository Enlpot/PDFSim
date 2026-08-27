# -*- coding: utf-8 -*-
"""异常弹窗 / 输出确认（依据《Stage3_提示语.md》5.7 与《UI原型说明.md》第 6 章）。

Stage 3 采用更友好的交互：损坏 / 空文档 / 密码取消均停留在空界面（不退出程序），
允许用户重新打开其他文件。
"""
from __future__ import annotations

import os
import subprocess
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QInputDialog,
    QLineEdit,
    QMessageBox,
)

if TYPE_CHECKING:  # pragma: no cover
    from PySide6.QtWidgets import QWidget


def show_corrupted(parent: "QWidget | None" = None) -> None:
    """损坏 PDF：仅确定 → 停留空界面。"""
    QMessageBox.critical(parent, "无法打开", "PDF 文件已损坏，无法打开")


def show_empty_document(parent: "QWidget | None" = None) -> None:
    """空文档：仅确定 → 停留空界面。"""
    QMessageBox.critical(parent, "无法打开", "PDF 文档无页面")


def show_load_error(parent: "QWidget | None" = None, detail: str = "") -> None:
    """通用加载错误（IO 等）。"""
    text = "PDF 文件无法打开"
    if detail:
        text += f"\n{detail}"
    QMessageBox.critical(parent, "无法打开", text)


def ask_password(parent: "QWidget | None" = None) -> str | None:
    """询问密码；取消返回 None。"""
    pwd, ok = QInputDialog.getText(
        parent,
        "输入密码",
        "该 PDF 已加密，请输入密码",
        QLineEdit.EchoMode.Password,
    )
    return pwd if ok else None


def show_password_error(parent: "QWidget | None" = None) -> bool:
    """密码错误：返回 True=重试，False=取消。"""
    box = QMessageBox(QMessageBox.Icon.Warning, "密码错误", "密码错误")
    retry = box.addButton("重试", QMessageBox.ButtonRole.AcceptRole)
    box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
    box.exec()
    return box.clickedButton() is retry


def show_output_exists(parent: "QWidget | None" = None, path: str = "") -> None:
    """输出文件已存在：仅确定，不覆盖。"""
    text = "输出文件已存在，已跳过"
    if path:
        text += f"\n{os.path.basename(path)}"
    QMessageBox.warning(parent, "输出", text)


def show_output_success(
    parent: "QWidget | None" = None, path: str = "", has_report: bool = False
) -> str:
    """输出成功对话框。

    返回点击按钮标识：'open'=打开文件夹 / 'report'=查看处理报告 / 'ok'=确定。
    """
    box = QMessageBox(QMessageBox.Icon.Information, "输出完成", f"输出完成：{path}")
    open_btn = box.addButton("打开文件夹", QMessageBox.ButtonRole.AcceptRole)
    report_btn = None
    if has_report:
        report_btn = box.addButton("查看处理报告", QMessageBox.ButtonRole.ActionRole)
    box.addButton("确定", QMessageBox.ButtonRole.RejectRole)
    box.exec()
    clicked = box.clickedButton()
    if clicked is report_btn:
        return "report"
    if clicked is open_btn:
        return "open"
    return "ok"


def show_output_failed(parent: "QWidget | None" = None, message: str = "") -> None:
    """输出失败（非已存在场景）。"""
    QMessageBox.critical(parent, "输出失败", message or "输出失败，请重试")


def open_folder(path: str) -> None:
    """打开输出文件所在文件夹。"""
    folder = os.path.dirname(os.path.abspath(path))
    try:
        if os.path.exists(folder):
            os.startfile(folder)  # type: ignore[attr-defined]  # Windows only
    except OSError:  # pragma: no cover
        pass
