import unittest

from src.hook_engine import generate_hook


class HookEngineTests(unittest.TestCase):
    def test_prefers_grounded_short_publisher_lead(self):
        title = "Ünlü oyuncudan yeni proje açıklaması"
        paragraphs = [
            "Ünlü oyuncu, yeni dizisinin çekimlerine gelecek ay başlanacağını açıkladı. "
            "Projenin yayın tarihi henüz duyurulmadı.",
            "Oyuncu röportajda rolü hakkında da konuştu ve hazırlık yaptığını belirtti.",
        ]
        result = generate_hook(title, paragraphs)
        self.assertTrue(result["selected"])
        self.assertIn(result["selected_type"], {"publisher_lead", "publisher_detail", "headline"})
        self.assertTrue(all(c["source_grounded"] for c in result["candidates"]))

    def test_empty_input_does_not_invent_hook(self):
        result = generate_hook("", [])
        self.assertEqual(result["selected"], "")
        self.assertEqual(result["selected_type"], "none")
        self.assertEqual(result["candidates"], [])

    def test_candidates_are_limited_to_three(self):
        result = generate_hook(
            "Sanatçı yeni açıklama yaptı",
            [
                "Sanatçı yeni albümünün gelecek ay dinleyicilerle buluşacağını söyledi.",
                "Konser takviminin önümüzdeki hafta açıklanması bekleniyor.",
                "Yeni albümde farklı müzisyenlerle çalıştığını da belirtti.",
            ],
        )
        self.assertLessEqual(len(result["candidates"]), 3)
