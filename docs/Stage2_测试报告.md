# PDFSim Stage 2 测试报告

> 项目：PDFSim（PDF 双面打印前的页码编排与装订准备，Windows 桌面单文件软件）
> 阶段：Stage 2（核心算法 + 底层模块 + 单元测试全覆盖）
> 报告日期：2026-08-26
> 依据：《Stage2_提示语.md》九（交付物 4）与十（验收标准）

---

## 1. 测试运行结果

全部测试通过，共 **127 个用例**，0 失败。

| 测试文件 | 用例数 | 结果 |
|----------|-------:|------|
| `test_models.py`（数据结构） | 21 | ✅ 通过 |
| `test_config.py`（配置读写） | 15 | ✅ 通过 |
| `test_engine.py`（5 大算法，核心） | 40 | ✅ 通过 |
| `test_loader.py`（加载模块） | 31 | ✅ 通过 |
| `test_renderer.py`（渲染模块） | 6 | ✅ 通过 |
| `test_output.py`（输出模块） | 12 | ✅ 通过 |
| `test_integration.py`（端到端集成） | 10 | ✅ 通过 |
| **合计** | **127** | **全部通过** |

运行命令：

```
python -m pytest src/tests/ -q
```

---

## 2. 覆盖率报告

> 命令：`python -m pytest src/tests/ --cov=pdfsim --cov-report=term`

| 模块 | 语句数 | 未覆盖 | 覆盖率 |
|------|-------:|-------:|-------:|
| `models.py` | 100 | 0 | **100%** |
| `renderer.py` | 20 | 0 | **100%** |
| `output.py` | 91 | 2 | **98%** |
| `config.py` | 205 | 14 | **93%** |
| `loader.py` | 150 | 11 | **93%** |
| `engine.py` | 231 | 19 | **92%** |
| `__init__.py` | 1 | 0 | 100% |
| **TOTAL** | **798** | **46** | **94%** |

- 全部 6 个业务模块覆盖率均 **≥ 90%**，总体 **94%**，满足验收标准（≥90%）。
- 未覆盖行均为防御性异常分支 / 极端边界（如文件 IO 异常、极端旋转角兜底、破坏性书签解析异常等），不影响主路径正确性。

---

## 3. 集成测试结果（样本 PDF 端到端验证）

`test_integration.py` 用 `gen_samples.py` 生成的 13 个样本做全链路（加载 → 规划 → 输出）验证：

| 场景 | 样本 | 验证结果 |
|------|------|---------|
| 基础端到端 | `sample_a4_portrait.pdf` | ✅ 输出页数与 ProcessPlan 一致；封面背面/推动正面/签字背面空白页正确插入；物理奇数位全为正面 |
| A3 纵向旋转 | `sample_a3_portrait.pdf` | ✅ A3 纵向页检测旋转 90°，输出页 `/Rotate=90`，显示尺寸 1190.55×841.89pt |
| 混合尺寸 | `sample_mixed.pdf` | ✅ A4 纵 / A3 纵(90°) / A3 横 / A4 纵 各页旋转判定正确 |
| 不占序号 | `sample_no_count.pdf` | ✅ NO_COUNT 页原地替换为空白页，内容丢弃、尺寸不变、不占序号不显示 |
| 重叠检测 | `sample_with_pagenum.pdf` | ✅ 检测到已有页码与新增页码重叠，产出 `OverlapWarning` |
| 加密处理 | `sample_encrypted.pdf` | ✅ 无密码抛 `PDFPasswordError`；正确密码端到端输出成功 |
| 性能样本 | `sample_200pages.pdf` | ✅ 200 页完整处理并输出 |
| 单页 | `sample_single.pdf` | ✅ 输出 1 页 |
| 方向标记 | `sample_direction_markers.pdf` | ✅ A4 横向、A3 纵向页输出旋转正确；方向标记文字在旋转后仍完整可提取 |

其它专项验证：

