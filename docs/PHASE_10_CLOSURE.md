# Faz 10 kapanışı (10A, 10B, 10C)

**Tarih:** 2026-11-05. **Karar:** Sahip, Faz 10A, 10B ve 10C'yi kapattı.

"Tamamlandı", bu fazlar için karar verilen geliştirme kapsamının kapatıldığı anlamına gelir. **Güvenilirlik sorunlarının çözüldüğü anlamına gelmez.**

## Test durumu

**Sahibin talimatıyla bu kapanışta hiçbir test çalıştırılmadı:** birim, entegrasyon, `make check`, statik denetim, Gemma, performans, gerçek uygulama. **Birleşik `main` test edilmedi.** Otomatik öğrenme değişikliği ve yazılan yeni testler hiç çalıştırılmadı; kırılan test olabilir. Önceki sonuçlar kendi kodlarına aittir: 10C `386c17e` için `make check` geçmişti.

## Otomatik öğrenmenin kapatılması

| Yol | Değişiklik |
|---|---|
| `memory.auto_extract` | Varsayılan `False` (`config/model.py`) |
| Mesajdan öğrenme işi | `learning.enqueue` artık iş oluşturmuyor |
| Her mesajdan sonra öğrenme modeli | `engine._learn_now` hemen çıkıyor; çağrı yok |
| Daha önce bekleyen işler | Silinmedi; kayıt üretmiyor, işlenmiyor |
| Örtük üslup öğrenmesi | `adaptation.observe(implicit=False)`: sinyal sayılmıyor |
| "Hafızaya kaydedildi mi" notu | Bekleyen öğrenme varsaymıyor |
| Kişilik metni | "Zamanla hafızana alırsın" cümlesi yanlış olacaktı; düzeltildi (`persona-v5`) |

**Değişmeyenler:** Kayıtlı hafıza, geri çağırma, açık unutma, sohbet geçmişi, özetleme, açık üslup talimatları ve daha önce öğrenilmiş tercihler. Günlük hafıza bakımı (dizin, kopya kayıt) ve post-turn ön ısıtma aynı; öğrenme değiller.

## Manuel öğrenme

Her mesajda model çağrılmaz. `commands.detect` kurallarla açık isteği arar; yalnızca o zaman mevcut güvenli kayıt adımı çalışır (bir model çağrısı). Sonuç gerçek işlemden gelir; kayıt başarısızsa hafıza denetimi başarı iddiasına izin vermez.

Tetikleyenler: "Bunu hatırla", "Hafızana kaydet", "Bunu unutma", "Not al", "Aklında tut" ve yeni eklenen "Şunu öğren".

**Kalan sınır:** Bu kurallar geniş; "kaydet" geçen sıradan bir cümle de o model çağrısını tetikleyebilir. Ayrıca açık düzeltme ve aynı/farklı kişi komutları da kalıcı değişiklik yapar; bunlar açık talimat sayıldı.

## Faz durumu

| Faz | Durum |
|---|---|
| 10A | Tamamlandı (sahip kabulü 2026-10-31) |
| 10B | Tamamlandı (sahip kabulü 2026-11-02, kapanış 2026-11-05) |
| 10C | İlk sürümle kapsam kapatıldı; varsayılan kapalı; **gerçek kullanımda denenmedi** |

Faz 10C'nin geniş kapsamı (`open_loops`, `episodes`, ilişki özeti) yapılmadı.

## Açık kalanlar

- **REL-001:** Belirsiz bilginin kesinleşmesi. Otomatik öğrenme kapalıyken yeni kayıt yolu daralır; mevcut kayıtlar ve açık kayıt adımı için çözülmüş sayılmaz.
- **REL-002:** Hafızadan geri çağırma hatası.
- **REL-003:** Özetlemede bilgi kaybı.
- **REL-004:** Yapılmamış hatırlatma vaadi. Düzeltme kabul testini geçmedi, ürüne alınmadı.
- **Uzun konuşma sıkıştırma gecikmeleri.**

## Ürüne alınmayanlar

| Çalışma | Dal |
|---|---|
| `carry.py`, okuma testleri, kaynak getirme ölçümü | `experiment/rel003-carry` (arşiv) |
| `s3-v5` | `experiment/rel003-s3-v5` (arşiv; `main` `s3-v3`'te) |
| Başarısız REL-004 düzeltmesi, kabul testi araçları | `rel004/action-claims` |
| Değişiklik algılayıcısı | Kaldırıldı; git geçmişinde |

## Sonraki

Faz 10D. Ayrı başlatılacak.
