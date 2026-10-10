from __future__ import annotations

import json
import logging
import re
import sys
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "src" / "sources.json"
LOG = logging.getLogger("news_collector")
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/128.0.0.0 Safari/537.36"


def clean_text(value: object) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(value or ""))).strip()


def normalize_title(value: str) -> str:
    value = str(value or "").replace("ı", "i").replace("İ", "i")
    value = unicodedata.normalize("NFKD", value.casefold())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value)).strip()


def within_lookback(published_at: str | None, hours: int) -> bool:
    if not published_at:
        return True
    try:
        stamp = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return stamp >= datetime.now(timezone.utc) - timedelta(hours=hours)
    except ValueError:
        return False


class GoogleNewsHTMLParser(HTMLParser):
    """Extract Google News article cards from the rendered HTML, not publisher RSS feeds."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self._anchor = None
        self._article_depth = 0
        self._card = None
        self.cards = []

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag.lower() == "article":
            self._article_depth += 1
            if self._article_depth == 1:
                self._card = {"text": [], "links": []}
        if tag.lower() == "a":
            self._anchor = {"href": a.get("href", ""), "direct_url": a.get("data-n-au", "") or a.get("data-url", ""), "aria": a.get("aria-label", ""), "text": ""}
        # Google sometimes puts the original publisher URL in a data attribute.
        for key in ("data-n-au", "data-url"):
            if a.get(key) and self._card is not None:
                self._card["links"].append({"href": a[key], "direct_url": a[key], "text": a.get("aria-label", "")})

    def handle_data(self, data):
        value = clean_text(data)
        if not value:
            return
        if self._anchor is not None:
            self._anchor["text"] += (" " if self._anchor["text"] else "") + value
        if self._card is not None:
            self._card["text"].append(value)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._anchor is not None:
            link = self._anchor
            if link.get("href") or link.get("direct_url"):
                self.links.append(link)
                if self._card is not None:
                    self._card["links"].append(link)
            self._anchor = None
        if tag.lower() == "article" and self._article_depth:
            self._article_depth -= 1
            if self._article_depth == 0 and self._card is not None:
                self.cards.append(self._card)
                self._card = None


def fetch_html(url: str) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.5"})
    with urlopen(request, timeout=25) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read(6_000_000).decode(charset, errors="replace")


def source_from_card(card: dict) -> tuple[str, str, str, str]:
    """Return title, source label, best article URL and source domain."""
    links = card.get("links", [])
    title_link = None
    for link in links:
        href = str(link.get("href", ""))
        if "/articles/" in href or "/read/" in href or link.get("direct_url"):
            if len(clean_text(link.get("text", ""))) > 15:
                title_link = link
                break
    if title_link is None:
        return "", "", "", ""
    title = clean_text(title_link.get("text", ""))
    direct = str(title_link.get("direct_url") or "")
    href = str(title_link.get("href") or "")
    article_url = urljoin("https://news.google.com/", direct or href)
    domain = urlparse(article_url).netloc.lower().removeprefix("www.")
    text = " ".join(card.get("text", []))
    # Google News cards commonly show the publisher name alongside the headline.
    source = ""
    if domain and domain not in {"news.google.com", "google.com"}:
        source = domain
    else:
        # Do not falsely treat Google News itself as the publisher.
        parts = [clean_text(x) for x in card.get("text", []) if clean_text(x) and clean_text(x) != title]
        source = parts[0] if parts else "Google News sonucu"
        domain = "publisher-label:" + normalize_title(source).replace(" ", "-")
    return title, source, article_url, domain


def fetch_google_news_source(source: dict, max_items: int, lookback_hours: int) -> list[dict]:
    url = source["url"]
    name = source.get("name", "Google News")
    LOG.info("Google News sayfası okunuyor: %s", name)
    html = fetch_html(url)
    parser = GoogleNewsHTMLParser()
    parser.feed(html)
    results = []
    seen = set()

    # Google News /read and /stories pages are story clusters. Their useful signal
    # is the list of distinct publisher articles inside the cluster, not the Google URL.
    path = urlparse(url).path
    if "/read/" in path or "/stories/" in path:
        # Google News cluster pages often link to opaque news.google.com/read IDs.
        # Resolve those IDs to the real publisher URLs in one batch request.
        candidates = []
        for link in parser.links:
            href = str(link.get("direct_url") or link.get("href") or "")
            title = clean_text(link.get("text", ""))
            if not href or not title or len(title) < 12:
                continue
            full_url = urljoin(url, href)
            host = urlparse(full_url).netloc.lower()
            if host.endswith("google.com") or host.endswith("googleusercontent.com"):
                continue
            candidates.append({"title": title, "url": full_url})
        decode_results = []
        google_urls = [x["url"] for x in candidates if "news.google.com/" in x["url"]]
        if google_urls:
            try:
                from googlenewsdecoder import gnewsdecoder
                decoded = gnewsdecoder(google_urls, interval=0.5, timeout=15.0)
                decode_results = decoded if isinstance(decoded, list) else [decoded]
            except Exception as exc:
                LOG.warning("Google News bağlantılarını yayıncı URL'lerine çözme başarısız: %s", exc)
        decoded_by_input = {}
        for original, result in zip(google_urls, decode_results):
            if isinstance(result, dict) and result.get("success") and result.get("decoded_url"):
                decoded_by_input[original] = result["decoded_url"]
        for candidate in candidates:
            article_url = decoded_by_input.get(candidate["url"], candidate["url"])
            parsed = urlparse(article_url)
            domain = parsed.netloc.lower().removeprefix("www.")
            if not domain or domain.endswith("google.com") or domain.endswith("googleusercontent.com"):
                continue
            title = candidate["title"]
            key = (domain, normalize_title(title))
            if key in seen:
                continue
            seen.add(key)
            results.append({
                "title": title,
                "normalized_title": normalize_title(title),
                "url": article_url,
                "source": domain,
                "source_role": "publisher",
                "source_domain": domain,
                "published_at": None,
                "summary": "Google News hikâye kümesinden çıkarılan yayıncı haberi; yayıncı alan adı doğrudan bağlantıdan çözüldü.",
                "image_url": None,
                "collected_at": datetime.now(timezone.utc).isoformat(),
                "status": "google_news_cluster_article",
                "discovery_source": name,
            })
            if len(results) >= max_items:
                break
        LOG.info("Google News haber kümesinden çıkarılan yayıncı haberi: %d", len(results))
        return results

    cards = parser.cards
    # Google News topic layout sometimes has no <article> wrappers. In that case
    # retain the /read/ or /stories/ cluster URL and do not invent a publisher name.
    if not cards:
        cards = [{"text": [x.get("text", "")], "links": [x]} for x in parser.links
                 if len(clean_text(x.get("text", ""))) > 18]
    for card in cards:
        title, publisher_name, link, domain = source_from_card(card)
        if not title or not link or title.lower() in seen:
            continue
        if len(title) < 18:
            continue
        seen.add(title.lower())
        results.append({
            "title": title,
            "normalized_title": normalize_title(title),
            "url": link,
            "source": publisher_name,
            "source_role": "google_news_cluster",
            "source_domain": "google-news-cluster:" + normalize_title(title)[:70].replace(" ", "-"),
            "published_at": None,
            "summary": "Google News konu akışından bulunan haber kümesi. Kaynak sayısı ilgili /read/ veya /stories/ sayfasından çıkarılmalıdır.",
            "image_url": None,
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "status": "google_news_discovered_not_verified",
            "discovery_source": name,
        })
        if len(results) >= max_items:
            break
    LOG.info("Google News sayfasından çıkarılan aday: %d", len(results))
    return results



def search_gdelt_news(query: str, max_items: int = 50) -> list[dict]:
    """Search indexed publisher articles through GDELT's public JSON API (no RSS)."""
    from urllib.parse import urlencode
    params = urlencode({
        "query": query,
        "mode": "ArtList",
        "format": "json",
        "maxrecords": min(max_items, 250),
        "sort": "HybridRel",
        "timespan": "72h",
    })
    endpoint = "https://api.gdeltproject.org/api/v2/doc/doc?" + params
    request = Request(endpoint, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urlopen(request, timeout=25) as response:
        payload = json.loads(response.read(5_000_000).decode("utf-8", errors="replace"))
    results = []
    seen = set()
    for article in payload.get("articles", []):
        title = clean_text(article.get("title", ""))
        link = str(article.get("url", ""))
        domain = str(article.get("domain") or urlparse(link).netloc).lower().removeprefix("www.")
        if not title or not link.startswith("http") or not domain or domain == "news.google.com":
            continue
        key = (domain, normalize_title(title))
        if key in seen:
            continue
        seen.add(key)
        results.append({
            "title": title,
            "normalized_title": normalize_title(title),
            "url": link,
            "source": domain,
            "source_role": "publisher",
            "source_domain": domain,
            "published_at": article.get("seendate"),
            "summary": "",
            "image_url": article.get("socialimage"),
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "status": "publisher_article_found_via_gdelt_search",
            "discovery_source": "GDELT web-news index",
        })
    return results


def search_google_news(query: str, max_items: int = 30) -> list[dict]:
    """Search Google News HTML for one event to discover independently published coverage."""
    url = "https://news.google.com/search?q=" + quote(query) + "&hl=tr&gl=TR&ceid=TR%3Atr"
    return fetch_google_news_source({"name": "Google News arama: " + query, "url": url}, max_items, 72)


def path_is_allowed(link: str, source: dict) -> bool:
    """Kept for compatibility with existing tests and optional URL-path filters."""
    prefixes = source.get("allowed_url_path_prefixes", [])
    if not prefixes:
        return True
    path = urlparse(link).path.lower()
    return any(path.startswith(str(prefix).lower()) for prefix in prefixes)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not CONFIG_PATH.exists():
        LOG.error("Kaynak ayar dosyası bulunamadı: %s", CONFIG_PATH)
        return 2
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    settings = config.get("settings", {})
    lookback_hours = int(settings.get("lookback_hours", 48))
    max_items = int(settings.get("max_items_per_source", 100))
    output_path = ROOT / settings.get("output_path", "data/news_latest.json")
    sources = [s for s in config.get("sources", []) if s.get("enabled", False)]
    if not sources:
        LOG.error("Etkin Google News kaynağı yok.")
        return 2

    collected = []
    for source in sources:
        try:
            collected.extend(fetch_google_news_source(source, max_items, lookback_hours))
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            LOG.exception("Google News kaynağı okunamadı: %s (%s)", source.get("name", source.get("url", "")), exc)
        except Exception:
            LOG.exception("Google News kaynağı işlenemedi: %s", source.get("name", source.get("url", "")))

    unique = {}
    for item in collected:
        key = item["normalized_title"] or item["url"]
        if key not in unique:
            unique[key] = item
            unique[key]["also_reported_by"] = []
        else:
            unique[key]["also_reported_by"].append({
                "source": item["source"], "source_role": "publisher", "source_domain": item["source_domain"],
                "title": item["title"], "url": item["url"], "published_at": item["published_at"]
            })
    results = list(unique.values())
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "collection_method": "Google News topic/search HTML; no publisher RSS feeds",
        "lookback_hours": lookback_hours,
        "source_count": len(sources),
        "collected_count_before_deduplication": len(collected),
        "unique_count": len(results),
        "note": "Google News sonuçları keşif ve kapsama sinyalidir; arama sonuçları tek başına editoryal doğruluk veya viral izlenme verisi kanıtlamaz.",
        "items": results
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LOG.info("Google News adayları: %d | Tekil başlık: %d | Çıktı: %s", len(collected), len(results), output_path)
    print(f"Google News taraması tamamlandı: {len(results)} aday.")
    print(f"JSON çıktısı: {output_path.relative_to(ROOT)}")
    for item in results[:10]:
        print(f"- [{item['source']}] {item['title']}")
    return 0 if results else 1


if __name__ == "__main__":
    sys.exit(main())
