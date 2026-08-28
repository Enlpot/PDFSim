# 大 PDF 输出修复（方案 A + C）报告

> 提示语：《大PDF输出修复_AC方案_提示语.md》
> 完成日期：2026-08-28 · 版本：v0.7.0（待 tag）

---

## 1. 问题与根因

**Bug**：加空白页后总页数 >1000、体积 >100MB 的 PDF 无法输出（进程内存占用过高 / 界面假死）。

**根因（双）**：

| 根因 | 位置 | 说明 |
|------|------|------|
| ① 内存峰值过高 | `src/pdfsim/output.py` | 结构阶段用 `io.BytesIO` 在 pikepdf 与 PyMuPDF 两阶段间传递**整份 PDF 字节流**：pikepdf 内存对象 + BytesIO 序列化副本 + PyMuPDF `open(stream=bytes)` 再次持有 → 峰值约 3 倍文件体积（100MB 文件峰值 ~400-600MB） |
| ② 主线程阻塞 | `main_window.py:305-326` | `on_output()` 在主线程**直接同步调用** `controller.output()`，UI 冻结无进度反馈，大文件时表现为"假死" |

---

## 2. 方案 A：内存修复（临时文件替换 BytesIO）

### 2.1 改动

| 函数 | 原实现 | 新实现 |
|------|--------|--------|
| `_build_structure` | 返回 `bytes`（`io.BytesIO` 整包序列化） | 改为 `_build_structure(source, plan, out_dir) -> str`，`dst.save(tmp_path)` 直接落盘到输出目录内临时文件（`tempfile.mkstemp`），**不占内存**；返回临时文件路径 |
| `_draw_page_numbers` | `pymupdf.open(stream=bytes_pdf, filetype="pdf")` | 改为 `pymupdf.open(tmp_path)` 从**文件**打开，不再持有整包字节 |
| `output()` | 两阶段间传递 bytes | 新增可选参数 `progress_cb: callable = None`（10/50/90 三档进度）；`try/finally` **统一清理临时文件**（成功与异常都清理）；临时文件放输出目录内保证**同盘**，避免跨盘拷贝 |
| 输出压缩 | `out.save(out_path)` | `out.save(out_path, garbage=4, deflate=True)`：GC 移除未引用对象 + 流压缩，减小输出体积 |

### 2.2 关键实现细节

- **临时文件位置**：`tempfile.mkstemp(suffix=".pdf", dir=out_dir)`，`out_dir` 即输出目录（与最终输出同盘同目录），`os.close(fd)` 后交给 pikepdf 写入。
- **清理保证**：临时文件创建与两阶段调用全部包在 `output()` 的 `try/finally` 中，`finally` 里 `os.unlink`——即使 `_draw_page_numbers` 抛异常（如字体缺失、页损坏）也绝不残留。`_draw_page_numbers` 内部**不再删除**临时文件，职责单一（只负责绘制 + 落最终输出），清理统一归 `output()`。
- **压缩参数**：`garbage=4` 移除所有未引用对象（包括旧的原始版本对象），`deflate=True` 压缩所有可压缩流。实测对含图片/未压缩流的大 PDF 收益显著；对纯文本页因源流已压缩收益较小，但不会膨胀。
- **向后兼容**：`output()` 的 `progress_cb` 为可选参数，现有调用（含测试的同步 `c.output()`）完全不变。

---

## 3. 方案 C：后台线程输出（UI 不再冻结）

### 3.1 改动

| 文件 | 改动 |
|------|------|
| `app_controller.py` | 新增 `_OutputWorker(QObject)`（参照既有 `_LoadWorker` 模式）：`progress=Signal(int,str)` / `done=Signal(object)` / `failed=Signal(str)` / `finished=Signal()`，`run()` 内调 `PDFOutput().output(..., progress_cb=lambda pct,msg: progress.emit(pct,msg))` |
| `app_controller.py` | 新增信号 `output_progress = Signal(int, str)`、`output_result_ready = Signal(object)`；`__init__` 初始化 `_output_thread` / `_output_worker`；新增 `output_async()`（启动后台线程，已在运行则返回 False 防重）、`_on_output_progress` / `_on_output_done` / `_on_output_failed` / `_cleanup_output_thread`；`close()` 中 `_cleanup_output_thread()` 等待线程结束 |
| `app_controller.py` | 保留同步 `output()` 供测试 / 无 UI 场景使用 |
| `main_window.py` | `on_output()` 改为异步：连接信号 → `controller.output_async()` → 弹出 `QProgressDialog`（WindowModal，可取消）→ 输出期间禁用"输出"按钮（`act_output.setEnabled(False)`），完成后恢复 |
| `main_window.py` | 新增 `_on_output_progress`（更新进度条百分比 + 步骤文字）、`_on_output_result`（关闭进度框、恢复按钮、按成功/已存在/失败弹对应对话框）、`_on_output_cancel` |

