from __future__ import annotations

import sqlite3
import tkinter
from pathlib import Path

import customtkinter as ctk
import pytest

from app import glossary
from app.core.models import LINK_PATTERN
from app.glossary import ALL_GROUPS, Term, find_terms, load_terms, search
from tests.tk_env import Env, card_texts, env, fresh  # noqa: F401

TERMS = load_terms()


# ---- dữ liệu -----------------------------------------------------------------------------


def test_terms_file_is_complete_and_clean() -> None:
    assert len(TERMS) >= 80
    names = [t.term.lower() for t in TERMS]
    assert len(names) == len(set(names)), "thuật ngữ bị trùng"
    for term in TERMS:
        assert term.term.strip() and term.full.strip() and term.group.strip() and term.vi.strip()
        for text in (term.full, term.vi, term.example):
            assert not LINK_PATTERN.search(text), f"{term.term} chứa link"
    assert {"RAG", "LLM", "MoE", "LoRA", "MCP", "Skill", "Subagent"} <= {t.term for t in TERMS}


def test_every_group_is_listed_once_after_all() -> None:
    groups = glossary.groups(TERMS)
    assert groups[0] == ALL_GROUPS and len(groups) == len(set(groups))
    assert "Claude & công cụ" in groups


def test_broken_or_missing_file_gives_no_terms(tmp_path: Path) -> None:
    bad = tmp_path / "bad.toml"
    bad.write_text("[[term]]\nterm = ", encoding="utf-8")
    assert load_terms(bad) == ()
    assert load_terms(tmp_path / "missing.toml") == ()
    no_vi = tmp_path / "no_vi.toml"
    no_vi.write_text('[[term]]\nterm = "X"\nfull = "X"\ngroup = "G"\n', encoding="utf-8")
    assert load_terms(no_vi) == ()


# ---- tìm kiếm ----------------------------------------------------------------------------


def test_search_puts_exact_name_first_and_ignores_case_and_accents() -> None:
    assert search(TERMS, "rag")[0].term == "RAG"
    assert search(TERMS, "  LoRA ")[0].term == "LoRA"
    accentless = search(TERMS, "huan luyen")
    assert accentless and all(
        "huấn luyện" in f"{t.full} {t.vi}".lower() or "huấn luyện" in t.group.lower()
        for t in accentless
    )
    assert search(TERMS, "zzz-không-có") == []


def test_search_by_alias_full_name_and_group() -> None:
    assert search(TERMS, "function calling")[0].term == "Tool use"
    assert any(t.term == "RAG" for t in search(TERMS, "retrieval"))
    claude = search(TERMS, group="Claude & công cụ")
    assert claude and all(t.group == "Claude & công cụ" for t in claude)
    assert search(TERMS, "rag", group="Claude & công cụ") == []
    assert search(TERMS) == list(TERMS)


# ---- nhận ra thuật ngữ trong bài ---------------------------------------------------------


def _names(text: str) -> list[str]:
    return [t.term for t in find_terms(text, TERMS)]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("New RAG pipeline uses MoE and LoRA", ["RAG", "MoE", "LoRA"]),
        ("garage sale; rag doll; Ann went home", []),  # ranh giới từ + hoa thường
        ("AI and API news", []),  # quá phổ biến nên không gắn chip
        ("Shrinking the KV cache with QLoRA", ["KV cache", "QLoRA"]),
        ("Write a better claude.md for your repo", ["CLAUDE.md"]),
        ("Whisper speech-to-text", ["ASR"]),  # khớp theo alias
        ("RAG, MoE, LoRA, MCP, RLHF and DPO", ["RAG", "MoE", "LoRA", "MCP"]),  # tối đa 4
        ("Tool use and skill files", []),  # từ thường (một chữ hoa) không gắn chip
    ],
)
def test_find_terms(text: str, expected: list[str]) -> None:
    assert _names(text) == expected


def test_taggable_needs_two_capitals_and_not_common() -> None:
    assert Term("RAG", "x", "g", "v", "e").taggable
    assert not Term("Token", "x", "g", "v", "e").taggable
    assert not Term("API", "x", "g", "v", "e", common=True).taggable


def test_terms_in_real_titles_from_fixtures() -> None:
    title = "Show HN: RAG over your PDFs with a local LLM"
    assert _names(title) == ["RAG", "LLM"]


# ---- tab Thuật ngữ trên widget ------------------------------------------------------------


def test_glossary_tab_search_and_group(fresh: Env) -> None:  # noqa: F811
    view = fresh.widget.glossary
    view._query.set("lora")
    view.render()
    assert view.shown[0].term == "LoRA"
    view._query.set("")
    view._on_group("Claude & công cụ")
    assert view.shown and all(t.group == "Claude & công cụ" for t in view.shown)
    view._group_menu.set(ALL_GROUPS)
    view._on_group(ALL_GROUPS)
    assert len(view.shown) == len(TERMS)


def _buttons(root: tkinter.Misc) -> list[ctk.CTkButton]:
    found: list[ctk.CTkButton] = []
    for child in root.winfo_children():
        if isinstance(child, ctk.CTkButton):
            found.append(child)
        found += _buttons(child)
    return found


def test_term_chip_on_card_opens_glossary_tab(fresh: Env) -> None:  # noqa: F811
    widget = fresh.widget
    db = fresh.path.parent / "ui.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE raw_items SET title = 'Rust 2.0 adds RAG and MoE' WHERE title = 'Rust 2.0 released'"
    )
    conn.commit()
    try:
        widget.refresh()
        card = widget._cards[fresh.ids["plain"]]
        chips = [b for b in _buttons(card) if b.cget("text") in {"RAG", "MoE"}]
        assert [b.cget("text") for b in chips] == ["RAG", "MoE"]
        chips[1].invoke()
        assert widget._tabs.get() == "Thuật ngữ"
        assert widget.glossary.shown[0].term == "MoE"
    finally:
        conn.execute(
            "UPDATE raw_items SET title = 'Rust 2.0 released' "
            "WHERE title = 'Rust 2.0 adds RAG and MoE'"
        )
        conn.commit()
        conn.close()
        widget._tabs.set("Tin tức")
        widget.refresh()
    assert not any(t == "RAG" for t in card_texts(widget))
