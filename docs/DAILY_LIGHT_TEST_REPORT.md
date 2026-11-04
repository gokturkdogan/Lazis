# LAZIS — Hafif Günlük Kullanım Testi Raporu

- **Tarih:** 2026-11-04, 09:56–10:22
- **Kod:** `44bd74e`; ürün kodu `c366fbf` ile aynı. Sentetik veri, geçici profil, 11499 portunda geçici Ollama süreci (önbellek 2048 MiB). Gerçek profil, gerçek servis ve migration'a dokunulmadı.
- **Sonuç:** **Tamamlanmadı.** Kritik bellek baskısında test kendini durdurdu: 10 mesajın 8'i yapıldı, son 2 soru sorulamadı.
- **Ham veri:** `evals/reports/phase10/perf/daily/daily_r1_progress/`. Test bitmeden durduğu için özet rapor dosyası yazılmadı.

## 1. Koşullar

Mac prizde, kapak açık. Test başlarken açık olanlar: Outlook, Chrome, Teams, Slack, WhatsApp, Telegram, VS Code. Sahibi Cursor'u kapattı; denetimde görülen Codex ve ChatGPT de test başlarken kapalıydı. ChatGPT test boyunca açılmadı, yani plandaki ortamdan bir uygulama eksikti. Diğer programların belleği medyan 10,6 GB (10,3–12,1 GB), planlanan 10–12 GB aralığında.

## 2. Kabul edilmiş hedeflerle karşılaştırma

| Ölçüm | Hafif hedef | Sonuç | Durum |
|---|---|---|---|
| Medyan ilk token | ≤1,5 s | 1,0 s | Tuttu |
| Sıcak mesajlarda en kötü ilk token | ≤5 s | 1,2 s | Tuttu |
| Soğuk yükleme sonrası ilk token | ≤10 s | 9,8 s | Tuttu, sınırda |
| Kritik bellek baskısı | 0 | 1 | **Tutmadı** |
| Swap artışı | ≤2 GB | 5,6 GB (0,3 → 5,9) | **Tutmadı** |
| En uzun kesintisiz uyarı | ≤1 dakika | 13,5 dakika | **Tutmadı** |
| Tur içinde sıkıştırma beklemesi | Hiç | Hiç; bağlam yalnızca 2,2 bin token, sıkıştırma hiç başlamadı | Tuttu, ama sınanmadı |

Hız hedefleri 8 mesaja dayanır ve son 2 soru eksiktir. Uyarı düzeyi test süresinin %86'sında sürdü (1 536 s'nin 1 314 s'si); ilk uyarı 3 dakika 20 saniyede geldi.

**Ölçülemeyenler:** son iki soru, hafıza kayıtları, belirsizlik (REL-001), hatırlama (REL-002) ve özet koruma (REL-003). Sıkıştırma olmadığı için 60–64 s'nin çıktı sınırı olup olmadığı da doğrulanamadı. Bu test C için kanıt vermez.

**Sistem yanıt ölçümleri:** program başlatma en çok 3,1 ms, disk yazma 2,0 ms, zamanlayıcı gecikmesi 13,3 ms. Bu üç düşük düzey ölçüm kötüleşme göstermedi; arayüz akıcılığını ölçmezler.

## 3. Kritik an

- 10:21:06 son model çağrısı bitti. Kritik anda model **çalışmıyordu**.
- 10:22:19 macOS günlüğünde ekran açıldı (13 dakikadır kapalıydı). Kimin ya da neyin açtığı kayıtlarda yok.
- 10:22:22 kritik. Son 8 saniyede swap 4,3 → 5,9 GB; kablolu bellek 10,4 → 12,7 GB; WindowServer, Slack, VS Code, Teams ve Chrome birlikte yaklaşık 1,8 GB büyüdü.

Ekranın açılması tetikleyici görünüyor (zaman uyumu, tek olay). Ama sistem o anda zaten 13 dakikadır uyarıdaydı. Sıradan bir kullanım anı, payı kalmayan sistemi kritik düzeye taşıdı.

## 4. Ana bulgu: büyüyen bellek uygulamalarda değil, model çalışma sürecinde

