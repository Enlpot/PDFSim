# -*- coding: utf-8 -*-
"""配置读写测试（依据 Stage2 提示语 5.2 测试要求）。"""
import json
import os

import pytest

from pdfsim.config import ConfigManager, PageConfigData
from pdfsim.models import (
    DocumentConfig,
    PageInfo,
    PageMark,
    PageNumberPos,
    PageNumberStyle,
    RotationOverride,
)


@pytest.fixture
def cfg_mgr():
    return ConfigManager()


@pytest.fixture(autouse=True)
def _isolate_global_default(tmp_path, monkeypatch):
    """隔离应用级全局默认配置路径，避免测试读到真实用户配置。"""
    gd = tmp_path / "PDFSim" / "global_default.json"
    monkeypatch.setattr(
        ConfigManager, "global_default_path", staticmethod(lambda: str(gd)))
    return gd


@pytest.fixture
def fake_pdf(tmp_path):
    """模拟一个 PDF 文件路径（不实际创建 PDF，仅用于配置文件路径推导）。"""
    p = tmp_path / "合同.pdf"
    p.write_bytes(b"%PDF-1.4 fake")
    return str(p)


@pytest.fixture
def a3_page():
    return PageInfo(original_index=2, width_mm=297.0, height_mm=420.0)


class TestConfigPath:
    def test_config_path(self, cfg_mgr, fake_pdf):
        expected = os.path.splitext(fake_pdf)[0] + ".pagerconfig.json"
        assert cfg_mgr.config_path_for(fake_pdf) == expected

    def test_config_exists_false(self, cfg_mgr, fake_pdf):
        assert cfg_mgr.config_exists(fake_pdf) is False


class TestSaveLoadRoundtrip:
    def test_default_roundtrip(self, cfg_mgr, fake_pdf):
        cfg = DocumentConfig()
        cfg_mgr.save_config(fake_pdf, cfg)
        assert cfg_mgr.config_exists(fake_pdf)
        loaded = cfg_mgr.load_config(fake_pdf)
        assert loaded.start_page_number == cfg.start_page_number
        assert loaded.global_style.font == cfg.global_style.font
        assert loaded.global_style.fontsize_pt == cfg.global_style.fontsize_pt
        assert loaded.global_style.color == cfg.global_style.color
        assert loaded.auto_fill_last_page == cfg.auto_fill_last_page

    def test_custom_roundtrip(self, cfg_mgr, fake_pdf):
        cfg = DocumentConfig()
        cfg.start_page_number = 7
        cfg.global_style = PageNumberStyle(
            font="SimSun", fontsize_pt=12.0, color=(255, 0, 0),
            margin_right_mm=15.0, margin_left_mm=12.0, margin_bottom_mm=8.0,
        )
        cfg.auto_fill_last_page = True
        cfg.auto_detect_keywords[PageMark.COVER].append("titlepage")
        cfg.custom_labels = ["已审阅"]
        cfg_mgr.save_config(fake_pdf, cfg)
        loaded = cfg_mgr.load_config(fake_pdf)
        assert loaded.start_page_number == 7
        assert loaded.global_style.font == "SimSun"
        assert loaded.global_style.fontsize_pt == 12.0
        assert loaded.global_style.color == (255, 0, 0)
        assert loaded.global_style.margin_right_mm == 15.0
        assert loaded.auto_fill_last_page is True
        assert "titlepage" in loaded.auto_detect_keywords[PageMark.COVER]
        assert loaded.custom_labels == ["已审阅"]

    def test_load_nonexistent_returns_default(self, cfg_mgr, fake_pdf):
        loaded = cfg_mgr.load_config(fake_pdf)
        assert loaded.start_page_number == 1


