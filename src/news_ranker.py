from __future__ import annotations

import json
import logging
import re
import sys
import unicodedata
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT_PATH = ROOT / "data" / "news_latest.json"
OUTPUT_PATH = ROOT / "data" / "selected_news.json"
LOG = logging.getLogger("news_ranker")

STOPWORDS = {
    "ve", "ile", "icin", "için", "bir", "bu", "su", "şu", "o", "da", "de",
    "mi", "mu", "mı", "mü", "son", "sonra", "aciklama", "açıklama", "resmen",
    "iste", "işte", "yeni", "gundem", "gündem", "magazin", "oldu", "etti",
    "ediyor", "konustu", "konuştu", "paylasti", "paylaştı", "geldi", "yapti",
    "yaptı", "kim", "ne", "var", "yok", "ilk", "kez", "iddia", "iddiasi",
}
VAGUE_HEADLINES = {
    "askini paylasti", "aşkını paylaştı", "ve resmen bitti", "sessizligini bozdu",
    "sessizliğini bozdu", "sular durulmuyor", "gundem oldu", "gündem oldu",
    "olay oldu", "sok sozler", "şok sözler", "iste o anlar", "işte o anlar",
}
IMPORTANT_TERMS = {
    "vefat", "oldu", "hayatını kaybetti", "hayatini kaybetti", "evlendi",
    "bosandi", "boşandı", "ayrildi", "ayrıldı", "elendi", "final", "itiraf",
    "mahkeme", "gozaltina", "gözaltına", "duyurdu", "acikladi", "açıkladı",
    "survivor", "masterchef", "kizilcik serbeti", "kızılcık şerbeti",
}


def plain(text: str) -> str:
    text = unicodedata.normalize("NFKD", (text or "").casefold())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokens(item: dict) -> set[str]:
    title = plain(item.get("title", ""))
    return {t for t in title.split() if len(t) > 2 and t not in STOPWORDS}


def vague_title(title: str) -> bool:
    normalized = plain(title)
    return any(plain(vague) == normalized for vague in VAGUE_HEADLINES) or len(normalized.split()) < 3


def similarity(a: dict, b: dict) -> float:
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    jaccard = len(ta & tb) / len(ta | tb)
    seq = SequenceMatcher(None, plain(a.get("title", "")), plain(b.get("title", ""))).ratio()
    # Shared distinctive tokens often indicate the same person/event even when wording differs.
    shared = len(ta & tb)
    return max(jaccard, seq * 0.85, 0.72 if shared >= 2 and min(len(ta), len(tb)) <= 5 else 0.0)


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def score(item: dict) -> tuple[float, list[str]]:
    title = item.get("title", "")
    body = item.get("summary", "")
    haystack = plain(title + " " + body)
    points = 0.0
    reasons = []

    if not vague_title(title):
        points += 3
        reasons.append("anlaşılır başlık")
    else:
        points -= 5
        reasons.append("belirsiz başlık")

    if len(plain(body).split()) >= 18:
        points += 2
        reasons.append("yeterli özet")
    elif len(plain(body).split()) < 6:
        points -= 2
        reasons.append("zayıf özet")

    matched = [term for term in IMPORTANT_TERMS if plain(term) in haystack]
    if matched:
        points += min(3, 1 + 0.5 * len(matched))
        reasons.append("haber değeri taşıyan konu")

    published = parse_date(item.get("published_at"))
    if published:
        age_hours = max(0.0, (datetime.now(timezone.utc) - published).total_seconds() / 3600)
        points += max(0.0, 4.0 * (1 - age_hours / 48))
        reasons.append("güncellik")
    else:
        points -= 1
        reasons.append("yayın tarihi yok")

    if item.get("image_url"):
        points += 0.5
        reasons.append("görsel adayı mevcut")

    # This is a heuristic ranking, not verification of the story.
    return points, reasons


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not INPUT_PATH.exists():
        LOG.error("Girdi bulunamadı: %s", INPUT_PATH)
        return 2

    payload = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    items = payload.get("items", [])
    if not isinstance(items, list):
        LOG.error("news_latest.json içindeki items alanı liste değil.")
        return 2

    ranked = []
    for item in items:
        points, reasons = score(item)
        candidate = dict(item)
        candidate["ranking_score"] = round(points, 2)
        candidate["ranking_reasons"] = reasons
        candidate["status"] = "selected_not_verified"
        ranked.append(candidate)
    ranked.sort(key=lambda x: x["ranking_score"], reverse=True)

    selected = []
    rejected_duplicates = []
    for candidate in ranked:
        if candidate["ranking_score"] < 1:
            continue
        duplicate_of = next((chosen for chosen in selected if similarity(candidate, chosen) >= 0.62), None)
        if duplicate_of:
            rejected_duplicates.append({
                "title": candidate.get("title"),
                "url": candidate.get("url"),
                "duplicate_of": duplicate_of.get("title"),
                "reason": "Muhtemel aynı olay; otomatik benzerlik kontrolü"
            })
            continue
        selected.append(candidate)
        if len(selected) >= 3:
            break

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "selection_count": len(selected),
        "target_count": 3,
        "note": "Otomatik puanlama ve benzerlik kontrolüdür. Haberlerin doğruluğu, kişi/olay bağlamı ve görsel kullanım hakları ayrıca doğrulanmalıdır. Otomatik seçim yayın onayı değildir.",
        "items": selected,
        "possible_duplicates_skipped": rejected_duplicates,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Seçilen haber: {len(selected)}/3")
    for i, item in enumerate(selected, 1):
        print(f"{i}. [{item['ranking_score']}] {item.get('title', '(başlıksız)')}")
    print(f"Çıktı: {OUTPUT_PATH.relative_to(ROOT)}")
    if len(selected) < 3:
        print("UYARI: Yeterli puan alan 3 farklı haber bulunamadı; zayıf haberlerle sayı tamamlanmadı.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
