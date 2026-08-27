# -*- coding: utf-8 -*-
"""《空白页开关_双列_滚动平滑_提示语》三项功能专项测试。

功能 1 空白页编页码开关：auto_number_blank_pages（默认关）
功能 2 缩略图双列（宽度自适应）
功能 3 鼠标滚动平滑
"""
import json
import os

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent

from pdfsim.engine import plan_page_numbers, plan_physical_order
from pdfsim.models import (
    A3_HEIGHT_MM,
    A3_WIDTH_MM,
    A4_HEIGHT_MM,
    A4_WIDTH_MM,
    BlankPageSource,
    DocumentConfig,
    PageInfo,
    PageMark,
)


# ---------------------------------------------------------------------------
# helpers（与 test_engine.py 一致）
# ---------------------------------------------------------------------------
def mk(idx, w, h, marks=None, **kw):
    return PageInfo(original_index=idx, width_mm=w, height_mm=h,
                    marks=set(marks or []), **kw)


def a4(idx, **kw):
    return mk(idx, A4_WIDTH_MM, A4_HEIGHT_MM, **kw)


def a3(idx, **kw):
    return mk(idx, A3_WIDTH_MM, A3_HEIGHT_MM, **kw)


def cfg(**kw):
    return DocumentConfig(**kw)


# ===========================================================================
# 功能 1：空白页编页码开关
# ===========================================================================
class TestBlankNumberSwitch:
    def test_off_push_front_no_number(self):
        """开关关 + PUSH_FRONT → 不显示页码、不占序号、后续顺延。"""
        plan = plan_physical_order([a4(0), a3(1)], cfg())  # [A4, push, A3, a3_back]
        proc = plan_page_numbers(plan, 1, auto_number_blank_pages=False)
        assert proc[1].blank_source is BlankPageSource.PUSH_FRONT
        assert proc[1].number_text is None
        assert proc[1].number_occupies is False
        # 后续顺延：A3 原页序号为 2（未因 PUSH_FRONT 占号）
        assert proc[2].is_blank is False and proc[2].number_text == "2"

    def test_on_push_front_number(self):
        """开关开 + PUSH_FRONT → 显示页码、占序号。"""
        plan = plan_physical_order([a4(0), a3(1)], cfg())
        proc = plan_page_numbers(plan, 1, auto_number_blank_pages=True)
        assert proc[1].blank_source is BlankPageSource.PUSH_FRONT
        assert proc[1].number_text == "2"
        assert proc[1].number_occupies is True
        assert proc[2].number_text == "3"

    def test_off_fill_last_no_number(self):
        """开关关 + FILL_LAST → 不显示、不占序号。"""
        plan = plan_physical_order([a4(0)], cfg(auto_fill_last_page=True))
        assert plan[-1].blank_source is BlankPageSource.FILL_LAST
        proc = plan_page_numbers(plan, 1, auto_number_blank_pages=False)
        assert proc[-1].number_text is None
        assert proc[-1].number_occupies is False

    def test_on_fill_last_number(self):
        """开关开 + FILL_LAST → 显示、占序号。"""
        plan = plan_physical_order([a4(0)], cfg(auto_fill_last_page=True))
        proc = plan_page_numbers(plan, 1, auto_number_blank_pages=True)
        assert proc[-1].number_text == "2"
        assert proc[-1].number_occupies is True

    def test_off_cover_back_unchanged(self):
        """开关关 + COVER_BACK → 仍显示、占序号（不变）。"""
        plan = plan_physical_order([a4(0, marks=[PageMark.COVER])], cfg())
        assert plan[1].blank_source is BlankPageSource.COVER_BACK
        proc = plan_page_numbers(plan, 1, auto_number_blank_pages=False)
        assert proc[1].number_text == "2"
        assert proc[1].number_occupies is True

    def test_off_sign_a3_back_unchanged(self):
        """开关关 + SIGN_BACK / A3_BACK → 仍不显示、不占序号（不变）。"""
        plan = plan_physical_order(
            [a4(0, marks=[PageMark.SIGNATURE]), a3(1)], cfg())
        proc = plan_page_numbers(plan, 1, auto_number_blank_pages=False)
        sign_back = next(p for p in proc if p.blank_source is BlankPageSource.SIGN_BACK)
        a3_back = next(p for p in proc if p.blank_source is BlankPageSource.A3_BACK)
        assert sign_back.number_text is None and sign_back.number_occupies is False
        assert a3_back.number_text is None and a3_back.number_occupies is False

    def test_user_no_number_overrides_switch(self):
        """用户显式 NO_NUMBER 覆盖开关（开开关仍不编页码）。"""
        plan = plan_physical_order([a4(0), a3(1)], cfg())
        plan[1].marks.add(PageMark.NO_NUMBER)  # PUSH_FRONT 用户显式不加页码
        proc = plan_page_numbers(plan, 1, auto_number_blank_pages=True)
        assert proc[1].blank_source is BlankPageSource.PUSH_FRONT
        assert proc[1].number_text is None
        assert proc[1].number_occupies is False
        # 覆盖后后续顺延
        assert proc[2].number_text == "2"

    def test_default_is_off(self):
        """默认（未传参数）开关关 → PUSH_FRONT 不编页码（向后兼容）。"""
        plan = plan_physical_order([a4(0), a3(1)], cfg())
        proc = plan_page_numbers(plan, 1)
        assert proc[1].number_text is None


