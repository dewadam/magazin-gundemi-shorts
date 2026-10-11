from __future__ import annotations

import json
import logging
import re
import sys
import unicodedata
from difflib import SequenceMatcher

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


MATCH_STOPWORDS = {
    "bir", "bu", "su", "şu", "ve", "veya", "ile", "icin", "için", "ama",
    "daha", "çok", "gibi", "olan", "olarak", "son", "yeni", "ünlü", "unlu",
    "magazin", "gündem", "gundem", "açıklama", "aciklama", "dedi", "diye",
    "etti", "oldu", "oluyor", "olacak", "paylaştı", "paylasti", "konuştu",
    "konustu", "iddia", "iddiası", "iddiasi", "sonra", "önce", "once",
    "bugün", "bugun", "dün", "dun", "resmen", "işte", "iste", "şok", "sok",
    # Magazin başlıklarında sık görülen, olayı ayırt etmeyen kelimeler ve ek parçaları
    "esi", "es", "tan", "ten", "dan", "den", "yla", "yle", "oyuncu",
    "sanatci", "usta", "yildiz", "tepki", "veda", "yas", "yasam",
    "hayat", "durumu", "nasil", "nice", "gorusmek", "uzere", "yalniz",
}


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", (text or "").casefold())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def content_tokens(text: str) -> set[str]:
    return {
        token for token in normalize(text).split()
        if len(token) >= 3 and token not in MATCH_STOPWORDS
    }


def title_similarity(a: str, b: str) -> float:
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    ta, tb = content_tokens(a), content_tokens(b)
    overlap = len(ta & tb)
    jaccard = overlap / len(ta | tb) if ta and tb else 0.0
    containment = overlap / min(len(ta), len(tb)) if ta and tb else 0.0
    sequence = SequenceMatcher(None, na, nb).ratio()
    # This is a candidate-match score, not a truth score.
    return max(sequence * 0.85, jaccard, containment * 0.65)


def event_similarity(item: dict, other_title: str, other_summary: str) -> tuple[float, list[str], str]:
    original_title = str(item.get("title", ""))
    original_summary = str(item.get("summary", ""))
    left = content_tokens(original_title + " " + original_summary)
    right = content_tokens(other_title + " " + other_summary)
    shared = sorted(left & right)
    if not left or not right or not shared:
        return title_similarity(original_title, other_title), shared, "title_only"

    jaccard = len(shared) / len(left | right)
    containment = len(shared) / min(len(left), len(right))
    title_score = title_similarity(original_title, other_title)
    # Short RSS summaries can still match through shared people, programme names,
    # or distinctive event words even if publishers phrase headlines differently.
    context_score = 0.65 * containment + 0.35 * jaccard
    return max(title_score, context_score), shared, "title_and_context"


def collect_other_source_headlines(selected_items: list[dict]) -> dict[str, list[dict]]:
    """Use Google News-derived direct publisher coverage; do not call RSS or rate-limited search APIs."""
    matches: dict[str, list[dict]] = {str(item.get("url", "")): [] for item in selected_items}
    for item in selected_items:
        target = matches[str(item.get("url", ""))]
        own_url = str(item.get("url", ""))
        own_domain = re.sub(r"^www\.", "", str(item.get("source_domain", "")).lower())
        seen_urls = {own_url}
        for candidate in item.get("source_articles", []) or []:
            url = str(candidate.get("url", ""))
            domain = re.sub(r"^www\.", "", str(candidate.get("source_domain", "")).lower())
            if not url.startswith(("https://", "http://")) or url in seen_urls:
                continue
            if domain and own_domain and domain == own_domain:
                continue
            sim, shared, basis = event_similarity(item, str(candidate.get("title", "")), "")
            if sim >= 0.25 and len(shared) >= 2:
                seen_urls.add(url)
                target.append({
                    "source": candidate.get("source", domain),
                    "source_domain": domain,
                    "title": candidate.get("title", ""),
                    "summary": "",
                    "url": url,
                    "match_score": round(sim, 2),
                    "shared_keywords": shared[:12],
                    "match_basis": basis,
                    "discovery_method": "Google News üzerinden bulunan yayıncı kapsamı; bağımsız doğrulama değildir",
                })
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
        record["verification_status"] = ("publisher_coverage_candidates_need_manual_confirmation" if has_match else ("source_page_reachable_no_second_source_match" if page["reachable"] else "source_page_unavailable_needs_review"))
        record["publication_approved"] = False
        record["verification_note"] = (
            "Google News üzerinden bulunan yayıncı kapsamı manuel inceleme adaylarıdır; bunlar doğrulanmış haber veya bağımsız teyit değildir. "
            "Sayfa erişimi haberi doğrulamaz. Yayın öncesinde olayın bağlamı, kaynağın bağımsızlığı ve görsel kullanım hakkı ayrıca kontrol edilmelidir."
        )
        results.append(record)
        match_count = len(record["independent_source_matches"])
        print(f"- {'ERİŞİLEBİLİR' if page['reachable'] else 'KONTROL GEREKİYOR'}: {item.get('title', '(başlıksız)')} | manuel inceleme adayı: {match_count}")

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "checked_count": len(results),
        "publication_approved_count": 0,
        "note": "Başlık ve özet benzerliği geniş bir manuel inceleme aday listesi üretir. Adaylar haber doğrulaması, bağımsız teyit veya yayın onayı değildir.",
        "items": results,
    }
    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Doğrulama kuyruğu: {OUTPUT_PATH.relative_to(ROOT)}")
    print("Yayın onayı verilmedi; bağımsız kaynak doğrulaması ve görsel hakları kontrolü sonraki aşamadır.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
