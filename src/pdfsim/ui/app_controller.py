# -*- coding: utf-8 -*-
"""应用控制器（依据《Stage3_提示语.md》5.1 与《UI原型说明.md》第 7 章）。

职责：协调 loader / engine / renderer / config / output，管理应用状态，连接 UI 与核心模块。
UI 层只做渲染与交互，不在此处做业务决策；业务逻辑全部在 engine.py。
"""
from __future__ import annotations

import io
import os

from PIL import Image
from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot

from pdfsim import engine
from pdfsim.config import ConfigManager, _overlap_fingerprint
from pdfsim.loader import PDFLoader, PDFLoadError, PDFPasswordError
from pdfsim.models import (
    DocumentConfig,
    PageInfo,
    PageMark,
    PageNumberPos,
    PageNumberStyle,
    OverlapWarning,
    ProcessedPage,
    ProcessPlan,
    RotationOverride,
    is_a3,
    MM_TO_PT,
)
from pdfsim.output import OutputResult, PDFOutput
from pdfsim.renderer import PDFRenderer
from pdfsim.ui.styles import BOOK_VIEW_DPI, CONFIG_SAVE_DEBOUNCE_MS, THUMBNAIL_DPI


# ---------------------------------------------------------------------------
# 处理报告辅助（新提示语《旋转确认与处理报告》任务 2）
# ---------------------------------------------------------------------------
def _blank_source_cn(source) -> str:
    from pdfsim.models import BlankPageSource

    if source is None:
        return "无"
    return {
        BlankPageSource.COVER_BACK: "封面背面",
        BlankPageSource.SIGN_BACK: "签字页背面",
        BlankPageSource.NO_COUNT_USER: "（已废弃）",
        BlankPageSource.PUSH_FRONT: "推动正面",
        BlankPageSource.A3_BACK: "A3 背面",
        BlankPageSource.FILL_LAST: "补齐末页",
    }.get(source, str(source.value))


def _mark_cn(mark: PageMark) -> str:
    return {
        PageMark.COVER: "封面",
        PageMark.SIGNATURE: "签字页",
        PageMark.NO_NUMBER: "不加页码",
        PageMark.NO_COUNT: "不加页码",  # 已废弃（旧"不占序号"），迁移后不再出现
        PageMark.FRONT: "从正面开始",
    }.get(mark, str(mark.value))


def _pos_cn(pos: PageNumberPos) -> str:
    return {
        PageNumberPos.BOTTOM_RIGHT: "右下角",
        PageNumberPos.BOTTOM_LEFT: "左下角",
        PageNumberPos.TOP_RIGHT: "右上角",
        PageNumberPos.TOP_LEFT: "左上角",
        PageNumberPos.CUSTOM: "自定义",
    }.get(pos, "自动")


def _size_cn(size_mm: tuple[float, float]) -> str:
    """按输出尺寸判定页面尺寸描述。"""
    w, h = size_mm
    tol = 2.0
    a4 = (abs(w - 210) <= tol and abs(h - 297) <= tol) or (
        abs(w - 297) <= tol and abs(h - 210) <= tol)
    a3 = (abs(w - 297) <= tol and abs(h - 420) <= tol) or (
        abs(w - 420) <= tol and abs(h - 297) <= tol)
    if a4:
        return "A4 纵向" if w < h else "A4 横向"
    if a3:
        return "A3 纵向" if w < h else "A3 横向"
    return f"{w:.0f}×{h:.0f} mm"


def _vert_margin_cn(style: PageNumberStyle) -> str:
    """按垂直位置返回 距上/距下 文案。"""
    if getattr(style, "vertical_position", "bottom") == "top":
        return f"{style.margin_top_mm:g} / -"
    return f"- / {style.margin_bottom_mm:g}"


class _LoadWorker(QObject):
    """后台打开工作线程（性能优化 P0-1）。

    在线程内完成：PDFLoader.open + 逐页文本提取（最耗时）+ 配置加载。
    提取结果通过信号回传主线程；主线程再原子接管并重建规划。
    """

    progress = Signal(int, str)   # (percent, step_text)
    done = Signal(dict)           # {"text_data", "config", "page_configs"}
    failed = Signal(str, str)     # (error_kind, detail)
    finished = Signal()           # run() 结束（成功或失败）

    def __init__(self, path: str, password: str = "") -> None:
        super().__init__()
        self._path = path
        self._password = password

    @Slot()
    def run(self) -> None:
        try:
            loader = PDFLoader()
            try:
                result = loader.open(self._path, self._password)
            finally:
                pass
            n = len(result.pages)
            self.progress.emit(0, "正在加载 PDF…")
            cfg_mgr = ConfigManager()
            config = cfg_mgr.load_config(self._path)
            page_configs = cfg_mgr.load_page_configs(self._path)
            text_data: dict[int, dict] = {}
            for i in range(n):
                text_data[i] = loader.extract_text_data(i)
                pct = int((i + 1) / max(n, 1) * 100)
                self.progress.emit(pct, f"分析页面 {i + 1}/{n}")
            self.done.emit(
                {"text_data": text_data, "config": config,
                 "page_configs": page_configs}
            )
        except PDFPasswordError as e:
            self.failed.emit("password", str(e))
        except PDFLoadError as e:
            self.failed.emit("load", str(e))
        except Exception as e:  # pragma: no cover
            self.failed.emit("other", str(e))
        finally:
            try:
                loader.close()
            except Exception:
                pass
            self.finished.emit()


