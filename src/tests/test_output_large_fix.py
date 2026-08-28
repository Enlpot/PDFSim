# -*- coding: utf-8 -*-
"""大 PDF 输出修复（方案 A：temp file 替换 BytesIO + 压缩；方案 C：后台线程）专项测试。

对应提示语：AgentPrompt\大PDF输出修复_AC方案_提示语.md
覆盖：
  方案 A：
    - 输出成功/异常后临时文件均被清理（finally 保证）
    - out.save(garbage=4, deflate=True)：输出文件可打开、页数校验通过、体积合理
    - progress_cb 收到 10/50/90 进度
    - 大 PDF（100+ 页）输出成功
  方案 C：
    - output_async 不阻塞主线程、返回 True
    - output_progress 信号被发射
    - output_result_ready 信号携带成功 OutputResult
"""
from __future__ import annotations

import os

import pymupdf
import pytest

from pdfsim.engine import build_process_plan
from pdfsim.loader import PDFLoader
from pdfsim.models import DocumentConfig
from pdfsim.output import PDFOutput
from pdfsim.renderer import PDFRenderer


def _build_plan(src_path, out_dir):
    """加载 PDF → 构建 ProcessPlan（真实文本检测 + 真实字体宽度）。"""
    loader = PDFLoader()
    r = loader.open(src_path)
    try:
        text_data = {i: loader.extract_text_data(i) for i in range(len(r.pages))}
        renderer = PDFRenderer()
        config = DocumentConfig(output_dir=str(out_dir))
        plan = build_process_plan(
            r.pages,
            config,
            page_text_data=text_data,
            text_width_calculator=renderer.get_text_width,
        )
        return r, plan, config
    finally:
        loader.close()


def _make_pdf(path, pages=5):
    """生成 A4 纵向多页 PDF（每页一段文字）。"""
    doc = pymupdf.open()
    for i in range(pages):
        p = doc.new_page(width=595, height=842)
        p.insert_text((72, 72), f"Page {i + 1} content line")
    doc.save(path)
    doc.close()


def _temp_files(out_dir: str) -> list:
    """输出目录下残留的临时 .pdf（mkstemp 默认前缀 tmp*，排除源/输出文件）。"""
    return [f for f in os.listdir(out_dir) if f.startswith("tmp") and f.endswith(".pdf")]


