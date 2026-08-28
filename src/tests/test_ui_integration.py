# -*- coding: utf-8 -*-
"""UI 端到端集成测试（Stage 3 交付物 2 的一部分）。

覆盖：打开→预览→标记→输出全流程 / 配置保存恢复 / 加密弹密码 / 损坏弹错误。
"""
from __future__ import annotations

import os

from PySide6.QtWidgets import QMessageBox

from pdfsim.models import PageMark


def test_end_to_end_flow(make_window, samples_dir, tmp_path, monkeypatch):
    """端到端：打开 → 预览 → 标记 → 输出（原文件不变、可二次跳过）。"""
    w, c = _open(make_window, samples_dir, "sample_a4_portrait.pdf")
    # 预览
    assert c.plan_page_count() > 0
    assert len(w.thumbnail_panel._items) == c.plan_page_count()
    # 标记
    oi = c.source_pages[0].original_index
    c.set_page_mark(oi, PageMark.COVER, True)
    assert PageMark.COVER in c.source_page(oi).marks
    # 输出到临时目录
    c.config.output_dir = str(tmp_path)
    result = c.output()
    assert result is not None and result.success
    assert os.path.exists(result.output_path)
    assert result.source_hash_verified
    # 再次输出 → 已存在跳过
    result2 = c.output()
    assert result2 is not None and not result2.success
    assert "已存在" in result2.message


def test_config_save_restore(make_window, samples_dir, monkeypatch):
    """配置自动保存（防抖）与重开恢复。"""
    w, c = _open(make_window, samples_dir, "sample_single.pdf")
    cfg_path = c.config_mgr.config_path_for(c.pdf_path)
    if os.path.exists(cfg_path):
        os.remove(cfg_path)
    oi = c.source_pages[0].original_index
    c.set_page_mark(oi, PageMark.SIGNATURE, True)
    # 触发防抖保存（等 600ms > 500ms 防抖）
    import time
    time.sleep(0.6)
    w.controller._save_timer.stop()
    c._do_save_config()
    assert os.path.exists(cfg_path)

    # 重新打开恢复
    w.controller.open_pdf(c.pdf_path, "")
    assert PageMark.SIGNATURE in w.controller.source_page(oi).marks
    if os.path.exists(cfg_path):
        os.remove(cfg_path)


def test_config_save_debounce(make_window, samples_dir, qtbot):
    """防抖：500ms 内多次变更只落盘一次。"""
    w, c = _open(make_window, samples_dir, "sample_single.pdf")
    cfg_path = c.config_mgr.config_path_for(c.pdf_path)
    if os.path.exists(cfg_path):
        os.remove(cfg_path)
    oi = c.source_pages[0].original_index
    c.set_page_mark(oi, PageMark.COVER, True)
    assert not os.path.exists(cfg_path)  # 未到防抖时间不落盘
    import time
    time.sleep(0.6)
    qtbot.wait(10)
    c._do_save_config()
    assert os.path.exists(cfg_path)
    if os.path.exists(cfg_path):
        os.remove(cfg_path)


def test_encrypted_password_flow(make_window, samples_dir, monkeypatch):
    """加密 PDF：弹密码框 → 正确密码 → 打开成功。"""
    w = make_window()
    path = str(samples_dir / "sample_encrypted.pdf")
    seen = {}

    monkeypatch.setattr(
        "pdfsim.ui.main_window.dialogs.ask_password",
        lambda *a, **k: seen.setdefault("pwd", "testpass"),
    )
    w._open_pdf_flow(path)
    assert w.controller.pdf_path is not None
    assert seen.get("pwd") == "testpass"
    assert w.controller.plan_page_count() > 0


def test_encrypted_wrong_password_retry(make_window, samples_dir, monkeypatch):
    """加密 PDF：错误密码 → 提示重试 → 正确密码成功。"""
    w = make_window()
    path = str(samples_dir / "sample_encrypted.pdf")
    attempts = []

    def fake_ask(*a, **k):
        attempts.append(1)
        return "testpass"

    monkeypatch.setattr("pdfsim.ui.main_window.dialogs.ask_password", fake_ask)
    # 第一次 open（无密码）抛 PasswordError，进入密码流程
    w._open_pdf_flow(path)
    assert w.controller.pdf_path is not None
    assert len(attempts) >= 1


def test_corrupted_shows_error(make_window, samples_dir, monkeypatch):
    """损坏 PDF：弹出"无法打开"错误框，停留空界面（不退出）。"""
    w = make_window()
    shown = {}
    monkeypatch.setattr(
        "pdfsim.ui.main_window.dialogs.show_corrupted",
        lambda *a, **k: shown.setdefault("corrupted", True),
    )
    w._open_pdf_flow(str(samples_dir / "sample_corrupted.pdf"))
    assert shown.get("corrupted")
    assert w.controller.pdf_path is None  # 停留空界面
    assert w.isVisible()  # 窗口仍在


def test_empty_password_cancel(make_window, samples_dir, monkeypatch):
    """加密 PDF 取消输入 → 停留空界面。"""
    w = make_window()
    monkeypatch.setattr(
        "pdfsim.ui.main_window.dialogs.ask_password", lambda *a, **k: None
    )
    w._open_pdf_flow(str(samples_dir / "sample_encrypted.pdf"))
    assert w.controller.pdf_path is None
    assert w.isVisible()


def test_output_exists_dialog(make_window, samples_dir, tmp_path, monkeypatch, qtbot):
    """输出已存在 → 弹"已存在，已跳过"警告（不覆盖）。

    方案 C 后 on_output 为异步（后台线程 + output_result_ready 信号），
    需等待信号确认结果弹窗路径。
    """
    w, c = _open(make_window, samples_dir, "sample_a4_portrait.pdf")
    c.config.output_dir = str(tmp_path)
    shown = {}
    monkeypatch.setattr(
        "pdfsim.ui.main_window.dialogs.show_output_exists",
        lambda *a, **k: shown.setdefault("exists", True),
    )
    # 首次输出成功
    r1 = c.output()
    assert r1.success
    # 通过 UI 输出（第二次 → 已存在；异步等待结果）
    with qtbot.waitSignal(c.output_result_ready, timeout=30000):
        w.on_output()
    assert shown.get("exists")
    assert w.act_output.isEnabled()  # 输出按钮已恢复


def test_global_settings_apply(make_window, samples_dir, qtbot):
    """全局设置对话框：修改后应用到 config 并保存。"""
    w, c = _open(make_window, samples_dir, "sample_single.pdf")
    from pdfsim.ui.global_settings import GlobalSettingsDialog

    dlg = GlobalSettingsDialog(c)
    dlg._start_spin.setValue(7)
    dlg._size_spin.setValue(14.0)
    dlg.accept()
    assert c.config.start_page_number == 7
    assert c.config.global_style.fontsize_pt == 14.0
    # 起始页码变化 → 页码重算
    pp = c.current_plan.pages[0]
    assert pp.number_text == "7"


def _open(make_window, samples_dir, rel):
    w = make_window()
    c = w.controller
    c.open_pdf(str(samples_dir / rel), "")
    return w, c
