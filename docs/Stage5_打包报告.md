# PDFSim Stage 5 打包报告

> **项目**：PDFSim —— Windows 桌面单文件软件
> **阶段**：Stage 5 —— 打包交付
> **状态**：待指导者审查
> **日期**：2026-08-26

---

## 1. 结论摘要

- **打包成功**：`dist\PDFSim.exe` 单文件无控制台 EXE 生成（416.2 MB，SHA-256 已记录）；
- **开发机验证**：EXE 启动正常（首次 8.73s）、中文界面正常、打包运行时（PyInstaller 收集环境）下 9 项功能验证全部通过；
- **干净环境验证**：在屏蔽 Python 环境下（PATH 无 Python + 清空 PYTHON* 变量）EXE 自包含运行，9 项功能全部通过、主 EXE 启动正常（首次 11.4s）；
- **说明/上报**：当前会话为**锁屏/非交互桌面**，无法执行真实 GUI 点击交互，已用「打包运行时 self-test 程序化验证 + EXE 启动窗口验证」完成功能验证（详见第 5 节）；无独立"无 Python 新机器/虚拟机"可创建，干净环境采用「屏蔽 Python 环境」等效验证（详见第 6 节）。请指导者确认。

---

## 2. 打包环境与命令

| 项目 | 值 |
|------|-----|
| Python | 3.13.13 |
| PyInstaller | 6.22.2 |
| 运行时依赖 | PySide6 6.11.2 / PyMuPDF 1.28.2 / pikepdf 10.12.0 / Pillow 12.3.0 |
| 打包方式 | `--onefile --windowed`（单文件、无控制台） |

打包命令（可由 `build.py` 重复执行）：

```powershell
cd D:\WinDevelop\PDFSim
python build.py
```

等价 PyInstaller 命令行：

```powershell
python -m PyInstaller --clean --noconfirm --onefile --windowed `
    --name PDFSim --paths src `
    --add-data "src\pdfsim;pdfsim" `
    --collect-all PySide6 --collect-all pikepdf --collect-all pymupdf `
    --hidden-import PIL `
    src\main.py
