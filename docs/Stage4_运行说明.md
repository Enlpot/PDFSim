# PDFSim Stage 4 运行说明（集成测试）

> **项目**：PDFSim —— Windows 桌面单文件软件
> **阶段**：Stage 4 —— 集成测试
> **状态**：待指导者审查
> **日期**：2026-08-26

---

## 1. 如何运行集成测试

```powershell
cd D:\WinDevelop\PDFSim

# 全部测试（Stage 2/3/4，共 231 个）
python -m pytest src/tests/

# 仅 Stage 4 集成测试
python -m pytest src/tests/test_integration_t01_t08.py `
    src/tests/test_integration_t09_t16.py `
    src/tests/test_rotation_readability.py `
    src/tests/test_physical_order.py `
    src/tests/test_universal_checks.py `
    src/tests/test_stage3_concerns.py

# 覆盖率（可选）
python -m pytest src/tests/ --cov=pdfsim --cov-report=term
```

> UI 交互测试（T14/T16、Stage3 关注点 2/4/5）自动在 `QT_QPA_PLATFORM=offscreen` 下运行（conftest 已设置），无需真实显示器。依赖：`pytest-qt`、`PyMuPDF`、`pikepdf`、`Pillow`（安装方式见 Stage3 运行说明）。

---

## 2. 样本生成命令

样本已存在于 `src\tests\samples\`（13 个 PDF），由 `gen_samples.py` 生成，可重复执行：

```powershell
cd D:\WinDevelop\PDFSim
python src\tests\samples\gen_samples.py
```

- 全部样本可重复生成（不依赖外部文件）；
- **方向标记样本**（A3 纵向/横向、direction_markers）内嵌四角"顶/底/左/右"角标 + 中心水平箭头；
- 加密样本密码：`testpass`；
- 测试运行会自动清理 samples 目录的 `*.pagerconfig.json` 残留（配置防污染）。

### 2.1 样本与场景对照

| 样本 | 场景 |
|------|------|
| sample_a4_portrait.pdf | T01（含书签） |
| sample_no_bookmark.pdf | T02 |
| sample_a3_portrait.pdf | T03（A3 纵向 + 方向标记） |
| sample_a3_landscape.pdf | T04（A3 横向 + 方向标记） |
| sample_single.pdf | T05 / T15 |
| sample_odd_last.pdf | T06 / T14 |
| sample_encrypted.pdf | T07 |
| sample_corrupted.pdf | T08 |
| sample_200pages.pdf | T09（性能） |
| sample_with_pagenum.pdf | T10（重叠） |
| sample_no_count.pdf | T11 |
| sample_mixed.pdf | T12 / T13（A3 级联） |
| sample_direction_markers.pdf | T16 / 旋转可读性 |

---

## 3. 性能测试方法

性能指标在 `TestT09_Performance` 中测量并打印 `PERF {...}`（也可用 pytest -s 查看）：

```powershell
python -m pytest "src/tests/test_integration_t09_t16.py::TestT09_Performance" -s
```

| 指标 | 测量方法 |
|------|---------|
| 打开+首屏 | `PDFLoader.open` + 全页文本提取耗时（`time.perf_counter`） |
| 旋转检测 | `build_process_plan` 全程耗时 |
| 翻页响应 | 连续 10 次 plan 查询平均耗时 |
| 输出耗时 | `PDFOutput.output` 全程耗时 |
| 内存峰值 | Windows `GetProcessMemoryInfo.PeakWorkingSetSize`（ctypes，见报告第 8 节实测值） |

> 性能不达标不阻塞 Stage 4（测试矩阵约定）；当前 5 项指标全部达标。

---

## 4. 新增测试文件说明

```
src\tests\
  ├── _stage4_helpers.py            # 共享辅助（Pipeline / 期望表断言 / 方向标记检查）
  ├── test_integration_t01_t08.py   # T01–T08 端到端
  ├── test_integration_t09_t16.py   # T09–T16 端到端 + 性能指标（PERF）
  ├── test_rotation_readability.py  # 旋转可读性专项（渲染 + 方向标记实证）
  ├── test_physical_order.py        # 物理顺序专项（期望表 + 级联）
  ├── test_universal_checks.py      # 跨场景通用检查（6 项 × 16 场景）
  └── test_stage3_concerns.py       # Stage 3 审查报告 5 个关注点
```

---

## 5. 已知事项

- **B4-01 bug 已修复**：重叠检测 `_display_anchor` 未计入 CUSTOM 偏移 → 指导者审查批准后已修复（详见 Stage4 测试报告第 9 节）。修复仅改动 `src\pdfsim\engine.py` 的 `_display_anchor` 一个函数；新增 1 个回归测试（`test_engine.py::TestBuildProcessPlan::test_custom_offset_clears_overlap_warning`）。
- 本阶段除 B4-01 修复外，未修改任何 Stage 2/3 代码；新增 6 个集成测试文件 + 1 个辅助文件 + 1 个回归测试。
- 测试可重复执行（231 用例全通过，无外部依赖残留）。

---

*—— Stage 4 运行说明结束 ——*
