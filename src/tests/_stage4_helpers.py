# -*- coding: utf-8 -*-
"""Stage 4 集成测试共享辅助（下划线前缀，pytest 不收集）。

仅被 Stage 4 新增测试文件 import；不修改任何 Stage 2/3 文件。
"""
from __future__ import annotations

import hashlib
import os

import pymupdf

from pdfsim.engine import build_process_plan
from pdfsim.loader import PDFLoader
from pdfsim.models import (
    A3_HEIGHT_MM,
    A3_WIDTH_MM,
    A4_HEIGHT_MM,
    A4_WIDTH_MM,
    BlankPageSource,
    DocumentConfig,
    PageNumberPos,
    ProcessPlan,
)
from pdfsim.output import PDFOutput
from pdfsim.renderer import PDFRenderer

SAMPLES_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "samples")


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def copy_sample(src_name: str, dst: str) -> str:
    """把样本复制到临时目录（保证输出不污染 samples 目录）。"""
    import shutil
    src = os.path.join(SAMPLES_DIR, src_name)
    out = os.path.join(dst, src_name)
    shutil.copyfile(src, out)
    return out


class Pipeline:
    """端到端流水线（真实文本检测 + 真实字体宽度 + 重叠检测回调）。"""

    def __init__(self, src_path: str, out_dir: str, password: str = "", **cfg_kw):
        self.src = src_path
        self.loader = PDFLoader()
        cfg_kw.setdefault("output_dir", str(out_dir))
        self.config = DocumentConfig(**cfg_kw)
        self.result = self.loader.open(self.src, password)
        self.text_data = {
            i: self.loader.extract_text_data(i)
            for i in range(len(self.result.pages))
        }
        self.renderer = PDFRenderer()
        self.plan = build_process_plan(
            self.result.pages,
            self.config,
            page_text_data=self.text_data,
            text_width_calculator=self.renderer.get_text_width,
            text_block_calculator=self.text_block_calculator,
        )

    def text_block_calculator(self, idx):
        """文本块显示坐标（A4/A3 不旋转样本 content==display；旋转页由 UI 层换算，
        此处用于无旋转场景的直接 bbox）。"""
        if idx is None:
            return None
        blocks = self.text_data.get(idx, {}).get("blocks", [])
        return [
            (b["bbox"][0], b["bbox"][1], b["bbox"][2], b["bbox"][3])
            for b in blocks if b.get("type") == 0
        ]

    def rebuild(self, **cfg_kw):
        """按新配置重建 plan（标记已在 pages 上就地修改）。"""
        for k, v in cfg_kw.items():
            setattr(self.config, k, v)
        self.plan = build_process_plan(
            self.result.pages,
            self.config,
            page_text_data=self.text_data,
            text_width_calculator=self.renderer.get_text_width,
            text_block_calculator=self.text_block_calculator,
        )
        return self.plan

    def output(self) -> PDFOutput:
        return PDFOutput().output(self.src, self.plan, self.config)

    def close(self):
        self.loader.close()


# ---------------------------------------------------------------------------
# 物理顺序专项：期望表断言
# ---------------------------------------------------------------------------
def assert_physical_table(plan: ProcessPlan, expected: list[dict]):
    """逐项断言最终物理顺序表。

    expected: [{phys, blank, blank_source, number_text, number_occupies,
                number_position, rotation, src_index}, ...]
    """
    assert len(plan.pages) == len(expected), (
        f"物理页数 {len(plan.pages)} != 期望 {len(expected)}")
    for row, pp in zip(expected, plan.pages):
        assert pp.physical_index == row["phys"]
        assert pp.is_blank == row["blank"]
        bs = pp.blank_source.value if pp.blank_source else None
        assert bs == row.get("blank_source"), (
            f"phys{pp.physical_index} 空白来源 {bs} != {row.get('blank_source')}")
        assert pp.number_text == row.get("number_text")
        assert pp.number_occupies == row.get("number_occupies")
        assert pp.number_position == row.get("number_position")
        assert pp.rotation == row.get("rotation", 0)
        src = pp.source_page_info.original_index
        assert src == row.get("src_index"), (
            f"phys{pp.physical_index} 源页 {src} != {row.get('src_index')}")
        # 尺寸校验
        if "size_mm" in row:
            assert pp.output_size_mm == pytest_approx(row["size_mm"])


def pytest_approx(value, abs=0.2):
    import pytest
    return pytest.approx(value, abs=abs)


def blank(bs: str, num=None, occ=False, pos=PageNumberPos.BOTTOM_RIGHT, rot=0):
    return {"blank": True, "blank_source": bs, "number_text": num,
            "number_occupies": occ, "number_position": pos, "rotation": rot}


def original(num, pos=PageNumberPos.BOTTOM_RIGHT, rot=0, occ=True):
    return {"blank": False, "blank_source": None, "number_text": str(num),
            "number_occupies": occ, "number_position": pos, "rotation": rot}


# ---------------------------------------------------------------------------
# 旋转可读性专项：渲染 + 方向标记检查
# ---------------------------------------------------------------------------
def direction_marker_positions(out_path: str, phys_index: int) -> dict:
    """返回输出页中方向标记'顶/底/左/右'在显示坐标（读者视角）的 bbox。

    用 rotation_matrix 把未旋转 PDF 坐标变换到显示坐标（左上原点、y 向下），
    与渲染画面一致。
    """
    doc = pymupdf.open(out_path)
    try:
        page = doc[phys_index - 1]
        rm = page.rotation_matrix
        disp = {}
        for word in ("顶", "底", "左", "右"):
            rects = page.search_for(word)
            if not rects:
                continue
            r = rects[0]
            p0 = pymupdf.Point(r.x0, r.y0) * rm
            p1 = pymupdf.Point(r.x1, r.y1) * rm
            disp[word] = (min(p0.x, p1.x), min(p0.y, p1.y),
                          max(p0.x, p1.x), max(p0.y, p1.y))
        return disp
    finally:
        doc.close()


def assert_marks_upright(out_path: str, phys_index: int) -> dict:
    """断言显示画面中'顶在上、底在下、左在左、右在右'（正文正立的前提）。

    方向标记布置在四角（顶=上缘、底=下缘、左=左缘、右=右缘），旋转正确时
    （rotation_matrix 显示坐标，y 向下）应满足相对关系：
      顶.y < 底.y（顶在上）、左.x < 右.x（左在右的左方）。
    """
    disp = direction_marker_positions(out_path, phys_index)
    assert set(disp) == {"顶", "底", "左", "右"}, f"方向标记缺失: {disp}"
    def cy(w):
        return (disp[w][1] + disp[w][3]) / 2.0
    def cx(w):
        return (disp[w][0] + disp[w][2]) / 2.0
    assert cy("顶") < cy("底"), f"顶({cy('顶'):.0f}) 不在底({cy('底'):.0f})上方"
    assert cx("左") < cx("右"), f"左({cx('左'):.0f}) 不在右({cx('右'):.0f})左方"
    return disp
