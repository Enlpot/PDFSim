# PDFSim Stage 2 运行说明

> 依据：《Stage2_提示语.md》九（交付物 5）

---

## 1. 环境依赖与安装

| 依赖 | 版本（本机实测） | 用途 |
|------|----------------|------|
| Python | 3.13.13 | 运行环境 |
| pikepdf | 10.12.0 | 结构阶段（页面重组 / 旋转 / 加密处理） |
| PyMuPDF | 1.28.2（`import pymupdf`） | 渲染 / 文本提取 / 页码绘制 |
| pytest | 9.1.1 | 测试框架 |
| pytest-cov | 7.1.0 | 覆盖率 |
| PySide6 | 未安装（Stage 3 需要时装） | UI（本阶段不实现） |

安装命令（`requirements.txt`）：

```
python -m pip install -r requirements.txt
```

> 注意：本机裸 `pip` 可执行文件异常退出（code -1），一律使用 `python -m pip`。

---

## 2. 项目结构

```
D:\WinDevelop\PDFSim\
├── docs\
│   ├── 技术方案.md              # Stage 1：冻结技术方案 v1.1
│   ├── UI原型说明.md / 测试矩阵.md / Stage1_修改说明.md
│   ├── Stage2_验证报告.md       # 前置验证 1/2 结论 + 检测映射修正
│   ├── Stage2_测试报告.md       # 本阶段测试与覆盖率报告
│   └── Stage2_运行说明.md       # 本文件
├── src\
│   ├── pdfsim\                  # 源码包
│   │   ├── __init__.py          # __version__="0.1.0"
│   │   ├── models.py            # 数据结构（PageInfo/ProcessedPage/...）
│   │   ├── config.py            # 配置读写（全局 + 页面级）
│   │   ├── engine.py            # 5 大算法 + build_process_plan（纯计算）
│   │   ├── loader.py            # PDF 加载（加密/损坏/书签/尺寸）
│   │   ├── renderer.py          # 渲染/文本块/文字宽度（只读）
│   │   └── output.py            # PDF 输出（结构+内容+校验）
│   └── tests\
│       ├── conftest.py          # fixtures（samples_dir 等）
│       ├── test_models.py / test_config.py / test_engine.py
│       ├── test_loader.py / test_renderer.py / test_output.py
│       ├── test_integration.py  # 端到端集成测试
│       └── samples\
│           ├── gen_samples.py   # 样本生成脚本（13 个样本）
│           └── sample_*.pdf     # 生成的测试样本
├── pyproject.toml               # 项目配置（src 布局，pytest testpaths）
├── requirements.txt
└── _verify\                     # 验证过程临时目录（非交付物，可清理）
```

---

## 3. 生成测试样本

```
python src/tests/samples/gen_samples.py
```

- 输出到 `src\tests\samples\`，生成 13 个样本（可重复执行，覆盖式重写）。
- 样本清单与用途见《Stage2_提示语.md》六：

| 样本 | 用途 |
|------|------|
| sample_a4_portrait.pdf | 基础（多页 + 书签：封面/目录/正文/签字） |
| sample_no_bookmark.pdf | 无书签 |
| sample_a3_portrait.pdf | A3 纵向旋转（四角方向标记 + 中心箭头） |
| sample_a3_landscape.pdf | A3 横向 |
| sample_mixed.pdf | A4 + A3 混合 |
| sample_single.pdf | 单页 |
| sample_odd_last.pdf | 末页奇数 |
| sample_encrypted.pdf | 加密（用户密码 testpass） |
| sample_corrupted.pdf | 损坏（%PDF 头 + 垃圾体，触发 PdfError） |
| sample_200pages.pdf | 性能 |
| sample_with_pagenum.pdf | 重叠检测（右下角已有页码） |
| sample_no_count.pdf | 不占序号（页面标题供关键词识别） |
| sample_direction_markers.pdf | 旋转验证（A4 横 + A3 纵方向标记） |

---

## 4. 运行测试

全部测试（含覆盖率）：

```
python -m pytest src/tests/ --cov=pdfsim --cov-report=term
```

仅单元测试：

```
python -m pytest src/tests/ -q
```

仅某个模块：

```
python -m pytest src/tests/test_engine.py -q
```

---

## 5. 模块间协作关系

```
loader（打开/读尺寸/书签/文本）
   │  加载 → source_pages: list[PageInfo]  +  get_text("dict")
   ▼
engine.build_process_plan（纯计算，算法 1→3→2→4→5）
   │  产出 → ProcessPlan（pages/start_page_number/warnings/output_path）
   ▼
renderer.get_text_width（供 build 的文字宽度回调）
   ▼
output（pikepdf 结构阶段 + PyMuPDF 内容阶段 + 校验）
   │  产出 → 原文件名（打印装订）.pdf
```

- `engine.py` 不依赖任何 PDF 库，通过参数传入数据，可独立单元测试。
- `renderer.py` 只读，永不保存文件。
- `output.py` 只读源文件（SHA-256 校验），输出新文件，已存在则跳过不覆盖。

---

## 6. 常见问题

- **裸 `pip` 异常退出**：使用 `python -m pip ...`。
- **样本被覆盖**：`gen_samples.py` 可重复执行，覆盖式重写同名样本。
- **验证临时目录 `_verify\`**：仅验证过程产物（渲染图等），不属于交付物，可随时删除。
- **PySide6 未安装**：Stage 2 不实现 UI，无需安装；Stage 3 需要时再安装。
