# -*- coding: utf-8 -*-
"""PDFSim 打包自检脚本：在 PyInstaller 打包运行时内程序化验证核心功能。

用法（源码）：python _verify\\verify_bundled.py
用法（打包）：见 build_selftest.py，产物为独立 self-test EXE。

验证项（对应 Stage5 开发机 10 项的功能等价）：
  1 模块加载 + QApplication（offscreen）
  2 打开 PDF（含书签自动识别）
  3 标记封面/签字 → 联动 FRONT + 物理顺序（含自动空白页）
  4 旋转页（A4 横向自动检测 90°）
  5 输出 → 生成“（打印装订）.pdf”且页数正确
  6 原文件 SHA-256 全程不变
  7 加密 PDF：无/错密码抛错，正确密码可打开
  8 损坏 PDF：抛 PDFLoadError
  9 配置保存/恢复一致
 10 中文界面：系统中文字体可加载、主窗口标题中文正常

结果输出：stdout JSON + _verify\\selftest_result.json，非零退出码表示失败。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# 非 UTF-8 控制台下中文输出不崩溃（CI / Windows cp1252）
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

RESULTS = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append({"name": name, "ok": bool(ok), "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return bool(ok)


def find_samples() -> str:
    for cand in (
        os.path.join(os.getcwd(), "src", "tests", "samples"),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "src", "tests", "samples"),
    ):
        if os.path.isdir(cand):
            return cand
    return ""


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    t0 = time.time()
    # 1. 模块加载 + QApplication（offscreen）
    try:
        from PySide6.QtGui import QFontDatabase
        from PySide6.QtWidgets import QApplication
        from pdfsim.loader import PDFLoader, PDFLoadError, PDFPasswordError
        from pdfsim.models import PageMark, RotationOverride
        from pdfsim.output import PDFOutput
        from pdfsim.renderer import PDFRenderer
        app = QApplication.instance() or QApplication([])
        check("模块加载 + QApplication", True, "pdfsim+PySide6+pymupdf+pikepdf 收集完整")
    except Exception as e:  # noqa
        check("模块加载 + QApplication", False, repr(e))
        _finish()
        return 1

    # 10. 中文界面：字体加载 + 主窗口标题
    ok_font = False
    for fp in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simsun.ttc"):
        try:
            if QFontDatabase.addApplicationFont(fp) != -1:
                ok_font = True
        except Exception:  # noqa
            pass
    try:
        from pdfsim.ui.main_window import MainWindow
        win = MainWindow()
        title = win.windowTitle()
        check("中文界面", ok_font and "PDFSim" in title,
              f"字体加载={'OK' if ok_font else 'FAIL'}; 标题={title!r}")
    except Exception as e:  # noqa
        check("中文界面", False, repr(e))

    samples = find_samples()
    if not samples:
        check("样本定位", False, "未找到 src/tests/samples")
        _finish()
        return 1
    tmp = tempfile.mkdtemp(prefix="pdfsim_selftest_")

    # 2. 打开 PDF + 书签
    try:
        src = os.path.join(samples, "sample_a4_portrait.pdf")
        orig_hash = sha256(src)
        loader = PDFLoader()
        res = loader.open(src, password="")
        pages = res.pages
        check("打开 PDF（含书签）", len(pages) == 6 and len(res.bookmarks) >= 3,
              f"页数={len(pages)} 书签={len(res.bookmarks)}")
    except Exception as e:  # noqa
        check("打开 PDF（含书签）", False, repr(e))

    # 3. 标记 + 物理顺序
    from pdfsim.engine import build_process_plan
    from pdfsim.config import ConfigManager
    from pdfsim.models import DocumentConfig
    try:
        p0 = pages[0]
        p0.marks.add(PageMark.COVER)
        p0.marks.add(PageMark.FRONT)
        p4 = pages[4]
        p4.marks.add(PageMark.SIGNATURE)
        p4.marks.add(PageMark.FRONT)
        plan = build_process_plan(
            pages, DocumentConfig(),
            text_width_calculator=PDFRenderer().get_text_width,
        )
        blanks = [p for p in plan.pages if p.is_blank]
        check("标记封面/签字→联动+物理顺序", len(plan.pages) == 9 and len(blanks) == 3,
              f"物理页={len(plan.pages)} 空白={len(blanks)}")
    except Exception as e:  # noqa
        check("标记封面/签字→联动+物理顺序", False, repr(e))

    # 4. 旋转页
    try:
        dsrc = os.path.join(samples, "sample_direction_markers.pdf")
        dres = loader.open(dsrc, password="")
        from pdfsim.engine import plan_rotation, final_rotation
        det, _ = plan_rotation(dres.pages[0], None)
        final = final_rotation(dres.pages[0])
        check("旋转页自动检测", det in (90, 270) and final in (90, 270),
              f"detect={det} final={final}")
    except Exception as e:  # noqa
        check("旋转页自动检测", False, repr(e))

    # 5+6. 输出 + 原文件不变
    try:
        out_path = os.path.join(tmp, "out.pdf")
        # 直接复用 output 模块：复制源到 tmp 再输出（避免污染 samples）
        tmp_src = os.path.join(tmp, "in.pdf")
        shutil.copy(src, tmp_src)
        cfg = DocumentConfig()
        cfg.output_dir = tmp
        cfg.output_suffix = "（打印装订）"
        out_res = PDFOutput().output(tmp_src, plan, cfg)
        out_file = os.path.join(tmp, "in（打印装订）.pdf")
        ok_out = os.path.exists(out_file)
        pages_out = 0
        if ok_out:
            import pymupdf
            with pymupdf.open(out_file) as d:
                pages_out = d.page_count
        unchanged = sha256(src) == orig_hash
        check("输出+原文件不变", ok_out and pages_out == 9 and unchanged,
              f"输出页数={pages_out} 原文件SHA一致={unchanged}")
    except Exception as e:  # noqa
        check("输出+原文件不变", False, repr(e))

    # 7. 加密 PDF
    try:
        enc = os.path.join(samples, "sample_encrypted.pdf")
        enc_hash = sha256(enc)
        try:
            loader.open(enc, password="")
            pw_fail = False
        except PDFPasswordError:
            pw_fail = True
        ok_decrypt = False
        epages = None
        try:
            eres = loader.open(enc, password="testpass")
            epages = eres.pages
            ok_decrypt = len(epages) == 1
        except Exception:  # noqa
            pass
        check("加密 PDF", pw_fail and ok_decrypt and sha256(enc) == enc_hash,
              f"无密码拒绝={pw_fail} 正确密码页数={len(epages) if epages else 'N/A'}")
    except Exception as e:  # noqa
        check("加密 PDF", False, repr(e))

    # 8. 损坏 PDF
    try:
        bad = os.path.join(samples, "sample_corrupted.pdf")
        bad_hash = sha256(bad)
        try:
            loader.open(bad, password="")
            bad_ok = False
        except PDFLoadError:
            bad_ok = True
        except Exception:
            bad_ok = False
        check("损坏 PDF", bad_ok and sha256(bad) == bad_hash,
              f"抛 PDFLoadError={bad_ok}")
    except Exception as e:  # noqa
        check("损坏 PDF", False, repr(e))

    # 9. 配置保存/恢复
    try:
        cm = ConfigManager()
        cfg_pdf = os.path.join(tmp, "cfgtest.pdf")
        open(cfg_pdf, "wb").close()  # 仅作为配置关联的“源文件”占位
        cfg = DocumentConfig()
        cfg.start_page_number = 3
        cfg.save_page_configs = None  # 占位（实际由 config 对象承载）
        cm.save_config(cfg_pdf, cfg)
        loaded = cm.load_config(cfg_pdf)
        check("配置保存/恢复", loaded.start_page_number == 3,
              f"reload start={loaded.start_page_number}")
    except Exception as e:  # noqa
        check("配置保存/恢复", False, repr(e))

    shutil.rmtree(tmp, ignore_errors=True)
    elapsed = time.time() - t0
    _finish(elapsed=elapsed)
    return 0 if all(r["ok"] for r in RESULTS) else 1


def _finish(elapsed: float = 0.0) -> None:
    summary = {
        "total": len(RESULTS),
        "passed": sum(1 for r in RESULTS if r["ok"]),
        "failed": sum(1 for r in RESULTS if not r["ok"]),
        "elapsed_s": round(elapsed, 2),
        "items": RESULTS,
    }
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "selftest_result.json")
    try:
        with open(out, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
    except Exception:  # noqa
        pass
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())