Kritik ana kadar programlar büyümedi: 11,8 GB ile başladı, çoğunlukla 10,3–10,9 GB'ta kaldı. Büyüyen, Ollama test sürecinin ayak iziydi:

| | Bu test | Çoklu sıkıştırma (gece) | Boşaltılmış sistem, 40 mesaj |
|---|---|---|---|
| Öğrenme | Açık | **Kapalı** | Açık |
| Diğer programlar, medyan | 10,6 GB | 10,1 GB | 6,6 GB |
| Kablolu bellek, medyan | 10,5 GB | 10,5 GB | 10,3 GB |
| Ollama ayak izi, tepe | **11,3 GB** | 5,3 GB | **13,3 GB** |
| Sıkıştırılmış (Ollama), tepe | 10,3 GB | 1,6 GB | 11,3 GB |
| Bellek sıkıştırıcı, medyan | 7,6 GB | 2,7 GB | 2,2 GB |
| Swap, tepe | 5,9 GB | 0,6 GB | 7,2 GB |

- Bellek durumu çoklu testle aynı program yükünde bambaşka: orada 46 dakika hiç uyarı yoktu.
- Ayak izi yaklaşık 24 dakikada 4,8 → 11,3 GB oldu; bağlam ise yalnızca 2,2 bin tokendi. Artışlar model çağrılarının hemen ardından geliyor; 30 saniyelik örneklemede en büyük adımlar öğrenme çağrılarıyla aynı döneme düşüyor.
- Swap da ekran kapalıyken, kullanıcı yokken 1,5 → 4,1 GB büyüdü.
- ADR-0010, 2048 MiB önbellekle çalıştırıcı için 6,4 GB tepe kaydediyor. Burada yaklaşık iki katı görüldü; ölçüm biçimleri farklı olabilir, karşılaştırılması gerekir.

**Bilinmeyen:** bu belleğin ne olduğu. Sızıntı, önbellek davranışı ya da istem değişimi olabilir. Öğrenmeyle ilişki yalnızca üç koşunun karşılaştırmasından geliyor ve bu koşular başka yönlerden de farklı (çoklu testte kullanıcı yanıtları yalnızca konuşmanın sonunda). **Neden kanıtlanmadı; yalnızca güçlü bir işaret.** Tek koşu.

**Yan gözlem:** en uzun boşlukta (10:04:13 → 10:08:53) kablolu bellek 10:08:33–10:08:49 arasında 2,4 GB'a düştü ve baskı normale döndü; sonraki tur ilk tokeni yine 0,8 s. Kablolu 8 GB'ın baskıdaki payını gösteriyor. Bu davranışın kaynağı incelenmedi.

## 5. Model süresi

| Çağrı | Sayı | Toplam süre | Çıktı token |
|---|---|---|---|
| Yanıt | 8 | 23,1 s | 525 |
| Öğrenme | 8 | 89,7 s | 734 |
| Yeniden ısıtma | 17 | 13,0 s | 17 |
| Yükleme | 1 | 4,6 s | 0 |

Öğrenme, yanıtın 3,9 katı model süresi aldı. 8 öğrenme çağrısının 5'i hiçbir şey kaydetmedi (her biri 8,2 s, 10 token). Kayıt yapan 3 çağrı 16 s sürdü. Kullanıcı bunu beklemedi; ilk tokeni etkilemedi. Bu tek koşudaki sayılar seçici öğrenme önerisinin girdisidir, kanıtı değil.

## 6. Test sonrası durum

Test süreci ve 11499 portu kapandı, gerçek serviste yüklü model yok, geçici profilin anahtarı Anahtar Zinciri'nde kalmadı, gerçek veritabanının değişim zamanı aynı. Bellek baskısı normale döndü; swap 2,1 GB'ta kaldı (macOS zamanla boşaltır).

## 7. Sınırlar

Tek koşu, 8 mesaj, tek kritik olay. Test ortamında ChatGPT yoktu. Sentetik mesajlar gerçek kullanımı tam temsil etmez. Ayak izi 30 s'de bir, bellek düzeyi 5 s'de bir örneklendi. `top` ayak izi ile RSS farklı şeyleri ölçer; toplanamazlar.
