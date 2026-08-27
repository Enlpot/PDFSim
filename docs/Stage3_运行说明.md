# PDFSim Stage 3 运行说明（UI 实现）

> **项目**：PDFSim —— Windows 桌面单文件软件
> **阶段**：Stage 3 —— UI 实现
> **状态**：待指导者审查
> **日期**：2026-08-26

---

## 1. 环境依赖

| 依赖 | 版本（本机实测） | 用途 |
|------|------------------|------|
| Python | 3.13.13 | 运行环境 |
| PySide6 | 6.11.2 | Qt UI 框架 |
| pytest-qt | 4.5.0 | UI 自动化测试 |
| PyMuPDF（pymupdf） | 1.28.2 | 渲染 / 文字提取 / 输出 |
| pikepdf | 10.12.0 | 结构重组 / 加密处理 |
| Pillow（PIL） | 已装 | 旋转预览图像 |
| pytest / pytest-cov | 9.1.1 / 7.1.0 | 测试与覆盖率 |

### 1.1 安装

```powershell
python -m pip install PySide6 pytest-qt pymupdf pikepdf Pillow pytest pytest-cov
```

> **本机注意事项（Windows Long Path 限制）**：
> 本机的 Python 安装在深层路径（`C:\Users\bendi\AppData\Local\Doubao\...\python`），且系统未开启
> LongPathsEnabled（`HKLM\SYSTEM\CurrentControlSet\Control\FileSystem\LongPathsEnabled = 0`）。
> PySide6 包内嵌套路径极深，直接 `pip install` 到默认 site-packages 会因路径超 260 字符失败。
> **解决**：安装到短路径目录并让解释器自动加载——
> ```powershell
> python -m pip install --target C:\pdfsim_pylibs PySide6 pytest-qt
> # 在 site-packages 下写 .pth 引用，使默认解释器可直接 import
> Set-Content "$(python -c "import sysconfig;print(sysconfig.get_paths()['purelib'])")" `
>     -Value "C:\pdfsim_pylibs"
> ```
> 若系统已开启长路径支持（或 Python 安装路径较短），直接常规安装即可，无需此步骤。

---

## 2. 如何启动 UI

```powershell
cd D:\WinDevelop\PDFSim
python src\main.py
```

启动后：
1. 点击工具栏"打开"（或 文件 → 打开 PDF…，Ctrl+O）选择 PDF 文件；
2. 打开后左侧缩略图、右侧书视图、底部配置面板自动加载并按默认规则排好物理顺序；
3. 在缩略图/书视图翻页选择页面，在底部面板调整标签、页码位置、旋转方向、样式；
4. 点击"输出"生成 `原文件名（打印装订）.pdf`（不覆盖已有文件，不修改原文件）。

### 2.1 无头（offscreen）验证

测试环境若无显示器，可用 offscreen 平台验证界面逻辑（截图存档用此模式）：

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
python src\main.py   # 或用测试驱动脚本
```

---

## 3. 如何运行 UI 测试

```powershell
cd D:\WinDevelop\PDFSim

# 全部测试（含 Stage 2 + Stage 3 UI）
python -m pytest src/tests/

# 仅 UI 测试
python -m pytest src/tests/test_ui_main_window.py src/tests/test_ui_book_view.py `
    src/tests/test_ui_config_panel.py src/tests/test_ui_integration.py src/tests/test_ui_dialogs.py

# 覆盖率（UI ≥ 80% 验收）
python -m pytest src/tests/ --cov=pdfsim --cov-report=term
```

> UI 测试自动在 `QT_QPA_PLATFORM=offscreen` 下运行（`conftest.py` 已设置），无需真实显示器。
> 需要中文字体渲染时，`conftest.py` 的 `ui_fonts` fixture 会加载系统 `msyh.ttc`。

---

## 4. 截图目录说明

手动测试 8 项截图存放于 **`D:\WinDevelop\PDFSim\docs\screenshots\`**：

| 文件 | 内容 |
|------|------|
| `mt01_open_a4_portrait.png` | 打开 A4 纵向多页（含书签）主界面 |
| `mt02_cover_linkage.png` | 标记封面 → 联动 FRONT + 背面空白插入 |
| `mt03_a3_front_disabled.png` | A3 页"从正面开始"置灰 + 背面空白 |
| `mt04_rotation_badge.png` | A4 横向页旋转角标（自动检测顺时针 90°） |
| `mt04b_rotation_switch.png` | 旋转方向切换后的效果 |
| `mt05_output_success.png` | 输出成功弹窗 |
| `mt06_config_restore.png` | 关闭重开后配置恢复 |
| `mt07_encrypted_password.png` | 加密 PDF 密码弹窗 |
| `mt08_corrupted.png` | 损坏 PDF 错误弹窗 |

---

## 5. 项目结构（Stage 3 新增）

```
D:\WinDevelop\PDFSim\src\
  ├── main.py                     # 程序入口
  └── pdfsim\
      ├── models.py / config.py / engine.py / loader.py / renderer.py / output.py   # Stage 2（未修改）
      └── ui\
          ├── __init__.py
          ├── styles.py           # 样式常量（颜色/间距/字体/尺寸）
          ├── app_controller.py   # 应用控制器（协调核心模块）
          ├── main_window.py      # 主窗口（三段式布局 + 菜单/工具栏）
          ├── book_view.py        # 书视图（状态机 + 翻页 + 渲染）
          ├── thumbnail_panel.py  # 缩略图列表（徽标/页码预览/空白页）
          ├── config_panel.py     # 页面配置面板（6 子区）
          ├── global_settings.py  # 全局设置对话框
          └── dialogs.py          # 异常弹窗 / 输出确认
```

---

## 6. 已知说明

- **核心模块未修改**：Stage 3 未改动 Stage 2 的 6 个核心模块；UI 层仅通过控制器调用其公开接口。
- **性能**：大文档（200 页）打开/重排时同步渲染（旋转检测需逐页提取文字）。提示语性能注意事项中的后台线程优化留作后续增强；当前 `_ensure_text_data` 已缓存文本数据避免重复提取，缩略图渲染结果按页缓存于 item 内。
- **输出进度**：输出为同步耗时操作，期间禁用输出按钮并显示忙光标（未启用后台 QThread，属已知限制，功能正确）。

---

*—— Stage 3 运行说明结束 ——*