class TestBlankNumberSwitchConfig:
    def test_save_load_roundtrip(self, tmp_path):
        """配置保存/加载新字段。"""
        from pdfsim.config import ConfigManager

        pdf = tmp_path / "t.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")
        cfg_ = DocumentConfig()
        cfg_.auto_number_blank_pages = True
        mgr = ConfigManager()
        mgr.save_config(str(pdf), cfg_)
        loaded = mgr.load_config(str(pdf))
        assert loaded.auto_number_blank_pages is True

    def test_old_config_default_false(self, tmp_path):
        """旧配置无该字段 → 默认 False（向后兼容，不升级版本）。"""
        from pdfsim.config import ConfigManager

        pdf = tmp_path / "t.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")
        mgr = ConfigManager()
        path = mgr.config_path_for(str(pdf))
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"version": 2, "source_file": str(pdf).replace("\\", "/"),
                       "global": {"start_page_number": 3}}, f)
        loaded = mgr.load_config(str(pdf))
        assert loaded.auto_number_blank_pages is False
        assert loaded.start_page_number == 3

    def test_controller_setter(self, open_sample):
        """controller.set_auto_number_blank_pages 更新配置并重建。"""
        w, c = open_sample("sample_no_bookmark.pdf")
        assert c.config.auto_number_blank_pages is False
        c.set_auto_number_blank_pages(True)
        assert c.config.auto_number_blank_pages is True
        c.set_auto_number_blank_pages(False)
        assert c.config.auto_number_blank_pages is False

    def test_global_settings_dialog_has_switch(self, make_window):
        """全局设置对话框含"其他空白页自动编页码"复选框。"""
        from pdfsim.ui.global_settings import GlobalSettingsDialog

        w = make_window()
        dlg = GlobalSettingsDialog(w.controller)
        assert dlg._blank_num_check is not None
        assert dlg._blank_num_check.isChecked() is False  # 默认关
        dlg._blank_num_check.setChecked(True)
        dlg.accept()
        assert w.controller.config.auto_number_blank_pages is True


# ===========================================================================
# 功能 2：缩略图双列（宽度自适应）
# ===========================================================================
class TestThumbnailTwoColumn:
    def _open(self, open_sample):
        return open_sample("sample_200pages.pdf")

    def test_two_columns_when_wide(self, open_sample):
        """面板拖宽 → 自动双列（第二项 x 大于第一项 x）。"""
        w, _ = open_sample("sample_200pages.pdf")
        panel = w.thumbnail_panel
        panel.setFixedWidth(300)  # 2×132=264 ≤ 300 → 双列
        panel.rebuild()
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        r1 = panel.visualItemRect(panel._items[1])
        r2 = panel.visualItemRect(panel._items[2])
        assert r2.x() > r1.x(), f"双列下第2项应在第二列: r1.x={r1.x()} r2.x={r2.x()}"
        # 列间距 = grid 宽（132）
        assert abs((r2.x() - r1.x()) - 132) <= 4

    def test_single_column_when_narrow(self, open_sample):
        """面板拖窄 → 自动回退单列（第二项在下方同 x）。"""
        w, _ = open_sample("sample_200pages.pdf")
        panel = w.thumbnail_panel
        panel.setFixedWidth(180)  # 单列
        panel.rebuild()
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        r1 = panel.visualItemRect(panel._items[1])
        r2 = panel.visualItemRect(panel._items[2])
        assert r2.x() == r1.x()
        assert r2.y() > r1.y()

    def test_two_column_multi_select(self, open_sample):
        """双列下多选正常（ExtendedSelection + 批量集合）。"""
        w, c = open_sample("sample_200pages.pdf")
        panel = w.thumbnail_panel
        panel.setFixedWidth(300)
        panel.rebuild()
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        c.set_selected_pages([1, 2, 3])
        panel.on_plan_changed()
        assert c.selected_physical_pages() == [1, 2, 3]
        assert panel._items[1].isSelected()
        assert panel._items[3].isSelected()

    def test_two_column_scroll_to_item(self, open_sample):
        """双列下 scrollToItem 定位准确（不抛异常且目标可见）。"""
        w, _ = open_sample("sample_200pages.pdf")
        panel = w.thumbnail_panel
        panel.setFixedWidth(300)
        panel.rebuild()
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        target = 150
        panel._ensure_visible(target)
        rect = panel.visualItemRect(panel._items[target])
        vp = panel.viewport()
        assert not (rect.bottom() < 0 or rect.top() > vp.height())


# ===========================================================================
# 功能 3：鼠标滚动平滑
# ===========================================================================
class TestScrollSmooth:
    def test_single_step_small(self, open_sample):
        """滚动条 singleStep 为小步长（20）。"""
        w, _ = open_sample("sample_200pages.pdf")
        assert w.thumbnail_panel.verticalScrollBar().singleStep() == 20

    def test_wheel_event_smooth(self, open_sample):
        """滚轮一格滚动固定小步长（~24px），不再一滚好几行。"""
        w, _ = open_sample("sample_200pages.pdf")
        panel = w.thumbnail_panel
        panel.setFixedWidth(180)
        panel.rebuild()
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        bar = panel.verticalScrollBar()
        bar.setValue(0)
        ev = QWheelEvent(
            QPointF(50, 50), QPointF(50, 50), QPoint(0, 0), QPoint(0, -120),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase, False,
        )
        panel.wheelEvent(ev)
        assert bar.value() == 24, f"一格应滚动 24px，实际 {bar.value()}"

    def test_wheel_event_small_delta(self, open_sample):
        """触控板小步幅（<120）也能滚动（像素级）。"""
        w, _ = open_sample("sample_200pages.pdf")
        panel = w.thumbnail_panel
        panel.setFixedWidth(180)
        panel.rebuild()
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        bar = panel.verticalScrollBar()
        bar.setValue(0)
        ev = QWheelEvent(
            QPointF(50, 50), QPointF(50, 50), QPoint(0, 0), QPoint(0, -24),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase, False,
        )
        panel.wheelEvent(ev)
        assert bar.value() >= 4  # 24*24//120 = 4（按比例滚动，不吞事件）
