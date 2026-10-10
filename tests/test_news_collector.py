import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from news_collector import path_is_allowed


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


if __name__ == "__main__":
    unittest.main()
