from __future__ import annotations

import json
import logging
import re
import sys
import unicodedata
from difflib import SequenceMatcher

import feedparser
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
INPUT_PATH = ROOT / "data" / "selected_news.json"
OUTPUT_PATH = ROOT / "data" / "verification_queue.json"
SOURCES_PATH = ROOT / "src" / "sources.json"
LOG = logging.getLogger("news_verifier")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", (text or "").casefold())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def title_similarity(a: str, b: str) -> float:
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    ta, tb = set(na.split()), set(nb.split())
    jaccard = len(ta & tb) / len(ta | tb) if ta and tb else 0.0
    return max(jaccard, SequenceMatcher(None, na, nb).ratio() * 0.85)


def collect_other_source_headlines(selected_items: list[dict]) -> dict[str, list[dict]]:
    if not SOURCES_PATH.exists():
        return {}
    config = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
    matches: dict[str, list[dict]] = {str(item.get("url", "")): [] for item in selected_items}
    for source in config.get("sources", []):
        if not source.get("enabled"):
            continue
        try:
            feed = feedparser.parse(source["url"], request_headers={"User-Agent": "MagazinGundemiShorts/0.1"})
            entries = getattr(feed, "entries", [])
            LOG.info("İkinci kaynak RSS: %s | aday başlık: %d | biçim uyarısı: %s", source.get("name", source["url"]), len(entries), getattr(feed, "bozo", False))
            if not entries:
                LOG.warning("İkinci kaynak RSS içinde haber bulunamadı; URL doğrudan RSS olmayabilir: %s", source["url"])
            for entry in entries[:400]:
                def clean(value: object) -> str:
                    return re.sub(r"\\s+", " ", re.sub(r"<[^>]+>", " ", str(value or ""))).strip()

                other_title = clean(getattr(entry, "title", ""))
                other_summary = clean(getattr(entry, "summary", "") or getattr(entry, "description", ""))
                other_url = str(getattr(entry, "link", ""))
                domain = re.sub(r"^www\\.", "", __import__("urllib.parse", fromlist=["urlparse"]).urlparse(other_url).netloc.lower())
                if not other_title or not other_url:
                    continue
                for item in selected_items:
                    original_domain = re.sub(r"^www\\.", "", str(item.get("source_domain", "")).lower())
                    if domain == original_domain:
                        continue
                    # Başlıklar farklı yazılmış olabileceği için haber özetiyle de karşılaştır.
                    item_title = str(item.get("title", ""))
                    item_summary = str(item.get("summary", ""))
                    title_sim = title_similarity(item_title, other_title)
                    summary_sim = title_similarity(item_summary, other_title + " " + other_summary) if item_summary else 0.0
                    sim = max(title_sim, summary_sim)
                    if sim >= 0.45:
                        target = matches[str(item.get("url", ""))]
                        candidate = {
                            "source": source.get("name", domain), "title": other_title,
                            "url": other_url, "title_similarity": round(sim, 2),
                            "match_basis": "title" if title_sim >= summary_sim else "summary_and_title"
                        }
                        # Aynı RSS kaydını tekrar ekleme.
                        if not any(existing.get("url") == other_url for existing in target):
                            target.append(candidate)
        except Exception as exc:
            LOG.warning("İkinci kaynak akışı okunamadı (%s): %s", source.get("name", "bilinmiyor"), str(exc)[:200])
    return matches


class MetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title_parts: list[str] = []
        self.in_title = False
        self.meta: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {k.lower(): (v or "") for k, v in attrs}
        if tag.lower() == "title":
            self.in_title = True
        if tag.lower() == "meta":
            key = (attrs_dict.get("property") or attrs_dict.get("name") or "").lower()
            value = attrs_dict.get("content", "")
            if key and value:
                self.meta[key] = value

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data.strip())


def fetch_page(url: str) -> dict:
    request = Request(url, headers={"User-Agent": "MagazinGundemiShorts/0.1 (source-check)"})
    try:
        with urlopen(request, timeout=15) as response:
            raw = response.read(1_500_000)
            charset = response.headers.get_content_charset() or "utf-8"
            html = raw.decode(charset, errors="replace")
            parser = MetadataParser()
            parser.feed(html)
            return {
                "reachable": 200 <= response.status < 400,
                "http_status": response.status,
                "page_title": " ".join(parser.title_parts).strip(),
                "og_title": parser.meta.get("og:title", ""),
                "description": parser.meta.get("description", "") or parser.meta.get("og:description", ""),
                "error": None,
            }
    except HTTPError as exc:
        return {"reachable": False, "http_status": exc.code, "page_title": "", "og_title": "", "description": "", "error": f"HTTP {exc.code}"}
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        return {"reachable": False, "http_status": None, "page_title": "", "og_title": "", "description": "", "error": str(exc)[:250]}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not INPUT_PATH.exists():
        LOG.error("Girdi bulunamadı: %s", INPUT_PATH)
        return 2

    payload = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    selected_items = payload.get("items", [])
    cross_source_matches = collect_other_source_headlines(selected_items)
    results = []
    for item in selected_items:
        url = str(item.get("url", ""))
        page = fetch_page(url) if url.startswith(("https://", "http://")) else {
            "reachable": False, "http_status": None, "page_title": "", "og_title": "", "description": "", "error": "Geçersiz haber URL'si"
        }
        record = dict(item)
        record["source_page_check"] = page
        record["independent_source_matches"] = cross_source_matches.get(url, [])
        has_match = bool(record["independent_source_matches"])
        record["verification_status"] = ("second_source_match_needs_manual_confirmation" if has_match else ("source_page_reachable_no_second_source_match" if page["reachable"] else "source_page_unavailable_needs_review"))
        record["publication_approved"] = False
        record["verification_note"] = (
            "Bu kontrol yalnızca bağlantının erişilebilirliğini ve sayfa üst verilerini denetler. Haberin doğruluğunu veya görsel kullanım iznini kanıtlamaz; yayın öncesi bağımsız kaynak doğrulaması gerekir."
        )
        results.append(record)
        match_count = len(record["independent_source_matches"])
        print(f"- {'ERİŞİLEBİLİR' if page['reachable'] else 'KONTROL GEREKİYOR'}: {item.get('title', '(başlıksız)')} | olası bağımsız kaynak eşleşmesi: {match_count}")

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "checked_count": len(results),
        "publication_approved_count": 0,
        "note": "Başlık benzerliği yalnızca olası ikinci kaynak eşleşmesi bulur; haberin doğruluğunu kanıtlamaz. Manuel kontrol ve görsel hakları incelemesi gerekir.",
        "items": results,
    }
    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Doğrulama kuyruğu: {OUTPUT_PATH.relative_to(ROOT)}")
    print("Yayın onayı verilmedi; bağımsız kaynak doğrulaması ve görsel hakları kontrolü sonraki aşamadır.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
