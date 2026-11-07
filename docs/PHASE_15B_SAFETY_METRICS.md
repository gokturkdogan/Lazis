# Faz 15B: Mikrofon güvenliği ve sınırlı performans ölçümü

**Tarih:** 2026-11-07. **Dal:** `phase15/safety-metrics`, `main`'den (`83d7cc0`) açıldı; Faz 15A denetim raporu bu dala taşındı. **Durum:** **Tamamlandı ve sahibin kararıyla kabul edildi** (2026-11-07); `main`'e alındı. Mikrofon kapanışı **sahibin gerçek mikrofon gözlemiyle** doğrulandı; uygulama ve macOS kayıtlarıyla doğrulanmadı (bölüm 6).

## 1. Mikrofon düzeltmesi

**Sorun (15A, P1-1):** Pencere kapatılınca (menü çubuğuna) yalnızca gizleniyordu; açık bir sesli oturumda mikrofon açık kalıyordu.

**Çözüm:** LAZIS görülemediği her durumda oturum biter ve mikrofon kapanır. Kabuk ayrıca konuşmayı durdurur ve konuşma modelini bırakır.

| Durum | Nasıl algılanıyor | Ne zaman |
|---|---|---|
| Pencere kapatma (menü çubuğuna) | Kabuk, kapatma isteğinde, gizlemeden önce | Anında |
| Simge durumuna küçültme | Kabuk, pencere boyut olayında | Anında |
| ⌘H ile gizleme, başka yoldan gizlenme | Kabuktaki koruma iş parçacığı pencerenin görünürlüğünü denetler | En geç 1,5 sn |
| Ekran kilidi | Aynı iş parçacığı, pencere sunucusunun oturum bilgisinden (`CGSSessionScreenIsLocked`) | En geç 1,5 sn |
| Uyku | Uyanmada kabuk ve arayüz oturumu bitirir | Uyanınca |
| Mikrofon izninin geri alınması, cihazın çıkarılması | Ses izinin "bitti" olayı | Anında |
| Sayfanın kapanması, sohbet ekranından çıkış, uygulamadan çıkış | Arayüz (`pagehide`, bileşen kaldırılması), kabuk (çıkışta konuşma ve model temizliği) | Anında |

**Bitirmeyenler (bilerek):** Odağın başka uygulamaya geçmesi; pencerenin başka bir pencerenin altında kalması. Pencere hâlâ açık.

**Yeniden açılma:** Hiçbir olay mikrofonu açmaz. Pencere yeniden gösterildiğinde "Sesli oturumu başlat" düğmesi görünür ve yeni bir tıklama gerekir. Oturumun neden bittiği kırmızı hata olarak değil, bilgi satırı olarak gösterilir ("Pencere kapatıldığı için sesli oturum bitti; mikrofon kapalı.").

**Testler (modelsiz):**
- Gizleme, küçültme, kilit ve uyku: her biri mikrofonu kapatıyor, modeli bırakıyor ve hiçbir şeyi yeniden açmıyor.
- Uyanma, mikrofonun kaybı ve sayfanın kapanması oturumu bitiriyor.
- Odak kaybı oturumu bitirmiyor.
- Oturum yokken gelen sinyal hiçbir şeyi değiştirmiyor.
- Kilit kontrolü açık masaüstünde "kilitli değil" diyor.

**Gerçek pencerede görülen:** Ölçüm sırasında pencere kırmızı düğmeyle kapatıldığında kabuk `voice.session_stop_requested reason=hidden` yazdı ve koruma iş parçacığı gizlenmeyi ayrıca yakaladı. O anda açık oturum yoktu.

## 2. Ölçüm altyapısı

- **Uygulama içi:** Yalnızca `LAZIS_METRICS=1` ile açılır. Açıkken arayüz 10 saniyede bir FPS'yi, sesli turda konuşma tanıma, yanıt, ilk ses ve uçtan uca süreleri bildirir. Kabuk bunları kendi yerel günlüğüne yazar. Yalnızca listelenen adlar ve sayılar kabul edilir; metin ve içerik reddedilir (testli).
- **Dış ölçüm:** `scripts/measure-resources.py`, salt okuyan bir araç. LAZIS süreçlerinin işlemci ve bellek kullanımını, boş belleği ve swap'ı izler. Boş bellek %20'nin altına inerse ya da swap 512 MB'tan fazla artarsa durur; `--unload-on-stop` ile modeli bellekten boşaltır. `--report-log` uygulama günlüğündeki süreleri ortalama, medyan ve en kötü değer olarak özetler.

