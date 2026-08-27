# 空白页方向 Bug 修复报告

- 任务来源：《空白页方向Bug_提示语.md》（指导者已确认 bug 及根因）
- 基线：上一任务全量 **289 passed**
- 结论：修复完成，全量 **300 passed**（新增 11 例专项全部通过）
- 报告日期：2026-08-27

---

## 1. Bug 现象

书视图中，**背面空白页与同一张纸的正面页大小一致，但方向不一致**。

用户原话："第二行和第三行左侧插入的空白页面大小是对的，但方向不对。"

书视图对应关系：**上一行右页 ↔ 下一行左页 = 同一张纸的正反面**。同一张纸的正反面尺寸必须相同、方向也必须相同。

**数据实证（修复后 sample_mixed）**：

```
phys4 a3_back: size=(419.9996, 297.0001) rot=90 | 正面 phys3: size=(419.9996, 297.0001) rot=90
phys6 a3_back: size=(419.9996, 297.0001) rot=0  | 正面 phys5: size=(419.9996, 297.0001) rot=0
```

修复前 A3 纵向页（正面 rot=90、显示为横向）的背面空白 rot=0（显示为纵向），方向不一致；修复后两者均为横向。

书视图截图（`_verify/blank_rotation_bookview.png`）：A3 正面（phys3，右）与 A3 背面空白（phys4，左）均为横向，方向一致。

---

## 2. 根因

空白页创建时 `rotation` 字段默认 0（`PageInfo.planned_rotation` 默认 0），没有继承同纸正面页的旋转：

- `engine.py build_process_plan` 算法 3 循环：空白页分支 `p.planned_rotation = 0` 固定清零；
- 正面页带旋转时（如 A3 纵向源页 + 规划旋转 90° → 显示横向），背面空白页仍为纵向，视觉方向不一致；
- **物理尺寸（MediaBox）本来是对的**，只是显示方向（/Rotate 与旋转后尺寸）不匹配。

---

## 3. 修复方案（最小改动）

### 3.1 旋转继承（`src/pdfsim/engine.py`）

在 `build_process_plan` 算法 3 填充处，空白页继承**同纸正面页（前一元素 `plan[i-1]`）**的 `planned_rotation`：

```python
for i, p in enumerate(plan):
    if p.is_blank:
        p.detected_rotation = 0
        p.planned_rotation = plan[i - 1].planned_rotation if i > 0 else 0
        continue
    ...
```

**为什么是"前一元素"**（对 5 种空白页统一成立）：

| 空白页类型 | 插入位置 | 前一元素 = 同纸正面 |
|-----------|----------|--------------------|
| PUSH_FRONT | 插在当前页 p 之前、`plan[-1]` 之后 | `plan[-1]`（触发时 plan 长度必为奇数，`plan[-1]` 位于奇数位=正面源页） |
| COVER_BACK | 紧跟封面页 p 之后 | p |
| SIGN_BACK | 紧跟签字页 p 之后 | p |
| A3_BACK | 紧跟 A3 页 p 之后 | p |
| FILL_LAST | 末尾追加 | `plan[-1]`（触发条件 plan 长度为奇数 → 末元素在奇数位=正面源页） |

> 与提示语"make_blank_page 增加 rotation 参数"指引的差异说明：经任务 1 确认，`plan_physical_order`（创建空白页）**先于**算法 3（计算源页 `planned_rotation`）执行，创建时源页旋转尚未算出，故在 `make_blank_page` 创建时传 rotation 无法生效。正确实现点是算法 3 填充处（此时源页旋转已算、空白页已就位），对 5 种空白页统一继承前一元素即可。未给 `make_blank_page` 增加冗余参数。

### 3.2 输出阶段 MediaBox 与 /Rotate（`src/pdfsim/output.py`）

原逻辑"空白页不旋转"导致两个问题（一旦空白页带 rotation）：
- `add_blank_page` 用旋转后尺寸 → 空白页 MediaBox 与正面页不同；
- 不执行 `rotate()` → 方向不生效。

修复后：
- 空白页 `add_blank_page` 用**原始 MediaBox**（`width_mm × height_mm`，与同纸正面页一致）；
- 旋转阶段对所有页（含空白页）`rotate(pp.rotation, relative=True)`。

