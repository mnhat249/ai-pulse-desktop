"""Cho chữ xuống dòng theo độ rộng thật của khung (thay cho `wraplength` cố định)."""

from __future__ import annotations

import tkinter
from typing import Any

import customtkinter as ctk

DEBOUNCE_MS = 120
MIN_WRAP = 200
STEP = 8  # đổi ít hơn số pixel này thì không cập nhật, tránh dựng lại khi kéo cửa sổ


class Wrapper:
    """Giữ các label xuống dòng của một khung và chỉnh `wraplength` khi khung đổi độ rộng.

    `margin` là phần đệm (theo đơn vị chưa nhân DPI) giữa mép khung và chữ; `scaled_by` là widget
    customtkinter cho biết hệ số DPI khi `frame` là widget Tk thường (ví dụ canvas của khung cuộn).
    """

    def __init__(
        self, frame: tkinter.Misc, margin: int, initial: int, scaled_by: Any = None
    ) -> None:
        self._frame = frame
        self._scaled_by = scaled_by if scaled_by is not None else frame
        self._margin = margin
        self.width = max(MIN_WRAP, initial)
        self._labels: list[tuple[ctk.CTkLabel, int]] = []
        self._job: str | None = None
        frame.bind("<Configure>", self._on_configure, add="+")

    def label(self, parent: Any, *, indent: int = 0, **options: Any) -> ctk.CTkLabel:
        """CTkLabel xuống dòng theo độ rộng khung; `indent` trừ thêm phần thụt vào."""
        widget = ctk.CTkLabel(parent, wraplength=self.width - indent, **options)
        self._labels.append((widget, indent))
        return widget

    def forget_dead(self) -> None:
        self._labels = [(w, i) for w, i in self._labels if w.winfo_exists()]

    def _scaling(self) -> float:
        getter = getattr(self._scaled_by, "_get_widget_scaling", None)
        return float(getter()) if getter else 1.0

    def _on_configure(self, event: tkinter.Event) -> None:
        if self._job is not None:
            self._frame.after_cancel(self._job)
        self._job = self._frame.after(DEBOUNCE_MS, lambda: self.resize(event.width))

    def resize(self, pixel_width: int) -> None:
        self._job = None
        width = max(MIN_WRAP, round(pixel_width / self._scaling()) - self._margin)
        if abs(width - self.width) < STEP:
            return
        self.width = width
        self.forget_dead()
        for widget, indent in self._labels:
            widget.configure(wraplength=width - indent)