# ---------------------------------------------------------------------------
# 方案 A：内存修复（temp file + 压缩）
# ---------------------------------------------------------------------------
class TestOutputTempFile:
    def test_temp_file_cleaned_on_success(self, samples_dir, tmp_path):
        """输出成功后临时文件已删除（输出目录无残留临时 .pdf）。"""
        src = str(tmp_path / "in.pdf")
        _make_pdf(src)
        r, plan, config = _build_plan(src, tmp_path)
        res = PDFOutput().output(src, plan, config)
        assert res.success
        # 无残留临时文件（tmp*.pdf 已被 finally 清理）
        assert _temp_files(str(tmp_path)) == []

    def test_temp_file_cleaned_on_failure(self, samples_dir, tmp_path, monkeypatch):
        """输出异常后临时文件也已删除（finally 保证）。"""
        src = str(tmp_path / "in.pdf")
        _make_pdf(src)
        r, plan, config = _build_plan(src, tmp_path)
        out = PDFOutput()

        def _boom(*args, **kwargs):
            raise RuntimeError("模拟绘制页码失败")

        monkeypatch.setattr(out, "_draw_page_numbers", _boom)
        with pytest.raises(RuntimeError):
            out.output(src, plan, config)
        # 异常后临时文件仍被清理
        assert _temp_files(str(tmp_path)) == []

    def test_output_with_garbage_and_deflate(self, samples_dir, tmp_path):
        """输出文件可正常打开、页数校验通过、体积合理（garbage=4 + deflate）。"""
        src = str(tmp_path / "in.pdf")
        _make_pdf(src, pages=10)
        r, plan, config = _build_plan(src, tmp_path)
        res = PDFOutput().output(src, plan, config)
        assert res.success
        assert res.page_count == 10
        with pymupdf.open(res.output_path) as d:
            assert d.page_count == 10
        # 体积不应显著大于源文件（10 页文本 ≈ 几十 KB，无异常膨胀）
        size_out = os.path.getsize(res.output_path)
        assert size_out < 2 * 1024 * 1024, f"输出体积异常: {size_out}"

    def test_output_progress_callback(self, samples_dir, tmp_path):
        """progress_cb 收到 10/50/90 三个阶段。"""
        src = str(tmp_path / "in.pdf")
        _make_pdf(src)
        r, plan, config = _build_plan(src, tmp_path)
        steps = []
        PDFOutput().output(src, plan, config, progress_cb=lambda p, m: steps.append((p, m)))
        pcts = [p for p, _ in steps]
        assert 10 in pcts and 50 in pcts and 90 in pcts
        assert pcts == sorted(pcts)  # 递增

    def test_output_large_pdf(self, samples_dir, tmp_path):
        """大 PDF（150 页）输出成功，页数校验通过（不再 MemoryError）。"""
        src = str(tmp_path / "large.pdf")
        _make_pdf(src, pages=150)
        r, plan, config = _build_plan(src, tmp_path)
        res = PDFOutput().output(src, plan, config)
        assert res.success
        assert res.page_count == 150
        with pymupdf.open(res.output_path) as d:
            assert d.page_count == 150
        # 无残留临时文件
        assert _temp_files(str(tmp_path)) == []

    def test_output_source_page_with_F0_font(self, tmp_path):
        """回归：源 PDF 某页自带 /F0 字体名时，输出不报 m_internal（Bug 修复）。

        根因：嵌入字体名硬编码 "F0" 与源 PDF 页面字体名冲突，PyMuPDF insert_font
        走复用分支 get_char_widths 读不到 FontFile → 'NoneType' object has no
        attribute 'm_internal'。改为独特名 "PDFSimFont" 后不再冲突。
        """
        import pikepdf

        src = str(tmp_path / "f0conflict.pdf")
        pdf = pikepdf.Pdf.new()
        pg = pdf.add_blank_page(page_size=(595, 842))
        # 注入名为 /F0 的字体资源（Type1 Helvetica，无 FontFile 流），复现冲突场景
        fobj = pdf.make_indirect(
            pikepdf.Dictionary(Type="/Font", Subtype="/Type1", BaseFont="/Helvetica")
        )
        res = pg.obj.get("/Resources", pikepdf.Dictionary())
        res["/Font"] = pikepdf.Dictionary({"/F0": fobj})
        pg.obj["/Resources"] = res
        pdf.save(src)
        pdf.close()

        r, plan, config = _build_plan(src, tmp_path)
        res = PDFOutput().output(src, plan, config)
        assert res.success
        # 页码仍正确写出
        with pymupdf.open(res.output_path) as d:
            assert d.page_count == len(plan.pages)
            assert d[0].get_text().strip()  # 首页应有页码文字



# ---------------------------------------------------------------------------
# 方案 C：后台线程输出（不阻塞主线程 + 进度 + 结果信号）
# ---------------------------------------------------------------------------
class TestOutputAsync:
    def _open_controller(self, samples_dir, tmp_path):
        src = str(tmp_path / "in.pdf")
        _make_pdf(src)
        from pdfsim.ui.app_controller import AppController

        c = AppController()
        c.open_pdf(src, "")
        return c, src

    def test_output_async_does_not_block(self, samples_dir, tmp_path):
        """output_async 返回 True 且立即返回（不阻塞），线程启动。"""
        c, src = self._open_controller(samples_dir, tmp_path)
        try:
            started = c.output_async()
            assert started is True
            assert c._output_thread is not None
        finally:
            c.close()

    def test_output_progress_signal(self, samples_dir, tmp_path, qtbot):
        """输出过程中 output_progress 信号被发射（10/50/90）。"""
        from pdfsim.ui.app_controller import AppController

        c = AppController()
        try:
            src = str(tmp_path / "in.pdf")
            _make_pdf(src)
            with qtbot.waitSignal(c.output_progress, timeout=15000) as blocker:
                c.open_pdf(src, "")
                c.output_async()
            pct, msg = blocker.args  # (percent, step_text)
            assert pct in (10, 50, 90)
            assert msg  # 步骤文字非空
        finally:
            c.close()

    def test_output_result_signal(self, samples_dir, tmp_path, qtbot):
        """输出完成后 output_result_ready 携带成功 OutputResult。"""
        c, src = self._open_controller(samples_dir, tmp_path)
        try:
            with qtbot.waitSignal(c.output_result_ready, timeout=30000) as blocker:
                c.output_async()
            result = blocker.args[0]
            assert result.success
            assert result.page_count > 0
            assert os.path.exists(result.output_path)
            # 完成后线程已清理，可再次启动
            assert c.output_async() is True
        finally:
            c.close()
