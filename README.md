# Magazin Gündemi Shorts

İlk aşama: RSS kaynaklarından aday magazin haberlerini toplar, başlıkları tekilleştirir ve `data/news_latest.json` dosyasına yazar.

## Çalıştırma

```bash
python -m pip install -r requirements.txt
python src/news_collector.py
```

Kaynakları `src/sources.json` içinden düzenleyebilirsin. `enabled: true` olan kaynaklar çalıştırılır.

> Bu modül yalnızca aday haber toplar. Haberlerin doğrulanması, görsel kullanım hakları ve yayın kararı sonraki aşamalarda ele alınır.
