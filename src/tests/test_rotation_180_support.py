# -*- coding: utf-8 -*-
"""旋转检测优化 + 180° 支持 专项测试。

覆盖：
1. 页码位置在 180° 页上正确（_derotate 坐标变换 + calculate_number_position 对称）
2. 空白页正确继承 180°（ROT180 覆盖 → 同纸背面同向）
3. UI 旋转下拉含"旋转 180°"项，切换后生效
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # 供导入 _stage4_helpers

import pytest

from _stage4_helpers import copy_sample

from pdfsim.engine import _derotate, calculate_number_position
from pdfsim.models import (
    MM_TO_PT,
    BlankPageSource,
    PageInfo,
    PageMark,
    PageNumberPos,
    PageNumberStyle,
    ProcessedPage,
    RotationOverride,
)


def open_pdf(tmp_path, rel: str):
    from pdfsim.ui.app_controller import AppController

    src = copy_sample(rel, str(tmp_path))
    c = AppController()
    c.open_pdf(src, "")
    return c


def _back(c, source: BlankPageSource):
    return next(pp for pp in c.current_plan.pages
                if pp.blank_source is source)


def _a4_pp(rotation: int, physical_index: int = 1) -> ProcessedPage:
    """构造 A4 纵向 ProcessedPage（源页无自带 /Rotate）。"""
    src = PageInfo(original_index=0, width_mm=210.0, height_mm=297.0)
    src.detected_rotation = rotation
    return ProcessedPage(
        physical_index=physical_index,
        source_page_info=src,
        is_blank=False,
        blank_source=None,
        number_text="1",
        number_occupies=True,
        number_position=PageNumberPos.BOTTOM_RIGHT,
        number_point=None,
        rotation=rotation,
        output_size_mm=(210.0, 297.0) if rotation in (0, 180) else (297.0, 210.0),
    )


class TestPageNumberPosition180:
    def test_derotate_180(self):
        Wd, Hd = 210.0 * MM_TO_PT, 297.0 * MM_TO_PT
        x, y = 40.0, 60.0
        assert _derotate(x, y, 180, Wd, Hd) == (Wd - x, Hd - y)

    def test_calculate_position_180_symmetric(self):
        """rotation=0 与 180 的页码点互为 180° 对称，且不越界。"""
        style = PageNumberStyle()
        p0 = _a4_pp(0)
        p180 = _a4_pp(180)
        pt0 = calculate_number_position(p0, style, 1, 50.0)
        pt180 = calculate_number_position(p180, style, 1, 50.0)
        assert pt0 is not None and pt180 is not None
        Wd, Hd = 210.0 * MM_TO_PT, 297.0 * MM_TO_PT
        assert pt180[0] == pytest.approx(Wd - pt0[0], abs=1e-6)
        assert pt180[1] == pytest.approx(Hd - pt0[1], abs=1e-6)
        assert 0 <= pt180[0] <= Wd
        assert 0 <= pt180[1] <= Hd

    def test_calculate_position_180_bottom_right(self):
        """180° 页 + 默认样式：页码落在旋转后右下角（正面）。"""
        style = PageNumberStyle()
        p = _a4_pp(180, physical_index=1)
        pt = calculate_number_position(p, style, 1, 50.0)
        assert pt is not None
        Wd, Hd = 210.0 * MM_TO_PT, 297.0 * MM_TO_PT
        # 旋转后右下角 → 未旋转左上角附近（x 小、y 接近 Hd）
        assert pt[0] < Wd * 0.5
        assert pt[1] > Hd * 0.5


class TestBlankInherit180:
    def test_push_front_inherits_rot180(self, tmp_path):
        """前一页 ROT180 → PUSH_FRONT 空白页同向 180°，尺寸一致。"""
        c = open_pdf(tmp_path, "sample_no_bookmark.pdf")
        try:
            c.set_rotation_override(0, RotationOverride.ROT180)
            c.set_page_mark(1, PageMark.FRONT, True)
            pf = _back(c, BlankPageSource.PUSH_FRONT)
            front = c.current_plan.pages[pf.physical_index - 2]  # 同纸正面
            assert front.rotation == 180
            assert pf.rotation == 180
            assert pf.output_size_mm == front.output_size_mm
        finally:
            c.close()

    def test_cover_back_inherits_rot180(self, tmp_path):
        """封面页 ROT180 → COVER_BACK 空白页同向 180°。"""
        c = open_pdf(tmp_path, "sample_no_bookmark.pdf")
        try:
            c.set_rotation_override(0, RotationOverride.ROT180)
            c.set_page_mark(0, PageMark.COVER, True)
            cb = _back(c, BlankPageSource.COVER_BACK)
            assert cb.rotation == 180
        finally:
            c.close()


class TestUiRotationCombo180:
    def test_combo_has_rot180_and_switch(self, make_window, samples_dir, qtbot):
        """下拉含 5 项（含"旋转 180°"），切换到 180° 后 override 生效。"""
        w = make_window()
        c = w.controller
        c.open_pdf(str(samples_dir / "sample_direction_markers.pdf"), "")
        rot_idx = next(p.original_index for p in c.source_pages
                       if c.needs_rotation(p.original_index))
        phys = next(pp.physical_index for pp in c.current_plan.pages
                    if not pp.is_blank and pp.source_page_info.original_index == rot_idx)
        c.select_physical(phys)
        panel = w.config_panel
        panel.load_page(phys)

        assert panel._rot_combo.count() == 5
        assert panel._rot_combo.itemText(3) == "旋转 180°"
        assert panel._rot_combo.itemText(4) == "不旋转"

        panel._rot_combo.setCurrentIndex(3)  # ROT180
        qtbot.wait(10)
        assert c.source_page(rot_idx).rotation_override is RotationOverride.ROT180
        pp = next(pp for pp in c.current_plan.pages
                  if not pp.is_blank and pp.source_page_info.original_index == rot_idx)
        assert pp.rotation == 180
