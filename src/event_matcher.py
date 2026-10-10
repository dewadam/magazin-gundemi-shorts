"""Conservative Turkish magazine event matching.

Same celebrity/show is not sufficient: matching requires event-specific headline
evidence. Ambiguous similarities are deliberately left for manual review.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher

GENERIC = {
    "ve", "ile", "icin", "bir", "bu", "su", "son", "sonra", "yeni",
    "magazin", "gundem", "oldu", "etti", "konustu", "paylasti",
    "aciklama", "iste", "sok", "unlu", "oyuncu", "kim", "ne", "ilk",
    "kez", "resmen", "dedi", "diye", "haber", "detay", "tum", "her",
    "gibi", "daha", "olan", "yine", "iddia", "iddiasi", "ekim", "2026",
}
SHOWS = {"masterchef", "survivor", "kizilcik", "serbeti"}
EVENT_WORDS = {
    "evlendi", "evlilik", "dugun", "nikah", "bosandi", "bosanma",
    "ayrildi", "ayrilik", "vefat", "olum", "hayatini", "kaybetti",
    "eleme", "adayi", "potaya", "dokunulmazlik", "dokunulmazligi",
    "kazandi", "elendi", "final", "gozaltina", "mahkeme", "hastane",
    "hamile", "dogum", "dogurdu", "nisanlandi", "nisan", "itiraf",
}
EVENT_ALIASES = {
    "dugun": "evlilik", "nikah": "evlilik", "evlendi": "evlilik",
    "bosandi": "bosanma", "bosaniyor": "bosanma", "bosanma": "bosanma",
    "ayrildi": "ayrilik", "ayriliyor": "ayrilik",
    "vefat": "olum", "oldu": "olum", "kaybetti": "olum",
    "hayatini": "olum", "hayatini_kaybetti": "olum",
    "dokunulmazligi": "dokunulmazlik",
    "elendi": "eleme", "elenen": "eleme",
    "nisanlandi": "nisan",
}


def normalize(value: str) -> str:
    value = str(value or "").replace("ı", "i").replace("İ", "i")
    value = unicodedata.normalize("NFKD", value.casefold())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value)).strip()


def words(value: str) -> set[str]:
    return {w for w in normalize(value).split() if len(w) > 2 and w not in GENERIC}


def event_terms(title: str) -> set[str]:
    # Event verbs must be read before generic stopword removal (e.g. "oldu").
    raw = set(normalize(title).split())
    result = {EVENT_ALIASES.get(w, w) for w in raw if w in EVENT_WORDS or w in EVENT_ALIASES}
    # Turkish death headlines often express the event as a phrase.
    if {"hayatini", "kaybetti"} <= raw:
        result.add("olum")
    return result


def same_event(a: dict, b: dict) -> tuple[bool, float, str]:
    ta, tb = words(a.get("title", "")), words(b.get("title", ""))
    if not ta or not tb:
        return False, 0.0, "empty_title"
    # Title is authoritative for event identity; summaries may contain unrelated
    # recommendations, ads, or syndicated descriptions.
    shared = ta & tb
    distinct_shared = shared - SHOWS
    overlap = len(shared) / min(len(ta), len(tb))
    jaccard = len(shared) / len(ta | tb)
    seq = SequenceMatcher(None, normalize(a.get("title", "")), normalize(b.get("title", ""))).ratio()
    score = max(jaccard, overlap * 0.85, seq * 0.80)
    ea, eb = event_terms(a.get("title", "")), event_terms(b.get("title", ""))
    action_agrees = bool(ea & eb)
    if ea and eb and not action_agrees:
        return False, score, "different_event_actions"
    if not distinct_shared:
        return False, score, "only_show_or_generic_terms"
    if len(distinct_shared) < 2:
        return False, score, "insufficient_distinctive_overlap"
    # An identical named subject with two different developments must not merge.
    if (ta & SHOWS) and (tb & SHOWS) and not (ea & eb) and score < 0.80:
        return False, score, "same_show_not_same_event"
    # Publication dates farther apart are weak evidence for the same daily event.
    try:
        da = datetime.fromisoformat(str(a.get("published_at", "")).replace("Z", "+00:00"))
        db = datetime.fromisoformat(str(b.get("published_at", "")).replace("Z", "+00:00"))
        if abs((da - db).total_seconds()) > 72 * 3600:
            return False, score, "publication_dates_far_apart"
    except (ValueError, TypeError):
        pass
    matched = score >= 0.59 or (action_agrees and len(shared) >= 2 and score >= 0.50)
    return matched, score, ("headline_event_match" if matched else "weak_match")


def group_events(items: list[dict]) -> tuple[list[list[dict]], list[dict]]:
    clusters: list[list[dict]] = []
    review: list[dict] = []
    for item in items:
        best_index, best_score = None, 0.0
        for i, members in enumerate(clusters):
            # Complete-link against all existing cluster members prevents chaining
            # A~B and B~C from merging unrelated A and C.
            comparisons = [same_event(item, member) for member in members]
            if all(matched for matched, _, _ in comparisons):
                minimum = min(score for _, score, _ in comparisons)
                if minimum > best_score:
                    best_index, best_score = i, minimum
            elif any(score >= 0.45 and reason not in {
                "different_event_actions", "same_show_not_same_event",
                "only_show_or_generic_terms", "publication_dates_far_apart",
            } for _, score, reason in comparisons):
                review.append({
                    "title": item.get("title", ""),
                    "possible_group": members[0].get("title", ""),
                    "reason": "borderline_match_not_counted",
                })
        if best_index is None:
            clusters.append([item])
        else:
            clusters[best_index].append(item)
    return clusters, review
