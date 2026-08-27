# -*- coding: utf-8 -*-
"""异常弹窗模块测试（Stage 3 交付物 2 的补充）。

覆盖：损坏 / 空文档 / 密码询问 / 密码错误 / 输出已存在 / 输出成功 / 打开文件夹。
"""
from __future__ import annotations

from pdfsim.ui import dialogs


class _FakeMsgBox:
    """可点击按钮的假 QMessageBox（作为类替换，需带 Icon 类属性）。"""

    class Icon:
        Warning = 0
        Information = 1
        Critical = 2

    class ButtonRole:
        AcceptRole = 0
        RejectRole = 1
        ActionRole = 2

    _clicked = "确定"

    def __init__(self, *args, **kwargs):
        self._buttons = {}

    def addButton(self, text, role=None):
        self._buttons[text] = text
        return text

    def exec(self):
        return None

    def clickedButton(self):
        return self._buttons.get(self._clicked)


def _patch_msgbox(monkeypatch, clicked):
    _FakeMsgBox._clicked = clicked
    monkeypatch.setattr("pdfsim.ui.dialogs.QMessageBox", _FakeMsgBox)


def test_show_corrupted(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        "pdfsim.ui.dialogs.QMessageBox.critical",
        lambda *a, **k: seen.setdefault("args", a),
    )
    dialogs.show_corrupted()
    assert "损坏" in seen["args"][2]


def test_show_empty_document(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        "pdfsim.ui.dialogs.QMessageBox.critical",
        lambda *a, **k: seen.setdefault("args", a),
    )
    dialogs.show_empty_document()
    assert "无页面" in seen["args"][2]


def test_show_load_error_with_detail(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        "pdfsim.ui.dialogs.QMessageBox.critical",
        lambda *a, **k: seen.setdefault("args", a),
    )
    dialogs.show_load_error(detail="IO 异常")
    assert "IO 异常" in seen["args"][2]


def test_ask_password_ok(monkeypatch):
    monkeypatch.setattr(
        "pdfsim.ui.dialogs.QInputDialog.getText",
        lambda *a, **k: ("secret", True),
    )
    assert dialogs.ask_password() == "secret"


def test_ask_password_cancel(monkeypatch):
    monkeypatch.setattr(
        "pdfsim.ui.dialogs.QInputDialog.getText",
        lambda *a, **k: ("", False),
    )
    assert dialogs.ask_password() is None


def test_show_password_error_retry(monkeypatch):
    _patch_msgbox(monkeypatch, "重试")
    assert dialogs.show_password_error() is True


def test_show_password_error_cancel(monkeypatch):
    _patch_msgbox(monkeypatch, "取消")
    assert dialogs.show_password_error() is False


def test_show_output_exists(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        "pdfsim.ui.dialogs.QMessageBox.warning",
        lambda *a, **k: seen.setdefault("args", a),
    )
    dialogs.show_output_exists(path="C:/x/out.pdf")
    assert "已存在" in seen["args"][2]
    assert "out.pdf" in seen["args"][2]


def test_show_output_success_open(monkeypatch):
    _patch_msgbox(monkeypatch, "打开文件夹")
    assert dialogs.show_output_success(path="C:/x/out.pdf") == "open"


def test_show_output_success_close(monkeypatch):
    _patch_msgbox(monkeypatch, "确定")
    assert dialogs.show_output_success(path="C:/x/out.pdf") == "ok"


def test_show_output_success_report(monkeypatch):
    _patch_msgbox(monkeypatch, "查看处理报告")
    assert dialogs.show_output_success(path="C:/x/out.pdf", has_report=True) == "report"


def test_open_folder(monkeypatch, tmp_path):
    called = {}
    sub = tmp_path / "sub"
    sub.mkdir()
    target = sub / "out.pdf"
    target.write_bytes(b"x")
    monkeypatch.setattr(
        "pdfsim.ui.dialogs.os.startfile",
        lambda p: called.setdefault("path", p),
    )
    dialogs.open_folder(str(target))
    assert called.get("path") == str(sub)


def test_show_output_failed(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        "pdfsim.ui.dialogs.QMessageBox.critical",
        lambda *a, **k: seen.setdefault("args", a),
    )
    dialogs.show_output_failed(message="boom")
    assert "boom" in seen["args"][2]