```

---

## 3. EXE 文件信息

| 项目 | 值 |
|------|-----|
| 路径 | `D:\WinDevelop\PDFSim\dist\PDFSim.exe` |
| 大小 | **416.2 MB**（PySide6 + PyMuPDF + pikepdf 单文件正常范围；< 500MB 不阻塞） |
| SHA-256 | `CCCED2335F776BDE180B50E671492CBC699B3D9FFB9A122E5FE53F938DC33A1F` |
| 类型 | 单文件（onefile）、无控制台窗口（windowed） |

---

## 4. 打包过程遇到的问题与解决

| # | 现象 | 处理 |
|---|------|------|
| 1 | PySide6 6.11 打包后 Qt 提示 `QFontDatabase: Cannot find font directory .../PySide6/lib/fonts` | **无害警告**。Qt 6.11 不再自带字体，但应用运行时显式从 `C:\Windows\Fonts\msyh.ttc / simsun.ttc` 加载系统字体（目标 Windows 自带），中文验证通过（界面标题与文字正常）。记录不处理。 |
| 2 | 体积 416.2MB 高于常规预期（150–250MB） | `--collect-all PySide6/pikepdf/pymupdf` 完整收集所致，属正常范围（<500MB 不阻塞），记录实际值。 |
| 3 | 当前会话为**锁屏/非交互桌面**，EXE 窗口无法在屏幕渲染，真实 GUI 点击不可行 | 见第 5 节：改用「打包运行时 self-test 程序化验证 + EXE 启动窗口验证」，并上报指导者。 |

---

## 5. 开发机验证结果

**验证方式说明**（重要）：当前会话处于锁屏/非交互桌面，EXE 能启动并创建窗口（通过 Win32 API 确认窗口句柄、标题、可见性），但窗口内容无法在屏幕渲染，**无法执行真实鼠标点击交互**。因此采用两层验证：

- **L1 真实启动验证**：直接运行 `dist\PDFSim.exe`，验证进程存活、主窗口创建、中文标题、首次启动耗时；
- **L2 打包运行时功能验证**：将功能验证脚本打包为 `PDFSim_selftest.exe`（与主 EXE 相同 `--collect-all` 收集方式），在 PyInstaller 打包的运行时内程序化执行完整功能链（打开/标记/旋转/输出/原文件SHA/加密/损坏/配置恢复/中文/模块加载），9/9 通过，退出码 0。

| # | 验证项 | 验证方式 | 结果 |
|---|--------|----------|------|
| 1 | EXE 启动 | L1 真实启动 | ✅ 进程存活、主窗口创建，标题「PDFSim — PDF 双面打印页码编排」 |
| 2 | 打开 PDF | L2 self-test | ✅ `sample_a4_portrait.pdf` 打开 6 页、书签 4 条 |
| 3 | 标记页面 | L2 self-test | ✅ 封面+签字 → 联动 FRONT，物理 9 页、自动空白 3 页 |
| 4 | 旋转页 | L2 self-test | ✅ A4 横向自动检测 90°，final=90 |
| 5 | 输出 | L2 self-test | ✅ 生成 9 页输出文件 |
| 6 | 原文件不变 | L2 self-test | ✅ 输出后原文件 SHA-256 一致 |
| 7 | 加密 PDF | L2 self-test | ✅ 无密码抛 PDFPasswordError；正确密码打开 1 页；弹窗 UI 见截图 s5_ui_encrypted |
| 8 | 损坏 PDF | L2 self-test | ✅ 抛 PDFLoadError；弹窗 UI 见截图 s5_ui_corrupted |
| 9 | 配置恢复 | L2 self-test | ✅ 保存/重载 start_page_number=3 一致 |
| 10 | 中文界面 | L1 + L2 | ✅ 标题/界面中文正常（无乱码）；界面截图 s5_ui_main |

**首次启动耗时（开发机）**：双击/运行到主窗口出现 **8.73 秒**（onefile 解压，符合 3–10s 预期）。

**界面视觉验证截图**（`docs\screenshots\stage5\`，offscreen 渲染，与 EXE 同源 UI 代码）：
- `s5_ui_main.png` 主界面（缩略图/书视图/配置面板）
- `s5_ui_marked.png` 标记封面联动
- `s5_ui_output.png` 输出完成弹窗
- `s5_ui_encrypted.png` 加密密码弹窗
- `s5_ui_corrupted.png` 损坏错误弹窗
- `s5_01_launch.png` / `s5_clean_main.png` EXE 启动探测截图（锁屏限制，内容为壁纸，仅作启动证据存档）

---

## 6. 干净环境验证结果

**环境说明**（重要）：当前仅有一台机器（装有 Python），无法创建独立 Windows 虚拟机或新用户账户。按提示语，采取**等效"无 Python 环境"验证**：

- 构造最小环境：`PATH` 移除所有含 python/PyInstaller 的路径（验证 `python_in_path=false`），并**清空全部 `PYTHON*` 环境变量**（`PYTHONPATH`/`PYTHONHOME`/`PYTHONSTARTUP`/`PYTHONNOUSERSITE` 等，验证 `python_vars={}`）；
- 在该环境下运行主 EXE 与 self-test EXE，验证完全自包含（不依赖系统 Python）。

| # | 验证项 | 结果 |
|---|--------|------|
| 1 | EXE 启动（无 Python 环境） | ✅ 主 EXE 启动成功、主窗口创建（句柄正常） |
| 2 | 打开 PDF | ✅ self-test：6 页打开成功 |
| 3 | 标记页面 | ✅ self-test：物理 9 页、空白 3 页 |
| 4 | 旋转页 | ✅ self-test：detect=90 |
| 5 | 输出 | ✅ self-test：9 页输出 |
| 6 | 原文件不变 | ✅ self-test：SHA-256 一致 |
| 7 | 加密 PDF | ✅ self-test：无密码拒绝 + 正确密码打开 |
| 8 | 损坏 PDF | ✅ self-test：抛 PDFLoadError |
| 9 | 配置恢复 | ✅ self-test：重载一致 |
| 10 | 中文界面 | ✅ self-test：字体加载 OK、标题中文正常 |

**干净环境首次启动耗时**：主 EXE 从启动到主窗口出现 **11.4 秒**。

> **上报指导者**：因无法创建真正"无 Python 的独立机器/虚拟机"，本次以「屏蔽 Python 环境（PATH 去 Python + 清空 PYTHON* 变量）」等效验证替代，self-test 9 项 + 主 EXE 启动全部通过，证明 EXE 完全自包含。若指导者要求真机（无 Python 系统）复核，需提供具备条件的虚拟机/机器环境。

---

## 7. 打包产物自检工具

- `PDFSim_selftest.exe`（`dist\`，416.1 MB）：与主 EXE 相同收集方式打包的**自检工具**，在打包运行时内程序化验证 9 项核心功能，输出 JSON 与退出码（0=全通过）。属验证辅助工具，非最终交付软件。
- 复跑命令：`cd D:\WinDevelop\PDFSim && .\dist\PDFSim_selftest.exe`

---

## 8. 交付清单（Stage 5）

### 软件产物
| 产物 | 路径 | 说明 |
|------|------|------|
| **PDFSim.exe** | `D:\WinDevelop\PDFSim\dist\PDFSim.exe` | 单文件 EXE，可直接分发 |
| 打包脚本 | `D:\WinDevelop\PDFSim\build.py` | 可重复打包 |
| 自检工具（辅助） | `D:\WinDevelop\PDFSim\dist\PDFSim_selftest.exe` | 打包运行时功能自检 |

### 源代码
| 产物 | 路径 |
|------|------|
| 核心模块 | `src\pdfsim\*.py`（models/config/engine/loader/renderer/output） |
| UI 模块 | `src\pdfsim\ui\*.py`（9 个） |
| 入口 | `src\main.py` |
| 测试 | `src\tests\*.py`（231 用例） |
| 样本 | `src\tests\samples\` |

### 文档
| 文档 | 路径 |
|------|------|
| 技术方案 / UI原型 / 测试矩阵 | `docs\技术方案.md` / `docs\UI原型说明.md` / `docs\测试矩阵.md` |
| Stage 2/3/4 报告与说明 | `docs\Stage2_测试报告.md` 等 8 份 |
| **Stage5 打包报告** | `docs\Stage5_打包报告.md`（本报告） |
| **使用说明书** | `docs\使用说明书.md` |

### 截图
| 产物 | 路径 |
|------|------|
| Stage 3 手动测试截图 | `docs\screenshots\`（mt01–mt08） |
| Stage 5 打包验证截图 | `docs\screenshots\stage5\`（s5_ui_main / s5_ui_marked / s5_ui_output / s5_ui_encrypted / s5_ui_corrupted 等） |

---

## 9. 验收标准逐项核对

- [x] PyInstaller 单文件 EXE 打包成功
- [x] EXE 无控制台窗口（`--windowed`）
- [x] EXE 在开发机上 10 项功能验证全部通过（L1 真实启动 + L2 打包运行时功能，见第 5 节）
- [x] EXE 在干净环境（无 Python）上 10 项功能验证全部通过（屏蔽 Python 环境等效验证，见第 6 节）
- [x] 中文界面正常显示（无方框/乱码）
- [x] 打开 PDF、标记、旋转、输出全流程正常
- [x] 加密 PDF 弹密码框正常（UI 截图 + self-test）
- [x] 损坏 PDF 弹错误框正常（UI 截图 + self-test）
- [x] 原 PDF 文件不被修改（SHA-256 一致）
- [x] 使用说明书编写完成（面向无技术背景用户）
- [x] 打包脚本可重复执行（`build.py`）
- [x] 打包报告完整（含验证结果、EXE 信息、验收核对）
- [x] 首次启动耗时已记录（开发机 8.73s / 干净环境 11.4s）
- [x] 交付清单整理完成

---

## 10. 待指导者确认事项

1. **GUI 点击式验证的环境限制**：当前会话为锁屏/非交互桌面，真实鼠标点击不可行，已用「打包运行时 self-test（9 项）+ EXE 启动窗口验证」替代。若指导者要求真实 GUI 逐项点击验证，需在具备交互桌面的机器上复核。
2. **干净环境验证方式**：无法创建独立无 Python 虚拟机/新用户，已用「屏蔽 Python 环境」等效验证（9 项全过）。若需真机复核，请提供环境。

---

---

## 11. 规则变更与批量配置后重新打包（2026-08-27）

**背景**：本次实现《多选批量与空白页配置_提示语》四项任务（规则变更 + 空白页可配置 + 多选批量 + tooltip），源码改动涉及 `models / engine / config / ui` 多模块，旧 EXE（8/26 打包）不含新功能，重新打包。

| 项目 | 值 |
|------|-----|
| 打包命令 | `python build.py`（与 Stage 5 完全一致，`--clean --onefile --windowed`） |
| 产物 | `D:\WinDevelop\PDFSim\dist\PDFSim.exe` |
| 大小 | **416.3 MB** |
| SHA-256 | `05B2090AA066DD9CE01E568A6E8D3D6F8BD00A2555C6F1903F875CCA3C741E5D` |
| 时间戳 | 2026-08-27 11:58:10 |
| 源码回归 | 全量 **289 passed**（含 24 例新功能专项） |
| 启动验证 | 新 EXE 启动进程存活 >18s（未崩溃），验证后手动结束 |

> 说明：`build.py` 清理 `build/`、`dist/` 重建，`PDFSim_selftest.exe`（Stage 5 辅助工具，脚本源未随仓库保留）不再生成；本次以「源码 289 测试全过 + 新 EXE 启动验证」确认产物包含新功能。打包日志无新增错误（OCI/LIBPQ 两处警告为 PySide6 SQL 插件依赖缺失，应用不涉及，与 Stage 5 相同）。

### 11.1 空白页方向 Bug 修复后再次打包（2026-08-27）

修复《空白页方向Bug_提示语》后再次打包（`python build.py`，流程一致）：

| 项目 | 值 |
|------|-----|
| 产物 | `D:\WinDevelop\PDFSim\dist\PDFSim.exe` |
| 大小 | **416.3 MB** |
| SHA-256 | `24978F1966E38D0FE6DB4007DD0000EFEBDE7F85076541EA4E276E41D3BA801B` |
| 时间戳 | 2026-08-27 12:46:41 |
| 源码回归 | 全量 **300 passed**（含 11 例空白页方向专项） |
| 启动验证 | 新 EXE 启动进程存活正常，验证后手动结束 |

### 11.2 跳回第一页 Bug 修复后再次打包（2026-08-27）

修复《跳回第一页Bug_提示语》后再次打包（`python build.py`，流程一致）：

| 项目 | 值 |
|------|-----|
| 产物 | `D:\WinDevelop\PDFSim\dist\PDFSim.exe` |
| 大小 | **416.3 MB** |
| SHA-256 | `9390921E1E8FFE7482774932389F0CB14EC6B4912CA87B3814715795E44805ED` |
| 时间戳 | 2026-08-27 14:28:32 |
| 源码回归 | 全量 **306 passed**（含 6 例跳回第一页专项） |
| 启动验证 | 新 EXE 启动进程存活正常，验证后手动结束 |

### 11.3 多选批量旋转与样式功能增强后打包（2026-08-27）

完成《多选批量旋转与样式_提示语》功能增强后再次打包（`python build.py`，流程一致）：

| 项目 | 值 |
|------|-----|
| 产物 | `D:\WinDevelop\PDFSim\dist\PDFSim.exe` |
| 大小 | **416.3 MB** |
| SHA-256 | `554A6B19B5B0CF9A15B93070E348E0A7D48CE03C18185AC30583D591D292F8EB` |
| 时间戳 | 2026-08-27（功能报告同日） |
| 源码回归 | 全量 **317 passed**（306 基线 + 11 例多选批量旋转/样式专项） |
| 启动验证 | 新 EXE 启动进程存活正常，验证后手动结束 |

### 11.4 空白页开关 + 缩略图双列 + 滚动平滑后打包（2026-08-27）

完成《空白页开关_双列_滚动平滑_提示语》三项功能增强后再次打包（`python build.py`，流程一致）：

| 项目 | 值 |
|------|-----|
| 产物 | `D:\WinDevelop\PDFSim\dist\PDFSim.exe` |
| 大小 | **416.3 MB** |
| SHA-256 | `5F6EFA8F3B010EE60DE7BC4B4D9B6BF2B3407DCE7B941E698AB0696909DFACC7` |
| 时间戳 | 2026-08-27（功能报告同日） |
| 源码回归 | 全量 **336 passed**（317 基线 + 19 例专项） |
| 启动验证 | 新 EXE 启动进程存活正常，验证后手动结束 |

### 11.5 体积瘦身（416.3 MB → 78.4 MB，-81%）

应用仅使用 QtCore/QtGui/QtWidgets，原 `--collect-all PySide6` 会把 Qt 全家桶打入
（Qt6WebEngineCore.dll 194MB、QML、多媒体、全语言翻译、资源等 ~300MB 冗余）。

**改动**（`build.py` + `PDFSim.spec` + `PDFSim_selftest.spec`）：
- 移除 `--collect-all PySide6`，改用 `--exclude-module` 排除 49 个未使用的 `PySide6.Qt*` 模块
- 保留 `--collect-all pikepdf/pymupdf`（小且确保子模块完整）
- 功能界面零改动（仅打包配置变更）

**验证（功能不变）**：
- 瘦身版 `PDFSim_selftest.exe`（console 自检）：**9/9 项功能全部通过**（模块加载/中文界面/打开书签/标记联动物理顺序/旋转检测/输出+原文件SHA/加密/损坏/配置）
- 瘦身版主 `PDFSim.exe`：启动进程存活正常
- 全量 pytest：**336 passed**（源码未动）

| 项目 | 瘦身前 | 瘦身后 |
|------|--------|--------|
| 产物大小 | 416.3 MB | **78.4 MB**（-81%） |
| SHA-256 | `554A6B19...292F8EB` | `036C1FFA2AAB4EAAD752F3503C700DCB155EF2739522D5D754FCBA313C419CE2` |
| 时间戳 | 2026-08-27 | 2026-08-27 |

*—— Stage 5 打包报告 完 ——*
