# -*- coding: utf-8 -*-
"""用 PyMuPDF 生成全部测试样本（可重复执行，不依赖外部文件）。

用法：
    python gen_samples.py [输出目录]
默认输出目录：本文件所在目录（src/tests/samples）。
"""
from __future__ import annotations

import io
import os
import sys

# CI / 非 UTF-8 控制台（如 Windows cp1252）下中文 print 不崩溃
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

import pikepdf
import pymupdf

# 页面尺寸（pt）
A4_W, A4_H = 595.28, 841.89
A3_W, A3_H = 841.89, 1190.55

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = sys.argv[1] if len(sys.argv) > 1 else HERE


def _mm(w, h):
    return w * 72 / 25.4, h * 72 / 25.4


def _new_doc():
    return pymupdf.open()


def _add_text_page(doc, size, title, body="This is a sample body text line."):
    page = doc.new_page(width=size[0], height=size[1])
    page.insert_text((72, 100), title, fontsize=24, fontname="china-s")
    page.insert_text((72, 150), body, fontsize=12, fontname="helv")
    for i in range(3):
        page.insert_text((72, 180 + i * 30), f"line {i}: {body}", fontsize=11,
                         fontname="helv")
    return page


def gen_a4_portrait():
    """A4 纵向多页，含书签（封面/目录/正文/签字）。"""
    doc = _new_doc()
    for i in range(6):
        _add_text_page(doc, (A4_W, A4_H), f"第{i + 1}页标题",
                       f"A4 portrait sample page {i + 1}")
    doc.set_toc([
        [1, "封面", 1],
        [1, "目录", 2],
        [1, "正文", 3],
        [1, "签字", 5],
    ])
    return doc


def gen_no_bookmark():
    """A4 纵向多页，无 Outline。"""
    doc = _new_doc()
    for i in range(4):
        _add_text_page(doc, (A4_W, A4_H), f"Page {i + 1}",
                       f"no bookmark sample {i + 1}")
    return doc


def gen_a3_portrait():
    """含 A3 纵向页（需旋转），四角方向标记 + 中心箭头。"""
    doc = _new_doc()
    _add_text_page(doc, (A4_W, A4_H), "Page 1 A4", "first a4 page")
    _add_text_page(doc, (A3_W, A3_H), "A3 纵向页", "a3 portrait page")
    # A3 纵向页：四角方向标记 + 中心箭头
    page = doc[-1]
    _add_direction_markers(page, (A3_W, A3_H))
    _add_text_page(doc, (A4_W, A4_H), "Page 3 A4", "third page")
    return doc


def gen_a3_landscape():
    """含 A3 横向页（不旋转），四角方向标记。"""
    doc = _new_doc()
    _add_text_page(doc, (A4_W, A4_H), "Page 1", "first")
    _add_text_page(doc, (A3_H, A3_W), "A3 横向页", "a3 landscape page")
    page = doc[-1]
    _add_direction_markers(page, (A3_H, A3_W))
    _add_text_page(doc, (A4_W, A4_H), "Page 3", "third")
    return doc


def gen_mixed():
    """A4 + A3 混合。"""
    doc = _new_doc()
    _add_text_page(doc, (A4_W, A4_H), "A4 1", "a4 one")
    _add_text_page(doc, (A3_W, A3_H), "A3 纵向", "a3 portrait")
    _add_direction_markers(doc[-1], (A3_W, A3_H))
    _add_text_page(doc, (A3_H, A3_W), "A3 横向", "a3 landscape")
    _add_direction_markers(doc[-1], (A3_H, A3_W))
    _add_text_page(doc, (A4_W, A4_H), "A4 2", "a4 two")
    return doc


def gen_single():
    """仅 1 页 A4。"""
    doc = _new_doc()
    _add_text_page(doc, (A4_W, A4_H), "Single Page", "only one page")
    return doc


def gen_odd_last():
    """3 页 A4（末页奇数）。"""
    doc = _new_doc()
    for i in range(3):
        _add_text_page(doc, (A4_W, A4_H), f"Odd {i + 1}", f"page {i + 1}")
    return doc


def gen_200pages():
    """200 页 A4（性能测试）。"""
    doc = _new_doc()
    for i in range(200):
        _add_text_page(doc, (A4_W, A4_H), f"Page {i + 1}", f"content {i + 1}")
    return doc


def gen_800pages():
    """800 页 A4 纵向（性能优化测试，模拟真实大文档，约 50-70MB）。

    每页：标题 + 约 45 行正文段落 + 一张独立噪声纹理图（模拟扫描/配图），
    接近真实标书/合同/报告，复现大文档的文本提取、规划与渲染负载。
    """
    from PIL import Image

    def _noise_jpeg(w: int, h: int) -> bytes:
        """生成一张噪声纹理 JPEG（压缩率低，模拟文档扫描/配图）。"""
        img = Image.effect_noise((w, h), 55).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=75)
        return buf.getvalue()

    doc = _new_doc()
    line = (
        "模拟真实业务文档正文，用于复现大文档打开与翻页时的文本提取、"
        "物理顺序规划与渲染负载。含标题、编号与段落，接近标书、合同与报告正文。"
    ) * 3  # 每行约 180 字符
    for i in range(800):
        page = doc.new_page(width=A4_W, height=A4_H)
        page.insert_text((72, 90), f"第{i + 1}页标题", fontsize=24, fontname="china-s")
        y = 150
        for r in range(45):
            page.insert_text((72, y), f"{r:02d} {line}", fontsize=11, fontname="helv")
            y += 15
        # 中部插入一张独立噪声纹理图（增大体积、贴近真实文档）
        jpeg = _noise_jpeg(460, 340)
        page.insert_image(pymupdf.Rect(72, y, 72 + 320, y + 236), stream=jpeg)
    return doc