- **损坏 PDF**：`sample_corrupted.pdf` → 加载器正确捕获并抛 `PDFLoadError`（弹窗路径由 Stage 3 UI 承接）。
- **空文档**：0 页 PDF → `PDFLoadError`。
- **页码内容流文字**：输出后 `get_text()` 能提取全部页码数字（非图片）。
- **页码位置**：物理奇页右下、偶页左下（A4 纵向样本逐页校验通过）。

---

## 4. 旋转可读性验证结果（方向标记样本）

### 4.1 输出行为

`sample_direction_markers.pdf` 端到端输出后：

- **A4 横向页**（源 297×210mm）：`detect_text_rotation` 检测到水平正文 → 默认旋转 90°（顺时针，实测结论见《Stage2_验证报告》3.4）→ 输出 `/Rotate=90`，显示尺寸 210×297mm。
- **A3 纵向页**（源 297×420mm）：同理由检测返回 90° → 输出 `/Rotate=90`，显示尺寸 420×297mm。

### 4.2 转书可读性目检

以"读者逆时针转书 90° 后可读"为标准，对输出渲染图做 `PIL Image.rotate(90, expand=True)` 模拟转书并目检（渲染图存档于 `_verify\readability\`）：

- **转书后**：方向标记"顶"位于上方、"底"位于下方；标题"横向/A3 纵向"正立可读；正文英文行正立可读；中心水平箭头指向阅读方向。
- **结论**：A4 横向 / A3 纵向页经本软件旋转 90°（顺时针）后，读者转书 90° 即可正常阅读，方向正确。

> 与《Stage2_验证报告》3.4 节实测结论一致：绝大多数真实需旋转页场景返回 90° 均可读；检测映射已按验证 2 授权修正并记录，供审查知悉。

---

## 5. 原文件完整性验证（SHA-256）

输出模块 `output()` 对源文件做输出前 / 输出后 SHA-256 对比：

- 全部集成与输出测试中 `source_hash_verified == True`；
- 测试内额外断言源文件 hash 前后一致（`test_page_count_and_hash`）；
- 结构阶段使用 `dst = pikepdf.Pdf.new()` + `dst.pages.append(...)`，源文件自始至终只读，从未被写入。

**结论：原 PDF 文件完整无损，符合"禁止修改原 PDF 文件"约束。**

---

## 6. 测试矩阵 T01–T16 覆盖情况

| 测试组 | 对应场景 | 位置 | 结果 |
|--------|---------|------|------|
| 算法1-基本 | T01 基础流程（封面/签字/A3 背面） | `test_engine.TestPlanPhysicalOrder::test_t01_basic_cover_signature_a3` | ✅ |
| 算法1-正面 | T12 A3 落偶数位 | `test_t12_a3_on_even_position_pushes_front` | ✅ |
| 算法1-级联 | T13 连续多个 A3 | `test_t13_cascade_multiple_a3` | ✅ |
| 算法1-不占序号 | T11 原地替换同尺寸 | `test_t11_no_count_replaced_blank_same_size` | ✅ |
| 算法1-补齐 | T06 末页奇数 | `test_t06_fill_last_page` | ✅ |
| 算法1-标记联动 | T01 封面/签字 FRONT 联动 | `test_mark_linkage_front_pushed` | ✅ |
| 算法1-冲突 | D6 A3 背面优先 | `test_d6_a3_cover_conflict` | ✅ |
| 算法2-编号 | T01 页码连续 | `test_t01_sequential_numbers` | ✅ |
| 算法2-不占序号 | T11 序号跳过 | `test_t11_no_count_skips_sequence` | ✅ |
| 算法2-不加页码 | NO_NUMBER 占序号不显示 | `test_no_number_occupies_but_hidden` | ✅ |
| 算法2-空白页 | 各类空白来源 | `test_blank_sources` | ✅ |
| 算法3-旋转判定 | T03/T04 横纵判定 | `test_a4_landscape_needs_rotation` 等 | ✅ |
| 算法3-文字方向 | 前置验证 2 | `test_horizontal/vertical/no_text/reversed` | ✅ |
| 算法3-无文字 | 纯图片页回退 90° | `test_no_text_fallback` | ✅ |
| 算法3-用户覆盖 | T16 rotation_override | `test_cw90/ccw90/none/auto` | ✅ |
| 算法4-坐标 | 奇右偶左 | `test_odd_page_bottom_right` 等 | ✅ |
| 算法4-旋转坐标 | derotation 换算 | `test_rotated_derotation` | ✅ |
| 算法4-自定义 | D8 偏移 | `test_custom_offset` | ✅ |
| 算法5-重叠 | T10 命中 | `test_t10_overlap_hit` | ✅ |
| 算法5-无重叠 | 无误报 | `test_no_overlap` | ✅ |
| 算法5-容差 | 0.5pt 边界 | `test_tolerance_edges` | ✅ |
| 集成-build_plan | T01 完整流程 | `TestBuildProcessPlan` | ✅ |

---

## 7. 验收标准逐项核对

- [x] 前置验证 1 和 2 完成，验证报告已写入（`docs\Stage2_验证报告.md`）
- [x] 全部 6 个模块实现完成（models / config / engine / loader / renderer / output）
- [x] 全部单元测试通过（124/124）
- [x] 测试覆盖率 ≥ 90%（总体 94%，各模块 ≥91%）
- [x] 集成测试通过（样本 PDF 端到端验证）
- [x] 旋转可读性验证通过（方向标记样本，转书后可读）
- [x] 原文件完整性验证通过（SHA-256 未变）
- [x] 页码为内容流文字（非图片，`insert_text` 绘制）
- [x] 空白页插入正确（各来源类型）
- [x] 物理顺序重排正确（级联场景）
- [x] 页码位置正确（奇右偶左、A3 右下）
- [x] 旋转方向正确（文字方向检测 + 用户覆盖）
- [x] 配置保存与恢复正确
- [x] 加密/损坏 PDF 处理正确
- [x] 代码无调试残留、无明显警告（测试全程无 warning）

---

## 8. 审查后修正记录（缺口 1 关闭）

### 8.1 发现的实现缺陷

《Stage2 审查报告》第四节的"缺口 1"（旋转页页码位置未端到端可视化验证）在审查后主动处理。端到端渲染验证发现**算法 4 derotation 公式实现有误**：

- **现象**：A4 横向页输出旋转 90° 后，页码被渲染到页面**右上角**，而非预期右下角（物理奇数页）。
- **根因**：`engine._derotate()` 中 `r=90` 的换算使用 `(y, Wd-x)`，与 PDF 规范实测映射不符。
- **修正**：以实测渲染映射（内容坐标→显示坐标）反推正确公式：
  - `r=90`:  `(x,y) → (Hd - y, Wd - x)`
  - `r=270`: `(x,y) → (y, Wd - x)`
  - `r=180`: `(x,y) → (Wd - x, Hd - y)`（不变）
- **验证**：修正后 A4 横向（90°/270° 覆盖）、A3 纵向（90°）旋转页，页码均正确显示在右下角（物理奇）或左下角（物理偶），渲染图目检 + 自动化断言双通道通过（`test_output.py::test_rotated_page_number_position`、`test_rotated_even_page_left`、`test_rotated_derotation_ccw`）。

### 8.2 新增测试

| 测试 | 覆盖 |
|------|------|
| `test_engine.py::test_rotated_derotation` | r=90 derotation 修正后换算（更新） |
| `test_engine.py::test_rotated_derotation_ccw` | r=270 derotation 换算 |
| `test_output.py::test_rotated_page_number_position` | 旋转页页码端到端位置（右下/左下，A4横+A3纵） |
| `test_output.py::test_rotated_even_page_left` | 旋转页落偶数位 → 左下角 |

### 8.3 缺口状态

- [x] A4 横向样本：页码在右下角（物理奇）/ 左下角（物理偶）
- [x] A3 纵向样本：页码在右下角（固定）
- [x] r=270（用户覆盖 CCW90）渲染验证通过
- **缺口 1 已关闭**：不再需要 Stage 3 补充验证
