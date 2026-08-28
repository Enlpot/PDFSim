# -*- coding: utf-8 -*-
"""旋转修复（两步法）+ 重建性能优化（缓存）+ 书视图框选放大 专项测试。

对应提示语：AgentPrompt\旋转修复与性能优化与放大_提示语.md
覆盖：
  - detect_text_rotation 两步法：8 种场景（正面/右面/对面/左面 × must_rotate 有/无）
    + 无文字回退 + 加权主导；
  - plan_rotation 全页面调用：A3横向/A4纵向 180° 翻转修正、A3纵向/A4横向 90/270°；
  - rotation_cache：改配置重建不重算旋转检测；
  - _text_block_cache：同 (源页, 旋转) 命中缓存；
  - 书视图放大：模式切换、框选、Esc 退出、退出清空放大区域。
"""
from __future__ import annotations

import pytest

from pdfsim import engine
from pdfsim.engine import (
    build_process_plan,
    detect_text_rotation,
    plan_rotation,
)
from pdfsim.models import (
    A3_HEIGHT_MM,
    A3_WIDTH_MM,
    A4_HEIGHT_MM,
    A4_WIDTH_MM,
    DocumentConfig,
    PageInfo,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def text_data(*dirs):
    """构造 get_text("dict") 风格的 mock 数据（每个 dir 一条 20 字符 line）。"""
    blocks = []
    for d in dirs:
        blocks.append(
            {"type": 0, "lines": [{"dir": d, "spans": [{"text": "x" * 20}]}]}
        )
    return {"blocks": blocks}


def mk(idx, w, h, **kw):
    return PageInfo(original_index=idx, width_mm=w, height_mm=h, **kw)


def a4(idx, **kw):
    return mk(idx, A4_WIDTH_MM, A4_HEIGHT_MM, **kw)


def a4_landscape(idx, **kw):
    return mk(idx, A4_HEIGHT_MM, A4_WIDTH_MM, **kw)


def a3(idx, **kw):
    return mk(idx, A3_WIDTH_MM, A3_HEIGHT_MM, **kw)


def a3_landscape(idx, **kw):
    return mk(idx, A3_HEIGHT_MM, A3_WIDTH_MM, **kw)


def cfg(**kw):
    return DocumentConfig(**kw)


# ---------------------------------------------------------------------------
# 任务 1：旋转两步法
# ---------------------------------------------------------------------------
class TestDetectTextRotationTwoStep:
    """detect_text_rotation 两步法（must_rotate 参数）。

    must_rotate=True：正面/左面 → 90°；对面/右面 → 270°。
    must_rotate=False：正面/右面 → 0°；对面/左面 → 180°。
    """

    def test_must_rotate_front(self):
        assert detect_text_rotation(text_data((1.0, 0.0)), must_rotate=True) == 90

    def test_must_rotate_left(self):
        assert detect_text_rotation(text_data((0.0, 1.0)), must_rotate=True) == 90

    def test_must_rotate_opposite(self):
        assert detect_text_rotation(text_data((-1.0, 0.0)), must_rotate=True) == 270

    def test_must_rotate_right(self):
        assert detect_text_rotation(text_data((0.0, -1.0)), must_rotate=True) == 270

    def test_no_must_rotate_front(self):
        assert detect_text_rotation(text_data((1.0, 0.0)), must_rotate=False) == 0

    def test_no_must_rotate_right(self):
        assert detect_text_rotation(text_data((0.0, -1.0)), must_rotate=False) == 0

    def test_no_must_rotate_opposite(self):
        assert detect_text_rotation(text_data((-1.0, 0.0)), must_rotate=False) == 180

    def test_no_must_rotate_left(self):
        assert detect_text_rotation(text_data((0.0, 1.0)), must_rotate=False) == 180

    def test_no_text(self):
        # 无文字 → 基础旋转（must_rotate→90；否则→0）
        assert detect_text_rotation({"blocks": []}, must_rotate=True) == 90
        assert detect_text_rotation({"blocks": []}, must_rotate=False) == 0

    def test_default_must_rotate_false(self):
        # 默认参数向后兼容：must_rotate 缺省 = False
        assert detect_text_rotation(text_data((1.0, 0.0))) == 0
        assert detect_text_rotation(text_data((-1.0, 0.0))) == 180

    def test_weighted_dominant(self):
        # 加权主导：正面为主 + 少量左面 → must_rotate=True → 90°
        data = {
            "blocks": [
                {"type": 0, "lines": [{"dir": (1.0, 0.0), "spans": [{"text": "a" * 100}]}]},
                {"type": 0, "lines": [{"dir": (0.0, 1.0), "spans": [{"text": "b" * 5}]}]},
            ]
        }
        assert detect_text_rotation(data, must_rotate=True) == 90
        assert detect_text_rotation(data, must_rotate=False) == 0


class TestPlanRotationAllPages:
    """plan_rotation 对所有页面类型调用 detect_text_rotation。"""

    def test_a3_portrait_front_rot90(self):
        p = a3(0)
        r, size = plan_rotation(p, text_data((1.0, 0.0)))
        assert r == 90
        assert size == (A3_HEIGHT_MM, A3_WIDTH_MM)  # 90° 交换宽高

    def test_a3_portrait_left_rot90(self):
        p = a3(0)
        r, _ = plan_rotation(p, text_data((0.0, 1.0)))
        assert r == 90

    def test_a3_portrait_opposite_rot270(self):
        p = a3(0)
        r, size = plan_rotation(p, text_data((-1.0, 0.0)))
        assert r == 270
        assert size == (A3_HEIGHT_MM, A3_WIDTH_MM)

    def test_a3_portrait_right_rot270(self):
        p = a3(0)
        r, _ = plan_rotation(p, text_data((0.0, -1.0)))
        assert r == 270

    def test_a3_landscape_front_0(self):
        p = a3_landscape(0)
        r, size = plan_rotation(p, text_data((1.0, 0.0)))
        assert r == 0
        assert size == (A3_HEIGHT_MM, A3_WIDTH_MM)  # 横向页原尺寸，0° 不交换

    def test_a3_landscape_right_0(self):
        p = a3_landscape(0)
        r, _ = plan_rotation(p, text_data((0.0, -1.0)))
        assert r == 0

    def test_a3_landscape_opposite_180(self):
        # A3 横向 + 对面文字 → 180°（翻转修正），尺寸不变（仍为横向原尺寸）
        p = a3_landscape(0)
        r, size = plan_rotation(p, text_data((-1.0, 0.0)))
        assert r == 180
        assert size == (A3_HEIGHT_MM, A3_WIDTH_MM)

    def test_a3_landscape_left_180(self):
        p = a3_landscape(0)
        r, _ = plan_rotation(p, text_data((0.0, 1.0)))
        assert r == 180

    def test_a4_portrait_upside_down_180(self):
        # A4 纵向 + 对面文字 → 180°
        p = a4(0)
        r, _ = plan_rotation(p, text_data((-1.0, 0.0)))
        assert r == 180

    def test_a4_portrait_front_0(self):
        p = a4(0)
        r, _ = plan_rotation(p, text_data((1.0, 0.0)))
        assert r == 0

    def test_a4_landscape_front_90(self):
        p = a4_landscape(0)
        r, size = plan_rotation(p, text_data((1.0, 0.0)))
        assert r == 90
        assert size == (A4_WIDTH_MM, A4_HEIGHT_MM)  # 交换

    def test_a4_landscape_reversed_270(self):
        p = a4_landscape(0)
        r, _ = plan_rotation(p, text_data((-1.0, 0.0)))
        assert r == 270

    def test_no_text_defaults(self):
        # 无文字：需改方向 → 90；方向已对 → 0；None → 0
        assert plan_rotation(a3(0), {"blocks": []})[0] == 90
        assert plan_rotation(a3_landscape(0), {"blocks": []})[0] == 0
        assert plan_rotation(a4(0), None)[0] == 0
        assert plan_rotation(a3_landscape(0), None)[0] == 0

    def test_other_size_no_rotation(self):
        p = mk(0, 215.9, 279.4)
        r, size = plan_rotation(p, text_data((-1.0, 0.0)))
        assert r == 0
        assert size == (215.9, 279.4)

    def test_user_override_highest_priority(self):
        # 用户覆盖优先级最高（即使导致方向不对也尊重用户选择）
        from pdfsim.models import RotationOverride
        p = a3(0, rotation_override=RotationOverride.ROT180)
        plan_rotation(p, text_data((1.0, 0.0)))  # 自动检测 90
        from pdfsim.engine import final_rotation
        assert final_rotation(p) == 180


# ---------------------------------------------------------------------------
# 任务 2：重建性能优化（缓存）
# ---------------------------------------------------------------------------
class TestRotationCache:
    def test_rotation_cache_hit(self, monkeypatch):
        """第二次 build_process_plan 时旋转检测走缓存，plan_rotation 不被调用。"""
        src = [a4_landscape(0), a3(1), a4(2)]
        texts = {
            0: text_data((1.0, 0.0)),
            1: text_data((0.0, 1.0)),
            2: text_data((-1.0, 0.0)),
        }
        cache: dict[int, int] = {}
        calls = {"n": 0}
        orig = engine.plan_rotation

        def counting(*a, **k):
            calls["n"] += 1
            return orig(*a, **k)

        monkeypatch.setattr(engine, "plan_rotation", counting)
        plan1 = build_process_plan(src, cfg(), page_text_data=texts,
                                   rotation_cache=cache)
        n1 = calls["n"]
        assert n1 == 3  # 首次逐页检测
        assert len(cache) == 3  # 缓存填充
        plan2 = build_process_plan(src, cfg(), page_text_data=texts,
                                   rotation_cache=cache)
        assert calls["n"] == n1  # 第二次命中缓存，不重算
        # 两次规划旋转结果一致（ProcessedPage.rotation = planned_rotation）
        r1 = [p.rotation for p in plan1.pages]
        r2 = [p.rotation for p in plan2.pages]
        assert r1 == r2

    def test_rotation_cache_respects_override(self, monkeypatch):
        """缓存存 detected_rotation；用户覆盖仍在 final_rotation 生效。"""
        from pdfsim.models import RotationOverride
        src = [a4_landscape(0, rotation_override=RotationOverride.NONE)]
        texts = {0: text_data((1.0, 0.0))}
        cache: dict[int, int] = {}
        plan = build_process_plan(src, cfg(), page_text_data=texts,
                                  rotation_cache=cache)
        assert cache[0] == 90            # 检测结果 90
        assert plan.pages[0].rotation == 0  # 用户覆盖 NONE → 0

    def test_no_cache_param_fallback(self, monkeypatch):
        """不传 rotation_cache 时行为不变（每次重算）。"""
        src = [a4(0)]
        texts = {0: text_data((1.0, 0.0))}
        calls = {"n": 0}
        orig = engine.plan_rotation

        def counting(*a, **k):
            calls["n"] += 1
            return orig(*a, **k)

        monkeypatch.setattr(engine, "plan_rotation", counting)
        build_process_plan(src, cfg(), page_text_data=texts)
        build_process_plan(src, cfg(), page_text_data=texts)
        assert calls["n"] == 2  # 无缓存 → 每次都重算


class TestTextBlockCache:
    def test_text_block_cache_hit(self, open_sample):
        """同 (源页, 旋转角) 二次调用命中 _text_block_cache。"""
        w, c = open_sample("sample_with_pagenum.pdf")
        c._text_block_cache.clear()
        r1 = c._text_block_calculator(0, 0)
        assert (0, 0) in c._text_block_cache
        r2 = c._text_block_calculator(0, 0)
        assert r1 is r2                 # 命中缓存返回同一对象
        assert len(c._text_block_cache) == 1

    def test_text_block_cache_keyed_by_rotation(self, open_sample):
        """不同旋转角 → 不同缓存条目。"""
        w, c = open_sample("sample_with_pagenum.pdf")
        c._text_block_cache.clear()
        c._text_block_calculator(0, 0)
        c._text_block_calculator(0, 90)
        assert (0, 0) in c._text_block_cache
        assert (0, 90) in c._text_block_cache
        assert len(c._text_block_cache) == 2

    def test_open_new_pdf_clears_caches(self, open_sample, samples_dir):
        """打开新 PDF 时清空旋转/文本块缓存（清空后按新 PDF 重新填充）。

        缓存 key 使用源页索引——若打开新 PDF 未清空，旧 PDF 的 fake 索引
        （999 不存在于任何样本）会残留。
        """
        w, c = open_sample("sample_with_pagenum.pdf")
        c._rotation_cache[999] = 90
        c._text_block_cache[(999, 0)] = [(1, 2, 3, 4)]
        c.open_pdf(str(samples_dir / "sample_a4_portrait.pdf"), "")
        assert 999 not in c._rotation_cache
        assert (999, 0) not in c._text_block_cache


# ---------------------------------------------------------------------------
# 任务 3：书视图框选放大
# ---------------------------------------------------------------------------
class TestBookViewZoom:
    def test_zoom_mode_toggle(self, make_window):
        w = make_window()
        bv = w.book_view
        assert bv._zoom_mode is False
        w.tb_zoom.setChecked(True)
        assert bv._zoom_mode is True
        w.tb_zoom.setChecked(False)
        assert bv._zoom_mode is False
        assert bv.zoom_rect() is None  # 退出清空放大区域

    def test_zoom_button_syncs_with_view(self, make_window):
        """Esc 退出时按钮状态同步（信号双向连接不循环）。"""
        w = make_window()
        bv = w.book_view
        bv.set_zoom_mode(True)
        assert w.tb_zoom.isChecked() is True
        bv.set_zoom_mode(False)
        assert w.tb_zoom.isChecked() is False

    def test_zoom_rubber_band_zooms(self, make_window, qtbot):
        from PySide6.QtCore import QPoint, Qt
        w = make_window()
        bv = w.book_view
        bv.resize(600, 400)
        bv.set_zoom_mode(True)
        qtbot.mousePress(bv, Qt.MouseButton.LeftButton, pos=QPoint(50, 50))
        qtbot.mouseMove(bv, pos=QPoint(300, 250))
        qtbot.mouseRelease(bv, Qt.MouseButton.LeftButton, pos=QPoint(300, 250))
        rect = bv.zoom_rect()
        assert rect is not None
        assert rect.width() > 10 and rect.height() > 10
        # 放大渲染不崩溃
        bv.repaint()

    def test_zoom_too_small_ignored(self, make_window, qtbot):
        from PySide6.QtCore import QPoint, Qt
        w = make_window()
        bv = w.book_view
        bv.resize(600, 400)
        bv.set_zoom_mode(True)
        qtbot.mousePress(bv, Qt.MouseButton.LeftButton, pos=QPoint(50, 50))
        qtbot.mouseRelease(bv, Qt.MouseButton.LeftButton, pos=QPoint(56, 56))
        assert bv.zoom_rect() is None  # <10px 忽略

    def test_zoom_escape_exits(self, make_window, qtbot):
        from PySide6.QtCore import QPoint, Qt
        w = make_window()
        bv = w.book_view
        bv.resize(600, 400)
        bv.set_zoom_mode(True)
        qtbot.mousePress(bv, Qt.MouseButton.LeftButton, pos=QPoint(50, 50))
        qtbot.mouseMove(bv, pos=QPoint(300, 250))
        qtbot.mouseRelease(bv, Qt.MouseButton.LeftButton, pos=QPoint(300, 250))
        assert bv.zoom_rect() is not None
        qtbot.keyClick(bv, Qt.Key.Key_Escape)
        assert bv.zoom_rect() is None
        assert bv._zoom_mode is False
        assert w.tb_zoom.isChecked() is False

    def test_zoom_renders_with_pages(self, open_sample, qtbot):
        """有页面时框选放大渲染不崩溃（含角标/页码预览路径）。"""
        from PySide6.QtCore import QPoint, Qt
        w, c = open_sample("sample_with_pagenum.pdf")
        bv = w.book_view
        bv.resize(800, 600)
        bv.set_zoom_mode(True)
        qtbot.mousePress(bv, Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
        qtbot.mouseMove(bv, pos=QPoint(500, 400))
        qtbot.mouseRelease(bv, Qt.MouseButton.LeftButton, pos=QPoint(500, 400))
        assert bv.zoom_rect() is not None
        bv.repaint()  # 放大渲染（含 _paint_closed 页面 + 角标）不崩溃
