import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from news_ranker import compare, rank, select_top_stories

def article(title, source, domain, summary="", role="publisher", date="2026-10-10T15:00:00+00:00"):
    return {"title":title,"source":source,"source_domain":domain,"url":"https://"+domain+"/"+str(abs(hash(title+source))),"summary":summary,"source_role":role,"published_at":date}

class MatchingTests(unittest.TestCase):
    def test_same_wedding_different_headlines(self):
        a=article("Serhan Onat Merve Küsmenoğlu ile evlendi","CNN","cnnturk.com")
        b=article("Serhan Onat ile Merve Küsmenoğlu evlendi!","Mynet","mynet.com")
        self.assertTrue(compare(a,b)[0])
    def test_different_episodes_stay_separate(self):
        a=article("Güller ve Günahlar 37. bölüm fragmanı","CNN","cnnturk.com")
        b=article("Güller ve Günahlar 38. bölüm fragmanı","Mynet","mynet.com")
        self.assertFalse(compare(a,b)[0])
    def test_different_actions_stay_separate(self):
        a=article("Serhan Onat Merve Küsmenoğlu ile evlendi","CNN","cnnturk.com")
        b=article("Serhan Onat Merve Küsmenoğlu ile boşandı","Mynet","mynet.com")
        self.assertFalse(compare(a,b)[0])
    def test_discovery_feed_does_not_count(self):
        a=article("Serhan Onat Merve Küsmenoğlu ile evlendi","CNN","cnnturk.com")
        b=article("Serhan Onat ile Merve Küsmenoğlu evlendi!","Google News - Survivor ve MasterChef (keşif)","news.google.com",role="discovery_only")
        self.assertEqual(rank([a,b])[0]["publisher_count"],1)
    def test_two_publishers_count_as_two(self):
        a=article("Serhan Onat Merve Küsmenoğlu ile evlendi","CNN","cnnturk.com")
        b=article("Serhan Onat ile Merve Küsmenoğlu evlendi!","Mynet","mynet.com")
        self.assertEqual(rank([a,b])[0]["publisher_count"],2)
    def test_same_publisher_counts_once(self):
        a=article("Serhan Onat Merve Küsmenoğlu ile evlendi","CNN","cnnturk.com")
        b=article("Serhan Onat ile Merve Küsmenoğlu evlendi!","CNN","cnnturk.com")
        self.assertEqual(rank([a,b])[0]["publisher_count"],1)
    def test_exact_syndication_flagged(self):
        a=article("Ünlü oyuncu evlendi nikah töreni","CNN","cnnturk.com")
        b=article("Ünlü oyuncu evlendi nikah töreni","Mynet","mynet.com")
        self.assertTrue(rank([a,b])[0]["possible_syndication"])

    def test_three_distinct_single_publisher_events_can_be_selected(self):
        items = [
            article("Oyuncu A yeni projeye başladı", "CNN", "cnnturk.com", date="2026-10-10T18:00:00+00:00"),
            article("Şarkıcı B konser tarihini açıkladı", "Mynet", "mynet.com", date="2026-10-10T17:00:00+00:00"),
            article("Oyuncu C evlendi", "Habertürk", "haberturk.com", date="2026-10-10T16:00:00+00:00"),
        ]
        selected = select_top_stories(rank(items), 3)
        self.assertEqual(len(selected), 3)
        self.assertEqual(len({x["url"] for x in selected}), 3)

    def test_discovery_repetition_increases_trend_score(self):
        direct = article("Hadise Kerem Bürsin Milano Moda Haftası birlikte görüntülendi", "CNN", "cnnturk.com")
        discovery1 = article("Hadise Kerem Bürsin Milano Moda Haftası birlikte görüntülendi - Haberler", "Google News - Magazin (keşif)", "news.google.com", role="discovery_only")
        discovery2 = article("Hadise ve Kerem Bürsin Milano Moda Haftası - Mynet", "Google News - Ünlüler (keşif)", "news.google.com", role="discovery_only")
        baseline = rank([direct])[0]["popularity_score"]
        spread = rank([direct, discovery1, discovery2])[0]["popularity_score"]
        self.assertGreater(spread, baseline)

    def test_discovery_only_items_are_not_selected(self):
        item = article("Ünlü isimden açıklama", "Google News - keşif", "news.google.com", role="discovery_only")
        self.assertEqual(select_top_stories(rank([item]), 3), [])

if __name__=="__main__": unittest.main()
