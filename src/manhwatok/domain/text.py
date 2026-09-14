"""Small text helpers for slides and drafts: hook prefill and *accent* markup."""

from __future__ import annotations

import re

_SENTENCE_END = re.compile(r"[.!?](?=\s|$)")
_ACCENT = re.compile(r"\*([^*]+)\*")


def first_sentence(desc: str, max_len: int = 110) -> str:
    """First sentence of the first line, cut at a word boundary with '…' if longer than max_len."""
    first_line = desc.strip().split("\n", 1)[0].strip()
    if not first_line:
        return ""
    end = _SENTENCE_END.search(first_line)
    sentence = first_line[: end.end()] if end else first_line
    if len(sentence) <= max_len:
        return sentence
    cut = sentence.rfind(" ", 0, max_len)
    if cut <= 0:
        cut = max_len - 1
    return sentence[:cut].rstrip(" ,;:") + "…"


def accent_spans(title: str) -> list[tuple[str, bool]]:
    """Split `a *b* c` into [("a ", False), ("b", True), (" c", False)]; a lone `*` is literal."""
    spans: list[tuple[str, bool]] = []
    pos = 0
    for m in _ACCENT.finditer(title):
        if m.start() > pos:
            spans.append((title[pos : m.start()], False))
        spans.append((m.group(1), True))
        pos = m.end()
    if pos < len(title):
        spans.append((title[pos:], False))
    return spans


def plain_title(title: str) -> str:
    return "".join(text for text, _ in accent_spans(title))
