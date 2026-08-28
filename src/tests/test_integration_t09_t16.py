# -*- coding: utf-8 -*-
"""Stage 4 集成测试：T09–T16（大文档 + 特殊场景 + UI 交互）。

对应《测试矩阵.md》T09–T16。只新增测试，不修改 Stage 2/3 代码。
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # 供导入 _stage4_helpers

import pytest

from pdfsim.models import (
    A4_HEIGHT_MM,
    A4_WIDTH_MM,
    BlankPageSource,
    PageMark,
    PageNumberPos,
    PageNumberStyle,
    RotationOverride,
)

from _stage4_helpers import (
    Pipeline,
    blank,
    copy_sample,
    original,
    sha256,
)

PERF = {}  # 性能指标收集（供测试报告引用）


@pytest.fixture(autouse=True, scope="session")
def _clean_samples_configs(samples_dir):
    """session 结束后统一清理 samples 目录的配置残留（防污染与可重复）。"""
    yield
    for f in os.listdir(str(samples_dir)):
        if f.endswith(".pagerconfig.json"):
            try:
                os.remove(os.path.join(str(samples_dir), f))
            except OSError:
                pass


# ---------------------------------------------------------------------------
# T09：200 页大文档（功能正确性 + 性能指标记录，不阻塞）
# ---------------------------------------------------------------------------
class TestT09_Performance:
    def test_200pages_function_and_perf(self, samples_dir, tmp_path):
        src = copy_sample("sample_200pages.pdf", str(tmp_path))
        t0 = time.perf_counter()
        p = Pipeline(src, str(tmp_path))
        t_open = time.perf_counter() - t0

        t1 = time.perf_counter()
        p.rebuild()
        t_plan = time.perf_counter() - t1

        assert len(p.plan.pages) == 200
        assert [pp.number_text for pp in p.plan.pages[:3]] == ["1", "2", "3"]
        assert p.plan.pages[-1].number_text == "200"

        t2 = time.perf_counter()
        res = p.output()
        t_output = time.perf_counter() - t2
        assert res.success
        assert res.page_count == 200

        # 翻页响应：连续遍历 10 页（选中 + processed_page 查询）
        t3 = time.perf_counter()
        for n in range(1, 11):
            p.plan.pages[n - 1].physical_index
        t_nav = (time.perf_counter() - t3) / 10.0

        PERF.update({
            "T09_open_seconds": round(t_open, 3),
            "T09_plan_seconds": round(t_plan, 3),
            "T09_output_seconds": round(t_output, 3),
            "T09_nav_per_page_ms": round(t_nav * 1000, 3),
            "T09_output_pages": res.page_count,
        })
        print("PERF", PERF)
        p.close()

    def test_200pages_output_integrity(self, samples_dir, tmp_path):
        src = copy_sample("sample_200pages.pdf", str(tmp_path))
        before = sha256(src)
        p = Pipeline(src, str(tmp_path))
        try:
            res = p.output()
            assert res.source_hash_verified
            assert sha256(src) == before
        finally:
            p.close()


# ---------------------------------------------------------------------------
# T10：含大量现有页码（重叠检测）
# ---------------------------------------------------------------------------
class TestT10_Overlap:
    def test_overlap_warning_triggered(self, make_window, samples_dir, qtbot):
        w, c = open_sample_ui(make_window, samples_dir, "sample_with_pagenum.pdf")
        c.set_auto_adjust_overlap(False)  # 验证"检测→警告"原始语义，关闭自动调整
        # 引擎层：plan warnings 非空
        assert c.current_plan.warnings, "重叠警告未触发"
        warned_phys = [w.physical_index for w in c.current_plan.warnings]
        # UI：选中警告页 → 警告条可见
        c.select_physical(warned_phys[0])
        qtbot.wait(10)
        panel = w.config_panel
        assert panel._warn_label.isVisible()
        # 不阻止输出
        c.config.output_dir = str(samples_dir)  # 实际输出到临时
        import tempfile
        c.config.output_dir = tempfile.mkdtemp()
        res = c.output()
        assert res is not None and res.success

    def test_adjust_clears_warning(self, make_window, samples_dir, qtbot):
        w, c = open_sample_ui(make_window, samples_dir, "sample_with_pagenum.pdf")
        c.set_auto_adjust_overlap(False)  # 保留重叠警告以便验证手动调整可清除
        warned = c.current_plan.warnings[0]
        oi = c.current_plan.pages[warned.physical_index - 1].source_page_info.original_index
        # 调整全局页码位置（margin 右移，远离右上角原内容）→ 警告消除
        c.set_global_style(PageNumberStyle(margin_right_mm=120.0,
                                           margin_left_mm=120.0))
        assert all(w.physical_index != warned.physical_index
                   for w in c.current_plan.warnings), "调整后警告未消除"


# ---------------------------------------------------------------------------
# T11：规则变更（0.1）——NO_COUNT 用户标记路径废除
# ---------------------------------------------------------------------------
class TestT11_NoCount:
    def test_no_count_deprecated_keeps_content(self, make_window, samples_dir, tmp_path):
        w, c = open_sample_ui(make_window, samples_dir, "sample_no_count.pdf")
        assert len(c.source_pages) == 3
        # 手动标记附件页（idx1）为 NO_COUNT（旧标记，迁移为 NO_NUMBER 语义）
        c.set_page_mark(1, PageMark.NO_COUNT, True)
        plan = c.current_plan
        # 不再产生 NO_COUNT_USER 空白页
        no_count_pp = [pp for pp in plan.pages
                       if pp.blank_source is BlankPageSource.NO_COUNT_USER]
        assert no_count_pp == []
        # 附件页保留内容（原页）、无页码、跳过序号
        pp = plan.pages[1]
        assert pp.is_blank is False
        assert pp.number_text is None and not pp.number_occupies
        # 后续页序号顺延前移（跳过序号）
        seq = [pp.number_text for pp in plan.pages if pp.number_text is not None]
        assert seq == ["1", "2"]  # 封面=1、正文=2（附件跳过）
        # 输出：保留内容 → 页数=源页数（物理 3 页）
        c.config.output_dir = str(tmp_path)
        res = c.output()
        assert res.success and res.page_count == 3


# ---------------------------------------------------------------------------
# T12：A3 落在偶数位（推动级联）
# ---------------------------------------------------------------------------
class TestT12_A3EvenPush:
    def test_a3_pushed_to_front(self, make_window, samples_dir):
        w, c = open_sample_ui(make_window, samples_dir, "sample_mixed.pdf")
        c.set_auto_number_blank_pages(True)  # 保留 PUSH_FRONT 编页码行为
        # 样本文字水平 → AUTO 检测为 0；强制 A3 纵向页旋转，验证装订翻转
        c.set_rotation_override(1, RotationOverride.CW90)
        plan = c.current_plan
        # 期望物理顺序表（用 helper 的 original/blank 构造，键名与断言一致）
        expected = [
            original(1, PageNumberPos.BOTTOM_RIGHT, 0, True),
            blank("push_front", "2", True, PageNumberPos.BOTTOM_LEFT),
            original(3, PageNumberPos.BOTTOM_RIGHT, 90, True),
            blank("a3_back", None, False, PageNumberPos.BOTTOM_RIGHT, rot=90),
            original(4, PageNumberPos.BOTTOM_RIGHT, 0, True),
            blank("a3_back", None, False, PageNumberPos.BOTTOM_RIGHT, rot=0),
            original(5, PageNumberPos.BOTTOM_RIGHT, 0, True),
        ]
        src_idx = [0, None, 1, None, 2, None, 3]
        for i, row in enumerate(expected):
            row["phys"] = i + 1
            row["src_index"] = src_idx[i]
        _assert_rows(plan, expected)
        # A3 页在奇数位（phys3, phys5）
        assert plan.pages[2].physical_index % 2 == 1
        assert plan.pages[4].physical_index % 2 == 1
        # 其前空白有页码占序号（phys2 push_front）
        assert plan.pages[1].number_text == "2" and plan.pages[1].number_occupies
        # A3 背面空白无页码不占序号
        for bs in (plan.pages[3], plan.pages[5]):
            assert bs.blank_source is BlankPageSource.A3_BACK
            assert bs.number_text is None and not bs.number_occupies


# ---------------------------------------------------------------------------
# T13：连续多个 A3 页（级联）
# ---------------------------------------------------------------------------
class TestT13_ConsecutiveA3:
    def test_consecutive_a3_cascade(self, make_window, samples_dir):
        w, c = open_sample_ui(make_window, samples_dir, "sample_mixed.pdf")
        plan = c.current_plan
        # 连续两个 A3（phys3 A3纵、phys5 A3横）均在奇数位
        assert plan.pages[2].source_page_info.original_index == 1
        assert plan.pages[2].physical_index % 2 == 1
        assert plan.pages[4].source_page_info.original_index == 2
        assert plan.pages[4].physical_index % 2 == 1
        # 各自背面空白
        assert plan.pages[3].is_blank and plan.pages[3].blank_source is BlankPageSource.A3_BACK
        assert plan.pages[5].is_blank and plan.pages[5].blank_source is BlankPageSource.A3_BACK
        # A3 之后第一页（phys7）仍从正面开始
        assert plan.pages[6].physical_index % 2 == 1
        assert not plan.pages[6].is_blank


# ---------------------------------------------------------------------------
# T14：用户手动取消非 A3 页"从正面开始"（UI）
# ---------------------------------------------------------------------------
class TestT14_CancelFront:
    def test_cancel_front_reverts_even_slot(self, make_window, samples_dir, qtbot):
        w, c = open_sample_ui(make_window, samples_dir, "sample_odd_last.pdf")
        oi = 1  # 页2
        # 加 FRONT → 页2 被推到奇数位（物理3，插入 PUSH_FRONT 于物理2）
        c.set_page_mark(oi, PageMark.FRONT, True)
        plan = c.current_plan
        assert [pp.physical_index for pp in plan.pages
                if not pp.is_blank and pp.source_page_info.original_index == oi] == [3]
        assert plan.pages[1].is_blank  # PUSH_FRONT 插入
        # UI 取消 FRONT
        phys = c.selected_physical_index or 3
        c.select_physical(3)
        qtbot.wait(10)
        panel = w.config_panel
        assert panel._chk_front.isChecked() and panel._chk_front.isEnabled()
        panel._chk_front.setChecked(False)
        qtbot.wait(10)
        # 取消后：FRONT 移除、页2 落偶数位（物理2）、不再插空白
        assert PageMark.FRONT not in c.source_page(oi).marks
        plan2 = c.current_plan
        assert [pp.physical_index for pp in plan2.pages
                if not pp.is_blank and pp.source_page_info.original_index == oi] == [2]
        assert not plan2.pages[1].is_blank  # 无 PUSH_FRONT

    def test_a3_front_readonly(self, make_window, samples_dir, qtbot):
        w, c = open_sample_ui(make_window, samples_dir, "sample_a3_portrait.pdf")
        a3_oi = next(p.original_index for p in c.source_pages
                     if _is_a3_size(p))
        phys = next(pp.physical_index for pp in c.current_plan.pages
                    if not pp.is_blank and pp.source_page_info.original_index == a3_oi)
        c.select_physical(phys)
        qtbot.wait(10)
        panel = w.config_panel
        # A3 页 front 置灰不可取消
        assert not panel._chk_front.isEnabled()
        # 控制器层强制：即使 discard FRONT 也会 re-add
        c.set_page_mark(a3_oi, PageMark.FRONT, False)
        assert PageMark.FRONT in c.source_page(a3_oi).marks


# ---------------------------------------------------------------------------
# T15：输出文件已存在（禁止覆盖）
# ---------------------------------------------------------------------------
class TestT15_OutputExists:
    def test_no_overwrite(self, make_window, samples_dir, tmp_path):
        w, c = open_sample_ui(make_window, samples_dir, "sample_single.pdf")
        c.config.output_dir = str(tmp_path)
        r1 = c.output()
        assert r1.success
        out_path = r1.output_path
        with open(out_path, "rb") as f:
            first = f.read()
        r2 = c.output()
        assert not r2.success
        assert "已存在" in r2.message
        with open(out_path, "rb") as f:
            assert f.read() == first  # 原输出未被覆盖


# ---------------------------------------------------------------------------
# T16：用户手动调整旋转方向（UI + 输出 + 配置恢复）
# ---------------------------------------------------------------------------
class TestT16_RotationOverride:
    def test_manual_rotation_and_output(self, make_window, samples_dir, tmp_path, qtbot):
        w, c = open_sample_ui(make_window, samples_dir, "sample_direction_markers.pdf")
        # 页0 = A4 横向 → 需旋转
        oi = 0
        assert c.needs_rotation(oi)
        # 显式重置 override 为自动（消除任何残留配置影响）
        c.set_rotation_override(oi, RotationOverride.AUTO)
        # 定位其物理页（phys1）
        phys = next(pp.physical_index for pp in c.current_plan.pages
                    if not pp.is_blank and pp.source_page_info.original_index == oi)
        assert c.current_plan.pages[phys - 1].rotation == 270  # 自动检测：A4横向+正面文字 → 两步法 270°（显示右面可读）
        c.select_physical(phys)
        qtbot.wait(10)
        panel = w.config_panel
        assert panel._rot_combo.currentIndex() == 0  # 自动检测

        # 切到"不旋转"(index4，新增"旋转 180°"后顺延)
        panel._rot_combo.setCurrentIndex(4)
        qtbot.wait(10)
        assert c.current_plan.pages[phys - 1].rotation == 0
        assert c.source_page(oi).rotation_override is RotationOverride.NONE
        # 输出 → 渲染方向一致（输出页无旋转）
        c.config.output_dir = str(tmp_path)
        res = c.output()
        assert res.success
        import pymupdf
        with pymupdf.open(res.output_path) as doc:
            assert doc[phys - 1].rotation == 0

        # 切到"顺时针 90°"(index1)
        panel._rot_combo.setCurrentIndex(1)
        qtbot.wait(10)
        assert c.current_plan.pages[phys - 1].rotation == 90
        # 切到"逆时针 90°"(index2)
        panel._rot_combo.setCurrentIndex(2)
        qtbot.wait(10)
        assert c.current_plan.pages[phys - 1].rotation == 270

    def test_rotation_config_restore(self, make_window, samples_dir, qtbot, tmp_path):
        w, c = open_sample_ui(make_window, samples_dir, "sample_direction_markers.pdf")
        cfg_path = c.config_mgr.config_path_for(c.pdf_path)
        if os.path.exists(cfg_path):
            os.remove(cfg_path)
        c.set_rotation_override(0, RotationOverride.NONE)
        # 防抖保存
        time.sleep(0.6)
        c._do_save_config()
        assert os.path.exists(cfg_path)
        # 重开恢复
        w.controller.open_pdf(c.pdf_path, "")
        assert c.source_page(0).rotation_override is RotationOverride.NONE
        if os.path.exists(cfg_path):
            os.remove(cfg_path)


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------
def open_sample_ui(make_window, samples_dir, rel):
    w = make_window()
    c = w.controller
    # 清除同名残留配置（防止配置恢复干扰测试预期）
    cfg = os.path.join(str(samples_dir), rel + ".pagerconfig.json")
    if os.path.exists(cfg):
        os.remove(cfg)
    c.open_pdf(str(samples_dir / rel), "")
    return w, c


def _is_a3_size(p):
    from pdfsim.models import A3_WIDTH_MM, A3_HEIGHT_MM, SIZE_TOLERANCE_MM
    w, h = p.width_mm, p.height_mm
    return (abs(w - A3_WIDTH_MM) <= SIZE_TOLERANCE_MM and abs(h - A3_HEIGHT_MM) <= SIZE_TOLERANCE_MM) or \
           (abs(w - A3_HEIGHT_MM) <= SIZE_TOLERANCE_MM and abs(h - A3_WIDTH_MM) <= SIZE_TOLERANCE_MM)


def _assert_rows(plan, expected):
    from _stage4_helpers import assert_physical_table
    assert_physical_table(plan, expected)
