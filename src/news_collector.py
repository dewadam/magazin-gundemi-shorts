from __future__ import annotations

import json
import logging
import re
import sys
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import feedparser

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "src" / "sources.json"
LOG = logging.getLogger("news_collector")


def clean_text(value: object) -> str:
    text = str(value or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_title(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"[^a-z0-9ğüşöçıİ]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def parse_published(entry: object) -> str | None:
    parsed = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if not parsed:
        return None
    try:
        return datetime.fromtimestamp(time.mktime(parsed), tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def within_lookback(published_at: str | None, hours: int) -> bool:
    # Tarihi olmayan öğeleri ilk aşamada tutuyoruz; sonraki aşamada manuel kontrol edeceğiz.
    if not published_at:
        return True
    try:
        stamp = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return stamp >= datetime.now(timezone.utc) - timedelta(hours=hours)
    except ValueError:
        return False


def fetch_source(source: dict, max_items: int, lookback_hours: int) -> list[dict]:
    name = source.get("name", urlparse(source["url"]).netloc)
    LOG.info("RSS okunuyor: %s", name)
    feed = feedparser.parse(source["url"], request_headers={"User-Agent": "MagazinGundemiShorts/0.1"})
    if getattr(feed, "bozo", False):
        LOG.warning("%s akışında biçim uyarısı: %s", name, getattr(feed, "bozo_exception", "bilinmeyen hata"))
    if not feed.entries:
        LOG.warning("%s akışında haber bulunamadı. URL doğrudan RSS/XML olmayabilir.", name)
        return []

    items = []
    for entry in feed.entries[:max_items]:
        title = clean_text(getattr(entry, "title", ""))
        link = clean_text(getattr(entry, "link", ""))
        if not title or not link or not link.startswith(("https://", "http://")):
            continue
        published_at = parse_published(entry)
        if not within_lookback(published_at, lookback_hours):
            continue
        summary = clean_text(getattr(entry, "summary", "") or getattr(entry, "description", ""))
        image_url = None
        for media in getattr(entry, "media_content", []) or []:
            candidate = media.get("url")
            if candidate and str(media.get("type", "")).startswith("image"):
                image_url = candidate
                break
        if not image_url:
            for link_item in getattr(entry, "links", []) or []:
                if link_item.get("rel") == "enclosure" and str(link_item.get("type", "")).startswith("image"):
                    image_url = link_item.get("href")
                    break
        items.append({
            "title": title,
            "normalized_title": normalize_title(title),
            "url": link,
            "source": name,
            "source_domain": urlparse(link).netloc.removeprefix("www.").lower(),
            "published_at": published_at,
            "summary": summary[:1200],
            "image_url": image_url,
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "status": "collected_not_verified"
        })
    return items


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not CONFIG_PATH.exists():
        LOG.error("Kaynak ayar dosyası bulunamadı: %s", CONFIG_PATH)
        return 2

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    settings = config.get("settings", {})
    lookback_hours = int(settings.get("lookback_hours", 48))
    max_items = int(settings.get("max_items_per_source", 40))
    output_path = ROOT / settings.get("output_path", "data/news_latest.json")
    enabled_sources = [source for source in config.get("sources", []) if source.get("enabled", False)]
    if not enabled_sources:
        LOG.error("Etkin RSS kaynağı yok. src/sources.json dosyasını kontrol edin.")
        return 2

    collected: list[dict] = []
    for source in enabled_sources:
        try:
            collected.extend(fetch_source(source, max_items, lookback_hours))
        except Exception:
            LOG.exception("Kaynak okunamadı: %s", source.get("name", source.get("url", "bilinmiyor")))

    unique: dict[str, dict] = {}
    for item in collected:
        key = item["normalized_title"] or item["url"]
        if key not in unique:
            unique[key] = item
            unique[key]["also_reported_by"] = []
        else:
            existing = unique[key]
            existing["also_reported_by"].append({
                "source": item["source"], "source_domain": item["source_domain"], "title": item["title"], "url": item["url"], "published_at": item["published_at"]
            })
            if len(item.get("summary", "")) > len(existing.get("summary", "")):
                existing["summary"] = item["summary"]

    results = sorted(unique.values(), key=lambda item: item.get("published_at") or "", reverse=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "lookback_hours": lookback_hours,
        "source_count": len(enabled_sources),
        "collected_count_before_deduplication": len(collected),
        "unique_count": len(results),
        "note": "Ham aday haberlerdir; doğrulanmış haber veya görsel kullanım izni anlamına gelmez.",
        "items": results
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LOG.info("Toplanan: %d | Tekil aday: %d | Çıktı: %s", len(collected), len(results), output_path)
    print(f"\nHaber toplama tamamlandı: {len(results)} tekil aday haber.")
    print(f"JSON çıktısı: {output_path.relative_to(ROOT)}")
    for item in results[:10]:
        print(f"- [{item['source']}] {item['title']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
