# 页码位置 Bug 修复报告

> 依据《页码位置Bug修复_提示语.md》三任务（任务1 → 任务2 → 任务3）
> 项目：PDFSim · 修复日期：2026-08-27

---

## 一、Bug 现象

### Bug 1：页码位置错误（距下 10mm 实际跑到页面顶部/越界）

- 用户设置"距下 10mm、右下角"，真实文档（含源页 `/Rotate` 的扫描件）输出后页码出现在**页面顶部附近**；
- 修复前，带 `/Rotate=90` 的源页，页码插入坐标越过 MediaBox（`num_point.x≈809pt > 595pt`）。

### Bug 2：右侧书视图预览不显示页码

- 书视图只渲染原 PDF 内容，不显示规划后的页码位置，用户只能输出后才知道页码加在哪。

### 功能增强：页码垂直位置可选（距上/距下）

- 原仅"距下"，需支持顶部/底部切换。

---

## 二、根因定位

| Bug | 根因（实测确认） |
|-----|------|
| Bug 1（坐标错位） | `engine._derotate` 的 `r=90` 分支公式错误：y 分量误用 `Wd - x`，正确应为显示坐标 `x`。该错误使旋转页（A4 横向、A3 纵向）页码在显示坐标中错位，叠加源页 `/Rotate` 后进一步放大为越界/跑到顶部 |
| Bug 1（重叠检测错位） | `engine._display_anchor`（重叠检测用）原实现把"距底边距"直接当显示坐标 y，导致在页面顶部检测，与页码实际位置（底部）错位 |
| 顶部语义偏差（本次补充修复） | 顶部位置若仅按"基线距顶=margin_top"，页码 bbox 顶部实际距顶仅 7.8mm（期望 10mm）；按提示语 4.1 验收标准，顶部应让出字高 ascent，使**文字顶部距页顶 = margin_top** |
| Bug 2（预览缺失） | `book_view` 无页码绘制；`AppController` 无页码信息接口 |

---

## 三、修复方案与修改点

| 文件 | 修改 |
|------|------|
| `src\pdfsim\engine.py` | ① `_derotate` r=90 修正为 `(Hd - y, x)`；② `_display_anchor` 按显示坐标（左上原点 y 向下）换算，含 CUSTOM 偏移；③ **顶部位置**：`calculate_number_position` 顶部 anchor = `H - top_pt - fontsize*0.8`（让出字高），`_display_anchor` 顶部基线 = `top_pt + fontsize*0.8`，使文字顶部距页顶 = margin_top |
| `src\pdfsim\models.py` | `PageNumberPos` 扩展 `TOP_LEFT/TOP_RIGHT`；新增 `VerticalPosition`（bottom/top）；`PageNumberStyle` 增 `margin_top_mm`（默认 10）与 `vertical_position`（默认 bottom，向后兼容） |
| `src\pdfsim\config.py` | 配置读写增 `margin_top_mm` / `vertical_position`，旧配置缺省兼容 |
| `src\pdfsim\ui\config_panel.py` | 页码样式区增"垂直位置"下拉（底部/顶部）+ 距下/距上标签动态切换 |
| `src\pdfsim\ui\global_settings.py` | 全局设置同步增垂直位置/距上边距 |
| `src\pdfsim\ui\app_controller.py` | 新增 `get_page_number_info(physical_index)`：返回页码文字、显示坐标锚点、字号、颜色（复用 `_display_anchor`，与输出同源） |
| `src\pdfsim\ui\book_view.py` | `_draw_page` 叠加绘制页码文字（位置/字体/颜色来自规划；坐标 pt→widget 像素换算） |

---

## 四、验证结果（量化数据）

端到端：输出 PDF 渲染后做**页码墨迹像素检测**（bbox 距页面边缘）。

| 场景 | 页码 bbox 位置 | 距右(mm) | 距底/距顶(mm) | 结论 |
|------|------|:---:|:---:|:---:|
| A4 纵向 距下10mm 右下（物理1） | 右下角 | 10.4 | 底 10.1 | ✅ |
| A4 纵向 距下10mm 左下（物理2 偶数页） | 左下角 | 左 10.5 | 底 10.1 | ✅ |
| A4 纵向 距上10mm 右下 | 右上角 | 10.4 | **顶 10.3** | ✅（修复前 7.8mm） |

> 误差全部 ≤ 0.5mm，满足验收标准"±2mm"。10mm = 28.35pt，像素检测换算按此。

**书视图预览验证**：
- `get_page_number_info` 显示坐标：物理1 右下（距右 28.6pt、距底 28.3pt ≈10mm）；顶部设置后基线距顶 12.5mm（=10mm 边距 + 8pt 字高，文字顶部距顶 10mm）；
- 旋转页（A3 纵向→90°）：页码仍在显示坐标右下角；
- A3 背面（无页码）：返回 None，预览不绘制；
- 书视图截图目检：右下角页码"1"正确显示（`_verify\book_preview\preview_p1.png`）。

---

## 五、自动化测试

新增 `src\tests\test_page_number_preview.py`（6 例）：
右下 10mm / 偶数页左下 / 顶部距顶 10mm / 旋转页右下 / 无页码 None / 书视图绘制 smoke。

配合已有 `test_output.py`（旋转页页码位置）、`test_ui_config_panel.py`（顶部/底部 UI）。

---

## 六、回归测试

全量测试通过：**250 → 256 passed**（新增 6 例预览测试，顶部位置修正未破坏输出/旋转/重叠检测既有断言）。
最终全量口径为 **264 passed**（含后续旋转/处理报告 + 性能优化批次新增测试），见《旋转页码验证报告》《性能优化报告》最新快照。

---

*—— 页码位置 Bug 修复报告 完 ——*
