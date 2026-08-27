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
        """加载全局配置；无配置 / 损坏 / 版本或源文件不匹配时返回默认配置。"""
        data = self._read_raw(pdf_path)
        if data is None or not self._validate_config(data, pdf_path):
            return DocumentConfig()
        cfg = DocumentConfig()
        cfg.version = CONFIG_VERSION
        g = data.get("global", {}) or {}
        if isinstance(g.get("start_page_number"), int):
            cfg.start_page_number = g["start_page_number"]
        if isinstance(g.get("style"), dict):
            cfg.global_style = _style_from_dict(g["style"])
        if isinstance(g.get("auto_fill_last_page"), bool):
            cfg.auto_fill_last_page = g["auto_fill_last_page"]
        if isinstance(g.get("auto_number_blank_pages"), bool):
            cfg.auto_number_blank_pages = g["auto_number_blank_pages"]
        if isinstance(g.get("auto_detect_keywords"), dict):
            cfg.auto_detect_keywords = _keywords_from_dict(g["auto_detect_keywords"])
        if isinstance(g.get("custom_labels"), list):
            cfg.custom_labels = [str(x) for x in g["custom_labels"]]
        cfg.config_filename = self.config_path_for(pdf_path)
        return cfg

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
            "auto_detect_keywords": _keywords_to_dict(config.auto_detect_keywords),
            "custom_labels": list(config.custom_labels),
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
    ) -> None:
        """整体保存（全局 + 页面级）。"""
        path = self.config_path_for(pdf_path)
        data = {
            "version": CONFIG_VERSION,
            "source_file": os.path.abspath(pdf_path),
            "global": {
                "start_page_number": config.start_page_number,
                "style": _style_to_dict(config.global_style),
                "auto_fill_last_page": config.auto_fill_last_page,
                "auto_detect_keywords": _keywords_to_dict(config.auto_detect_keywords),
                "custom_labels": list(config.custom_labels),
            },
            "pages": [_page_to_dict(page_configs[k])
                      for k in sorted(page_configs, key=_config_key_sort)],
        }
        self._atomic_write(path, data)

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
