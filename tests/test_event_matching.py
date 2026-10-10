import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from event_matcher import same_event, group_events
from news_ranker import source_articles


def story(title, source="CNN Türk", role="publisher"):
    return {"title": title, "source": source, "source_role": role,
            "source_domain": "cnnturk.com" if role == "publisher" else "news.google.com",
            "url": "https://example.com/" + str(abs(hash(title))),
            "published_at": "2026-10-10T12:00:00+00:00"}


class EventMatcherTests(unittest.TestCase):
    def test_different_masterchef_events_do_not_merge(self):
        a = story("MasterChef eleme adayı kim oldu 10 Ekim")
        b = story("MasterChef yarışmacısı hastaneye kaldırıldı")
        self.assertFalse(same_event(a, b)[0])

    def test_same_show_not_sufficient(self):
        self.assertFalse(same_event(story("Survivor dokunulmazlık oyununu kazandı"),
                                    story("Survivor yarışmacısı evlendi"))[0])

    def test_same_event_reworded(self):
        a = story("Survivor Serhan Onat evlendi Merve Küsmenoğlu")
        b = story("Merve Küsmenoğlu ile Survivor Serhan Onat evlendi")
        self.assertTrue(same_event(a, b)[0])

    def test_distinctive_headlines_stay_separate(self):
        a = story("Selin Türkmen yeni rolüyle gündem oldu")
        b = story("Selin Türkmen yeni evini paylaştı")
        self.assertFalse(same_event(a, b)[0])

    def test_discovery_feed_is_not_a_publisher(self):
        a = story("Survivor Serhan Onat evlendi", role="discovery_only")
        self.assertEqual(source_articles(a), [])
        a["also_reported_by"] = [
            {"source": "CNN Türk", "source_role": "publisher",
             "source_domain": "cnnturk.com", "url": "https://cnnturk.com/a"},
            {"source": "Google News", "source_role": "discovery_only",
             "source_domain": "news.google.com", "url": "https://news.google.com/a"},
        ]
        self.assertEqual(len(source_articles(a)), 1)
        self.assertEqual(source_articles(a)[0]["source_domain"], "cnnturk.com")

    def test_same_publisher_multiple_urls_one_vote(self):
        a = story("Survivor Serhan Onat evlendi")
        a["also_reported_by"] = [
            {"source": "CNN Türk", "source_role": "publisher",
             "source_domain": "cnnturk.com", "url": "https://cnnturk.com/b"}
        ]
        self.assertEqual(len(source_articles(a)), 1)

    def test_complete_link_no_transitive_merging(self):
        items = [story("Serhan Onat Merve Küsmenoğlu evlendi"),
                 story("Serhan Onat Merve Küsmenoğlu düğün evlendi"),
                 story("Merve Küsmenoğlu başka projeye başladı")]
        groups, _ = group_events(items)
        self.assertGreaterEqual(len(groups), 2)


if __name__ == "__main__":
    unittest.main()