class TestGlobalDefault:
    """应用级全局默认配置（全局设置"保存为默认"）。"""

    def test_save_load_roundtrip(self, cfg_mgr):
        cfg = DocumentConfig(start_page_number=7)
        cfg.global_style = PageNumberStyle(
            font="SimSun", fontsize_pt=11.0, color=(255, 0, 0),
            margin_right_mm=15.0)
        cfg.auto_adjust_overlap = False
        cfg.auto_shrink_levels = 1
        cfg.auto_fill_last_page = True
        cfg.auto_number_blank_pages = True
        cfg.auto_detect_keywords[PageMark.COVER].append("titlepage")
        cfg.output_suffix = "（默认）"
        cfg_mgr.save_global_default(cfg)
        loaded = cfg_mgr.load_global_default()
        assert loaded is not None
        assert loaded.start_page_number == 7
        assert loaded.global_style.font == "SimSun"
        assert loaded.global_style.fontsize_pt == 11.0
        assert loaded.global_style.color == (255, 0, 0)
        assert loaded.global_style.margin_right_mm == 15.0
        assert loaded.auto_adjust_overlap is False
        assert loaded.auto_shrink_levels == 1
        assert loaded.auto_fill_last_page is True
        assert loaded.auto_number_blank_pages is True
        assert "titlepage" in loaded.auto_detect_keywords[PageMark.COVER]
        assert loaded.output_suffix == "（默认）"

    def test_load_missing_returns_none(self, cfg_mgr):
        assert cfg_mgr.load_global_default() is None

    def test_load_corrupted_returns_none(self, cfg_mgr):
        path = cfg_mgr.global_default_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("{bad json")
        assert cfg_mgr.load_global_default() is None

    def test_load_config_falls_back_to_global_default(self, cfg_mgr, fake_pdf):
        """新 PDF（无专属配置）→ 自动应用全局默认。"""
        cfg = DocumentConfig(start_page_number=9)
        cfg.global_style = PageNumberStyle(font="SimHei", fontsize_pt=10.0)
        cfg_mgr.save_global_default(cfg)
        loaded = cfg_mgr.load_config(fake_pdf)
        assert loaded.start_page_number == 9
        assert loaded.global_style.font == "SimHei"
        assert loaded.global_style.fontsize_pt == 10.0

    def test_load_config_prefers_pdf_specific(self, cfg_mgr, fake_pdf):
        """已有专属配置的 PDF 继续用专属，不受全局默认影响。"""
        cfg_mgr.save_global_default(DocumentConfig(start_page_number=9))
        spec = DocumentConfig(start_page_number=5)
        spec.global_style = PageNumberStyle(font="KaiTi")
        cfg_mgr.save_config(fake_pdf, spec)
        loaded = cfg_mgr.load_config(fake_pdf)
        assert loaded.start_page_number == 5
        assert loaded.global_style.font == "KaiTi"

    def test_load_config_hardcoded_when_no_global_default(self, cfg_mgr, fake_pdf):
        """无专属也无全局默认 → 硬编码默认。"""
        loaded = cfg_mgr.load_config(fake_pdf)
        assert loaded.start_page_number == 1
        assert loaded.global_style.font == "Times New Roman"


class TestImportConfig:
    """导入已有配置文件到目标 PDF（source_file 替换为当前 PDF 绝对路径）。"""

    def _make_src(self, tmp_path, target_name="合同.pdf"):
        """构造一份源配置（旧版本风格：source_file 为死路径）。"""
        src = tmp_path / "source.pagerconfig.json"
        src.write_text(
            '{"version": 2, "source_file": "D:\\\\@old\\\\旧文档.pdf",'
            ' "global": {"start_page_number": 7,'
            '   "style": {"font": "SimSun", "fontsize_pt": 11.0}},'
            ' "pages": [{"original_index": 0, "marks": ["signature"]}]}',
            encoding="utf-8",
        )
        return str(src)

    def test_import_replaces_source_file(self, cfg_mgr, tmp_path, fake_pdf):
        """导入后：写入目标 PDF 旁配置文件，source_file 替换为目标 PDF 绝对路径，
        全局与页面级配置完整保留。"""
        src = self._make_src(tmp_path)
        written = cfg_mgr.import_config(src, fake_pdf)
        assert written == cfg_mgr.config_path_for(fake_pdf)
        assert os.path.isfile(written)
        loaded = cfg_mgr.load_config(fake_pdf)
        assert loaded.start_page_number == 7
        assert loaded.global_style.font == "SimSun"
        pcs = cfg_mgr.load_page_configs(fake_pdf)
        assert 0 in pcs and PageMark.SIGNATURE in pcs[0].marks
        # source_file 已替换
        import json

        with open(written, encoding="utf-8") as f:
            data = json.load(f)
        assert data["source_file"] == os.path.abspath(fake_pdf)

    def test_import_missing_returns_none(self, cfg_mgr, tmp_path, fake_pdf):
        assert cfg_mgr.import_config(str(tmp_path / "none.json"), fake_pdf) is None

    def test_import_bad_version_returns_none(self, cfg_mgr, tmp_path, fake_pdf):
        src = tmp_path / "bad.json"
        src.write_text('{"version": 999, "source_file": "x"}', encoding="utf-8")
        assert cfg_mgr.import_config(str(src), fake_pdf) is None

    def test_import_v1_migrates_version(self, cfg_mgr, tmp_path, fake_pdf):
        src = tmp_path / "v1.json"
        src.write_text(
            '{"version": 1, "source_file": "D:\\\\@old\\\\旧.pdf",'
            ' "global": {"start_page_number": 3}}',
            encoding="utf-8",
        )
        written = cfg_mgr.import_config(str(src), fake_pdf)
        assert written is not None
        assert cfg_mgr.load_config(fake_pdf).start_page_number == 3

    def test_import_corrupted_returns_none(self, cfg_mgr, tmp_path, fake_pdf):
        src = tmp_path / "bad.json"
        src.write_text("{oops", encoding="utf-8")
        assert cfg_mgr.import_config(str(src), fake_pdf) is None


