# -*- coding: utf-8 -*-
"""output.py 测试（依据 Stage2 提示语 5.5，用样本 PDF 端到端验证）。"""
import hashlib

import pymupdf
import pytest

from pdfsim.engine import build_process_plan
from pdfsim.loader import PDFLoader
from pdfsim.models import A4_HEIGHT_MM, A4_WIDTH_MM, DocumentConfig
from pdfsim.output import PDFOutput
from pdfsim.renderer import PDFRenderer


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _make_plan(sample_name, samples_dir, tmp_output, **cfg_kw):
    """加载样本 → 构建 ProcessPlan（真实文本检测 + 真实字体宽度）。"""
    loader = PDFLoader()
    r = loader.open(str(samples_dir / sample_name))
    try:
        text_data = {i: loader.extract_text_data(i) for i in range(len(r.pages))}
        renderer = PDFRenderer()
        cfg_kw.setdefault("output_dir", str(tmp_output))
        config = DocumentConfig(**cfg_kw)
        plan = build_process_plan(
            r.pages,
            config,
            page_text_data=text_data,
            text_width_calculator=renderer.get_text_width,
        )
        return r, plan, config
    finally:
        loader.close()


@pytest.fixture()
def out():
    return PDFOutput()


class TestOutput:
    def test_page_count_and_hash(self, out, samples_dir, tmp_path):
        """页数一致 + 原文件 SHA-256 未变。"""
        src = samples_dir / "sample_a4_portrait.pdf"
        hash_before = _sha256(str(src))
        _, plan, config = _make_plan("sample_a4_portrait.pdf", samples_dir, tmp_path)
        result = out.output(str(src), plan, config)
        assert result.success
        assert result.page_count == len(plan.pages)
        assert result.source_hash_verified
        assert _sha256(str(src)) == hash_before  # 原文件未被修改

    def test_page_number_text_extractable(self, out, samples_dir, tmp_path):
        """页码文字可提取（内容流文字）。"""
        src = samples_dir / "sample_a4_portrait.pdf"
        _, plan, config = _make_plan("sample_a4_portrait.pdf", samples_dir, tmp_path)
        result = out.output(str(src), plan, config)
        assert result.success
        doc = pymupdf.open(result.output_path)
        try:
            text = " ".join(doc[i].get_text() for i in range(doc.page_count))
            expected = {pp.number_text for pp in plan.pages if pp.number_text}
            for n in expected:
                assert n in text, f"页码 {n} 未在输出文本中找到"
        finally:
            doc.close()

    def test_font_embedded(self, out, samples_dir, tmp_path):
        """页码字体为嵌入字体。"""
        src = samples_dir / "sample_a4_portrait.pdf"
        _, plan, config = _make_plan("sample_a4_portrait.pdf", samples_dir, tmp_path)
        result = out.output(str(src), plan, config)
        doc = pymupdf.open(result.output_path)
        try:
            fonts = doc[0].get_fonts()
            # 元组: (xref, ext, type, basefont, name, encoding)；嵌入 TTF → ext == 'ttf'
            assert any(f[4] == "F0" and f[1] == "ttf" for f in fonts), f"未找到嵌入字体 F0: {fonts}"
        finally:
            doc.close()

    def test_blank_pages_inserted(self, out, samples_dir, tmp_path):
        """空白页正确插入（封面背面 = A4 尺寸）。"""
        src = samples_dir / "sample_a4_portrait.pdf"
        _, plan, config = _make_plan("sample_a4_portrait.pdf", samples_dir, tmp_path)
        result = out.output(str(src), plan, config)
        doc = pymupdf.open(result.output_path)
        try:
            assert doc.page_count == len(plan.pages)
            # 第 2 页应为封面背面空白（A4 纵向尺寸）
            r = doc[1].rect
            assert r.width == pytest.approx(A4_WIDTH_MM * 72 / 25.4, abs=1)
            assert r.height == pytest.approx(A4_HEIGHT_MM * 72 / 25.4, abs=1)
        finally:
            doc.close()

    def test_rotation_a3_portrait(self, out, samples_dir, tmp_path):
        """A3 纵向页输出后旋转 90，显示尺寸 1190×841。"""
        src = samples_dir / "sample_a3_portrait.pdf"
        _, plan, config = _make_plan("sample_a3_portrait.pdf", samples_dir, tmp_path)
        result = out.output(str(src), plan, config)
        doc = pymupdf.open(result.output_path)
        try:
            # 找到 A3 页（输出后物理页），验证旋转
            a3_idx = None
            for pp in plan.pages:
                if not pp.is_blank and pp.rotation == 90:
                    a3_idx = pp.physical_index - 1
                    break
            assert a3_idx is not None
            r = doc[a3_idx].rect
            assert r.width == pytest.approx(1190.55, abs=1)
            assert r.height == pytest.approx(841.89, abs=1)
            # 页面 /Rotate 应为 90
            import pikepdf
            with pikepdf.open(result.output_path) as p:
                assert p.pages[a3_idx].rotation % 360 == 90
        finally:
            doc.close()

    def test_number_position_odd_right_even_left(self, out, samples_dir, tmp_path):
        """页码位置：物理奇页右下、偶页左下（A4 纵向）。"""
        src = samples_dir / "sample_a4_portrait.pdf"
        _, plan, config = _make_plan("sample_a4_portrait.pdf", samples_dir, tmp_path)
        result = out.output(str(src), plan, config)
        doc = pymupdf.open(result.output_path)
        try:
            for pp in plan.pages:
                if pp.number_text is None or pp.number_point is None:
                    continue
                page = doc[pp.physical_index - 1]
                words = page.get_text("words")
                # 页码在页面底部；取 y0 最小（最靠底）的匹配 span
                candidates = [w for w in words if w[4] == pp.number_text]
                if not candidates:
                    continue
                num = max(candidates, key=lambda w: w[1])  # y0 最大 = 最靠底（页码在底部）
                x = num[0]
                W = page.rect.width
                margin = 10 * 72 / 25.4
                if pp.physical_index % 2 == 1:
                    assert x > W - margin * 3  # 右下角区域
                else:
                    assert x < margin * 3  # 左下角区域
        finally:
            doc.close()

    def test_existing_output_not_overwritten(self, out, samples_dir, tmp_path):
        """输出文件已存在时不覆盖。"""
        src = samples_dir / "sample_single.pdf"
        _, plan, config = _make_plan("sample_single.pdf", samples_dir, tmp_path)
        r1 = out.output(str(src), plan, config)
        assert r1.success
        # 已存在 → 跳过
        r2 = out.output(str(src), plan, config)
        assert r2.success is False
        assert "已存在" in r2.message

    def test_rotated_page_number_position(self, out, samples_dir, tmp_path):
        """旋转页页码位置端到端验证（审查缺口 1 关闭）。

        A4 横向/A3 纵向页输出旋转 90 后：
          - 物理奇页 → 页码在显示坐标右下角；
          - 物理偶页 → 页码在显示坐标左下角（A3 固定右下角除外）。
        """
        src = samples_dir / "sample_direction_markers.pdf"
        _, plan, config = _make_plan("sample_direction_markers.pdf", samples_dir, tmp_path)
        result = out.output(str(src), plan, config)
        assert result.success
        doc = pymupdf.open(result.output_path)
        try:
            checked = 0
            for pp in plan.pages:
                if pp.is_blank or pp.rotation == 0 or pp.number_text is None:
                    continue
                page = doc[pp.physical_index - 1]
                words = page.get_text("words")
                cand = [w for w in words if w[4] == pp.number_text]
                assert cand, f"旋转页物理{pp.physical_index} 未找到页码"
                num = max(cand, key=lambda w: w[1])  # y0 最大=最靠底（页码在底部）
                cx = (num[0] + num[2]) / 2.0
                cy = (num[1] + num[3]) / 2.0
                Wd, Hd = page.rect.width, page.rect.height
                # 内容坐标 → 显示坐标（r=90 实测映射）：x_d=Wd-y, y_d=Hd-x
                x_disp = Wd - cy
                y_disp = Hd - cx
                if pp.physical_index % 2 == 1:
                    assert x_disp > Wd * 0.75, f"物理{pp.physical_index} 页码应靠右"
                    assert y_disp < Hd * 0.15, f"物理{pp.physical_index} 页码应靠底部"
                else:
                    assert x_disp < Wd * 0.25, f"物理{pp.physical_index} 页码应靠左"
                    assert y_disp < Hd * 0.15, f"物理{pp.physical_index} 页码应靠底部"
                checked += 1
            assert checked >= 2  # A4 横向 + A3 纵向至少各一
        finally:
            doc.close()

    def test_rotated_even_page_left(self, out, samples_dir, tmp_path):
        """旋转页落偶数位 → 页码在左下角（构造两个 A4 横向页）。"""
        import shutil
        work = tmp_path / "even"
        work.mkdir()
        # 用 PyMuPDF 生成两页 A4 横向样本
        import pymupdf as mf
        p = mf.open()
        for _ in range(2):
            pg = p.new_page(width=841.89, height=595.28)
            pg.insert_text((100, 100), "landscape even test", fontsize=14, fontname="china-s")
        src = work / "two_landscape.pdf"
        p.save(str(src)); p.close()
        from pdfsim.loader import PDFLoader
        from pdfsim.engine import build_process_plan
        from pdfsim.renderer import PDFRenderer
        loader = PDFLoader()
        r = loader.open(str(src))
        try:
            td = {i: loader.extract_text_data(i) for i in range(len(r.pages))}
            rend = PDFRenderer()
            cfg = DocumentConfig(output_dir=str(tmp_path))
            plan = build_process_plan(r.pages, cfg, page_text_data=td,
                                      text_width_calculator=rend.get_text_width)
            # 两页 A4 横向，均 rot90；phys1 奇右下、phys2 偶左下
            assert plan.pages[0].rotation == 90
            assert plan.pages[1].rotation == 90
            res = out.output(str(src), plan, cfg)
            assert res.success
            doc = pymupdf.open(res.output_path)
            try:
                for pp in plan.pages:
                    page = doc[pp.physical_index - 1]
                    cand = [w for w in page.get_text("words") if w[4] == pp.number_text]
                    num = max(cand, key=lambda w: w[1])
                    cx = (num[0] + num[2]) / 2.0
                    cy = (num[1] + num[3]) / 2.0
                    Wd, Hd = page.rect.width, page.rect.height
                    x_disp = Wd - cy
                    y_disp = Hd - cx
                    if pp.physical_index % 2 == 1:
                        assert x_disp > Wd * 0.75
                    else:
                        assert x_disp < Wd * 0.25
                    assert y_disp < Hd * 0.15
            finally:
                doc.close()
        finally:
            loader.close()

    def test_output_to_source_dir_when_no_output_dir(self, out, samples_dir, tmp_path, monkeypatch):
        """output_dir 为空 → 输出到原 PDF 所在文件夹。"""
        import os
        import shutil
        src = samples_dir / "sample_single.pdf"
        # 复制到临时目录，避免污染 samples
        work = tmp_path / "work"
        work.mkdir()
        dst_src = work / "sample_single.pdf"
        shutil.copy(str(src), str(dst_src))
        _, plan, config = _make_plan("sample_single.pdf", samples_dir, tmp_path,
                                     output_dir="")
        # 用 work 下的副本作为源
        result = out.output(str(dst_src), plan, config)
        assert result.success
        expected = work / "sample_single（打印装订）.pdf"
        assert os.path.exists(str(expected))

