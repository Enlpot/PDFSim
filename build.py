# -*- coding: utf-8 -*-
"""PDFSim 打包脚本。用法：python build.py

打包为 Windows 单文件无控制台 EXE（PyInstaller --onefile --windowed）。
产物：dist\\PDFSim.exe
"""
import os
import shutil
import subprocess
import sys


def main() -> None:
    # 清理上一次打包产物，保证可重复执行
    for d in ("build", "dist"):
        if os.path.isdir(d):
            shutil.rmtree(d)
            print(f"[build] 已清理 {d}\\")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--clean",
        "--noconfirm",
        "--onefile",
        "--windowed",
        "--name", "PDFSim",
        "--paths", "src",
        "--add-data", "src\\pdfsim;pdfsim",
        "--collect-all", "PySide6",
        "--collect-all", "pikepdf",
        "--collect-all", "pymupdf",
        "--hidden-import", "PIL",
        "src\\main.py",
    ]
    print("[build] 开始打包:", " ".join(cmd))
    subprocess.run(cmd, check=True)

    exe = os.path.join("dist", "PDFSim.exe")
    if os.path.isfile(exe):
        size_mb = os.path.getsize(exe) / 1024 / 1024
        print(f"[build] 完成：{exe}（{size_mb:.1f} MB）")
    else:
        raise SystemExit(f"[build] 失败：未找到 {exe}")


if __name__ == "__main__":
    main()
