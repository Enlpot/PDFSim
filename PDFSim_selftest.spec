# -*- mode: python ; coding: utf-8 -*-
# PDFSim 打包自检 spec（瘦身版，console 无头验证核心功能）。
# 与 PDFSim.spec 一致的瘦身策略：排除未使用的 Qt 模块。
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = ['PIL']
tmp_ret = collect_all('pikepdf')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pymupdf')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

_exclude_qt = [
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

a = Analysis(
    ['src/tests/verify_bundled.py'],
    pathex=['src'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=_exclude_qt,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='PDFSim_selftest',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