class _OutputWorker(QObject):
    """后台输出工作线程（大 PDF 修复方案 C）。

    在线程内调用 PDFOutput.output()，避免主线程冻结。
    进度信号驱动主线程进度条更新；结果/错误信号回传主线程。
    """

    progress = Signal(int, str)   # (percent, step_text)
    done = Signal(object)         # OutputResult
    failed = Signal(str)          # error message
    finished = Signal()           # run() 结束（成功或失败）

    def __init__(self, pdf_path: str, plan, config: DocumentConfig) -> None:
        super().__init__()
        self._pdf_path = pdf_path
        self._plan = plan
        self._config = config

    @Slot()
    def run(self) -> None:
        try:
            output_module = PDFOutput()
            result = output_module.output(
                self._pdf_path,
                self._plan,
                self._config,
                progress_cb=lambda pct, msg: self.progress.emit(pct, msg),
            )
            self.done.emit(result)
        except Exception as e:  # pragma: no cover
            self.failed.emit(str(e))
        finally:
            self.finished.emit()


class AppController(QObject):
    """应用控制器：协调核心模块 + 管理应用状态。

    信号：
      plan_changed()       —— 规划变化（缩略图 / 书视图 / 配置面板需要刷新）
      selection_changed(int) —— 当前选中物理页变化（1-based）
      status_message(str)  —— 状态栏 / 底部提示信息
    """

    plan_changed = Signal()
    selection_changed = Signal(int)
    selection_set_changed = Signal(list)  # 多选集合变化（物理页号列表，有序）
    status_message = Signal(str)
    load_progress = Signal(int, str)   # 后台打开进度 (percent, step)
    load_finished = Signal()           # 后台打开完成（成功或失败）
    load_failed = Signal(str, str)     # 后台打开失败 (error_kind, detail)
    output_progress = Signal(int, str)     # 后台输出进度 (percent, step_text)
    output_result_ready = Signal(object)   # 后台输出完成 → OutputResult

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.pdf_path: str | None = None
        self.loader = PDFLoader()
        self.renderer = PDFRenderer()
        self.config_mgr = ConfigManager()
        self.output_module = PDFOutput()
        self.load_result = None
        self.source_pages: list[PageInfo] = []
        self.config = DocumentConfig()
        self.page_configs: dict[int | str, object] = {}
        self._blank_configs: dict[str, set[PageMark]] = {}  # blank_id -> 用户显式标记
        self.current_plan: ProcessPlan | None = None
        self.selected_physical_index: int = 1
        self._selected_pages: list[int] = []   # 多选（物理页号集合，有序）
        self._text_data: dict[int, dict] = {}

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._do_save_config)

        # 操作防抖（性能优化 P2-5）：默认关闭，保持"变更后数据立即可读"契约；
        # 高频批量输入可显式开启（≤500ms 合并重建）。
        self._debounce_ms = 0
        self._debounce_timer: QTimer | None = None

        # 后台打开（性能优化 P0-1）
        self._load_thread: QThread | None = None
        self._load_worker: _LoadWorker | None = None
        self._pending_path: str | None = None
        self._pending_password: str = ""
        self._async_on_success = None
        self._async_on_failed = None

        # 性能优化（重建缓存）：旋转检测只依赖源页文本内容，文本块 bbox 只依赖
        # (源页, 旋转角)——两者都不随配置变化，改配置重建时命中缓存跳过重算。
        # overlap_cache 依赖 (源页, 页码位置, 字号, 旋转角)，改字号/位置时对应
        # cache_key 变化自动重算。
        # PDF 打开时（_clear）清空，不在改配置时清空。
        self._rotation_cache: dict[int, int] = {}       # src_index -> detected_rotation
        self._text_block_cache: dict[tuple[int, int], list] = {}  # (src_index, rotation) -> bbox list
        self._overlap_cache: dict[tuple, tuple] = {}  # (src_idx, base, fontsize, total_rot) -> (hits, pixel, rect)
        # 后台输出线程（方案 C：大 PDF 输出不阻塞主线程）
        self._output_thread: QThread | None = None
        self._output_worker: _OutputWorker | None = None

    # ------------------------------------------------------------------
    # 打开 / 关闭
    # ------------------------------------------------------------------
    def _clear(self) -> None:
        """清理当前会话状态（不关闭 loader 句柄以外的资源）。"""
        self.loader.close()
        self.pdf_path = None
        self.load_result = None
        self.source_pages = []
        self.config = DocumentConfig()
        self.page_configs = {}
        self._blank_configs = {}
        self.current_plan = None
        self.selected_physical_index = 1
        self._selected_pages = []
        self._text_data = {}
        # 打开新 PDF → 清空重建缓存（旋转/文本块/重叠只与源页内容相关，与配置无关）
        self._rotation_cache = {}
        self._text_block_cache = {}
        self._overlap_cache = {}

    def _extract_blank_configs(self) -> None:
        """从 page_configs 中提取空白页配置（str 键）→ _blank_configs。"""
        self._blank_configs = {}
        for k, pc in self.page_configs.items():
            if isinstance(k, str):
                self._blank_configs[k] = set(pc.marks)

    def open_pdf(self, path: str, password: str = "") -> None:
        """打开 PDF（可带密码重试）。

        抛 PDFPasswordError（需密码 / 密码错误）、PDFLoadError（损坏 / 空文档 / IO）。
        """
        self._clear()
        result = self.loader.open(path, password)
        self.pdf_path = os.path.abspath(path)
        self.load_result = result
        self.source_pages = result.pages
        self._text_data = {}

        # 配置恢复（若有 .pagerconfig.json 则恢复优先于自动识别）
        self.config = self.config_mgr.load_config(self.pdf_path)
        self.page_configs = self.config_mgr.load_page_configs(self.pdf_path)
        self._extract_blank_configs()
        self.config_mgr.apply_page_configs(self.source_pages, self.page_configs)
        # A3 页 front 强制：apply_page_configs 仅对"有配置的页"强制，
        # 这里对全部 A3 页补强制，与异步路径 _on_async_done 行为一致。
        for p in self.source_pages:
            if is_a3(p):
                p.marks.add(PageMark.FRONT)

        self.selected_physical_index = 1
        self._prewarm_computed()
        self.rebuild_plan()

    def _prewarm_computed(self) -> None:
        """打开 PDF 后从配置文件预热计算缓存（rotation_cache / overlap_cache）。

        旋转检测只依赖源页内容（source_file 匹配即有效）；重叠缓存需指纹一致
        才预热（全局样式/自动调整/起始页码任一变化则失效）。单页覆盖页不预取。
        """
        if self.pdf_path is None:
            return
        fp = _overlap_fingerprint(self.config)
        rot_cache, ov_cache = self.config_mgr.load_computed(
            self.pdf_path, fp, source_pages=self.source_pages
        )
        self._rotation_cache.update(rot_cache)
        self._overlap_cache.update(ov_cache)

    # ------------------------------------------------------------------
    # 后台打开（性能优化 P0-1）
    # ------------------------------------------------------------------
    def open_pdf_async(self, path: str, password: str = "") -> None:
        """后台线程打开 PDF（UI 使用，主线程不阻塞）。

        进度 → load_progress(percent, step)；成功 → load_finished；
        失败 → load_failed(kind, detail)（kind: password/load/other）。
        同步 open_pdf 保留给测试/无 UI 场景。
        """
        self._cancel_async_load()
        self._pending_path = path
        self._pending_password = password
        self._load_worker = _LoadWorker(path, password)
        self._load_thread = QThread(self)
        self._load_worker.moveToThread(self._load_thread)
        self._load_thread.started.connect(self._load_worker.run)
        self._load_worker.progress.connect(self.load_progress)
        self._load_worker.done.connect(self._on_async_done)
        self._load_worker.failed.connect(self._on_async_failed)
        self._load_worker.finished.connect(self._load_thread.quit)
        self._load_worker.finished.connect(self._load_worker.deleteLater)
        self._load_thread.finished.connect(self._load_thread.deleteLater)
        self._load_thread.start()

    def set_async_callbacks(self, on_success=None, on_failed=None) -> None:
        """设置异步打开完成/失败回调（供主窗口在对话框上下文执行）。"""
        self._async_on_success = on_success
        self._async_on_failed = on_failed

    def _cancel_async_load(self) -> None:
        if self._load_thread is not None:
            try:
                self._load_thread.quit()
                self._load_thread.wait(500)
            except Exception:  # pragma: no cover
                pass
        self._load_thread = None
        self._load_worker = None

    def _on_async_done(self, data: dict) -> None:
        """worker 提取完成 → 主线程原子接管（重新 open，复用文本缓存）。"""
        try:
            self._clear()
            result = self.loader.open(self._pending_path, self._pending_password)
            self.pdf_path = os.path.abspath(self._pending_path)
            self.load_result = result
            self.source_pages = result.pages
            self._text_data = data.get("text_data") or {}
            self.config = data.get("config") or DocumentConfig()
            self.page_configs = data.get("page_configs") or {}
            self._extract_blank_configs()
            self.config_mgr.apply_page_configs(self.source_pages, self.page_configs)
            for p in self.source_pages:
                if is_a3(p):
                    p.marks.add(PageMark.FRONT)
            self.selected_physical_index = 1
            self._prewarm_computed()
            self.rebuild_plan()  # 复用 _text_data 缓存，不重复提取
            cb = self._async_on_success
            self._async_on_success = None
            if cb:
                cb()
        except Exception as e:  # pragma: no cover
            self._on_async_failed("load", str(e))
        finally:
            self.load_finished.emit()

    def _on_async_failed(self, kind: str, detail: str) -> None:
        self._clear()
        cb = self._async_on_failed
        self._async_on_failed = None
        self.load_failed.emit(kind, detail)
        if cb:
            cb(kind, detail)

    def close(self) -> None:
        self._cancel_async_load()
        # 等待后台输出线程结束（避免关闭窗口时线程仍在写 PDF）
        self._cleanup_output_thread()
        self.loader.close()

    # ------------------------------------------------------------------
    # 规划
    # ------------------------------------------------------------------
    def _ensure_text_data(self) -> dict[int, dict]:
        """懒加载全部源页文本数据（供算法 3 旋转检测 / 算法 5 重叠检测）。"""
        if self.load_result is None or self.loader._fitz_doc is None:  # noqa: SLF001
            return {}
        for p in self.source_pages:
            if p.original_index is None:
                continue
            if p.original_index not in self._text_data:
                try:
                    self._text_data[p.original_index] = self.loader.extract_text_data(
                        p.original_index
                    )
                except PDFLoadError:
                    self._text_data[p.original_index] = {}
        return self._text_data

    def _text_width_calculator(self, text: str, fontsize: float) -> float:
        return self.renderer.get_text_width(text, fontsize)

    def _content_to_display(
        self, x: float, y: float, rotation: int, content_w: float, content_h: float
    ) -> tuple[float, float]:
        """内容坐标 → 显示坐标（与 _derotate 互逆；供重叠检测 bbox 换算）。"""
        if rotation == 0:
            return x, y
        if rotation == 90:
            return content_h - y, content_w - x
        if rotation == 270:
            return content_h - y, x
        if rotation == 180:
            return content_w - x, content_h - y
        return x, y

    def _text_block_calculator(
        self, src_index: int | None, total_rotation: int | None = None
    ) -> list | None:
        """返回源页在输出显示坐标系下的文本块 bbox 列表（供算法 5）。

        复用 _ensure_text_data 已缓存的 get_text("dict") 结果，避免每页二次提取；
        未缓存时（理论上不会发生，_ensure_text_data 先于 build_process_plan）兜底按旧路径。

        total_rotation: 由 build_process_plan 传入的"源页自带 /Rotate + 规划旋转"
            总旋转角；不再从 current_plan 反查（构建中 current_plan 尚未就绪，
            首次 open_pdf 时会是 None/旧值，导致带 /Rotate 页坐标不回正）。
        """
        if src_index is None or self.loader._fitz_doc is None:
            return None
        rotation = (total_rotation or 0) % 360
        # 性能优化：同一 (源页, 旋转角) → 变换后 bbox 列表恒定，缓存复用
        cache_key = (src_index, rotation)
        cached = self._text_block_cache.get(cache_key)
        if cached is not None:
            return cached
        page = self.loader._fitz_doc[src_index]
        text_data = self._text_data.get(src_index)
        if text_data is None:
            blocks = self.renderer.extract_text_blocks(page)
        else:
            blocks = text_data.get("blocks", [])
        # 内容 bbox 基于"未旋转坐标系"（get_text 输出与 /Rotate 无关）；
        # 而 page.rect 对带 /Rotate 页返回"显示尺寸"（旋转后）。旋转 90/270 时
        # 显示宽=内容高、显示高=内容宽，需还原内容尺寸再变换，否则坐标错乱。
        if page.rotation in (90, 270):
            cw, ch = page.rect.height, page.rect.width
        else:
            cw, ch = page.rect.width, page.rect.height
        out: list[tuple[float, float, float, float]] = []
        for b in blocks:
            if not isinstance(b, dict) or b.get("type") != 0:
                continue
            bbox = b.get("bbox")
            if not bbox:
                continue
            x0, y0, x1, y1 = (float(v) for v in bbox)
            if rotation in (90, 270, 180):
                ax0, ay0 = self._content_to_display(x0, y0, rotation, cw, ch)
                ax1, ay1 = self._content_to_display(x1, y1, rotation, cw, ch)
                x0, y0, x1, y1 = (
                    min(ax0, ax1),
                    min(ay0, ay1),
                    max(ax0, ax1),
                    max(ay0, ay1),
                )
            out.append((x0, y0, x1, y1))
        result = out or None
        self._text_block_cache[cache_key] = result
        return result

    def _pixel_overlap_checker(
        self, src_index: int, num_rect_pt: tuple[float, float, float, float]
    ) -> bool:
        """像素级重叠检测回调：渲染页码区域小矩形，检测非白色像素。

        覆盖扫描件（整页图片时文本块为空，文本块检测 miss）；空白页跳过。
        """
        if src_index is None or self.loader._fitz_doc is None:
            return False
        try:
            page = self.loader._fitz_doc[src_index]
            if page.rect.is_empty:
                return False
        except Exception:
            return False
        return engine.detect_pixel_overlap(page, num_rect_pt)

    def rebuild_plan(self) -> None:
        """重新规划并通知 UI 刷新。"""
        if self.load_result is None:
            return
        text_data = self._ensure_text_data()
        plan = engine.build_process_plan(
            self.source_pages,
            self.config,
            page_text_data=text_data,
            text_width_calculator=self._text_width_calculator,
            text_block_calculator=self._text_block_calculator,
            pixel_overlap_checker=self._pixel_overlap_checker,
            blank_configs=self._blank_configs,
            rotation_cache=self._rotation_cache,
            overlap_cache=self._overlap_cache,
        )
        self.current_plan = plan
        if not plan.pages:
            self.selected_physical_index = 1
        elif self.selected_physical_index > len(plan.pages):
            self.selected_physical_index = len(plan.pages)
        self.plan_changed.emit()

    def auto_detect(self) -> None:
        """重新执行书签关键词自动识别（覆盖 source_pages 标记）。"""
        if self.load_result is None:
            return
        pdf = self.load_result.pdf_handle
        self.source_pages = self.loader.read_page_info(
            pdf,
            bookmarks=self.load_result.bookmarks,
            keywords=self.config.auto_detect_keywords,
        )
        self.page_configs = {}
        self._text_data = {}
        # A3 页 front 强制
        for p in self.source_pages:
            if is_a3(p):
                p.marks.add(PageMark.FRONT)
        self.selected_physical_index = 1
        self.rebuild_plan()
        self.status_message.emit("已重新执行自动识别")

    # ------------------------------------------------------------------
    # 页面修改（修改后防抖保存 + 重建规划）
    # ------------------------------------------------------------------
    def _after_change(self) -> None:
        self.schedule_save_config()
        if self._debounce_ms > 0 and self._debounce_timer is not None:
            self._debounce_timer.start(self._debounce_ms)
        else:
            self.rebuild_plan()

    def set_debounce(self, enabled: bool, ms: int = 500) -> None:
        """开关操作防抖（性能优化 P2-5）。

        enabled=True：_after_change 触发的重建合并到 ≤500ms 窗口内，适合
        高频批量输入（连续标记 / 拖动数值框）；enabled=False：立即 flush
        未决重建并恢复同步语义（保证后续变更后数据立即可读）。
        """
        if enabled:
            self._debounce_ms = max(1, min(int(ms), 500))
            if self._debounce_timer is None:
                self._debounce_timer = QTimer(self)
                self._debounce_timer.setSingleShot(True)
                self._debounce_timer.timeout.connect(self._rebuild_plan_flushed)
        else:
            self._debounce_ms = 0
            if self._debounce_timer is not None and self._debounce_timer.isActive():
                self._debounce_timer.stop()
                self.rebuild_plan()

    def _rebuild_plan_flushed(self) -> None:
        self.rebuild_plan()

    def _page_at(self, original_index: int) -> PageInfo | None:
        if not (0 <= original_index < len(self.source_pages)):
            return None
        return self.source_pages[original_index]

    def _set_source_mark(
        self, p: PageInfo, mark: PageMark, value: bool
    ) -> bool:
        """在源页上设置标记（含封面/签字 → 自动联动 FRONT；A3 页 FRONT 强制）。"""
        if mark is PageMark.NO_COUNT:
            # 规则变更：NO_COUNT 用户标记路径已废除，映射为 NO_NUMBER
            mark = PageMark.NO_NUMBER
        if value:
            if mark in p.marks:
                return False
            p.marks.add(mark)
            if mark in (PageMark.COVER, PageMark.SIGNATURE):
                p.marks.add(PageMark.FRONT)
            if is_a3(p):
                p.marks.add(PageMark.FRONT)
            return True
        if mark not in p.marks:
            return False
        p.marks.discard(mark)
        if is_a3(p):
            p.marks.add(PageMark.FRONT)  # A3 页 FRONT 强制保留
        return True

    def _set_blank_mark(
        self, p: PageInfo, mark: PageMark, value: bool
    ) -> bool:
        """在空白页上设置用户显式标记（同步到 _blank_configs）。

        空白页无语义标记（封面/签字/从正面）不适用——仅允许"不加页码"类标记。
        """
        if mark not in (PageMark.NO_NUMBER,):
            return False
        if value:
            if mark in p.marks:
                return False
            p.marks.add(mark)
        else:
            if mark not in p.marks:
                return False
            p.marks.discard(mark)
        if p.blank_id:
            if p.marks:
                self._blank_configs[p.blank_id] = set(p.marks)
            else:
                self._blank_configs.pop(p.blank_id, None)
        return True

    def set_page_mark(
        self, original_index: int, mark: PageMark, value: bool
    ) -> None:
        """设置源页标记（含封面/签字 → 自动联动 FRONT；A3 页 FRONT 强制）。"""
        p = self._page_at(original_index)
        if p is None:
            return
        if self._set_source_mark(p, mark, value):
            self._after_change()

    def set_page_mark_physical(
        self, physical_index: int, mark: PageMark, value: bool
    ) -> None:
        """按物理页设置标记（自动区分源页/空白页）。"""
        pp = self.processed_page(physical_index)
        if pp is None:
            return
        src = pp.source_page_info
        changed = (
            self._set_blank_mark(src, mark, value)
            if src.is_blank
            else self._set_source_mark(src, mark, value)
        )
        if changed:
            self._after_change()

    def set_page_mark_batch(
        self, physical_indexes: list[int], mark: PageMark, value: bool
    ) -> None:
        """批量设置标记（多选批量，任务 3）。

        - A3 页 FRONT 强制：取消 FRONT 时对 A3 页无效（保留）；
        - 空白页：仅"不加页码"可设置（其余无语义忽略）；
        - 联动与单页一致（取消签字页 → 若因联动添加的 FRONT 一并移除）。
        """
        if not physical_indexes:
            return
        changed = False
        for phys in physical_indexes:
            pp = self.processed_page(phys)
            if pp is None:
                continue
            src = pp.source_page_info
            if src.is_blank:
                if mark is PageMark.FRONT:
                    continue
                changed = self._set_blank_mark(src, mark, value) or changed
            else:
                changed = self._set_source_mark(src, mark, value) or changed
        if changed:
            self._after_change()

    def mark_state_for_pages(
        self, physical_indexes: list[int], mark: PageMark
    ) -> bool | None:
        """三态：True=全部选中页有该标记；False=全部无；None=部分有。"""
        vals: list[bool] = []
        for phys in physical_indexes:
            pp = self.processed_page(phys)
            if pp is None:
                continue
            vals.append(mark in pp.source_page_info.marks)
        if not vals:
            return False
        if all(vals):
            return True
        if not any(vals):
            return False
        return None

    def set_rotation_override(
        self, original_index: int, override: RotationOverride
    ) -> None:
        p = self._page_at(original_index)
        if p is None:
            return
        p.rotation_override = override
        self._after_change()

    def set_rotation_override_batch(
        self, physical_indexes: list[int], override: RotationOverride
    ) -> None:
        """批量设置旋转方向（功能增强：多选批量调整旋转）。

        空白页旋转由同纸正面页继承、不可手动覆盖 → 跳过。
        """
        if not physical_indexes:
            return
        changed = False
        for phys in physical_indexes:
            pp = self.processed_page(phys)
            if pp is None or pp.source_page_info is None:
                continue
            src = pp.source_page_info
            if src.is_blank:
                continue  # 空白页旋转跟随同纸正面，不可手动覆盖
            if src.rotation_override != override:
                src.rotation_override = override
                changed = True
        if changed:
            self._after_change()

    def set_page_style_override_batch(
        self, physical_indexes: list[int], style: PageNumberStyle | None
    ) -> None:
        """批量设置页码样式覆盖（多选批量调整页码样式；空白页也生效）。"""
        if not physical_indexes:
            return
        changed = False
        for phys in physical_indexes:
            pp = self.processed_page(phys)
            if pp is None or pp.source_page_info is None:
                continue
            src = pp.source_page_info
            if src.style_override != style:
                src.style_override = style
                changed = True
        if changed:
            self._after_change()

    def set_page_number_pos(
        self,
        original_index: int,
        pos: PageNumberPos | None,
        offset: tuple[float, float] | None = None,
    ) -> None:
        """设置页码位置；pos=None 表示自动（清除单页覆盖）。"""
        p = self._page_at(original_index)
        if p is None:
            return
        p.number_pos_override = pos
        p.number_custom_offset_mm = offset
        self._after_change()

    def set_page_style_override(
        self, original_index: int, style: PageNumberStyle | None
    ) -> None:
        p = self._page_at(original_index)
        if p is None:
            return
        p.style_override = style
        self._after_change()

    def set_custom_label(self, original_index: int, label: str) -> None:
        p = self._page_at(original_index)
        if p is None or not label:
            return
        p.custom_labels.append(label)
        self._after_change()

    def set_start_page_number(self, start: int) -> None:
        self.config.start_page_number = max(1, int(start))
        self._after_change()

    def set_global_style(self, style: PageNumberStyle) -> None:
        self.config.global_style = style
        self._after_change()

    def set_auto_fill_last(self, value: bool) -> None:
        self.config.auto_fill_last_page = bool(value)
        self._after_change()

    def set_auto_number_blank_pages(self, value: bool) -> None:
        """设置"其他空白页自动编页码"开关（PUSH_FRONT/FILL_LAST，默认关）。"""
        self.config.auto_number_blank_pages = bool(value)
        self._after_change()

    def set_auto_adjust_overlap(self, value: bool) -> None:
        """设置"检测到页码重叠自动调整"开关（默认开）。"""
        self.config.auto_adjust_overlap = bool(value)
        self._after_change()

    def set_auto_shrink_levels(self, levels: int) -> None:
        """设置"自动缩小字号最多几级"（0~4，默认 2）。"""
        self.config.auto_shrink_levels = max(0, min(4, int(levels)))
        self._after_change()

    def set_keywords(self, keywords: dict) -> None:
        self.config.auto_detect_keywords = keywords
        self._after_change()

    def set_output_suffix(self, suffix: str) -> None:
        self.config.output_suffix = suffix
        self._after_change()

    # ------------------------------------------------------------------
    # 选中页
    # ------------------------------------------------------------------
    def select_physical(self, physical_index: int) -> None:
        """单选切换选中页（1-based），通知书视图 / 缩略图 / 配置面板。"""
        if self.current_plan is None:
            return
        if physical_index < 1:
            physical_index = 1
        if physical_index > len(self.current_plan.pages):
            physical_index = len(self.current_plan.pages)
        self._selected_pages = [physical_index]
        self.selection_set_changed.emit([physical_index])
        if physical_index != self.selected_physical_index:
            self.selected_physical_index = physical_index
            self.selection_changed.emit(physical_index)

    def set_selected_pages(self, pages: list[int]) -> None:
        """多选集合（物理页号，Ctrl/Shift/拖框选）。主选中=最小页，驱动书视图。"""
        if self.current_plan is None:
            return
        total = self.plan_page_count()
        valid = sorted({p for p in pages if 1 <= p <= total})
        self._selected_pages = valid
        self.selection_set_changed.emit(list(valid))
        if valid:
            main = valid[0]
            if main != self.selected_physical_index:
                self.selected_physical_index = main
                self.selection_changed.emit(main)
        elif self.selected_physical_index:
            self.selection_changed.emit(self.selected_physical_index)

    def selected_physical_pages(self) -> list[int]:
        """当前选中物理页集合（有序）；单选时长度为 1。"""
        return list(self._selected_pages)

    # ------------------------------------------------------------------
    # 渲染
    # ------------------------------------------------------------------
    def _blank_png(self, size_mm: tuple[float, float], dpi: int) -> bytes:
        """生成空白页 PNG（按 output_size_mm 比例）。"""
        w_px = max(1, int(size_mm[0] / 25.4 * dpi))
        h_px = max(1, int(size_mm[1] / 25.4 * dpi))
        img = Image.new("RGB", (w_px, h_px), (255, 255, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def _rotate_image(self, data: bytes, rotation: int) -> bytes:
        """把 PNG 旋转 rotation°（顺时针；与输出 rotate 方向一致）。"""
        if rotation == 0:
            return data
        img = Image.open(io.BytesIO(data)).convert("RGB")
        if rotation == 90:
            img = img.transpose(Image.Transpose.ROTATE_270)  # 顺时针 90°
        elif rotation == 180:
            img = img.transpose(Image.Transpose.ROTATE_180)
        elif rotation == 270:
            img = img.transpose(Image.Transpose.ROTATE_90)  # 逆时针 90°
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def _render_physical(self, pp: ProcessedPage, dpi: int) -> bytes:
        """按 ProcessPlan 渲染单个物理页（含空白页与旋转效果）。"""
        if pp.is_blank:
            return self._blank_png(pp.output_size_mm, dpi)
        idx = pp.source_page_info.original_index
        if idx is None or self.loader._fitz_doc is None:
            return self._blank_png(pp.output_size_mm, dpi)
        page = self.loader._fitz_doc[idx]
        pix = page.get_pixmap(dpi=dpi)
        data = pix.tobytes("png")
        if pp.rotation != 0:
            data = self._rotate_image(data, pp.rotation)
        return data

    def get_thumbnail(self, physical_index: int) -> bytes | None:
        """缩略图 PNG bytes（物理页，1-based）；无效索引返回 None。"""
        if self.current_plan is None:
            return None
        if not (1 <= physical_index <= len(self.current_plan.pages)):
            return None
        pp = self.current_plan.pages[physical_index - 1]
        return self._render_physical(pp, THUMBNAIL_DPI)

    def get_book_view_page(self, physical_index: int) -> bytes | None:
        """书视图页面 PNG bytes（物理页，1-based）。"""
        if self.current_plan is None:
            return None
        if not (1 <= physical_index <= len(self.current_plan.pages)):
            return None
        pp = self.current_plan.pages[physical_index - 1]
        return self._render_physical(pp, BOOK_VIEW_DPI)

    def get_page_number_info(self, physical_index: int) -> dict | None:
        """书视图页码预览信息（页码位置 Bug 任务 2）。

        返回 {"text", "anchor", "fontsize", "color"}：
          anchor —— 页码文字左下基线在**显示坐标系**的坐标（pt，左上原点 y 向下），
                    与书视图渲染画面（_render_physical 已旋转）同一坐标系，可直接换算绘制。
        无页码的页返回 None。
        """
        pp = self.processed_page(physical_index)
        if pp is None or pp.number_text is None:
            return None
        style = pp.source_page_info.style_override or self.config.global_style
        text_w = self.renderer.get_text_width(pp.number_text, style.fontsize_pt)
        from pdfsim.engine import _display_anchor

        anchor = _display_anchor(
            pp, style, text_w, pp.output_size_mm[0] * MM_TO_PT
        )
        return {
            "text": pp.number_text,
            "anchor": anchor,
            "fontsize": style.fontsize_pt,
            "color": style.color,
        }

    # ------------------------------------------------------------------
    # 查询（供 UI 显示）
    # ------------------------------------------------------------------
    def processed_page(self, physical_index: int) -> ProcessedPage | None:
        if self.current_plan is None:
            return None
        if not (1 <= physical_index <= len(self.current_plan.pages)):
            return None
        return self.current_plan.pages[physical_index - 1]

    def current_processed_page(self) -> ProcessedPage | None:
        return self.processed_page(self.selected_physical_index)

    def source_page(self, original_index: int) -> PageInfo | None:
        return self._page_at(original_index)

    def plan_page_count(self) -> int:
        return len(self.current_plan.pages) if self.current_plan else 0

    def overlap_warning_for(self, physical_index: int) -> OverlapWarning | None:
        if self.current_plan is None:
            return None
        for w in self.current_plan.warnings:
            if w.physical_index == physical_index:
                return w
        return None

    def needs_rotation(self, original_index: int) -> bool:
        """该源页是否需旋转（A4 横向 / A3 纵向）。"""
        p = self._page_at(original_index)
        if p is None:
            return False
        from pdfsim.models import (
            A3_HEIGHT_MM,
            A3_WIDTH_MM,
            A4_HEIGHT_MM,
            A4_WIDTH_MM,
            SIZE_TOLERANCE_MM,
        )

        w, h = p.width_mm, p.height_mm
        a3_land = abs(w - A3_WIDTH_MM) <= SIZE_TOLERANCE_MM and abs(
            h - A3_HEIGHT_MM
        ) <= SIZE_TOLERANCE_MM
        a4_land = abs(w - A4_HEIGHT_MM) <= SIZE_TOLERANCE_MM and abs(
            h - A4_WIDTH_MM
        ) <= SIZE_TOLERANCE_MM
        return a3_land or a4_land

    def rotation_detection_text(self, original_index: int) -> str:
        """旋转自动检测结论文案（供配置面板显示）。"""
        p = self._page_at(original_index)
        if p is None:
            return ""
        if not self.needs_rotation(original_index):
            return "无需旋转"
        if p.detected_rotation == 270:
            return "自动检测：逆时针 90°"
        if p.detected_rotation == 180:
            return "自动检测：旋转 180°"
        if p.detected_rotation == 90:
            # 无法区分"有文字默认90"与"无文字回退90"，统一提示
            return "自动检测：顺时针 90°"
        return "自动检测：无需旋转"

    # ------------------------------------------------------------------
    # 配置保存（防抖 500ms）
    # ------------------------------------------------------------------
    def schedule_save_config(self) -> None:
        if self.pdf_path is None:
            return
        self._save_timer.start(CONFIG_SAVE_DEBOUNCE_MS)

    def _do_save_config(self) -> None:
        if self.pdf_path is None:
            return
        plan_pages = self.current_plan.pages if self.current_plan else None
        page_configs = self.config_mgr.collect_page_configs(
            self.source_pages, plan=plan_pages)
        self.config_mgr.save_all(
            self.pdf_path, self.config, page_configs,
            rotation_cache=self._rotation_cache,
            overlap_cache=self._overlap_cache,
            overlap_fingerprint=_overlap_fingerprint(self.config),
        )

    # ------------------------------------------------------------------
    # 输出
    # ------------------------------------------------------------------
    def output(self):
        """调用输出模块（同步）；返回 OutputResult（无文档时返回 None）。

        保留给测试/无 UI 场景；UI 使用 output_async 后台输出。
        """
        if self.current_plan is None or self.pdf_path is None:
            return None
        return self.output_module.output(self.pdf_path, self.current_plan, self.config)

    def output_async(self) -> bool:
        """启动后台输出（方案 C）。返回 True=已启动，False=无法启动/已在运行。"""
        if self.current_plan is None or self.pdf_path is None:
            return False
        if self._output_thread is not None:
            return False  # 已在运行，防重复

        self._output_thread = QThread(self)
        self._output_worker = _OutputWorker(
            self.pdf_path, self.current_plan, self.config
        )
        self._output_worker.moveToThread(self._output_thread)
        self._output_thread.started.connect(self._output_worker.run)
        self._output_worker.progress.connect(self._on_output_progress)
        self._output_worker.done.connect(self._on_output_done)
        self._output_worker.failed.connect(self._on_output_failed)
        self._output_worker.finished.connect(self._output_thread.quit)
        self._output_worker.finished.connect(self._output_worker.deleteLater)
        self._output_thread.finished.connect(self._output_thread.deleteLater)
        self._output_thread.start()
        return True

    def _on_output_progress(self, pct: int, msg: str) -> None:
        self.output_progress.emit(pct, msg)

    def _on_output_done(self, result) -> None:
        self.output_result_ready.emit(result)
        self._cleanup_output_thread()

    def _on_output_failed(self, msg: str) -> None:
        self.output_result_ready.emit(
            OutputResult(success=False, output_path="", message=msg)
        )
        self._cleanup_output_thread()

    def _cleanup_output_thread(self) -> None:
        if self._output_thread is not None:
            try:
                self._output_thread.quit()
                self._output_thread.wait(1000)
            except Exception:  # pragma: no cover
                pass
            self._output_thread = None
            self._output_worker = None

    def expected_output_path(self) -> str:
        """预计输出路径（供 UI 显示）。"""
        if self.pdf_path is None or self.config is None:
            return ""
        return self.output_module._output_path(self.pdf_path, self.config)  # noqa: SLF001

    # ------------------------------------------------------------------
    # 处理报告（新提示语任务 2）
    # ------------------------------------------------------------------
    def get_report_data(self) -> list[dict]:
        """生成处理报告数据（每行一个物理页）。

        只遍历 current_plan 组装数据，不修改任何状态；800 页 < 100ms。
        """
        if self.current_plan is None:
            return []
        rows: list[dict] = []
        warned = {w.physical_index for w in self.current_plan.warnings}
        for pp in self.current_plan.pages:
            src = pp.source_page_info
            style = src.style_override or self.config.global_style
            marks = sorted(src.marks, key=lambda m: m.value)
            rows.append(
                {
                    "物理页号": pp.physical_index,
                    "源文件页号": "-" if src.original_index is None
                    else src.original_index + 1,
                    "页面类型": "空白页" if pp.is_blank else "原页",
                    "空白页来源": _blank_source_cn(pp.blank_source),
                    "页面尺寸": _size_cn(pp.output_size_mm),
                    "旋转角度": f"{pp.rotation}°",
                    "旋转方式": "用户覆盖"
                    if src.rotation_override != RotationOverride.AUTO
                    else "自动检测",
                    "页码数字": pp.number_text if pp.number_text is not None else "-",
                    "页码位置": _pos_cn(pp.number_position),
                    "距右/左 (mm)": f"{style.margin_right_mm:g} / {style.margin_left_mm:g}",
                    "距上/下 (mm)": _vert_margin_cn(style),
                    "重叠警告": "有" if pp.physical_index in warned else "无",
                    "页面标记": "、".join(_mark_cn(m) for m in marks) or "-",
                }
            )
        return rows
