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


# ---------------------------------------------------------------------------
# 导入配置（import_config_to_current）
# ---------------------------------------------------------------------------
def _src_config(tmp_path, start=9, marks="") -> str:
    src = tmp_path / "source.pagerconfig.json"
    pages = (
        f', "pages": [{{"original_index": 0, "marks": [{marks}]}}]'
        if marks else ', "pages": []'
    )
    src.write_text(
        '{"version": 2, "source_file": "D:\\\\@old\\\\旧文档.pdf",'
        f' "global": {{"start_page_number": {start},'
        '   "style": {"font": "SimHei", "fontsize_pt": 10.0}}'
        f'{pages}}}',
        encoding="utf-8",
    )
    return str(src)


def _copy_sample(samples_dir, tmp_path, name="sample_a4_portrait.pdf") -> str:
    import shutil

    dst = tmp_path / name
    shutil.copyfile(str(samples_dir / name), dst)
    return str(dst)


def test_import_config_to_current_applies(make_window, tmp_path, samples_dir):
    """导入配置到当前 PDF：source_file 替换、全局+页面级配置应用、写入 PDF 旁。"""
    import json
    import os

    from pdfsim.models import PageMark

    dst = _copy_sample(samples_dir, tmp_path)
    w = make_window()
    c = w.controller
    c.open_pdf(dst, "")
    assert c.import_config_to_current(
        _src_config(tmp_path, start=9, marks='"signature"')
    ) is True
    # 全局设置应用
    assert c.config.start_page_number == 9
    assert c.config.global_style.font == "SimHei"
    assert c.config.global_style.fontsize_pt == 10.0
    # 页面级标记应用
    assert PageMark.SIGNATURE in c.source_pages[0].marks
    # 配置文件已写入目标 PDF 旁，且 source_file 替换为当前 PDF
    cfg_path = os.path.splitext(dst)[0] + ".pagerconfig.json"
    assert os.path.isfile(cfg_path)
    with open(cfg_path, encoding="utf-8") as f:
        data = json.load(f)
    assert data["source_file"] == os.path.abspath(dst)


def test_import_config_requires_open(make_window, tmp_path):
    """未打开 PDF 时导入返回 False。"""
    w = make_window()
    c = w.controller
    assert c.import_config_to_current(_src_config(tmp_path)) is False


def test_import_config_bad_source_returns_false(make_window, tmp_path, samples_dir):
    """源配置缺失/损坏 → 导入失败返回 False。"""
    dst = _copy_sample(samples_dir, tmp_path)
    w = make_window()
    c = w.controller
    c.open_pdf(dst, "")
    assert c.import_config_to_current(str(tmp_path / "none.json")) is False
