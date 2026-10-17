"""Factual opening-hook selection for Magazin Gündemi Shorts.

This module deliberately uses only the verified publisher title/body already
collected by the pipeline. It does not invent reactions, motives, or claims.
"""
from __future__ import annotations

import re
from typing import Iterable


def _clean(value: str) -> str:
    return re.sub(r"\\s+", " ", str(value or "")).strip(" \\t\\r\\n.•-")


def _sentences(paragraphs: Iterable[str]) -> list[str]:
    result: list[str] = []
    for paragraph in paragraphs:
        for sentence in re.split(r"(?<=[.!?])\\s+", _clean(paragraph)):
            sentence = _clean(sentence)
            words = sentence.split()
            if 7 <= len(words) <= 25 and 45 <= len(sentence) <= 190:
                if sentence not in result:
                    result.append(sentence)
    return result


def _score(text: str, source_sentence: bool) -> int:
    words = text.split()
    score = 0
    if 7 <= len(words) <= 16:
        score += 25
    elif len(words) <= 22:
        score += 15
    else:
        score += 5
    if any(ch.isdigit() for ch in text):
        score += 8
    if "“" in text or '"' in text or "‘" in text:
        score += 5
    if source_sentence:
        score += 20
    # Avoid clickbait wording unless the words are literally part of the source.
    clickbait = ("şok", "bomba", "büyük sır", "herkes şaşkın", "ortaya çıktı")
    if any(term in text.casefold() for term in clickbait) and not source_sentence:
        score -= 30
    return score


def generate_hook(title: str, paragraphs: Iterable[str]) -> dict:
    """Return three grounded candidates and a deterministic best candidate."""
    title = _clean(title)
    leads = _sentences(paragraphs)
    candidates: list[dict] = []

    if title:
        candidates.append({
            "type": "headline",
            "text": title,
            "source_grounded": True,
            "score": _score(title, False) + 5,
        })
    if leads:
        candidates.append({
            "type": "publisher_lead",
            "text": leads[0],
            "source_grounded": True,
            "score": _score(leads[0], True),
        })
    if len(leads) > 1:
        candidates.append({
            "type": "publisher_detail",
            "text": leads[1],
            "source_grounded": True,
            "score": _score(leads[1], True) - 3,
        })

    # Stable tie-break: prefer the shorter candidate, then original order.
    candidates.sort(key=lambda c: (-c["score"], len(c["text"])))
    if not candidates:
        return {
            "selected": "",
            "selected_type": "none",
            "candidates": [],
            "note": "Kaynakta kullanılabilir giriş bulunamadı; video üretilmemeli.",
        }
    chosen = candidates[0]
    return {
        "selected": chosen["text"],
        "selected_type": chosen["type"],
        "candidates": candidates[:3],
        "note": "Adaylar yalnızca haber başlığı ve yayıncı metninden seçildi; uydurma iddia eklenmedi.",
    }
