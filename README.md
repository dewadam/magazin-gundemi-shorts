# Magazin Gündemi Shorts

Magazin Gündemi için günlük haber keşfi, olay gruplama, 3 ayrı Shorts üretimi ve isteğe bağlı YouTube yükleme otomasyonu.

## Akış

1. Google News Türkiye magazin akışından adayları alır. Publisher RSS kullanılmaz.
2. Aday olaylar için Google News araması yapıp doğrudan yayıncı bağlantılarını bulmayı dener; aynı yayıncı tek oy sayılır.
3. Aynı olaya ait başlıkları gruplar, birbirinden farklı en fazla 3 haber seçer.
4. Kaynak sayfasından başlık/açıklama alır; Türkçe anlatım, TTS sesi, dikey 1080x1920 video, altyazı ve 1280x720 thumbnail üretir.
5. Videoları GitHub Actions artifact olarak verir. YOUTUBE_TOKEN_JSON secret varsa YouTube'a yüklemeyi dener.

Haber indeksindeki yayıncı sayısı gerçek izlenme/paylaşım sayısı değildir. Sayfanın açılması haberi bağımsız doğrulamaz. Kaynak sayfasında yeterli açıklama yoksa o video üretilmez; uydurma detay eklenmez.

## Hook Engine (ilk saniyeler)

`src/hook_engine.py` her haber için başlık ve yayıncı metninden en fazla üç açılış adayı üretir; kısa, somut ve kaynağa dayalı adayı puanlayıp seçer. Yeni bir iddia, tepki veya motivasyon uydurmaz. Seçim ve alternatifler her video klasöründeki `hook.json` dosyasına yazılır. Seslendirme ilk cümlede doğrudan konuya girer; uzun kanal selamlaması kullanılmaz.

Hook Engine testleri `tests/test_hook_engine.py` içindedir. GitHub Actions'ta **Hook Engine Tests** workflow'u ilgili dosyalar değiştiğinde testleri çalıştırır; elle de başlatılabilir. Bu değişiklik izlenme artışını garanti etmez; sonuçlar YouTube Analytics ile ölçülmelidir.

## Günlük çalışma

GitHub Actions her gün 09:15 Türkiye saatinde çalışır. Actions içinden Daily Magazin Shorts → Run workflow ile elle de başlatılabilir.

Artifact içeriği:
- Her haber için short.mp4, thumbnail.jpg, narration.txt, captions.srt
- source.json ve youtube-metadata.json
- manifest.json ve varsa upload_results.json

## YouTube otomatik yükleme

Yükleme kodu hazırdır; ilk yayın için YouTube kanalına bir kez OAuth izni verilmesi gerekir. Şifre veya token'ı bana göndermeyin ve GitHub koduna eklemeyin.

### Bir defalık kurulum
1. Google Cloud Console'da bir proje oluşturun: https://console.cloud.google.com/
2. **APIs & Services → Library** bölümünden **YouTube Data API v3** API'sini etkinleştirin.
3. **Google Auth Platform / OAuth consent screen** bölümünde uygulama bilgilerini tamamlayın. Uygulama test modundaysa kendi Google hesabınızı test kullanıcısı olarak ekleyin.
4. **Credentials → Create credentials → OAuth client ID** seçin; uygulama türü olarak **Desktop app** seçin ve istemci JSON dosyasını indirin.
5. Bilgisayarınızda Python 3.11 kurulu bir terminal açın; depoyu indirin/klonlayın ve proje klasöründe çalıştırın:
   `python -m pip install -r requirements.txt`
   `python scripts/get_youtube_token.py`
6. İndirilen OAuth istemci JSON dosyasının yolunu girin. Açılan tarayıcıda yayın yapacağınız YouTube kanalının Google hesabıyla giriş yapıp izni onaylayın. Proje klasöründe `authorized_user.json` oluşur.
7. `authorized_user.json` dosyasını metin düzenleyicide açıp tüm JSON içeriğini kopyalayın.
8. GitHub deposunda **Settings → Secrets and variables → Actions → New repository secret** yolunu açın. Adı tam olarak `YOUTUBE_TOKEN_JSON`, değeri kopyaladığınız JSON olsun; kaydedin.
9. OAuth istemci dosyasını ve `authorized_user.json` dosyasını depoya yüklemeyin veya başkalarıyla paylaşmayın.

Secret eklenince bir sonraki günlük veya elle başlatılan başarılı workflow, üretilen ve daha önce yüklenmemiş Shorts videolarını YouTube'a **public** olarak yükler ve küçük resmi ayarlar. `data/youtube_upload_history.json` daha önce yüklenen haber bağlantılarını kaydederek aynı haberin tekrar yüklenmesini önler.

Secret yoksa yükleme atlanır; videolar artifact olarak alınır. YouTube API kota/izin sorunları workflow loglarında görünür.

## Müzik

Kullanıcının seçeceği parça assets/music/selected_track.mp3 konumuna eklenirse anlatımın altında düşük sesle karıştırılır. Dosya yoksa telifli müzik eklenmez. Yalnızca kullanım hakkı bulunan veya YouTube Audio Library lisans koşullarına uygun müzik ekleyin.

## Görsel ve yayın notları

Kaynak sayfasının Open Graph görseli varsa arka planda kullanılır; yoksa özgün marka zemini oluşturulur. Görsel bağlantısı veya kaynak atfı yeniden kullanım lisansı vermez. Görsel hakkı, haber bağlamı ve anlatım doğruluğu ayrıca kontrol edilmelidir. İzlenme garantisi yoktur.

## Yerel çalıştırma

Python 3.11, FFmpeg ve DejaVu fontları gerekir. Sırasıyla: pip install -r requirements.txt; python -m unittest discover -s tests -v; python src/news_collector.py; python src/news_ranker.py; python src/news_verifier.py; python src/shorts_builder.py.
