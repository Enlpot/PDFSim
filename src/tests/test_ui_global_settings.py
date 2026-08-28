# -*- coding: utf-8 -*-
"""全局设置对话框『保存为默认』按钮测试。

覆盖：点击按钮写入应用级全局默认配置（不影响当前文档）。
"""
from __future__ import annotations

from pdfsim.config import ConfigManager


def _patch_msgboxes(monkeypatch):
    """避免 QMessageBox 弹窗阻塞测试。"""
    monkeypatch.setattr(
        "pdfsim.ui.global_settings.QMessageBox.information",
        staticmethod(lambda *a, **k: None),
    )
    monkeypatch.setattr(
        "pdfsim.ui.global_settings.QMessageBox.warning",
        staticmethod(lambda *a, **k: None),
    )


def test_save_default_button_writes_global_default(qtbot, monkeypatch, tmp_path):
    """点击『保存为默认』→ 写入应用级全局默认，可被 load_global_default 读回。"""
    gd = tmp_path / "PDFSim" / "global_default.json"
    monkeypatch.setattr(
        ConfigManager, "global_default_path", staticmethod(lambda: str(gd)))
    _patch_msgboxes(monkeypatch)

    from pdfsim.ui.global_settings import GlobalSettingsDialog

    dlg = GlobalSettingsDialog(controller=None)
    dlg._start_spin.setValue(3)
    dlg._font_combo.setCurrentText("SimSun")
    dlg._size_spin.setValue(11.0)
    dlg._auto_adj_check.setChecked(False)
    dlg._kw_cover.setText("封面, titlepage")
    dlg._save_default_btn.click()
    qtbot.wait(20)

    loaded = ConfigManager().load_global_default()
    assert loaded is not None
    assert loaded.start_page_number == 3
    assert loaded.global_style.font == "SimSun"
    assert loaded.global_style.fontsize_pt == 11.0
    assert loaded.auto_adjust_overlap is False
    assert "titlepage" in loaded.auto_detect_keywords[__import__(
        "pdfsim.models", fromlist=["PageMark"]).PageMark.COVER]


def test_save_default_keeps_current_doc_untouched(qtbot, monkeypatch, tmp_path):
    """『保存为默认』只写全局默认，不改变当前文档 controller.config。"""
    gd = tmp_path / "PDFSim" / "global_default.json"
    monkeypatch.setattr(
        ConfigManager, "global_default_path", staticmethod(lambda: str(gd)))
    _patch_msgboxes(monkeypatch)

    from pdfsim.models import DocumentConfig
    from pdfsim.ui.global_settings import GlobalSettingsDialog

    class _FakeController:
        def __init__(self):
            self.config = DocumentConfig(start_page_number=100)
            self.config_mgr = ConfigManager()

    controller = _FakeController()
    dlg = GlobalSettingsDialog(controller=controller)
    dlg._start_spin.setValue(3)  # 对话框里改起始页码
    dlg._save_default_btn.click()
    qtbot.wait(20)

    # 当前文档配置不变（保存为默认不 apply）
    assert controller.config.start_page_number == 100
    # 但全局默认已更新
    assert ConfigManager().load_global_default().start_page_number == 3