class TestVersionAndSourceValidation:
    def test_version_mismatch_ignored(self, cfg_mgr, fake_pdf):
        path = cfg_mgr.config_path_for(fake_pdf)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"version": 999, "global": {"start_page_number": 5}}, f)
        loaded = cfg_mgr.load_config(fake_pdf)
        assert loaded.start_page_number == 1  # 回退默认

    def test_source_file_mismatch_ignored(self, cfg_mgr, fake_pdf):
        path = cfg_mgr.config_path_for(fake_pdf)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {"version": 1, "source_file": "D:\\other\\other.pdf",
                 "global": {"start_page_number": 5}}, f)
        loaded = cfg_mgr.load_config(fake_pdf)
        assert loaded.start_page_number == 1  # 回退默认

    def test_source_file_same_basename_new_folder_ok(self, cfg_mgr, fake_pdf):
        """PDF + 配置一起复制到新文件夹：source_file 只按文件名匹配，配置仍生效。"""
        path = cfg_mgr.config_path_for(fake_pdf)
        old_path = os.path.join("D:\\@test", os.path.basename(fake_pdf))
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {"version": 2, "source_file": old_path,
                 "global": {"start_page_number": 5}}, f)
        loaded = cfg_mgr.load_config(fake_pdf)
        assert loaded.start_page_number == 5

    def test_page_configs_same_basename_new_folder_ok(self, cfg_mgr, fake_pdf):
        """复制后页面级配置同样生效（_validate_config 一致受益）。"""
        path = cfg_mgr.config_path_for(fake_pdf)
        old_path = os.path.join("D:\\@test", os.path.basename(fake_pdf))
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {"version": 2, "source_file": old_path,
                 "pages": [{"original_index": 0, "marks": ["signature"]}]}, f)
        loaded = cfg_mgr.load_page_configs(fake_pdf)
        assert 0 in loaded
        assert PageMark.SIGNATURE in loaded[0].marks

    def test_corrupted_json_ignored(self, cfg_mgr, fake_pdf):
        path = cfg_mgr.config_path_for(fake_pdf)
        with open(path, "w", encoding="utf-8") as f:
            f.write("{invalid json!!!")
        loaded = cfg_mgr.load_config(fake_pdf)
        assert loaded.start_page_number == 1  # 不崩溃，回退默认


