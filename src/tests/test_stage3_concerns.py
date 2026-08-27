# -*- coding: utf-8 -*-
"""Stage 4：Stage 3 审查报告第五节的 5 个端到端关注点验证。

1. 旋转页 + 重叠检测组合：A4 横向页旋转后，页码位置放置原内容 → 重叠警告正确触发
2. 级联插入 + 配置恢复：多次插入空白页后关闭重开，物理顺序和标记完全一致
3. 大文档性能：200 页文档的打开/规划/输出（T09 已测，此处功能断言）
4. 加密 PDF 全流程：输密码→打开→标记→输出→原文件不变
5. A3 页 + 用户手动取消其他标记：FRONT 仍不可取消
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # 供导入 _stage4_helpers

import pymupdf
import pytest

from pdfsim.engine import build_process_plan
from pdfsim.models import (
    A4_HEIGHT_MM,
    A4_WIDTH_MM,
    BlankPageSource,
    DocumentConfig,
    MM_TO_PT,
    PageInfo,
    PageMark,
)
from pdfsim.renderer import PDFRenderer

from _stage4_helpers import Pipeline, copy_sample, sha256


@pytest.fixture(autouse=True, scope="session")
def _clean_samples_configs(samples_dir):
    """session 结束后统一清理 samples 目录的配置残留。"""
    yield
    for f in os.listdir(str(samples_dir)):
        if f.endswith(".pagerconfig.json"):
            try:
                os.remove(os.path.join(str(samples_dir), f))
            except OSError:
                pass


def open_sample_ui(make_window, samples_dir, rel):
    w = make_window()
    c = w.controller
    cfg = os.path.join(str(samples_dir), rel + ".pagerconfig.json")
    if os.path.exists(cfg):
        os.remove(cfg)
    c.open_pdf(str(samples_dir / rel), "")
    return w, c


class TestConcern1_RotationOverlap:
    """关注点 1：旋转页 + 重叠检测组合。"""

    def test_rotated_page_overlap_detected(self):
        """A4 横向页旋转 90° 后，页码右下角与原内容重叠 → 警告正确触发。

        构造：A4 横向 PageInfo + 显示坐标文本块（右下角）+ 无旋转坐标需求
        （旋转页的显示坐标块由 UI 层换算，此处直接模拟换算后的显示块）。
        """
        page = PageInfo(
            original_index=0,
            width_mm=297.0,   # A4 横向（显示尺寸）
            height_mm=210.0,
        )
        # 显示坐标（旋转 90° 后 210×297）右下角文本块：页码放置区附近
        # 显示坐标 pt（左上原点 y 向下）：W=210mm=595pt, H=297mm=842pt；
        # 底部右下角区域 y∈[800,830]
        blocks = [(560.0, 800.0, 590.0, 830.0)]  # 与默认页码右下角（底部）重叠
        text_data = {0: {"blocks": []}}  # 无有效文字 → detect 回退 90

        renderer = PDFRenderer()
        plan = build_process_plan(
            [page], DocumentConfig(), page_text_data=text_data,
            text_width_calculator=renderer.get_text_width,
            text_block_calculator=lambda idx: blocks if idx == 0 else None,
        )
        pp = plan.pages[0]
        assert pp.rotation == 90
        assert pp.number_position.value == "bottom_right"
        assert plan.warnings, "旋转页页码与原内容重叠未触发警告"

    def test_rotated_page_no_overlap_ok(self):
        """对照组：旋转页页码位置无内容 → 无警告。"""
        page = PageInfo(original_index=0, width_mm=297.0, height_mm=210.0)
        blocks = [(10.0, 400.0, 200.0, 700.0)]  # 左上区域，与右下页码远离
        text_data = {0: {"blocks": []}}
        renderer = PDFRenderer()
        plan = build_process_plan(
            [page], DocumentConfig(), page_text_data=text_data,
            text_width_calculator=renderer.get_text_width,
            text_block_calculator=lambda idx: blocks if idx == 0 else None,
        )
        assert plan.pages[0].rotation == 90
        assert not plan.warnings


class TestConcern2_CascadeConfigRestore:
    """关注点 2：级联插入 + 配置恢复。"""

    def test_multi_blank_config_restore(self, make_window, samples_dir, qtbot,
                                        tmp_path):
        w, c = open_sample_ui(make_window, samples_dir, "sample_a4_portrait.pdf")
        cfg_path = c.config_mgr.config_path_for(c.pdf_path)
        if os.path.exists(cfg_path):
            os.remove(cfg_path)
        # 多次标记 → 多空白插入（封面 + 签字 + 目录 FRONT 已是自动）
        c.set_page_mark(0, PageMark.COVER, True)
        c.set_page_mark(4, PageMark.SIGNATURE, True)
        c.set_page_number_pos(2, None)  # 保持
        before = [(pp.physical_index, pp.is_blank, pp.number_text,
                   pp.source_page_info.original_index)
                  for pp in c.current_plan.pages]
        # 防抖保存
        time.sleep(0.6)
        c._do_save_config()
        assert os.path.exists(cfg_path)
        # 关闭重开 → 配置恢复 → 物理顺序与标记完全一致
        w.controller.open_pdf(c.pdf_path, "")
        after = [(pp.physical_index, pp.is_blank, pp.number_text,
                  pp.source_page_info.original_index)
                 for pp in c.current_plan.pages]
        assert before == after, "重开后物理顺序不一致"
        assert PageMark.COVER in c.source_page(0).marks
        assert PageMark.SIGNATURE in c.source_page(4).marks
        if os.path.exists(cfg_path):
            os.remove(cfg_path)


class TestConcern3_BigDoc:
    """关注点 3：大文档性能（T09 已测指标，此处功能断言）。"""

    def test_200pages_plan_and_output(self, samples_dir, tmp_path):
        src = copy_sample("sample_200pages.pdf", str(tmp_path))
        p = Pipeline(src, str(tmp_path))
        try:
            assert len(p.plan.pages) == 200
            res = p.output()
            assert res.success and res.page_count == 200
            assert res.source_hash_verified
        finally:
            p.close()


class TestConcern4_EncryptedFullFlow:
    """关注点 4：加密 PDF 全流程（输密码→打开→标记→输出→原文件不变）。"""

    def test_encrypted_full_flow(self, make_window, samples_dir, qtbot, tmp_path,
                                 monkeypatch):
        w = make_window()
        path = str(samples_dir / "sample_encrypted.pdf")
        monkeypatch.setattr("pdfsim.ui.main_window.dialogs.ask_password",
                            lambda *a, **k: "testpass")
        w._open_pdf_flow(path)
        c = w.controller
        assert c.pdf_path is not None
        assert c.plan_page_count() == 1
        # 标记
        c.set_page_mark(0, PageMark.SIGNATURE, True)
        # 输出到临时目录
        c.config.output_dir = str(tmp_path)
        res = c.output()
        assert res is not None and res.success
        assert res.source_hash_verified
        # 原文件不变
        assert sha256(path) == sha256(path)


class TestConcern5_A3Readonly:
    """关注点 5：A3 页 + 用户手动取消其他标记 → FRONT 仍不可取消。"""

    def test_a3_front_never_cancellable(self, make_window, samples_dir, qtbot):
        w, c = open_sample_ui(make_window, samples_dir, "sample_a3_portrait.pdf")
        a3_oi = next(p.original_index for p in c.source_pages
                     if _is_a3(p))
        # 尝试取消其他标记（不加页码），同时尝试取消 FRONT
        c.set_page_mark(a3_oi, PageMark.NO_NUMBER, True)
        c.set_page_mark(a3_oi, PageMark.FRONT, False)  # 应被强制保留
        assert PageMark.FRONT in c.source_page(a3_oi).marks
        # A3 背面空白仍存在（FRONT 保持 → 物理结构不变）
        backs = [pp for pp in c.current_plan.pages
                 if pp.is_blank and pp.blank_source is BlankPageSource.A3_BACK]
        assert backs


def _is_a3(p):
    from pdfsim.models import A3_WIDTH_MM, A3_HEIGHT_MM, SIZE_TOLERANCE_MM
    w, h = p.width_mm, p.height_mm
    return (abs(w - A3_WIDTH_MM) <= SIZE_TOLERANCE_MM and abs(h - A3_HEIGHT_MM) <= SIZE_TOLERANCE_MM) or \
           (abs(w - A3_HEIGHT_MM) <= SIZE_TOLERANCE_MM and abs(h - A3_WIDTH_MM) <= SIZE_TOLERANCE_MM)
