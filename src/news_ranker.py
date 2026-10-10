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
    # Başlıkların farklı olması aynı olayı iki ayrı Shorts olarak seçmemize yol açmasın.
    text = plain(str(item.get("title", "")) + " " + str(item.get("summary", "")))
    return {t for t in text.split() if len(t) > 2 and t not in STOPWORDS}


def vague_title(title: str) -> bool:
    normalized = plain(title)
    return any(plain(vague) == normalized for vague in VAGUE_HEADLINES) or len(normalized.split()) < 3


def similarity(a: dict, b: dict) -> float:
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    shared = ta & tb
    jaccard = len(shared) / len(ta | tb)
    containment = len(shared) / min(len(ta), len(tb))
    title_seq = SequenceMatcher(
        None, plain(a.get("title", "")), plain(b.get("title", ""))
    ).ratio()
    # A high shared-context score can reveal one event reported with different headlines.
    return max(jaccard, containment * 0.65, title_seq * 0.85)


def duplicate_event(a: dict, b: dict) -> bool:
    """Conservative event-level dedupe for differently worded headlines."""
    if similarity(a, b) >= 0.50:
        return True

    ta, tb = tokens(a), tokens(b)
    shared = ta & tb
    # Same show/franchise, same calendar day, and overlapping event vocabulary.
    franchise_terms = {"masterchef", "survivor", "kizilcik", "serbeti"}
    event_terms = {"eleme", "adayi", "potaya", "dokunulmazligi", "kazandi"}
    title_a = plain(a.get("title", ""))
    title_b = plain(b.get("title", ""))
    same_franchise = bool((ta & tb) & franchise_terms)
    same_event_vocabulary = len(shared & event_terms) >= 2 or (
        "masterchef" in shared and len(shared & {"eleme", "adayi", "potaya", "dokunulmazligi"}) >= 1
    )
    date_a = parse_date(a.get("published_at"))
    date_b = parse_date(b.get("published_at"))
    same_day = bool(date_a and date_b and date_a.date() == date_b.date())
    return same_franchise and same_event_vocabulary and same_day


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


def publisher_domain(item: dict) -> str:
    from urllib.parse import urlparse
    domain = str(item.get("source_domain") or urlparse(str(item.get("url", ""))).netloc).lower()
    return domain.removeprefix("www.").strip()


def source_articles(item: dict) -> list[dict]:
    articles = [{
        "source": item.get("source", "Bilinmeyen kaynak"),
        "source_domain": publisher_domain(item),
        "title": item.get("title", ""),
        "url": item.get("url", ""),
        "published_at": item.get("published_at"),
    }]
    for other in item.get("also_reported_by", []) or []:
        domain = str(other.get("source_domain") or publisher_domain(other))
        articles.append({
            "source": other.get("source", "Bilinmeyen kaynak"),
            "source_domain": domain,
            "title": other.get("title") or item.get("title", ""),
            "url": other.get("url", ""),
            "published_at": other.get("published_at"),
        })
    unique = {}
    for article in articles:
        key = article["source_domain"] or article["source"]
        if key not in unique:
            unique[key] = article
    return list(unique.values())


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

    # Group observations by event before selecting stories. Publisher coverage is
    # the primary ranking signal; editorial score breaks ties.
    ranked = []
    for item in items:
        points, reasons = score(item)
        candidate = dict(item)
        candidate["editorial_score"] = round(points, 2)
        candidate["ranking_reasons"] = reasons
        candidate["source_articles"] = source_articles(item)
        candidate["publisher_count"] = len({
            article["source_domain"] or article["source"]
            for article in candidate["source_articles"]
        })
        ranked.append(candidate)

    clusters: list[dict] = []
    for candidate in sorted(ranked, key=lambda x: (x["publisher_count"], x["editorial_score"]), reverse=True):
        match = next((cluster for cluster in clusters
                      if any(duplicate_event(candidate, member) for member in cluster["members"])), None)
        if match is None:
            clusters.append({"members": [candidate]})
        else:
            match["members"].append(candidate)

    event_groups = []
    for cluster in clusters:
        members = cluster["members"]
        representative = max(members, key=lambda x: (
            x["publisher_count"], x["editorial_score"], bool(x.get("image_url"))
        ))
        all_articles = []
        seen_domains, seen_urls = set(), set()
        for member in members:
            for article in member["source_articles"]:
                domain, url = article.get("source_domain") or article.get("source"), article.get("url")
                if domain in seen_domains or (url and url in seen_urls):
                    continue
                seen_domains.add(domain)
                if url:
                    seen_urls.add(url)
                all_articles.append(article)
        publisher_domains = sorted({
            article.get("source_domain") or article.get("source") for article in all_articles
        })
        count = len(publisher_domains)
        event_groups.append({
            **representative,
            "source_articles": all_articles,
            "publisher_domains": publisher_domains,
            "publisher_count": count,
            "coverage_label": ("çok kaynaklı ortak gündem" if count >= 3
                               else "iki yayın kuruluşunda yer alıyor" if count == 2
                               else "tek kaynaklı; ortak gündem olarak teyit edilmedi"),
            "event_member_count": len(members),
            "event_rank_score": round(count * 5 + representative["editorial_score"], 2),
            "status": "selected_not_verified",
        })

    event_groups.sort(key=lambda x: (
        x["publisher_count"], x["event_rank_score"], x["editorial_score"]
    ), reverse=True)
    multi_source = [g for g in event_groups if g["publisher_count"] >= 2]
    single_source = [g for g in event_groups if g["publisher_count"] == 1]
    selected = (multi_source + single_source)[:3]
    for item in selected:
        item["selection_basis"] = (
            "independent_publisher_coverage_then_editorial_score"
            if item["publisher_count"] >= 2 else "single_source_fallback_needs_manual_review"
        )

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "selection_count": len(selected),
        "target_count": 3,
        "candidate_count": len(items),
        "event_group_count": len(event_groups),
        "multi_publisher_event_count": len(multi_source),
        "note": (
            "Haberler olay düzeyinde gruplanır ve öncelikle farklı yayın kuruluşu alan adlarının "
            "sayısına göre sıralanır. Aynı yayın kuruluşunun birden fazla URL'si tek kaynak sayılır. "
            "Kaynak sayısı ortak gündem göstergesidir, doğruluk kanıtı değildir; içerik, bağlam ve "
            "görsel hakları ayrıca kontrol edilmelidir. Tek kaynaklı haberler yalnızca yeterli "
            "çok kaynaklı olay yoksa yedek olarak seçilir."
        ),
        "items": selected,
        "event_groups_preview": event_groups[:20],
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Ham tekil aday: {len(items)} | Olay grubu: {len(event_groups)} | Çok kaynaklı olay: {len(multi_source)}")
    print(f"Seçilen haber: {len(selected)}/3")
    for i, item in enumerate(selected, 1):
        sources = ", ".join(a.get("source", "?") for a in item["source_articles"])
        print(f"{i}. [{item['publisher_count']} yayın kuruluşu | puan {item['event_rank_score']}] {item.get('title', '(başlıksız)')}")
        print(f"   Kaynaklar: {sources}")
        print(f"   Kapsama: {item['coverage_label']}")
    print(f"Çıktı: {OUTPUT_PATH.relative_to(ROOT)}")
    if len(multi_source) < 3:
        print("UYARI: Üç çok kaynaklı olay bulunamadı; seçilen tek kaynaklı haberler manuel inceleme gerektirir.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
