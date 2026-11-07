# Faz 14 ilk sürüm: LAZOS görsel kimliğiyle yaşayan çekirdek

**Tarih:** 2026-11-07. **Dal:** `phase14/jarvis-ui`, `main`'den (`168589f`) açıldı. **Durum:** Sahibin onayı bekleniyor; `main`'e alınmadı. **Masaüstü penceresinde görsel olarak denenmedi.**

## 1. LAZOS'tan alınanlar

Kaynak: sahibin LAZOS projesi (`~/Downloads/LazOs-main`), salt okunarak incelendi; değiştirilmedi.

| LAZOS dosyası | LAZIS'teki karşılığı |
|---|---|
| `ai-core/shaders.ts` | `ui/src/core/shaders.ts`: **değiştirilmeden** taşındı (plazma çekirdek, parıltı, halkalar, dalga bandı, parçacıklar, enerji akışları, elektrik arkları, jeodezik kabuk, arka plan) |
| `ai-core/uniforms.ts` | `ui/src/core/uniforms.ts`: aynı |
| `ai-core/CoreScene.tsx` | `ui/src/core/scene.ts`: her bileşen React Three Fiber'dan düz three.js'e; aynı geometri, parametre ve kare başı sürücü |
| `ai-core/AICore.tsx` | `ui/src/components/core/CoreCanvas.vue`: kamera, otomatik kalite, Bloom + Vignette (three.js'in kendi eklentileriyle) |
| `ai-core/palette.ts` | `ui/src/core/palette.ts`: hareket parametreleri LAZOS'tan, renkler sahibin beş rengi |
| `layout/HudOverlay.tsx` | `ui/src/components/core/HudOverlay.vue`: dönen retikül, durum etiketi, telemetri, ses ölçerler, altyazı |
| `layout/TopBar.tsx` | `App.vue` üst çubuğu: marka, ortada durum çipi, sağda sekmeler |
| `chat/ChatPanel.tsx` | `AssistantView.vue`: sağda açılıp kapanan cam panel |
| `styles/globals.css` | `theme.css`: animasyonlu `--accent`, cam yüzeyler, HUD etiketi, köşe çerçeveleri, dönme animasyonları, Chakra Petch |

React'e dönüştürme yapılmadı. LAZOS'un altyapısı (backend, ses motoru, hafıza) alınmadı.

## 2. Beş durum

| Durum | Renk | Ne zaman (yalnızca gerçek durum) |
|---|---|---|
| Bekleme | `#00BFFF` | Başka bir şey olmadığında |
| Dinleme | `#A855F7` | Sesli oturum açık ve kullanıcıyı bekliyor |
| Düşünme | `#FFD600` | Konuşma yazıya çevriliyor ya da yanıt yazılıyor (sesli veya yazılı) |
| Konuşma | `#00E676` | Yelda'nın sesi çalıyor |
| Hata | `#FF1744` | Gerçek bir arıza (mikrofon izni, konuşma tanıma, sesli okuma, tur hatası) 6 saniye boyunca; "duyamadım" hata sayılmaz |

- Çekirdek, yörüngeler, parçacıklar, ışıklar, HUD çerçeveleri, durum çipi ve vurgu yazıları aynı renge geçer.
- Çekirdekte renk ve enerji her karede yumuşak yaklaşır (LAZOS'taki sönümleme); arayüzde `--accent` 900 ms'de geçer. Çekirdek hiçbir durumda yeniden oluşturulmaz.

## 3. Sesli oturum (bas-konuş kaldırıldı)

1. "Sesli oturumu başlat" tıklanınca mikrofon izni istenir, mikrofon açılır, çekirdek mora döner.
2. Konuşma ses düzeyinden algılanır; sessizlikle tur biter.
3. Whisper metni oluşturur, çekirdek sarı olur; Gemma yanıt yazar.
4. Yelda yanıtı okur, çekirdek yeşil olur.
5. Okuma bittikten 600 ms sonra dinleme yeniden başlar, çekirdek mora döner. Döngü oturum kapanana kadar sürer.

**Güvenlik:**
- Uygulama açılışında mikrofon kapalı.
- Oturum bitince, sohbet ekranından çıkınca ya da pencere kapanınca bütün ses izleri durur ve konuşma modeli bırakılır.
- Mikrofon açıkken altta kırmızı noktalı "Mikrofon açık" yazar.
- Yanıt hazırlanırken ve okunurken duyulan saklanmaz; okumadan sonraki 600 ms de duyulmaz. Böylece Yelda'nın sesi kullanıcı mesajına dönüşmez (testle doğrulandı).
- "Sesli yanıtı durdur" okumayı hemen keser.
- Arka planda kendiliğinden başlayan bir oturum yok.

## 4. Gerçek ses senkronizasyonu

- **Mikrofon:** Faz 13 kaydedicisi her ses karesinin seviyesini (RMS) bir tampona yazar; çekirdek ve ölçerler bunu her karede okur. Yalnızca dinlerken.
- **Yelda:** Kabuk her cümleyi `say` ile sentezleyip WAV olarak belleğe döndürür. `say` boruya yazamadığı için yalnızca size açık geçici bir klasöre yazar ve dosya okunur okunmaz silinir; bu yalnızca LAZIS'in kendi okuduğu yanıttır, kullanıcının sesi asla diske yazılmaz.
  - Arayüz sesi Web Audio ile çalar. Analizör gerçek genliği verir; çekirdek, halkalar, dalga bandı, parçacıklar ve ölçer buna tepki verir.
  - Sıradaki cümle, o anki çalarken sentezlenir.
- Seviyeler Vue durumunda değil, hafif bir tamponda durur: kare başına yeniden çizim yok. Ses yoksa seviye sıfırdır; sahte hareket üretilmez.

## 5. Korunanlar

- **Yazılı sohbet:** Sohbet paneli (sağda, açılıp kapanır, tercih hatırlanır) yazılı mesaj, geçmiş, ilk kurulum, belge paneli ve internet araştırması düğmesiyle aynen çalışır. Sesli mesajların metinleri sohbette görünür.
- **Ekranlar:** Hafıza, Genel Bakış, Ayarlar ve Tanılama sekmeleri üst çubukta.
- **Güvenlik:** Hafıza, araştırma ve güvenlik altyapısı değişmedi.

## 6. Performans

- three.js yalnızca sohbet ekranında, ayrı parça olarak yüklenir (~147 KB sıkıştırılmış).
- **Otomatik kalite:** 2 saniyelik pencerelerde 50 fps altına düşülürse önce piksel oranı, sonra sahne ayrıntısı düşer (4.200 → 1.800 parçacık). 58 fps üstünde geri çıkar; en çok 3 değişiklik.
- **Arka planda:** Pencere gizliyken kare çizilmez; görünür ama odakta değilken yaklaşık 24 fps.
- **Azaltılmış hareket:** macOS ayarı veya LAZIS tercihi hareketi yavaşlatır, ses tepkisini yumuşatır, kamera kaymasını ve retikül dönüşünü kapatır.
- **HUD ölçerleri:** Yalnızca dinlerken ve konuşurken çalışır.
- **WebGL yoksa:** Durgun bir CSS parıltısı gösterilir; uygulamanın geri kalanı etkilenmez.

## 7. Testler (modelsiz)

`make check` geçti (çıkış kodu 0): 3.496 çekirdek, 158 arayüz, 8 arayüz–arka uç, 47 Rust testi; lint ve tip denetimleri temiz.

Yeni ve güncellenen testler:
- Beş rengin tam değerleri ve durumun yalnızca gerçek girdilerden türemesi.
- Arıza kırmızısının süresi.
- Ses seviyelerinin kaynağı ve sönmesi.
- WebGL yokken yedek görünüm.
- Sohbet panelinin açılıp kapanması ve yazılı sohbetin, belgelerin korunması.
- Bas-konuş düğmesinin olmaması.
- Oturum döngüsü: dinle, yaz, gönder, cümle cümle oku, yeniden dinle.
- Yelda'nın sesinin tura dönüşmemesi.
- İzin reddi; oturum kapanınca mikrofonun kapanması ve modelin bırakılması.
- Okumanın durdurulması.
- Kabukta Yelda'nın sesinin bellekte dönmesi ve geçici dosyanın kalmaması (ses çalınmadan).

## 8. Bilinen sınırlar ve doğrulanmamış davranışlar

- **Görsel sonuç görülmedi.** Sahne kodu LAZOS'la aynı, ama LAZOS `postprocessing` kütüphanesini, LAZIS three.js'in kendi Bloom ve Vignette'ini kullanıyor. Parlaklık ve renk tonu biraz farklı olabilir; ince ayar pencerede bakılarak yapılmalı.
- **Kare hızı, GPU ve bellek ölçülmedi.** Özellikle Gemma, Whisper ve Yelda birlikte çalışırken.
- **WebKit ile ilgili belirsizlikler:** Tauri'nin WebKit görünümünde WebGL, `@property` renk geçişi, cam bulanıklığı ve Web Audio çalma (askıya alınma ihtimaline karşı ses bağlamı oturum tıklamasında hazırlanıyor) pencerede denenmedi.
- **Gecikme:** Yelda'nın ilk sesi, cümle sentezi yüzünden doğrudan `say`'e göre yaklaşık 0,5–0,7 sn daha geç başlayabilir (ölçülmedi).
- **Tek seferlik geçici dosya:** Sentezde yanıt sesi kısa süreli, yalnızca size açık bir dosyaya yazılıp hemen siliniyor.
- **HUD ölçümleri:** Son tur telemetrisi her turdan sonra tanılama ucundan okunuyor. "Ses tanıma" ve "İlk ses" yalnızca sesli turlarda dolu.
- **Faz 13'ten süren teknik borçlar:** Gürültülü ortam, LAZIS konuşurken sesle sözünü kesme, yankı engelleme, paketleme.
