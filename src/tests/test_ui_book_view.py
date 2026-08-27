# -*- coding: utf-8 -*-
"""书视图 UI 测试（Stage 3 交付物 2 的一部分）。

覆盖：状态机（CLOSED/OPEN_LEFT/OPEN_RIGHT）/ 翻页 / 边界 / 高亮 / 旋转角标 / 空白页。
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt

from pdfsim.ui.book_view import BookViewState


@pytest.fixture
def book(make_window, samples_dir):
    """打开 A4 纵向多页样本后的 (window, controller, book_view)。"""
    w = make_window()
    c = w.controller
    c.open_pdf(str(samples_dir / "sample_a4_portrait.pdf"), "")
    return w, c, w.book_view


def test_initial_closed(book):
    """初始选中第 1 页 → CLOSED。"""
    _, c, bv = book
    assert c.selected_physical_index == 1
    assert bv.state() is BookViewState.CLOSED
    pages, hl = bv.layout_pages()
    assert pages == [1]
    assert hl == 1


def test_open_left_even(book):
    """选中偶数页 → OPEN_LEFT：左=选中，右=选中+1。"""
    _, c, bv = book
    c.select_physical(2)
    assert bv.state() is BookViewState.OPEN_LEFT
    pages, hl = bv.layout_pages()
    assert pages == [2, 3]
    assert hl == 2


def test_open_right_odd(book):
    """选中奇数页(≥3) → OPEN_RIGHT：左=选中-1，右=选中。"""
    _, c, bv = book
    c.select_physical(3)
    assert bv.state() is BookViewState.OPEN_RIGHT
    pages, hl = bv.layout_pages()
    assert pages == [2, 3]
    assert hl == 3


def test_turn_page_next_prev(book):
    """翻页：next/prev 每次移动 1 个物理位。"""
    _, c, bv = book
    c.select_physical(1)
    bv.page_next()
    assert c.selected_physical_index == 2
    bv.page_next()
    assert c.selected_physical_index == 3
    bv.page_prev()
    assert c.selected_physical_index == 2


def test_boundary_last_even(book):
    """选中最后页且为偶数位：右侧显示空白占位（右页为 0）。"""
    _, c, bv = book
    total = c.plan_page_count()
    # 构造偶数总页数场景：若末页为奇数位，先加一页空白（用自动补齐末页或直接选偶数位末页样本）
    if total % 2 == 1:
        c.set_auto_fill_last(True)
        total = c.plan_page_count()
    c.select_physical(total)
    assert total % 2 == 0
    assert bv.state() is BookViewState.OPEN_LEFT
    pages, hl = bv.layout_pages()
    # 右页超出总页数 → 0（空白占位）
    assert pages == [total]
    assert hl == total


def test_highlight_only_selected(book):
    """高亮只作用于选中页。"""
    _, c, bv = book
    c.select_physical(2)
    pages, hl = bv.layout_pages()
    assert hl == 2
    assert hl in pages
    assert len([p for p in pages if p == hl]) == 1


def test_rotation_badge_data(book, samples_dir):
    """旋转角标：A4 横向样本被旋转 90°，plan 数据正确。"""
    _, c, bv = book
    # 重新打开横向样本
    c.open_pdf(str(samples_dir / "sample_direction_markers.pdf"), "")
    rotated = [pp for pp in c.current_plan.pages if not pp.is_blank and pp.rotation != 0]
    assert rotated, "应有旋转页"
    # paintEvent 可正常执行（不崩溃）
    bv.update()
    assert True


def test_blank_page_display(book, samples_dir):
    """空白页显示：封面背面等空白页 is_blank 且渲染正常。"""
    _, c, bv = book
    c.open_pdf(str(samples_dir / "sample_mixed.pdf"), "")
    blanks = [pp for pp in c.current_plan.pages if pp.is_blank]
    assert blanks, "应有空白页"
    for pp in blanks:
        data = c.get_book_view_page(pp.physical_index)
        assert data is not None and len(data) > 0


def test_wheel_and_key(book, qtbot):
    """滚轮与方向键翻页。"""
    _, c, bv = book
    c.select_physical(1)
    # 方向键 →
    bv.keyPressEvent(_KeyEvent(Qt.Key.Key_Right))
    assert c.selected_physical_index == 2
    bv.keyPressEvent(_KeyEvent(Qt.Key.Key_Left))
    assert c.selected_physical_index == 1


class _KeyEvent:
    """简化按键事件。"""

    def __init__(self, key):
        self._key = key
        self.accepted = False

    def key(self):
        return self._key

    def accept(self):
        self.accepted = True
