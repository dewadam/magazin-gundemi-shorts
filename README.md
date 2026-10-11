# Magazin Gündemi Shorts

Magazin Gündemi için günlük haber keşfi, olay gruplama, 3 ayrı Shorts üretimi ve isteğe bağlı YouTube yükleme otomasyonu.

## Akış

1. Google News Türkiye magazin akışından adayları alır. Publisher RSS kullanılmaz.
2. Aday olaylar için Google News araması yapıp doğrudan yayıncı bağlantılarını bulmayı dener; aynı yayıncı tek oy sayılır.
3. Aynı olaya ait başlıkları gruplar, birbirinden farklı en fazla 3 haber seçer.
4. Kaynak sayfasından başlık/açıklama alır; Türkçe anlatım, TTS sesi, dikey 1080x1920 video, altyazı ve 1280x720 thumbnail üretir.
5. Videoları GitHub Actions artifact olarak verir. YOUTUBE_TOKEN_JSON secret varsa YouTube'a yüklemeyi dener.

Haber indeksindeki yayıncı sayısı gerçek izlenme/paylaşım sayısı değildir. Sayfanın açılması haberi bağımsız doğrulamaz. Kaynak sayfasında yeterli açıklama yoksa o video üretilmez; uydurma detay eklenmez.

## Günlük çalışma

GitHub Actions her gün 09:15 Türkiye saatinde çalışır. Actions içinden Daily Magazin Shorts → Run workflow ile elle de başlatılabilir.

Artifact içeriği:
- Her haber için short.mp4, thumbnail.jpg, narration.txt, captions.srt
- source.json ve youtube-metadata.json
- manifest.json ve varsa upload_results.json

## YouTube otomatik yükleme

Settings → Secrets and variables → Actions → New repository secret bölümünde YOUTUBE_TOKEN_JSON secret eklenmelidir. Değer, YouTube Data API v3 için OAuth kullanıcı token JSON içeriği olmalı; client_id, client_secret, refresh_token, token_uri ve scopes alanlarını içermeli, youtube.upload kapsamıyla yetkilendirilmelidir. Secret/token depoya düz metin olarak commit edilmemelidir.

Secret yoksa video üretimi devam eder; yükleme atlanır ve videolar artifact olarak alınır. YouTube API kota/izin sorunları ayrıca raporlanır.

## Müzik

Kullanıcının seçeceği parça assets/music/selected_track.mp3 konumuna eklenirse anlatımın altında düşük sesle karıştırılır. Dosya yoksa telifli müzik eklenmez. Yalnızca kullanım hakkı bulunan veya YouTube Audio Library lisans koşullarına uygun müzik ekleyin.

## Görsel ve yayın notları

Kaynak sayfasının Open Graph görseli varsa arka planda kullanılır; yoksa özgün marka zemini oluşturulur. Görsel bağlantısı veya kaynak atfı yeniden kullanım lisansı vermez. Görsel hakkı, haber bağlamı ve anlatım doğruluğu ayrıca kontrol edilmelidir. İzlenme garantisi yoktur.

## Yerel çalıştırma

Python 3.11, FFmpeg ve DejaVu fontları gerekir. Sırasıyla: pip install -r requirements.txt; python -m unittest discover -s tests -v; python src/news_collector.py; python src/news_ranker.py; python src/news_verifier.py; python src/shorts_builder.py.
