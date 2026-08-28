# -*- coding: utf-8 -*-
"""增强版提示语新增功能专项测试。

对应提示语：AgentPrompt\旋转修复与性能优化与放大_提示语.md（增强版 5 任务）
覆盖：
  1. 任务 1：源页 /Rotate 坐标修正（detect_text_rotation 的 source_rotation 参数）
  2. 任务 2 优化 4：overlap_cache 命中 / 字号变化失效 / 边距变化失效
  3. 任务 5：配置文件 computed 段持久化（rotations / overlap + 指纹 / 单页覆盖过滤）
  4. 端到端：控制器保存写入 computed → 重开 PDF 预热缓存
"""
from __future__ import annotations

import pytest

from pdfsim import engine
from pdfsim.engine import (
    build_process_plan,
    detect_text_rotation,
)
from pdfsim.models import (
    A4_WIDTH_MM,
    A4_HEIGHT_MM,
    DocumentConfig,
    PageInfo,
    PageNumberPos,
    PageNumberStyle,
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


def _a4(idx):
    return PageInfo(original_index=idx, width_mm=A4_WIDTH_MM, height_mm=A4_HEIGHT_MM)


def _build(blocks, cfg=None, overlap_cache=None):
    src = [_a4(0)]
    cfg = cfg or DocumentConfig(start_page_number=1)
    calls = {"n": 0}

    def tbc(idx):
        calls["n"] += 1
        return blocks.get(idx)

    plan = build_process_plan(
        src, cfg,
        page_text_data={0: {"blocks": []}},
        text_width_calculator=lambda t, fs: len(t) * fs * 0.5,
        text_block_calculator=tbc,
        overlap_cache=overlap_cache,
    )
    return plan, calls


# ---------------------------------------------------------------------------
# 1. 任务 1：源页 /Rotate 坐标修正
# ---------------------------------------------------------------------------
class TestSourceRotation:
    """detect_text_rotation 的 source_rotation 参数。

    get_text("dict") 的 dir 处于 PDF 内部（未旋转）坐标系；带 /Rotate 页需先
    施加 source_rotation 变换到显示坐标系再判定（否则 90↔270、0↔180 混淆）。
    """

    def test_rot90_must_rotate_dir_left(self):
        """/Rotate=90 + 内部 dir=(-1,0) → 修正后 must_rotate=True 返回 90°
        （不修正返回 270° 错误）。"""
        assert detect_text_rotation(
            text_data((-1.0, 0.0)), must_rotate=True, source_rotation=90
        ) == 90

    def test_rot90_must_rotate_dir_front(self):
        """/Rotate=90 + 内部 dir=(1,0)（上面用例的反面）→ 270°（修正后）。"""
        assert detect_text_rotation(
            text_data((1.0, 0.0)), must_rotate=True, source_rotation=90
        ) == 270

    def test_rot180_no_must_dir_front(self):
        """/Rotate=180 + 内部 dir=(1,0) → 修正后 not_must 返回 180°
        （不修正返回 0° 错误）。"""
        assert detect_text_rotation(
            text_data((1.0, 0.0)), must_rotate=False, source_rotation=180
        ) == 180

    def test_rot180_no_must_dir_opposite(self):
        """/Rotate=180 + 内部 dir=(-1,0) → 修正后 dir=(1,0) 正面 → 0°。"""
        assert detect_text_rotation(
            text_data((-1.0, 0.0)), must_rotate=False, source_rotation=180
        ) == 0

    def test_source_rotation_zero_unchanged(self):
        """source_rotation=0 与不传完全一致（向后兼容）。"""
        for d in [(1.0, 0.0), (-1.0, 0.0), (0.0, 1.0), (0.0, -1.0)]:
            for must in (True, False):
                assert detect_text_rotation(
                    text_data(d), must_rotate=must, source_rotation=0
                ) == detect_text_rotation(text_data(d), must_rotate=must)


# ---------------------------------------------------------------------------
# 2. 任务 2 优化 4：overlap_cache
# ---------------------------------------------------------------------------
class TestOverlapCache:
    def test_second_build_hits_cache(self):
        """第二次构建（参数不变）→ 命中 overlap_cache，不再调 text_block_calculator。"""
        blocks = {0: [(10.0, 10.0, 50.0, 30.0)]}
        cache: dict = {}
        _, calls1 = _build(blocks, overlap_cache=cache)
        assert calls1["n"] == 1
        plan2, calls2 = _build(blocks, overlap_cache=cache)
        assert calls2["n"] == 0, "应命中缓存（text_block_calculator 不再调用）"
        assert plan2.warnings == []

    def test_fontsize_change_recompute(self):
        """改全局字号 → cache_key（含字号）变化 → 自动重算。"""
        blocks = {0: [(10.0, 10.0, 50.0, 30.0)]}
        cache: dict = {}
        _build(blocks, overlap_cache=cache)
        cfg2 = DocumentConfig(start_page_number=1)
        cfg2.global_style.fontsize_pt = 12.0
        _, calls2 = _build(blocks, cfg=cfg2, overlap_cache=cache)
        assert calls2["n"] == 1, "字号变化应重算"

    def test_margin_change_recompute(self):
        """改全局边距 → cache_key（含四边距）变化 → 自动重算（防止同 key 污染）。"""
        blocks = {0: [(10.0, 10.0, 50.0, 30.0)]}
        cache: dict = {}
        _build(blocks, overlap_cache=cache)
        cfg2 = DocumentConfig(start_page_number=1)
        cfg2.global_style.margin_right_mm = 20.0
        _, calls2 = _build(blocks, cfg=cfg2, overlap_cache=cache)
        assert calls2["n"] == 1, "边距变化应重算"

    def test_overlap_cache_populated(self):
        """构建后 overlap_cache 写入 (源页, 位置, 字号, 旋转, 边距) 键。"""
        cache: dict = {}
        _build({0: [(10.0, 10.0, 50.0, 30.0)]}, overlap_cache=cache)
        assert len(cache) == 1
        key = next(iter(cache))
        assert key[0] == 0  # src_index
        assert key[1] == PageNumberPos.BOTTOM_RIGHT  # 第 1 页默认右下
        assert key[2] == 9.0  # 字号
        assert key[3] == 0  # 总旋转
        assert key[4:] == (10.0, 10.0, 10.0, 10.0)  # 四边距


# ---------------------------------------------------------------------------
# 3. 任务 5：配置文件 computed 段持久化
# ---------------------------------------------------------------------------
class TestComputedPersistence:
    def test_roundtrip_rotation_and_overlap(self, tmp_path):
        from pdfsim.config import ConfigManager, _overlap_fingerprint

        pdf = tmp_path / "doc.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")
        mgr = ConfigManager()
        cfg = DocumentConfig(start_page_number=1)
        fp = _overlap_fingerprint(cfg)
        rot = {0: 90, 1: 0}
        ov = {
            (0, PageNumberPos.BOTTOM_RIGHT, 9.0, 0,
             10.0, 10.0, 10.0, 10.0): ([], False, (562.4, 804.5, 566.9, 820.7)),
            (1, PageNumberPos.BOTTOM_LEFT, 9.0, 0,
             10.0, 10.0, 10.0, 10.0): ([(1.0, 2.0, 3.0, 4.0)], True, (1.0, 2.0, 3.0, 4.0)),
        }
        mgr.save_all(str(pdf), cfg, {},
                     rotation_cache=rot, overlap_cache=ov, overlap_fingerprint=fp)
        rot2, ov2 = mgr.load_computed(str(pdf), fp)
        assert rot2 == rot
        assert ov2 == ov, "overlap 条目应完整还原（key/value）"

    def test_fingerprint_mismatch_no_overlap(self, tmp_path):
        from pdfsim.config import ConfigManager, _overlap_fingerprint

        pdf = tmp_path / "doc.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")
        mgr = ConfigManager()
        cfg = DocumentConfig(start_page_number=1)
        fp1 = _overlap_fingerprint(cfg)
        ov = {
            (0, PageNumberPos.BOTTOM_RIGHT, 9.0, 0,
             10.0, 10.0, 10.0, 10.0): ([], False, (1.0, 2.0, 3.0, 4.0)),
        }
        mgr.save_all(str(pdf), cfg, {},
                     rotation_cache={0: 90}, overlap_cache=ov, overlap_fingerprint=fp1)
        # 指纹变化（字号改）→ overlap 不预热；rotation 仍有效（只依赖源页内容）
        cfg2 = DocumentConfig(start_page_number=1)
        cfg2.global_style.fontsize_pt = 11.0
        fp2 = _overlap_fingerprint(cfg2)
        rot2, ov2 = mgr.load_computed(str(pdf), fp2)
        assert rot2 == {0: 90}
        assert ov2 == {}

    def test_override_page_not_prefetched(self, tmp_path):
        from pdfsim.config import ConfigManager, _overlap_fingerprint

        pdf = tmp_path / "doc.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")
        mgr = ConfigManager()
        cfg = DocumentConfig(start_page_number=1)
        fp = _overlap_fingerprint(cfg)
        ov = {
            (0, PageNumberPos.BOTTOM_RIGHT, 9.0, 0,
             10.0, 10.0, 10.0, 10.0): ([], False, (1.0, 2.0, 3.0, 4.0)),
            (1, PageNumberPos.BOTTOM_LEFT, 9.0, 0,
             10.0, 10.0, 10.0, 10.0): ([], False, (1.0, 2.0, 3.0, 4.0)),
        }
        mgr.save_all(str(pdf), cfg, {},
                     rotation_cache={}, overlap_cache=ov, overlap_fingerprint=fp)
        src = [
            _a4(0),
            PageInfo(original_index=1, width_mm=A4_WIDTH_MM, height_mm=A4_HEIGHT_MM,
                     style_override=PageNumberStyle(fontsize_pt=12.0)),
        ]
        rot2, ov2 = mgr.load_computed(str(pdf), fp, source_pages=src)
        assert {k[0] for k in ov2} == {0}, "无覆盖的页 0 应预取，覆盖页 1 不预取"

    def test_missing_computed_ok(self, tmp_path):
        """旧配置无 computed 段 → 正常加载（返回空缓存，不影响 global/pages）。"""
        from pdfsim.config import ConfigManager

        pdf = tmp_path / "doc.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")
        mgr = ConfigManager()
        mgr.save_config(str(pdf), DocumentConfig(start_page_number=1))
        rot, ov = mgr.load_computed(str(pdf), "any-fp")
        assert rot == {} and ov == {}
        # global/pages 仍正常
        cfg = mgr.load_config(str(pdf))
        assert cfg.start_page_number == 1

    def test_corrupted_computed_ok(self, tmp_path):
        """computed 段损坏 → 跳过，不影响 global/pages 加载。"""
        from pdfsim.config import ConfigManager, _overlap_fingerprint

        pdf = tmp_path / "doc.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")
        mgr = ConfigManager()
        cfg = DocumentConfig(start_page_number=1)
        fp = _overlap_fingerprint(cfg)
        mgr.save_all(str(pdf), cfg, {},
                     rotation_cache={0: 90}, overlap_cache={}, overlap_fingerprint=fp)
        # 手工破坏 computed 段
        import json
        path = mgr.config_path_for(str(pdf))
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["computed"] = {"rotations": {"bad": "x"}, "overlap": {"fingerprint": fp,
                                                                   "entries": [{"bad": 1}]}}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        rot, ov = mgr.load_computed(str(pdf), fp)
        assert rot == {} and ov == {}
        cfg2 = mgr.load_config(str(pdf))
        assert cfg2.start_page_number == 1


# ---------------------------------------------------------------------------
# 4. 端到端：控制器保存写入 computed → 重开预热
# ---------------------------------------------------------------------------
class TestControllerPersistPrewarm:
    def test_save_then_reopen_prewarms(self, tmp_path):
        import pymupdf

        doc = pymupdf.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 72), "hello world")
        pdf = tmp_path / "doc.pdf"
        doc.save(str(pdf))
        doc.close()

        from pdfsim.ui.app_controller import AppController

        c = AppController()
        c.open_pdf(str(pdf), "")
        # 触发保存 → 写入 computed 段（rotation_cache / overlap_cache）
        c._do_save_config()
        assert c._rotation_cache, "构建后应有旋转检测结果"
        assert c._overlap_cache, "构建后应有重叠检测缓存"

        # 重开 → 预热（clear 后 load_computed 回填）
        c2 = AppController()
        c2.open_pdf(str(pdf), "")
        try:
            assert c2._rotation_cache == c._rotation_cache
            assert c2._overlap_cache == c._overlap_cache
            # 预热后构建不重算（rotation_cache 命中）
            assert c2.current_plan is not None
        finally:
            c.close()
            c2.close()
