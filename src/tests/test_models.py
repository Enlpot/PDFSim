# -*- coding: utf-8 -*-
"""数据结构测试（依据技术方案第 2 章）。"""
import pytest

from pdfsim.models import (
    A4_HEIGHT_MM,
    A4_WIDTH_MM,
    A3_HEIGHT_MM,
    A3_WIDTH_MM,
    MM_TO_PT,
    SIZE_TOLERANCE_MM,
    BlankPageSource,
    DocumentConfig,
    PageInfo,
    PageMark,
    PageNumberPos,
    PageNumberStyle,
    PageOrientation,
    ProcessedPage,
    ProcessPlan,
    RotationOverride,
    is_a3,
    is_a4,
)


class TestConstants:
    def test_mm_to_pt(self):
        assert MM_TO_PT == 72 / 25.4
        assert round(MM_TO_PT, 4) == 2.8346

    def test_tolerance(self):
        assert SIZE_TOLERANCE_MM == 2.0


class TestEnums:
    def test_page_mark_values(self):
        assert PageMark.COVER.value == "cover"
        assert PageMark.SIGNATURE.value == "signature"
        assert PageMark.NO_NUMBER.value == "no_number"
        assert PageMark.NO_COUNT.value == "no_count"
        assert PageMark.FRONT.value == "front"

    def test_blank_source_values(self):
        assert BlankPageSource.COVER_BACK.value == "cover_back"
        assert BlankPageSource.SIGN_BACK.value == "sign_back"
        assert BlankPageSource.NO_COUNT_USER.value == "no_count_user"
        assert BlankPageSource.PUSH_FRONT.value == "push_front"
        assert BlankPageSource.A3_BACK.value == "a3_back"
        assert BlankPageSource.FILL_LAST.value == "fill_last"

    def test_orientation(self):
        assert PageOrientation.PORTRAIT.value == "portrait"
        assert PageOrientation.LANDSCAPE.value == "landscape"

    def test_number_pos(self):
        assert PageNumberPos.BOTTOM_RIGHT.value == "bottom_right"
        assert PageNumberPos.BOTTOM_LEFT.value == "bottom_left"
        assert PageNumberPos.CUSTOM.value == "custom"

    def test_rotation_override(self):
        assert RotationOverride.AUTO.value == "auto"
        assert RotationOverride.CW90.value == "cw90"
        assert RotationOverride.CCW90.value == "ccw90"
        assert RotationOverride.NONE.value == "none"


class TestPageInfo:
    def test_defaults(self):
        p = PageInfo(original_index=0, width_mm=210.0, height_mm=297.0)
        assert p.original_index == 0
        assert p.source_rotation == 0
        assert p.detected_rotation == 0
        assert p.planned_rotation == 0
        assert p.rotation_override is RotationOverride.AUTO
        assert p.marks == set()
        assert p.custom_labels == []
        assert p.is_blank is False
        assert p.blank_source is None
        assert p.number_pos_override is None
        assert p.number_custom_offset_mm is None
        assert p.style_override is None

    def test_full_construction(self):
        p = PageInfo(
            original_index=2,
            width_mm=297.0,
            height_mm=210.0,
            source_rotation=90,
            detected_rotation=90,
            planned_rotation=90,
            rotation_override=RotationOverride.CW90,
            marks={PageMark.COVER, PageMark.FRONT},
            custom_labels=["已审阅"],
        )
        assert p.original_index == 2
        assert p.source_rotation == 90
        assert p.detected_rotation == 90
        assert p.planned_rotation == 90
        assert p.rotation_override is RotationOverride.CW90
        assert PageMark.COVER in p.marks
        assert "已审阅" in p.custom_labels


class TestPageNumberStyle:
    def test_defaults(self):
        s = PageNumberStyle()
        assert s.font == "Times New Roman"
        assert s.fontsize_pt == 9.0
        assert s.color == (0, 0, 0)
        assert s.margin_right_mm == 10.0
        assert s.margin_left_mm == 10.0
        assert s.margin_bottom_mm == 10.0


class TestDocumentConfig:
    def test_defaults(self):
        c = DocumentConfig()
        assert c.version == 1
        assert c.start_page_number == 1
        assert isinstance(c.global_style, PageNumberStyle)
        assert PageMark.COVER in c.auto_detect_keywords
        assert "封面" in c.auto_detect_keywords[PageMark.COVER]
        assert c.auto_fill_last_page is False
        assert c.output_suffix == "（打印装订）"

    def test_cover_keywords_present(self):
        c = DocumentConfig()
        assert c.auto_detect_keywords[PageMark.COVER] == ["封面", "cover"]
        assert c.auto_detect_keywords[PageMark.SIGNATURE] == ["签字", "签名", "signature", "sign"]


class TestIsA3A4:
    def test_a4_portrait(self):
        p = PageInfo(original_index=0, width_mm=A4_WIDTH_MM, height_mm=A4_HEIGHT_MM)
        assert is_a4(p) is True
        assert is_a3(p) is False

    def test_a4_landscape(self):
        p = PageInfo(original_index=0, width_mm=A4_HEIGHT_MM, height_mm=A4_WIDTH_MM)
        assert is_a4(p) is True

    def test_a3_portrait(self):
        p = PageInfo(original_index=0, width_mm=A3_WIDTH_MM, height_mm=A3_HEIGHT_MM)
        assert is_a3(p) is True
        assert is_a4(p) is False

    def test_a3_landscape(self):
        p = PageInfo(original_index=0, width_mm=A3_HEIGHT_MM, height_mm=A3_WIDTH_MM)
        assert is_a3(p) is True

    def test_tolerance_boundary(self):
        # 容差 ±2mm 内仍判定为 A4
        p = PageInfo(original_index=0, width_mm=210.0 + 1.5, height_mm=297.0 - 1.5)
        assert is_a4(p) is True
        # 超过容差则不是 A4
        p2 = PageInfo(original_index=0, width_mm=210.0 + 5.0, height_mm=297.0 - 5.0)
        assert is_a4(p2) is False

    def test_letter_not_a4(self):
        p = PageInfo(original_index=0, width_mm=215.9, height_mm=279.4)
        assert is_a4(p) is False
        assert is_a3(p) is False


class TestProcessedPage:
    def test_creation(self):
        src = PageInfo(original_index=0, width_mm=210.0, height_mm=297.0)
        pp = ProcessedPage(
            physical_index=1,
            source_page_info=src,
            is_blank=False,
            blank_source=None,
            number_text="1",
            number_occupies=True,
            number_position=PageNumberPos.BOTTOM_RIGHT,
            number_point=(100.0, 50.0),
            rotation=0,
            output_size_mm=(210.0, 297.0),
        )
        assert pp.physical_index == 1
        assert pp.number_text == "1"
        assert pp.number_occupies is True
        assert pp.number_point == (100.0, 50.0)


class TestProcessPlan:
    def test_creation(self):
        plan = ProcessPlan(
            pages=[],
            start_page_number=1,
            warnings=[],
            output_path="D:\\out.pdf",
        )
        assert plan.start_page_number == 1
        assert plan.output_path == "D:\\out.pdf"
