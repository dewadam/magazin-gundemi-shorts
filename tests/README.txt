MAGAZIN GUNDEMI - OLAY BAZLI HABER SIRALAMA

Uygulama:
- Olay eşleştirme başlık, ayırt edici kelimeler, olay eylemi ve bölüm numarasını kullanır.
- Aynı programın farklı bölüm haberlerini, aynı kişinin farklı olaylarını birleştirmemeye çalışır.
- Google News keşif akışları yayın kuruluşu sayısına dahil edilmez.
- Aynı yayın kuruluşunun birden fazla URL'si tek oy sayılır.
- Tamamen aynı başlıkla yayımlanan farklı siteler olası ajans/sendikasyon içeriği olarak işaretlenir ve otomatik ilk üç seçiminden çıkarılır.
- Yalnızca en az iki yayın kuruluşunda görülen ve olası sendikasyon olarak işaretlenmeyen olaylar seçilir; yeterli olay yoksa kota doldurulmaz.
- Yayıncı sayısı popülerlik/ortak gündem sinyalidir, haberin doğruluk kanıtı değildir. Otomatik yayın onayı verilmez.

Test:
python -m unittest discover -s tests -v

GitHub Actions içinde ranker adımından önce test komutu çalıştırılır.
