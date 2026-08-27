# -*- coding: utf-8 -*-
"""把 Markdown 文档转成 PDF（PySide6/Qt，支持 GFM 表格 + 本地图片嵌入）。

用法：
    python scripts/md2pdf.py <输入.md> <输出.pdf>

说明：
- 图片使用相对路径，相对 .md 所在目录解析；
- 中文字体使用微软雅黑，A4 纵向，页边距 18mm；
- 在无桌面会话环境（CI）下也能工作（offscreen）。
"""
from __future__ import annotations

import os
import re
import sys

from PySide6.QtCore import QMarginsF, QUrl
from PySide6.QtGui import QFont, QPageLayout, QPageSize, QTextDocument
from PySide6.QtWidgets import QApplication
from PySide6.QtPrintSupport import QPrinter


def md_to_pdf(src: str, dst: str) -> None:
    with open(src, "r", encoding="utf-8") as f:
        text = f.read()

    app = QApplication.instance() or QApplication([])

    # markdown 里的相对图片路径 → 绝对 file URL（Qt 的 markdown 解析器无法按
    # 相对路径加载本地图片，会退化成 16x16 占位图）
    md_dir = os.path.dirname(src)

    def _fix_img(m: "re.Match[str]") -> str:
        alt = m.group(1)
        rel = m.group(2).split()[0]
        url = QUrl.fromLocalFile(os.path.abspath(os.path.join(md_dir, rel))).toString()
        return f"![{alt}]({url})"

    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", _fix_img, text)

    doc = QTextDocument()
    doc.setBaseUrl(QUrl.fromLocalFile(md_dir + os.sep))
    doc.setDefaultFont(QFont("Microsoft YaHei", 10))
    # Qt 6.5+ 的 GFM markdown 支持表格 / 代码块 / 图片
    doc.setMarkdown(text)

    printer = QPrinter(QPrinter.HighResolution)
    printer.setOutputFormat(QPrinter.PdfFormat)
    printer.setOutputFileName(dst)
    layout = QPageLayout(
        QPageSize(QPageSize.A4),
        QPageLayout.Portrait,
        QMarginsF(18, 18, 18, 18),  # mm
        QPageLayout.Millimeter,
    )
    printer.setPageLayout(layout)
    doc.print_(printer)
    print(f"[OK] {dst}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("用法: python scripts/md2pdf.py <输入.md> <输出.pdf>")
        sys.exit(2)
    md_to_pdf(sys.argv[1], sys.argv[2])