class TestPageConfigs:
    def test_page_roundtrip(self, cfg_mgr, fake_pdf):
        pc = PageConfigData(
            original_index=3,
            marks={PageMark.SIGNATURE, PageMark.FRONT},
            rotation_override=RotationOverride.CCW90,
            custom_labels=["签署"],
            number_pos_mode=PageNumberPos.CUSTOM,
            number_pos_offset_mm=(12.0, 8.0),
            style_override=PageNumberStyle(fontsize_pt=11.0),
        )
        cfg_mgr.save_page_configs(fake_pdf, {3: pc})
        loaded = cfg_mgr.load_page_configs(fake_pdf)
        assert 3 in loaded
        got = loaded[3]
        assert got.original_index == 3
        assert got.marks == {PageMark.SIGNATURE, PageMark.FRONT}
        assert got.rotation_override is RotationOverride.CCW90
        assert got.number_pos_mode is PageNumberPos.CUSTOM
        assert got.number_pos_offset_mm == (12.0, 8.0)
        assert got.style_override is not None and got.style_override.fontsize_pt == 11.0

    def test_rotation_override_serialize(self, cfg_mgr, fake_pdf):
        for rot in (RotationOverride.AUTO, RotationOverride.CW90,
                    RotationOverride.CCW90, RotationOverride.ROT180,
                    RotationOverride.NONE):
            pc = PageConfigData(original_index=0, rotation_override=rot)
            cfg_mgr.save_page_configs(fake_pdf, {0: pc})
            loaded = cfg_mgr.load_page_configs(fake_pdf)
            assert loaded[0].rotation_override is rot

    def test_old_config_without_rot180_falls_back(self, cfg_mgr, fake_pdf):
        # 旧配置无 rot180 值 → 加载 fallback AUTO（向后兼容）
        import json

        cfg_path = cfg_mgr.config_path_for(fake_pdf)
        os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump({"version": 2, "source_file": fake_pdf,
                       "pages": [{"original_index": 0, "rotation_override": "unknown_value"}]}, f)
        loaded = cfg_mgr.load_page_configs(fake_pdf)
        assert loaded[0].rotation_override is RotationOverride.AUTO

    def test_apply_to_pages(self, cfg_mgr, a3_page):
        pages = [
            PageInfo(original_index=0, width_mm=210.0, height_mm=297.0),
            a3_page,
        ]
        pcs = {
            0: PageConfigData(original_index=0, marks={PageMark.NO_COUNT},
                              rotation_override=RotationOverride.CW90),
            2: PageConfigData(original_index=2, marks=set(),
                              rotation_override=RotationOverride.NONE),
        }
        cfg_mgr.apply_page_configs(pages, pcs)
        # 普通页应用
        assert pages[0].marks == {PageMark.NO_COUNT}
        assert pages[0].rotation_override is RotationOverride.CW90
        # A3 页：应用 NONE 但 front 强制存在
        assert pages[1].rotation_override is RotationOverride.NONE
        assert PageMark.FRONT in pages[1].marks

    def test_a3_front_forced_even_if_not_in_config(self, cfg_mgr, a3_page):
        pages = [a3_page]
        pcs = {2: PageConfigData(original_index=2, marks={PageMark.COVER})}
        cfg_mgr.apply_page_configs(pages, pcs)
        assert PageMark.COVER in pages[0].marks
        assert PageMark.FRONT in pages[0].marks  # 强制

    def test_collect_and_save_all(self, cfg_mgr, fake_pdf, a3_page):
        cfg = DocumentConfig(start_page_number=3)
        pages = [PageInfo(original_index=0, width_mm=210.0, height_mm=297.0), a3_page]
        pages[0].marks.add(PageMark.NO_NUMBER)
        pages[1].marks.add(PageMark.FRONT)
        pcs = cfg_mgr.collect_page_configs(pages)
        cfg_mgr.save_all(fake_pdf, cfg, pcs)
        # 重新加载
        loaded_cfg = cfg_mgr.load_config(fake_pdf)
        loaded_pcs = cfg_mgr.load_page_configs(fake_pdf)
        assert loaded_cfg.start_page_number == 3
        assert loaded_pcs[0].marks == {PageMark.NO_NUMBER}
        assert PageMark.FRONT in loaded_pcs[2].marks

    def test_invalid_page_entry_skipped(self, cfg_mgr, fake_pdf):
        path = cfg_mgr.config_path_for(fake_pdf)
        data = {
            "version": 1, "source_file": os.path.abspath(fake_pdf),
            "pages": [{"no_index": 1}, {"original_index": "bad"}],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        loaded = cfg_mgr.load_page_configs(fake_pdf)
        assert loaded == {}