## 3. Ölçümler (Gemma olmadan)

Diğer uygulamalarınız açıktı. Swap ölçüm başında 782 MB'tı ve **hiçbir ölçümde artmadı**. Boş bellek en az %69 kaldı.

### M3: Whisper gecikmesi

- **Yöntem:** Yelda'nın okuduğu üç Türkçe kayıt, uygulamanın korumalı sunucusuyla, her biri 3 kez.
- **Sunucu:** Hazır olması 284 ms (tek ölçüm), belleği 750 MB.

| Kayıt | Ortalama | Medyan | En kötü | Gerçek zaman oranı |
|---|---|---|---|---|
| 4,6 sn | 508 ms | 501 ms | 524 ms | 0,11 |
| 10,3 sn | 564 ms | 564 ms | 566 ms | 0,05 |
| 23,4 sn | 698 ms | 698 ms | 699 ms | 0,03 |

Metinler doğru çıktı; yalnızca "LAZIS" "Lazız", "Moda" "moda" yazıldı. Sentetik ses temizdir, insan sesi ve oda gürültüsü ölçülmedi.

### M4: Yelda ilk ses

Uygulamanın sentez komutuyla, farklı uzunlukta 10 ilk cümle: **ortalama 685 ms, medyan 670 ms, en kötü 806 ms.** Süre cümle uzunluğundan çok `say`'in başlama maliyetinden geliyor (tek kelimelik "Evet." de yaklaşık aynı). Web Audio'da çözme ve çalmaya başlama bu ölçüme dahil değil.

### M1 ve M6: Boşta kaynak ve arayüz

- **Yöntem:** Geçici bir profil (ön ısıtma kapalı, Gemma yüklenmedi) ve geliştirme derlemesi kullanıldı.
- **Bozulma:** Ölçüm sırasında pencere elle öne alındı ve sonra kırmızı düğmeyle kapatıldı. Bu yüzden "odakta" ve "odak dışı" aşamaları ayrı ayrı ölçülemedi; aşağıdaki değerler gerçekleşen duruma göre ayrıldı.