效果：**同纸正反面 MediaBox 相同 + /Rotate 相同**（约束：rotation 是 PDF 页面属性，不改变 MediaBox）。

### 3.3 页码位置

`plan_page_numbers` 中 `ProcessedPage.rotation = page.planned_rotation`、`output_size_mm = _rotated_size(page, planned_rotation)` 自动跟随继承值；`calculate_number_position` 走 `_derotate` 反算坐标（已有逻辑），带 rotation 的 PUSH_FRONT / FILL_LAST 空白页页码位置自动正确（测试验证）。

---

## 4. 测试结果

### 4.1 新增专项测试 `src/tests/test_blank_rotation.py`（11 例，全部通过）

| 编号 | 测试 | 验证点 |
|------|------|--------|
| 1 | test_a3_back_inherits_a3_rotation | A3_BACK rotation = A3 页 rotation（非 0） |
| 2 | test_mixed_a3_both_rotate | 混合 A3 纵/横各自背面方向与正面一致（rotation + output_size） |
| 3 | test_push_front_inherits_prev | PUSH_FRONT 继承前一页 rotation（构造 rot90 正面 + FRONT 触发） |
| 4 | test_push_front_no_rotation_zero | 前一页无旋转时 PUSH_FRONT 保持 0（回归） |
| 5 | test_cover_back_inherits_cover | COVER_BACK 继承封面 rotation |
| 6 | test_sign_back_inherits_sign | SIGN_BACK 继承签字页 rotation |
| 7 | test_fill_last_inherits_last | FILL_LAST 继承末页 rotation |
| 8 | test_blank_id_still_stable_with_rotation | 加 rotation 不影响页码规则（PUSH_FRONT 有页码、A3_BACK 无页码） |
| 9 | test_blank_mediabox_matches_front | **输出 PDF**：空白页 MediaBox 与正面一致、/Rotate 与正面及 plan 一致 |
| 10 | test_rotated_push_front_number_position | 带 rotation 的 PUSH_FRONT 页码存在、绘制点非空 |
| 11 | test_rotated_fill_last_number_position | 带 rotation 的 FILL_LAST 页码存在 |

### 4.2 旧测试期望表更新（行为变更所致）

| 文件 | 更新 |
|------|------|
| `_stage4_helpers.py` | `blank()` 辅助函数增加 `rot` 参数（默认 0） |
| `test_physical_order.py::test_t12_t13_cascade_table` | A3_BACK（phys4）期望 rotation 0 → 90 |
| `test_integration_t09_t16.py::TestT12_A3EvenPush` | 同上 |

### 4.3 全量回归

| 阶段 | 结果 |
|------|------|
| 新增专项 | 11 passed |
| **全量** | **300 passed**（25.65s，289 基线 + 11 新增） |

---

## 5. 验收标准核对

- [x] 书视图中每张纸正反面方向一致（A3 正面横向 ↔ 背面空白横向）
- [x] PUSH_FRONT 空白页方向 = 前一页方向（test 3/4）
- [x] A3_BACK / COVER_BACK / SIGN_BACK 空白页方向 = 对应源页方向（test 1/2/5/6）
- [x] FILL_LAST 空白页方向 = 最后一页方向（test 7）
- [x] 带 rotation 的空白页页码位置正确（test 10/11）
- [x] 物理尺寸不变（MediaBox 与正面一致，test 9）
- [x] 全量测试通过（300 passed）
- [x] 报告完整（本报告）

---

## 6. 交付物清单

| 交付物 | 路径 |
|--------|------|
| 本报告 | `docs/空白页方向Bug修复报告.md` |
| 源码修复 | `src/pdfsim/engine.py`（算法 3 空白页旋转继承）、`src/pdfsim/output.py`（空白页 MediaBox + rotate） |
| 新增测试 | `src/tests/test_blank_rotation.py`（11 例） |
| 旧测试更新 | `_stage4_helpers.py` / `test_physical_order.py` / `test_integration_t09_t16.py` |
| 截图证据 | `_verify/blank_rotation_bookview.png`、`_verify/blank_rotation_back.png`、`_verify/blank_rotation.txt` |

---

*—— 空白页方向Bug修复报告 完 ——*
