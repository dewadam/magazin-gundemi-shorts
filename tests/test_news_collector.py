import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from news_collector import GoogleNewsHTMLParser, clean_text, normalize_title, path_is_allowed


class SourceCategoryFilterTests(unittest.TestCase):
    def test_milliyet_magazin_path_allowed(self):
        source = {"allowed_url_path_prefixes": ["/magazin/"]}
        self.assertTrue(path_is_allowed("https://www.milliyet.com.tr/magazin/unlu-haber-123", source))

    def test_milliyet_general_news_path_rejected(self):
        source = {"allowed_url_path_prefixes": ["/magazin/"]}
        self.assertFalse(path_is_allowed("https://www.milliyet.com.tr/gundem/deprem-123", source))
        self.assertFalse(path_is_allowed("https://www.milliyet.com.tr/dunya/haber-123", source))

    def test_no_filter_preserves_existing_sources(self):
        self.assertTrue(path_is_allowed("https://example.com/anything", {}))

    def test_google_news_text_normalization(self):
        self.assertEqual(clean_text("  Başlık\\n   haberi  "), "Başlık haberi")
        self.assertEqual(normalize_title("Hadise ve Kerem Bürsin"), "hadise ve kerem bursin")

    def test_google_news_parser_extracts_story_links(self):
        parser = GoogleNewsHTMLParser()
        parser.feed('<article><a href="/read/story-id">Necla Uygur son yolculuğuna uğurlandı</a></article>')
        self.assertEqual(len(parser.links), 1)
        self.assertIn("/read/story-id", parser.links[0]["href"])


if __name__ == "__main__":
    unittest.main()