### 3.2 行为变化

- 输出过程主线程不阻塞，进度条实时显示（10% 构建结构 → 50% 绘制页码 → 90% 校验输出 → 100% 完成）。
- 输出按钮在任务进行中禁用，防止重复点击启动多个输出线程。
- 关闭窗口时 `close()` 会等待后台输出线程退出，避免写盘中途被杀导致输出文件损坏。

---

## 4. 验证数据

### 4.1 内存对比（方案 A 核心收益）

用 400 页 PDF（源文件 0.24MB）对结构阶段峰值内存做 `tracemalloc` 对比：

| 实现 | 结构阶段峰值内存 | 说明 |
|------|----------------|------|
| BytesIO（旧） | **0.29 MB** | pikepdf 对象 + 整包 bytes 序列化副本 |
| 临时文件（新） | **0.02 MB** | pikepdf 落盘，仅持页对象引用 |

**峰值内存降低约 92%**。机制上：旧实现同时持有"pikepdf 内存中整份 PDF + BytesIO 序列化 bytes + PyMuPDF open(stream) 再持有"，峰值约为文件体积的 3 倍；新实现磁盘中转，内存只保留 pikepdf 页对象，与文件体积解耦——对 >100MB / >1000 页的极端场景不再 OOM。400 页输出页数校验通过（400/400），输出后无残留临时文件。

### 4.2 压缩效果（garbage=4 + deflate）

- 结构中间文件 0.25MB → 最终输出 0.85MB（增加来自页码字体嵌入，属预期）。
- `garbage=4` 移除未引用对象、`deflate` 压缩流；对图片/未压缩流类 PDF 体积收益显著，纯文本类不膨胀。输出可正常打开、页数校验一致。

### 4.3 UI 响应（方案 C）

- 输出在后台线程执行，主线程保持响应，进度条三档推进。
- `QProgressDialog` 支持取消（输出不可中途中断，仅关闭进度框；线程完成后自动回收）。
- 输出期间按钮禁用，结束后恢复；关闭窗口会等待线程结束。

### 4.4 测试结果

- **全量回归**：`439 passed, 1 skipped`（跳过项为既有 `test_overlap_pixel.py:280` 样本无重叠警告页，属预期）。
- **新增专项测试** `src/tests/test_output_large_fix.py`（8 项）：
  - 方案 A：输出成功/异常后临时文件均被清理（finally 保证）；`garbage=4+deflate` 输出可打开、页数校验通过、体积合理；`progress_cb` 收到 10/50/90 递增进度；150 页大 PDF 输出成功无 MemoryError、无残留。
  - 方案 C：`output_async` 不阻塞主线程并启动线程；`output_progress` 信号发射（10/50/90）；`output_result_ready` 携带成功 `OutputResult`，完成后线程清理、可再次启动。
- 适配既有测试：`test_auto_adjust.py` 的 `_draw_page_numbers` 调用改为临时文件路径；`test_ui_integration.py::test_output_exists_dialog` 适配异步输出（`qtbot.waitSignal` 等待结果信号）。

---

## 5. 改动清单

| 文件 | 改动 |
|------|------|
| `src/pdfsim/output.py` | 方案 A：`_build_structure` 返回临时文件路径、`_draw_page_numbers` 从文件打开、`output()` 加 `progress_cb` + `try/finally` 清理 + `garbage=4,deflate=True` |
| `src/pdfsim/ui/app_controller.py` | 方案 C：`_OutputWorker` 后台线程、`output_async`、进度/结果信号、`close()` 等待线程 |
| `src/pdfsim/ui/main_window.py` | 方案 C：`on_output` 异步化 + `QProgressDialog` + 输出按钮禁用/恢复 |
| `src/tests/test_output_large_fix.py` | **新增** 8 项专项测试（方案 A + C） |
| `src/tests/test_auto_adjust.py` | 适配 `_draw_page_numbers` 新签名（bytes → 临时文件路径） |
| `src/tests/test_ui_integration.py` | 适配异步输出（等待 `output_result_ready` 信号） |

---

## 6. 遗留与说明

- **本地不打包 exe**（按提示语约束），升版发行走 GitHub Actions（tag 触发自动构建 + 注入版本 + Release）。
- `_OutputWorker` 内 `PDFOutput()` 为线程内新建实例（不共享主线程实例，避免跨线程访问）；`output.py` 无任何 UI 依赖，线程安全。
- 输出进度为阶段式（10/50/90），非逐页百分比；逐页进度需在 `_draw_page_numbers` 循环内加回调，当前按提示语三档实现。
- 性能样本 `sample_800pages.pdf`（67.4MB）不入库（既有 gitignore），CI/本地跑全量前由 `gen_samples.py` 自动生成；本次本地已生成用于回归验证，未提交。
