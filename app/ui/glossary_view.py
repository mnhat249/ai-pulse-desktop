"""Tab "Thuật ngữ": tìm và đọc giải thích các từ viết tắt AI / CS."""

from __future__ import annotations

from typing import Any

import customtkinter as ctk

from app import glossary
from app.glossary import ALL_GROUPS, Term
from app.ui import theme
from app.ui.wrapping import Wrapper

SEARCH_DEBOUNCE_MS = 250
CARD_RADIUS = 6
TEXT_MARGIN = 44  # đệm của danh sách + thẻ, tính từ mép khung cuộn tới chữ


class GlossaryView(ctk.CTkFrame):  # type: ignore[misc]
    """Ô tìm, chọn nhóm và danh sách thẻ thuật ngữ. Chỉ đọc dữ liệu đã nạp sẵn trong RAM."""

    def __init__(
        self, parent: Any, terms: tuple[Term, ...], fonts: dict[str, ctk.CTkFont], width: int
    ) -> None:
        super().__init__(parent, fg_color="transparent")
        self._terms = terms
        self._fonts = fonts
        self._group = ALL_GROUPS
        self._job: str | None = None
        self.shown: list[Term] = []

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=6, pady=(4, 4))
        self._query = ctk.StringVar()
        self._entry = ctk.CTkEntry(
            top,
            textvariable=self._query,
            placeholder_text="Tìm: RAG, LoRA, huấn luyện…",
            font=fonts["body"],
            height=30,
            fg_color=theme.CARD,
            border_color=theme.BORDER,
            text_color=theme.INK,
        )
        self._entry.pack(side="left", fill="x", expand=True)
        self._group_menu = ctk.CTkOptionMenu(
            top,
            values=glossary.groups(terms),
            command=self._on_group,
            width=150,
            font=fonts["body"],
            dropdown_font=fonts["body"],
            fg_color=theme.CARD,
            button_color=theme.TRACK,
            button_hover_color=theme.BORDER,
            text_color=theme.INK,
            dropdown_fg_color=theme.CARD,
            dropdown_text_color=theme.INK,
        )
        self._group_menu.pack(side="right", padx=(6, 0))
        self._count = ctk.CTkLabel(
            self, text="", font=fonts["small"], text_color=theme.MUTED, anchor="w", height=14
        )
        self._count.pack(fill="x", padx=10)
        self._list = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._list.pack(fill="both", expand=True, pady=(2, 4))
        self._wrap = Wrapper(
            self._list._parent_canvas, TEXT_MARGIN, width - TEXT_MARGIN, scaled_by=self._list
        )
        self._query.trace_add("write", lambda *_: self._schedule())
        self.rendered = False  # dựng thẻ khi mở tab lần đầu, không làm chậm lúc mở app

    def focus_search(self) -> None:
        if not self.rendered:
            self.render()
        self._entry.focus_set()

    def show_term(self, term: str) -> None:
        """Mở đúng một thuật ngữ (bấm chip trên thẻ tin)."""
        self._group = ALL_GROUPS
        self._group_menu.set(ALL_GROUPS)
        self._query.set(term)
        self.render()

    def _on_group(self, group: str) -> None:
        self._group = group
        self.render()

    def _schedule(self) -> None:
        if self._job is not None:
            self.after_cancel(self._job)
        self._job = self.after(SEARCH_DEBOUNCE_MS, self.render)

    def render(self) -> None:
        if self._job is not None:
            self.after_cancel(self._job)
            self._job = None
        self.rendered = True
        for child in self._list.winfo_children():
            child.destroy()
        self._wrap.forget_dead()
        self.shown = glossary.search(self._terms, self._query.get(), self._group)
        self._count.configure(text=f"{len(self.shown)} / {len(self._terms)} thuật ngữ")
        if not self.shown:
            ctk.CTkLabel(
                self._list,
                text="Không có thuật ngữ nào khớp.",
                font=self._fonts["body"],
                text_color=theme.MUTED,
            ).pack(pady=20)
        for term in self.shown:
            self._add_card(term)
        self._list._parent_canvas.yview_moveto(0)

    def _add_card(self, term: Term) -> None:
        card = ctk.CTkFrame(
            self._list,
            corner_radius=CARD_RADIUS,
            fg_color=theme.CARD,
            border_width=1,
            border_color=theme.BORDER,
        )
        card.pack(fill="x", pady=3, padx=6)
        head = ctk.CTkFrame(card, fg_color="transparent")
        head.pack(fill="x", padx=12, pady=(10, 0))
        ctk.CTkLabel(
            head, text=term.term, font=self._fonts["term"], text_color=theme.INK, anchor="w"
        ).pack(side="left")
        ctk.CTkLabel(
            head,
            text=term.group,
            font=self._fonts["chip"],
            text_color=theme.INK,
            fg_color=theme.SELECTED,
            corner_radius=4,
            height=18,
        ).pack(side="right")
        if term.full != term.term:
            self._wrap.label(
                card,
                text=term.full,
                font=self._fonts["lead"],
                text_color=theme.MUTED,
                anchor="w",
                justify="left",
            ).pack(fill="x", padx=12)
        self._wrap.label(
            card,
            text=term.vi,
            font=self._fonts["body"],
            text_color=theme.INK,
            anchor="w",
            justify="left",
        ).pack(fill="x", padx=12, pady=(6, 0 if term.example else 10))
        if term.example:
            self._wrap.label(
                card,
                text=f"Ví dụ: {term.example}",
                font=self._fonts["small"],
                text_color=theme.MUTED,
                anchor="w",
                justify="left",
            ).pack(fill="x", padx=12, pady=(4, 10))