| Durum | FPS | LAZIS toplam işlemci (bir çekirdeğin %'si) | LAZIS toplam RSS |
|---|---|---|---|
| Odakta, çekirdek görünür | 57,8 ve 60,0 (iki 10 sn'lik pencere; ilk pencere açılış sırasında 29,6) | Medyan 29,5, ortalama 25,7, en kötü 57,6 (aşama, gizli ve odak dışı anları da içeriyor) | ~670–764 MB |
| Menü çubuğuna kapatılmış | 0 (çizim yok; 13 ölçüm) | Medyan 0,1, ortalama 0,2, en kötü 1,4 | ~761 MB |
| Odak dışı ama görünür | **Ölçülemedi.** Pencere başka pencerenin altında kaldığında WebKit kareleri kendisi durdurdu (tek ölçüm 0,4 fps) | — | — |

**Süreç başına (odakta aşaması, ortalama):**

| Süreç | İşlemci | RSS |
|---|---|---|
| WebKit GPU | %13,9 | 93–151 MB |
| WebKit içerik | %7,8 | 222–253 MB |
| Kabuk (hata ayıklama derlemesi) | %3,7 | 153–160 MB |
| WebKit ağ | — | 87 MB |
| Arka uç | %0,1 | 79 MB |
| Ağ yardımcısı | %0 | 35 MB |

RSS, süreçlerin paylaştığı belleği birden çok kez sayar; gerçek toplam daha düşüktür. Geliştirme modundaki Vite sunucusu hariç tutuldu.

## 4. M2 ve M5 (gerçek Gemma; sizin başlatmanız için hazır)

**M2: Gemma yüklüyken bellek ve swap**
1. Bir terminalde: `python3 scripts/measure-resources.py --seconds 120 --label m2 --unload-on-stop`
2. Hemen ardından: `LAZIS_METRICS=1 make dev`
3. Kısa bir yazılı mesaj gönderin. Gemma yüklenir; betik 2 dakika ölçer, sınır aşılırsa durur ve modeli boşaltır.

**M5: Sesli konuşmanın uçtan uca gecikmesi**
1. Aynı şekilde: `python3 scripts/measure-resources.py --seconds 180 --label m5 --unload-on-stop` ve `LAZIS_METRICS=1 make dev`
2. "Sesli oturumu başlat" ile üç kısa cümle söyleyin, sonra oturumu bitirin.
3. Rapor: `python3 scripts/measure-resources.py --report-log ~/Library/Logs/LAZIS/dev`. Konuşma tanıma, yanıt, ilk ses ve konuşmanın bitişinden ilk sese kadar geçen süre ile FPS gelir.

Bu adımlar geliştirme profilinizi kullanır (gerçek profil değil) ve hiçbir ayarı değiştirmez.

## 5. Açık riskler

- **Ekran kilidi algısı** gerçek kilitle denenmedi: anahtar, macOS'un belgelenmemiş oturum bilgisi. macOS sürümleriyle değişirse kilitte oturum bitmeyebilir. Pencere gizleme, küçültme ve uyku yolları bundan bağımsız.
- **Gecikme:** Gizleme ve kilit yolunda 1,5 saniyeye kadar gecikme var. Kapatma ve küçültme anında.
- **M6 tam ölçülmedi:** Odak dışı ama görünür durum, sürüm (release) derlemesi ve GPU zamanı ölçülmedi. Odaktaki işlemci değeri karışık bir aşamadan geliyor.
- **Ölçülmeyenler:** Yelda'nın Web Audio'daki çözme ve çalma payı, insan sesiyle STT doğruluğu.
- **M2, M5, M7 yapılmadı.** REL-001…004 ve diğer teknik borçlar açık.

## 6. Gerçek mikrofon kapanış testi (2026-11-07)

**Hazırlık:**
- Geliştirme profiline ön ısıtmayı kapatan geçici bir `config.toml` kondu; test sonrası silindi.
- Uygulama, ölçüm modunda mikrofonun açılma ve kapanma anlarını nedenleriyle kaydedecek şekilde ayarlandı.
- `scripts/mic-in-use.swift`, macOS'a varsayılan mikrofonun kullanımda olup olmadığını soran salt okuyan bir izleyici olarak 12:31–12:46 arasında çalıştı.

**Sonuç:**
- **Sahip:** Testi yaptığını ve her şeyin beklendiği gibi çalıştığını bildirdi.
- **Kayıtlar:** Testi göstermiyor. 12:31'den sonra hiçbir profilde LAZIS başlangıcı ya da mikrofon olayı kaydedilmemiş; macOS izleyicisi bu sürede mikrofonun hiç kullanılmadığını gördü.
- **Karar:** Sahip, kendi gözlemine dayanarak birleştirmeye karar verdi. Kayıtla doğrulama **açık teknik borç**.

## 7. Açık teknik borçlar (Faz 15B kapanışı)

- **Mikrofon kapanışı kayıtla doğrulanmadı.** Ayrıca macOS izleyicisinin sorduğu özelliğin (`kAudioDevicePropertyDeviceIsRunningSomewhere`) WebKit'in mikrofon kullanımını gösterdiği henüz görülmedi. Bir sonraki gerçek denemede `LAZIS_METRICS=1` ile `metrics.mic` satırları ve izleyici birlikte kontrol edilmeli.
- **Ekran kilidi algısı** gerçek kilitle denenmedi.
- **Ölçülmeyenler:** M2 (Gemma yüklüyken bellek ve swap), M5 (sesli uçtan uca gecikme), M7 (uzun sohbet sıkıştırma), odak dışı FPS, sürüm derlemesi ve GPU.
- REL-001…004 ve önceki fazlardan süren teknik borçlar açık.

