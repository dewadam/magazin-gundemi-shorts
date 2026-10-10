from __future__ import annotations

import json
import logging
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
INPUT_PATH = ROOT / "data" / "selected_news.json"
OUTPUT_PATH = ROOT / "data" / "verification_queue.json"
LOG = logging.getLogger("news_verifier")


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
    results = []
    for item in payload.get("items", []):
        url = str(item.get("url", ""))
        page = fetch_page(url) if url.startswith(("https://", "http://")) else {
            "reachable": False, "http_status": None, "page_title": "", "og_title": "", "description": "", "error": "Geçersiz haber URL'si"
        }
        record = dict(item)
        record["source_page_check"] = page
        record["verification_status"] = "source_page_reachable_needs_independent_confirmation" if page["reachable"] else "source_page_unavailable_needs_review"
        record["publication_approved"] = False
        record["verification_note"] = (
            "Bu kontrol yalnızca bağlantının erişilebilirliğini ve sayfa üst verilerini denetler. Haberin doğruluğunu veya görsel kullanım iznini kanıtlamaz; yayın öncesi bağımsız kaynak doğrulaması gerekir."
        )
        results.append(record)
        print(f"- {'ERİŞİLEBİLİR' if page['reachable'] else 'KONTROL GEREKİYOR'}: {item.get('title', '(başlıksız)')}")

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "checked_count": len(results),
        "publication_approved_count": 0,
        "note": "Sayfa erişim kontrolü bağımsız doğrulama değildir. Bu akış otomatik yayın izni vermez.",
        "items": results,
    }
    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Doğrulama kuyruğu: {OUTPUT_PATH.relative_to(ROOT)}")
    print("Yayın onayı verilmedi; bağımsız kaynak doğrulaması ve görsel hakları kontrolü sonraki aşamadır.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