def gen_with_pagenum():
    """每页右下角已有页码（重叠检测样本）。

    已有页码放在右下角（距右 40pt、距底 40pt），与新增页码区域（右边距 10mm、
    底边距 10mm）部分重叠，用于触发算法 5 重叠检测。
    （Bug 修复：insert_text 的 y 为左上原点向下，距底 40pt 应为 A4_H-40；
    原实现写 40 导致已有页码渲染在顶部，与新增页码（底部）不再重叠。）
    """
    doc = _new_doc()
    for i in range(4):
        page = _add_text_page(doc, (A4_W, A4_H), f"Page {i + 1}",
                              f"sample with existing page number {i + 1}")
        # 右下角已有页码（与新增页码区域实质重叠：距右 30pt、距底 30pt，
        # 新增页码距右/距底 10mm≈28.35pt，二者文字包围盒在 x/y 方向均有 >1pt 实质重叠）
        page.insert_text((A4_W - 30, A4_H - 30), str(i + 1), fontsize=12,
                         fontname="helv")
    return doc


def gen_no_count():
    """含标记为不占序号的页（通过页面标题，供加载器按关键词识别）。"""
    doc = _new_doc()
    _add_text_page(doc, (A4_W, A4_H), "封面", "cover page")
    _add_text_page(doc, (A4_W, A4_H), "附件", "attachment no count page")
    _add_text_page(doc, (A4_W, A4_H), "正文", "body")
    return doc


def _add_direction_markers(page, size):
    """四角方向标记 + 中心水平箭头。"""
    w, h = size
    markers = {
        "顶": (w * 0.12, h * 0.10),
        "右": (w * 0.88, h * 0.10),
        "底": (w * 0.88, h * 0.90),
        "左": (w * 0.12, h * 0.90),
    }
    for text, (x, y) in markers.items():
        page.insert_text((x, y), text, fontsize=24, fontname="china-s")
    # 中心水平箭头 →
    cy = h / 2
    page.draw_line(pymupdf.Point(w * 0.35, cy), pymupdf.Point(w * 0.65, cy),
                   color=(0, 0, 0), width=3)
    page.draw_line(pymupdf.Point(w * 0.65, cy), pymupdf.Point(w * 0.60, cy - 14),
                   color=(0, 0, 0), width=3)
    page.draw_line(pymupdf.Point(w * 0.65, cy), pymupdf.Point(w * 0.60, cy + 14),
                   color=(0, 0, 0), width=3)


def gen_direction_markers():
    """A4 横向 + A3 纵向方向标记样本（旋转验证）。"""
    doc = _new_doc()
    p = _add_text_page(doc, (A4_H, A4_W), "A4 横向", "a4 landscape markers")
    _add_direction_markers(p, (A4_H, A4_W))
    p = _add_text_page(doc, (A3_W, A3_H), "A3 纵向", "a3 portrait markers")
    _add_direction_markers(p, (A3_W, A3_H))
    return doc


def gen_encrypted(out_path):
    """加密样本（带用户密码 testpass）。"""
    raw = os.path.join(OUT_DIR, "_encrypted_raw.pdf")
    doc = _new_doc()
    _add_text_page(doc, (A4_W, A4_H), "Encrypted", "this file is encrypted")
    doc.save(raw)
    doc.close()
    with pikepdf.open(raw) as pdf:
        pdf.save(out_path, encryption=pikepdf.Encryption(owner="", user="testpass"))
    os.unlink(raw)


def gen_corrupted(out_path):
    """损坏样本：保留 %PDF 头部 + 填充损坏字节（无合法 trailer/xref）。

    实测：直接"截断后半部分"的损坏文件可被 pikepdf 容错打开（PDF 容错解析），
    无法触发损坏检测；改用"合法头 + 垃圾体"确保抛 PdfError（损坏检测验收点）。
    """
    with open(out_path, "wb") as f:
        f.write(b"%PDF-1.7\n")
        f.write(b"\x00\xff corrupted-object-stream-no-trailer " * 40)


# 名称 → (生成函数)
GENERATORS = {
    "sample_a4_portrait.pdf": gen_a4_portrait,
    "sample_no_bookmark.pdf": gen_no_bookmark,
    "sample_a3_portrait.pdf": gen_a3_portrait,
    "sample_a3_landscape.pdf": gen_a3_landscape,
    "sample_mixed.pdf": gen_mixed,
    "sample_single.pdf": gen_single,
    "sample_odd_last.pdf": gen_odd_last,
    "sample_200pages.pdf": gen_200pages,
    "sample_800pages.pdf": gen_800pages,
    "sample_with_pagenum.pdf": gen_with_pagenum,
    "sample_no_count.pdf": gen_no_count,
    "sample_direction_markers.pdf": gen_direction_markers,
}


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    for name, gen in GENERATORS.items():
        path = os.path.join(OUT_DIR, name)
        doc = gen()
        doc.save(path)
        doc.close()
        print(f"[生成] {name}")
    # 特殊样本（加密 / 损坏）
    gen_encrypted(os.path.join(OUT_DIR, "sample_encrypted.pdf"))
    print("[生成] sample_encrypted.pdf")
    gen_corrupted(os.path.join(OUT_DIR, "sample_corrupted.pdf"))
    print("[生成] sample_corrupted.pdf")
    print(f"全部样本已生成到: {OUT_DIR}")


if __name__ == "__main__":
    main()
