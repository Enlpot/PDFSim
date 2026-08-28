# -*- coding: utf-8 -*-
"""配置文件读写（依据《技术方案.md》第 4 章 + Stage2 提示语 5.2）。

配置文件：`原PDF文件名.pagerconfig.json`，存放于原 PDF 所在文件夹。
- 保存时先写临时文件再原子替换；
- 加载时校验 version 与 source_file，不匹配则忽略并返回默认；
- 页面级配置（marks / rotation_override 等）与全局配置分开读写，最终合并落盘。
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field

from pdfsim.models import (
    DocumentConfig,
    PageInfo,
    PageMark,
    PageNumberPos,
    PageNumberStyle,
    RotationOverride,
    is_a3,
)

CONFIG_VERSION = 2  # v2（规则变更）：空白页可配置（blank_id 键）；旧 NO_COUNT 用户标记迁移为 NO_NUMBER
CONFIG_EXT = ".pagerconfig.json"
# 应用级全局默认配置（全局设置"保存为默认"），与具体 PDF 无关
GLOBAL_DEFAULT_DIRNAME = "PDFSim"
GLOBAL_DEFAULT_FILENAME = "global_default.json"


def _config_key_sort(key: int | str) -> tuple:
    """配置键排序：int（源页）在前按值排，str（空白页）在后按标识排。"""
    return (0, key) if isinstance(key, int) else (1, key)


# ---------------------------------------------------------------------------
# 页面级配置数据
# ---------------------------------------------------------------------------
@dataclass
class PageConfigData:
    """配置文件 pages 数组中单个元素的解析结果。

    original_index（源页）与 blank_id（空白页）二选一作为键；
    空白页标识格式 "blank:{触发源标识}:{来源类型}"（见 engine.make_blank_id）。
    """
    original_index: int | None = None
    blank_id: str | None = None
    marks: set[PageMark] = field(default_factory=set)
    rotation_override: RotationOverride = RotationOverride.AUTO
    custom_labels: list[str] = field(default_factory=list)
    number_pos_mode: PageNumberPos | None = None
    number_pos_offset_mm: tuple[float, float] | None = None
    style_override: PageNumberStyle | None = None

    @property
    def key(self) -> int | str | None:
        """配置键：源页用 original_index，空白页用 blank_id。"""
        if self.original_index is not None:
            return self.original_index
        return self.blank_id


# ---------------------------------------------------------------------------
# 序列化 / 反序列化辅助
# ---------------------------------------------------------------------------
_MARK_TO_STR = {m: m.value for m in PageMark}
_STR_TO_MARK = {m.value: m for m in PageMark}
_POS_TO_STR = {p: p.value for p in PageNumberPos}
_STR_TO_POS = {p.value: p for p in PageNumberPos}
_ROT_TO_STR = {r: r.value for r in RotationOverride}
_STR_TO_ROT = {r.value: r for r in RotationOverride}


def _style_to_dict(style: PageNumberStyle) -> dict:
    return {
        "font": style.font,
        "fontsize_pt": style.fontsize_pt,
        "color": list(style.color),
        "margin_right_mm": style.margin_right_mm,
        "margin_left_mm": style.margin_left_mm,
        "margin_bottom_mm": style.margin_bottom_mm,
        "margin_top_mm": style.margin_top_mm,
        "vertical_position": style.vertical_position,
    }


def _style_from_dict(d: dict) -> PageNumberStyle:
    color = tuple(d.get("color", [0, 0, 0]))
    return PageNumberStyle(
        font=d.get("font", "Times New Roman"),
        fontsize_pt=float(d.get("fontsize_pt", 9.0)),
        color=tuple(int(c) for c in color),
        margin_right_mm=float(d.get("margin_right_mm", 10.0)),
        margin_left_mm=float(d.get("margin_left_mm", 10.0)),
        margin_bottom_mm=float(d.get("margin_bottom_mm", 10.0)),
        margin_top_mm=float(d.get("margin_top_mm", 10.0)),
        vertical_position=str(d.get("vertical_position", "bottom")),
    )


def _keywords_to_dict(kw: dict) -> dict:
    """auto_detect_keywords: {PageMark|str: list} -> {str: list}"""
    out = {}
    for k, v in kw.items():
        key = k.value if isinstance(k, PageMark) else k
        out[key] = list(v)
    return out


def _keywords_from_dict(d: dict | None) -> dict:
    """auto_detect_keywords: {str: list} -> {PageMark|str: list}"""
    from pdfsim.models import DocumentConfig

    base = DocumentConfig().auto_detect_keywords  # 默认值
    if not d:
        return base
    out = {}
    for key, vals in d.items():
        if key in _STR_TO_MARK:
            out[_STR_TO_MARK[key]] = list(vals)
        else:
            out[key] = list(vals)  # 自定义键（如 "body"）
    return out


def _page_to_dict(p: PageConfigData) -> dict:
    if p.blank_id is not None:
        d: dict = {"blank_id": p.blank_id}
    else:
        d = {"original_index": p.original_index}
    if p.marks:
        d["marks"] = sorted(_MARK_TO_STR[m] for m in p.marks)
    if p.rotation_override is not RotationOverride.AUTO:
        d["rotation_override"] = _ROT_TO_STR[p.rotation_override]
    if p.custom_labels:
        d["custom_labels"] = list(p.custom_labels)
    if p.number_pos_mode is not None:
        np = {"mode": _POS_TO_STR[p.number_pos_mode]}
        if p.number_pos_offset_mm is not None:
            np["offset_mm"] = list(p.number_pos_offset_mm)
        d["number_pos"] = np
    if p.style_override is not None:
        d["style_override"] = _style_to_dict(p.style_override)
    return d


def _page_from_dict(d: dict) -> PageConfigData:
    if "blank_id" in d:
        p = PageConfigData(blank_id=str(d["blank_id"]))
    else:
        p = PageConfigData(original_index=int(d["original_index"]))
    for m in d.get("marks", []):
        if m not in _STR_TO_MARK:
            continue
        mark = _STR_TO_MARK[m]
        # 规则变更迁移：旧"不占序号"（NO_COUNT）用户标记 → "不加页码"（NO_NUMBER）
        if mark is PageMark.NO_COUNT:
            mark = PageMark.NO_NUMBER
        p.marks.add(mark)
    rot = d.get("rotation_override", "auto")
    p.rotation_override = _STR_TO_ROT.get(rot, RotationOverride.AUTO)
    p.custom_labels = list(d.get("custom_labels", []))
    np = d.get("number_pos")
    if isinstance(np, dict):
        mode = np.get("mode")
        p.number_pos_mode = _STR_TO_POS.get(mode) if mode else None
        off = np.get("offset_mm")
        if isinstance(off, (list, tuple)) and len(off) >= 2:
            p.number_pos_offset_mm = (float(off[0]), float(off[1]))
    if "style_override" in d and isinstance(d["style_override"], dict):
        p.style_override = _style_from_dict(d["style_override"])
    return p


# ---------------------------------------------------------------------------
# computed 段（计算缓存持久化）辅助
# ---------------------------------------------------------------------------
def _overlap_fingerprint(config: DocumentConfig) -> str:
    """重叠检测结果指纹：影响重叠检测的全局参数拼接。

    全局样式（字号/四边距/垂直位置）+ 自动调整开关与级别 + 起始页码。
    任一变化 → 指纹变化 → 旧的 overlap 缓存视为失效（不预热）。
    单页覆盖（style_override / number_pos_override）不影响指纹（load_computed
    按页过滤覆盖页）；页码文本内容不影响（重叠检测只依赖页码矩形位置与字号）。
    """
    s = config.global_style
    parts = [
        str(s.fontsize_pt),
        str(s.margin_right_mm),
        str(s.margin_left_mm),
        str(s.margin_bottom_mm),
        str(s.margin_top_mm),
        str(s.vertical_position),
        str(config.auto_adjust_overlap),
        str(config.auto_shrink_levels),
        str(config.start_page_number),
    ]
    return "|".join(parts)


def _overlap_entry_to_dict(key: tuple, value: tuple) -> dict:
    """overlap_cache 条目 → JSON 字典。

    key = (src_index, PageNumberPos, fontsize_pt, total_rot,
           margin_right_mm, margin_left_mm, margin_bottom_mm, margin_top_mm)
    value = (text_hits list, pixel_hit bool, num_rect)
    """
    (src_idx, base, fontsize, total_rot,
     mr, ml, mb, mt) = key
    text_hits, pixel_hit, num_rect = value
    return {
        "key": [src_idx, _POS_TO_STR.get(base, str(base)), fontsize, total_rot,
                mr, ml, mb, mt],
        "text_hits": [[float(v) for v in h] for h in text_hits],
        "pixel_hit": bool(pixel_hit),
        "num_rect": [float(v) for v in num_rect],
    }


def _overlap_entry_from_dict(d: dict) -> tuple[tuple, tuple] | None:
    """JSON 字典 → overlap_cache 条目；损坏/不合法返回 None（跳过）。"""
    k = d.get("key")
    if not isinstance(k, (list, tuple)) or len(k) != 8:
        return None
    base = _STR_TO_POS.get(str(k[1])) if k[1] is not None else None
    if base is None:
        return None
    try:
        src_idx = int(k[0])
        fontsize = float(k[2])
        total_rot = int(k[3])
        mr, ml, mb, mt = (float(v) for v in k[4:8])
        text_hits = [tuple(float(v) for v in h) for h in d.get("text_hits", [])]
        pixel_hit = bool(d.get("pixel_hit", False))
        num_rect = tuple(float(v) for v in d.get("num_rect", []))
    except (TypeError, ValueError):
        return None
    if len(num_rect) != 4:
        return None
    key = (src_idx, base, fontsize, total_rot, mr, ml, mb, mt)
    return key, (text_hits, pixel_hit, num_rect)


# ---------------------------------------------------------------------------
# ConfigManager
# ---------------------------------------------------------------------------
class ConfigManager:
    """配置文件管理器。"""

    # -- 路径 --------------------------------------------------------------
    @staticmethod
    def config_path_for(pdf_path: str) -> str:
        """配置文件路径：原PDF同名 + .pagerconfig.json，位于原 PDF 所在文件夹。"""
        pdf_path = os.path.abspath(pdf_path)
        base = os.path.splitext(pdf_path)[0]
        return base + CONFIG_EXT

    # -- 基础 --------------------------------------------------------------
    def config_exists(self, pdf_path: str) -> bool:
        return os.path.isfile(self.config_path_for(pdf_path))

    def _read_raw(self, pdf_path: str) -> dict | None:
        path = self.config_path_for(pdf_path)
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            return None  # 损坏 JSON → 视为无配置
        return data if isinstance(data, dict) else None

    def _validate_config(self, data: dict, pdf_path: str) -> bool:
        """校验 version 与 source_file。不匹配返回 False（调用方回退默认）。

        v2 起支持空白页配置；v1（旧配置）接受并迁移（NO_COUNT → NO_NUMBER）。
        """
        version = data.get("version")
        if version not in (1, 2):
            return False
        src = data.get("source_file")
        if src is not None:
            norm_pdf = os.path.normcase(os.path.abspath(pdf_path))
            norm_src = os.path.normcase(os.path.abspath(str(src)))
            if norm_src != norm_pdf:
                return False
        return True

    # -- 全局配置 ----------------------------------------------------------
    def load_config(self, pdf_path: str) -> DocumentConfig:
        """加载全局配置。

        回退链：PDF 专属配置 → 应用级全局默认（global_default.json）→ 硬编码默认。
        无配置 / 损坏 / 版本或源文件不匹配时，优先回退应用级全局默认，使
        "保存为默认" 对打开新 PDF 自动生效；全局默认也不存在时才用硬编码默认。
        """
        data = self._read_raw(pdf_path)
        if data is None or not self._validate_config(data, pdf_path):
            return self.load_global_default() or DocumentConfig()
        cfg = DocumentConfig()
        cfg.version = CONFIG_VERSION
        self._apply_global_dict(cfg, data.get("global", {}) or {})
        cfg.config_filename = self.config_path_for(pdf_path)
        return cfg

    @staticmethod
    def _apply_global_dict(cfg: DocumentConfig, g: dict) -> None:
        """把配置文件的 global 段应用到 DocumentConfig（缺失字段保持默认）。"""
        if isinstance(g.get("start_page_number"), int):
            cfg.start_page_number = g["start_page_number"]
        if isinstance(g.get("style"), dict):
            cfg.global_style = _style_from_dict(g["style"])
        if isinstance(g.get("auto_fill_last_page"), bool):
            cfg.auto_fill_last_page = g["auto_fill_last_page"]
        if isinstance(g.get("auto_number_blank_pages"), bool):
            cfg.auto_number_blank_pages = g["auto_number_blank_pages"]
        if isinstance(g.get("auto_adjust_overlap"), bool):
            cfg.auto_adjust_overlap = g["auto_adjust_overlap"]
        if isinstance(g.get("auto_shrink_levels"), int):
            cfg.auto_shrink_levels = max(0, min(4, g["auto_shrink_levels"]))
        if isinstance(g.get("auto_detect_keywords"), dict):
            cfg.auto_detect_keywords = _keywords_from_dict(g["auto_detect_keywords"])
        if isinstance(g.get("custom_labels"), list):
            cfg.custom_labels = [str(x) for x in g["custom_labels"]]
        if isinstance(g.get("output_suffix"), str):
            cfg.output_suffix = g["output_suffix"]

    # -- 应用级全局默认配置（全局设置"保存为默认"） ------------------------
    @staticmethod
    def global_default_path() -> str:
        """应用级全局默认配置路径：优先 %APPDATA%/PDFSim/global_default.json。"""
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, GLOBAL_DEFAULT_DIRNAME, GLOBAL_DEFAULT_FILENAME)

    def load_global_default(self, path: str | None = None) -> DocumentConfig | None:
        """加载应用级全局默认配置；文件不存在 / 损坏 / 非对象返回 None。"""
        p = path or self.global_default_path()
        if not os.path.isfile(p):
            return None
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        cfg = DocumentConfig()
        cfg.config_filename = p
        self._apply_global_dict(cfg, data.get("global", {}) or {})
        return cfg

    def save_global_default(
        self, config: DocumentConfig, path: str | None = None
    ) -> str:
        """保存应用级全局默认配置（仅 global 段），返回写入路径。"""
        p = path or self.global_default_path()
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        data = {
            "version": CONFIG_VERSION,
            "global": {
                "start_page_number": config.start_page_number,
                "style": _style_to_dict(config.global_style),
                "auto_fill_last_page": config.auto_fill_last_page,
                "auto_number_blank_pages": config.auto_number_blank_pages,
                "auto_adjust_overlap": config.auto_adjust_overlap,
                "auto_shrink_levels": config.auto_shrink_levels,
                "auto_detect_keywords": _keywords_to_dict(config.auto_detect_keywords),
                "custom_labels": list(config.custom_labels),
                "output_suffix": config.output_suffix,
            },
        }
        self._atomic_write(p, data)
        return p

    def save_config(self, pdf_path: str, config: DocumentConfig) -> None:
        """保存全局配置（保留已有页面级配置）。"""
        path = self.config_path_for(pdf_path)
        data = self._read_raw(pdf_path) or {}
        data["version"] = CONFIG_VERSION
        data["source_file"] = os.path.abspath(pdf_path)
        data["global"] = {
            "start_page_number": config.start_page_number,
            "style": _style_to_dict(config.global_style),
            "auto_fill_last_page": config.auto_fill_last_page,
            "auto_number_blank_pages": config.auto_number_blank_pages,
            "auto_adjust_overlap": config.auto_adjust_overlap,
            "auto_shrink_levels": config.auto_shrink_levels,
            "auto_detect_keywords": _keywords_to_dict(config.auto_detect_keywords),
            "custom_labels": list(config.custom_labels),
            "output_suffix": config.output_suffix,
        }
        self._atomic_write(path, data)

    # -- 页面级配置 ----------------------------------------------------------
    def load_page_configs(self, pdf_path: str) -> dict[int | str, PageConfigData]:
        """加载页面级配置，返回 {键: PageConfigData}（int=源页 original_index，str=空白页 blank_id）。"""
        data = self._read_raw(pdf_path)
        if data is None or not self._validate_config(data, pdf_path):
            return {}
        out: dict[int | str, PageConfigData] = {}
        for item in data.get("pages", []):
            if not isinstance(item, dict):
                continue
            if "blank_id" not in item and "original_index" not in item:
                continue
            try:
                p = _page_from_dict(item)
                if p.key is None:
                    continue
                out[p.key] = p
            except (TypeError, ValueError, KeyError):
                continue
        return out

    def save_page_configs(
        self, pdf_path: str, page_configs: dict[int | str, PageConfigData]
    ) -> None:
        """保存页面级配置（保留已有全局配置）。"""
        path = self.config_path_for(pdf_path)
        data = self._read_raw(pdf_path) or {}
        data["version"] = CONFIG_VERSION
        data["source_file"] = os.path.abspath(pdf_path)
        ordered = [page_configs[k] for k in sorted(page_configs, key=_config_key_sort)]
        data["pages"] = [_page_to_dict(p) for p in ordered]
        self._atomic_write(path, data)

    def save_all(
        self,
        pdf_path: str,
        config: DocumentConfig,
        page_configs: dict[int | str, PageConfigData],
        rotation_cache: dict[int, int] | None = None,
        overlap_cache: dict[tuple, tuple] | None = None,
        overlap_fingerprint: str | None = None,
    ) -> None:
        """整体保存（全局 + 页面级 + 计算缓存 computed 段）。

        rotation_cache: {src_index: detected_rotation}——detected_rotation 只依赖
            源页文本内容，source_file 匹配即可复用（跨配置有效）。
        overlap_cache: 见 engine.build_process_plan 的 overlap_cache 参数；需
            overlap_fingerprint 与保存时一致才可复用（否则打开时不预热）。
        """
        path = self.config_path_for(pdf_path)
        data = {
            "version": CONFIG_VERSION,
            "source_file": os.path.abspath(pdf_path),
            "global": {
                "start_page_number": config.start_page_number,
                "style": _style_to_dict(config.global_style),
                "auto_fill_last_page": config.auto_fill_last_page,
                "auto_number_blank_pages": config.auto_number_blank_pages,
                "auto_adjust_overlap": config.auto_adjust_overlap,
                "auto_shrink_levels": config.auto_shrink_levels,
                "auto_detect_keywords": _keywords_to_dict(config.auto_detect_keywords),
                "custom_labels": list(config.custom_labels),
                "output_suffix": config.output_suffix,
            },
            "pages": [_page_to_dict(page_configs[k])
                      for k in sorted(page_configs, key=_config_key_sort)],
        }
        computed: dict = {}
        if rotation_cache:
            computed["rotations"] = {str(k): int(v) for k, v in rotation_cache.items()}
        if overlap_cache and overlap_fingerprint is not None:
            computed["overlap"] = {
                "fingerprint": overlap_fingerprint,
                "entries": [
                    _overlap_entry_to_dict(k, v)
                    for k, v in sorted(
                        overlap_cache.items(),
                        key=lambda kv: (kv[0][0], str(kv[0][1]), kv[0][2], kv[0][3]),
                    )
                ],
            }
        if computed:
            data["computed"] = computed
        self._atomic_write(path, data)

    def load_computed(
        self,
        pdf_path: str,
        current_fingerprint: str,
        source_pages: list[PageInfo] | None = None,
    ) -> tuple[dict[int, int], dict[tuple, tuple]]:
        """加载 computed 段（计算缓存），用于打开 PDF 时预热。

        - rotations: detected_rotation 只依赖源页内容，source_file 匹配即有效。
        - overlap: 需 current_fingerprint 与保存时指纹一致才返回；单页覆盖
          （style_override / number_pos_override）的页不预取——该页实际生效样式
          与全局指纹不一致，预取可能错误命中。
        - computed 段缺失 / 损坏不影响 global/pages（返回空缓存）。

        返回 (rotation_cache, overlap_cache)。
        """
        data = self._read_raw(pdf_path)
        if data is None or not self._validate_config(data, pdf_path):
            return {}, {}
        comp = data.get("computed")
        if not isinstance(comp, dict):
            return {}, {}
        rotations: dict[int, int] = {}
        rot_d = comp.get("rotations")
        if isinstance(rot_d, dict):
            for k, v in rot_d.items():
                try:
                    rotations[int(k)] = int(v)
                except (TypeError, ValueError):
                    continue
        overlap: dict[tuple, tuple] = {}
        ov_d = comp.get("overlap")
        if (
            isinstance(ov_d, dict)
            and isinstance(ov_d.get("entries"), list)
            and ov_d.get("fingerprint") == current_fingerprint
        ):
            overridden = set()
            if source_pages:
                for p in source_pages:
                    if p.original_index is None:
                        continue
                    if p.style_override is not None or p.number_pos_override is not None:
                        overridden.add(p.original_index)
            for item in ov_d["entries"]:
                if not isinstance(item, dict):
                    continue
                kv = _overlap_entry_from_dict(item)
                if kv is None:
                    continue
                key, value = kv
                if key[0] in overridden:
                    continue  # 有单页覆盖的页不预取
                overlap[key] = value
        return rotations, overlap

    # -- 应用页面配置到 PageInfo --------------------------------------------
    def apply_page_configs(
        self, source_pages: list[PageInfo], page_configs: dict[int, PageConfigData]
    ) -> None:
        """把页面级配置应用到 PageInfo（就地修改）；A3 页 front 标记强制存在。"""
        for p in source_pages:
            if p.original_index is None:
                continue
            pc = page_configs.get(p.original_index)
            if pc is None:
                continue
            p.marks.update(pc.marks)
            p.rotation_override = pc.rotation_override
            p.custom_labels = list(pc.custom_labels) or p.custom_labels
            if pc.number_pos_mode is not None:
                p.number_pos_override = pc.number_pos_mode
                p.number_custom_offset_mm = pc.number_pos_offset_mm
            if pc.style_override is not None:
                p.style_override = pc.style_override
            # A3 页 front 标记强制存在（只读）
            if is_a3(p):
                p.marks.add(PageMark.FRONT)

    def collect_page_configs(
        self,
        source_pages: list[PageInfo],
        plan: list | None = None,
    ) -> dict[int | str, PageConfigData]:
        """从 PageInfo 收集页面级配置（供保存）。

        源页：按 original_index；空白页：按 blank_id，仅收集用户显式标记非空的
        （空白页默认无配置，恢复来源默认行为）。plan 元素可为 PageInfo 或 ProcessedPage。
        """
        out: dict[int | str, PageConfigData] = {}
        for p in source_pages:
            if p.original_index is None:
                continue
            pc = PageConfigData(original_index=p.original_index)
            pc.marks = set(p.marks)
            pc.rotation_override = p.rotation_override
            pc.custom_labels = list(p.custom_labels)
            pc.number_pos_mode = p.number_pos_override
            pc.number_pos_offset_mm = p.number_custom_offset_mm
            pc.style_override = p.style_override
            out[p.original_index] = pc
        if plan:
            for item in plan:
                info = getattr(item, "source_page_info", item)
                if not getattr(info, "is_blank", False):
                    continue
                blank_id = getattr(info, "blank_id", None)
                marks = getattr(info, "marks", None)
                if blank_id and marks:
                    out[blank_id] = PageConfigData(
                        blank_id=blank_id, marks=set(marks))
        return out

    # -- 原子写入 ------------------------------------------------------------
    @staticmethod
    def _atomic_write(path: str, data: dict) -> None:
        d = os.path.dirname(path) or "."
        fd, tmp_path = tempfile.mkstemp(dir=d, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.write("\n")
            os.replace(tmp_path, path)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
