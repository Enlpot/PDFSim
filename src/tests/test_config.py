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
                    RotationOverride.CCW90, RotationOverride.NONE):
            pc = PageConfigData(original_index=0, rotation_override=rot)
            cfg_mgr.save_page_configs(fake_pdf, {0: pc})
            loaded = cfg_mgr.load_page_configs(fake_pdf)
            assert loaded[0].rotation_override is rot

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
