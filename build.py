# -*- coding: utf-8 -*-
"""PDFSim 打包脚本。用法：python build.py

打包为 Windows 单文件无控制台 EXE（PyInstaller --onefile --windowed）。
产物：dist\\PDFSim.exe

瘦身说明（功能不变的前提下）：
- 不采用 --collect-all PySide6（会把 Qt 全家桶全部打入：Qt6WebEngineCore.dll
  194MB、QML/多媒体/翻译/资源等），仅保留应用实际使用的 QtCore/QtGui/QtWidgets，
  其余 PySide6.Qt* 模块用 --exclude-module 排除。
"""
import os
import shutil
import subprocess
import sys


# 应用未使用的 PySide6 模块（排除后体积大幅下降）
_EXCLUDE_QT_MODULES = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngine",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQuickControls2",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
    "PySide6.QtDesigner", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic", "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras",
    "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtNetwork", "PySide6.QtNetworkAuth",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtSvg", "PySide6.QtSvgWidgets",
    "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtPrintSupport",
    "PySide6.QtXml", "PySide6.QtXmlPatterns", "PySide6.QtDBus",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning",
    "PySide6.QtLocation", "PySide6.QtSensors", "PySide6.QtSerialPort",
    "PySide6.QtWebSockets", "PySide6.QtWebChannel", "PySide6.QtStateMachine",
    "PySide6.QtScxml", "PySide6.QtRemoteObjects", "PySide6.QtTextToSpeech",
    "PySide6.QtUiTools", "PySide6.QtHelp",
]


def build_cmd(script: str, name: str, extra: list[str] | None = None) -> list[str]:
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--clean",
        "--noconfirm",
        "--onefile",
        "--windowed",
        "--name", name,
        "--paths", "src",
        "--add-data", "src\\pdfsim;pdfsim",
        # PySide6 瘦身：不 collect-all，排除未使用的 Qt 模块
        "--collect-all", "pikepdf",
        "--collect-all", "pymupdf",
        "--hidden-import", "PIL",
    ]
    for m in _EXCLUDE_QT_MODULES:
        cmd += ["--exclude-module", m]
    if extra:
        cmd += extra
    cmd.append(script)
    return cmd


def main() -> None:
    # 清理上一次打包产物，保证可重复执行
    for d in ("build", "dist"):
        if os.path.isdir(d):
            shutil.rmtree(d)
            print(f"[build] 已清理 {d}\\")

    cmd = build_cmd("src\\main.py", "PDFSim")
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
