# Faz 15A: Sistem denetimi ve önceliklendirme

**Tarih:** 2026-11-07. **Dal:** `phase15/audit`, `main`'den (`83d7cc0`) açıldı. **Yöntem:** Kod ve belge okuma, kısa modelsiz kontroller. Gemma, Whisper veya performans testi çalıştırılmadı. Hiçbir sorun test edilmeden çözüldü sayılmadı.

## 1. Genel durum

| Bileşen | Durum | Doğrulama düzeyi |
|---|---|---|
| Yerel Gemma sohbeti | Çalışıyor | Gerçek kullanımda; `make check` |
| Kalıcı hafıza, manuel öğrenme | Çalışıyor; otomatik öğrenme kapalı | Testli; REL-001…003 açık |
| Kişiselleştirme, günlük özet | Çalışıyor | Testli; özet doğruluğu gerçek modelle ölçülmedi |
| PDF, DOCX, TXT | Çalışıyor | Testli; modelle sadakat ölçülmedi |
| Wikipedia araştırması | Çalışıyor | Testli; bir gerçek istek doğrulandı |
| Whisper STT | Çalışıyor | Sahip denedi; gecikme ve doğruluk ölçülmedi |
| Yelda TTS | Çalışıyor | Sahip denedi (Faz 13); Web Audio yolu (Faz 14) ölçülmedi |
| Eller serbest oturum | Çalışıyor | Testli; gerçek döngü ve yankı ölçülmedi |
| LAZOS arayüzü | Kabul edildi | Sahip gördü; FPS/GPU ölçülmedi |
| Güvenlik ve izolasyon | Güçlü | Korumalı profiller testli (aşağıda bir P1 bulgu) |

**P0 bulunmadı.** Veri kaybı, güvenlik ihlali ya da uygulamayı çalışamaz hâle getiren doğrulanmış bir sorun yok. Bu denetim saldırı testi değildir.

## 2. Açık sorunlar

### P1: Günlük kullanımı ciddi bozan

| # | Sorun | Kanıt |
|---|---|---|
| P1-1 | **Pencere kapatılınca açık sesli oturumda mikrofon açık kalıyor.** "Kapatınca menü çubuğunda kalsın" varsayılan olarak açık; pencere yalnızca gizleniyor, web görünümü ve oturum sürüyor | `lib.rs` `CloseRequested` → `window.hide()`; oturum yalnızca görünüm kaldırılınca veya çıkışta bitiyor |
| P1-2 | **Uygulama bağımsız değil.** Sürüm derlemesi Python'u derleme anında sabitlenen `<depo>/core/.venv` yolundan çalıştırıyor; `whisper-server` Homebrew'den; imzalama yok. Depo taşınırsa veya güncellenirse çalışan uygulama değişir ya da açılmaz | `paths.rs` `core_dir`; `voice.rs` `DEFAULT_SERVER` |
| P1-3 | **REL-004:** Yapılamayan işlem (hatırlatma) için söz verilmesi. Düzeltme kabul testini geçmedi | `RELIABILITY_ISSUES.md` |
| P1-4 | **REL-002:** Kayıtlı bilginin hatırlanamaması | `RELIABILITY_ISSUES.md` |
| P1-5 | **REL-003 ve sıkıştırma gecikmesi:** Özet yeniden yazılırken bilgi kaybı. Arka plan sıkıştırması sürerken gönderilen turda ilk token medyan 17,8 sn, en kötü 61,8 sn (Faz 9 §12) | `PHASE_10_REPORT.md` |
| P1-6 | **Toplam kaynak tüketimi bilinmiyor.** Gemma yüklenince swap ~1 GB arttı (Faz 10 kontrolü); Whisper ve WebGL eklenince durum ölçülmedi | `PHASE_10D_FIRST_VERSION.md` bölüm 7.3 |

### P2: Kullanımı engellemeyen, iyileştirilmeli

| # | Sorun |
|---|---|
| P2-1 | REL-001: belirsiz bilginin kesinleşmesi. Otomatik öğrenme kapalı olduğu için yol daraldı; açık "Bunu hatırla" adımında hâlâ olası |
| P2-2 | Günlük özetin doğruluğu gerçek modelle ölçülmedi |
| P2-3 | Belge sadakati ve belge içi talimatlara direnç ölçülmedi. Belge turunda araç yok, etki yanlış yanıtla sınırlı |
| P2-4 | PDF ayrıştırma arka uç sürecinde. Süre denetimi sayfalar arasında; tek sayfada uzun işlem arka ucu meşgul edebilir |
| P2-5 | Araştırmada atıf doğruluğu ölçülmedi; hassas konular (sağlık, hukuk, para) algılanmıyor, yalnızca kısıtlı veri ve kişi adı denetleniyor |
| P2-6 | Sesli döngü: yankı engelleme yok, ses düzeyine dayalı sıra algılama gürültüde zayıf, sesle kesme yok, STT hatası normal mesaj olarak gidiyor (hafızaya yazılmıyor) |
| P2-7 | `whisper-server` çalışırken yerel portu kimlik doğrulamasız; aynı kullanıcı hesabındaki başka bir süreç ses gönderebilir (dışarıya erişimi yok) |
| P2-8 | Yelda'nın ilk sesi Web Audio yolunda tahminen 0,5–0,7 sn daha geç (ölçülmedi) |

### P3: Gelecek ya da kozmetik

| # | Sorun |
|---|---|
| P3-1 | Uygulama sentez sırasında çökerse geçici TTS klasörü kalabilir (açılışta temizleme taraması yok). Bugün artık dosya yok (kontrol edildi) |
| P3-2 | Ağ yardımcısı araştırma kapalıyken de çalışıyor (boşta ~35 MB, %0 işlemci) |
| P3-3 | Ollama uygulama korumalı alanının dışında bir sistem servisi (yalnızca 127.0.0.1, bulut kapalı) |
| P3-4 | Web görünümünün güvenlik politikası (CSP) her yerel porta izin veriyor (`http://127.0.0.1:*`) |
| P3-5 | Denetim kaydı gönderilen arama metnini tutmuyor (RES-12'den bilinçli sapma) |
| P3-6 | Genel web araması yok (yalnızca Wikipedia); "LAZIS" adı "Lazız" diye yazılabiliyor; tek ses Yelda; Bloom parlaklığı LAZOS'tan biraz farklı olabilir |

## 3. Güvenlik sınırları (kodla kontrol edildi)

| Sınır | Sonuç |
|---|---|
| Mikrofon yalnızca kullanıcı izniyle | **Kısmen.** Yalnızca "Sesli oturumu başlat" tıklamasıyla açılıyor; ama pencere gizlenince kapanmıyor (P1-1) |
| İzinsiz internet yok | **Korunuyor.** Arka uçtan ağa tek yol araştırma istemcisi; yalnızca izin ve kısıtlı veri denetiminden geçen onaylı arama. Arka uç işletim sistemi seviyesinde internete kapalı |
| Otomatik kalıcı öğrenme kapalı | **Korunuyor.** Varsayılan kapalı; ayar dosyası, ortam değişkeni ve başlatma seçeneği açamıyor; sesli mesaj hafızaya yazmıyor |
| Özel bilgi dışarı gitmiyor | **Büyük ölçüde.** Yalnızca onaylanan arama metni gidiyor; kısıtlı veri engelleniyor; hafıza aramaya eklenmiyor. Hassas konu algılama yok (P2-5) |
| Belge ve web metni komut değil | **Korunuyor (yapısal).** Metin, kapatılamayan bir not içinde "bilgidir" diye işaretleniyor; bu turlarda araç veya işlem yok. Modelin uyması ölçülmedi |
| Yerel servislerin gereksiz ağ izni yok | **Korunuyor.** Konuşma sunucusu tamamen ağsız, ağ yardımcısı yalnızca 443 + DNS, arka uç yalnızca Ollama ve tek soket. Ollama yalnızca loopback (P3-3) |
| Geçici TTS dosyaları temizleniyor | **Korunuyor.** Her cümlede yalnızca size açık klasör siliniyor; şu an artık yok. Çökme senaryosu: P3-1 |

## 4. Paketleme

**Eksikler:**
1. Gömülü Python çalışma ortamı.
2. `whisper-server` ikilisinin pakete alınması.
3. Kararlı imzalama kimliği.
4. İlk açılış kurulum sihirbazı.
5. Model ve Ollama denetimi.

**Önerilen en basit ve sürdürülebilir yol:**

| Konu | Öneri | Neden |
|---|---|---|
| Python | `uv` ile taşınabilir (relocatable) Python ve sanal ortam, `LAZIS.app/Contents/Resources/core` içinde; kilitli bağımlılıklar (`uv.lock`, karma doğrulamalı) | Donmuş ikili (PyInstaller) SQLCipher gibi yerel tekerleklerle kırılgan; ilk açılışta indirmek ağ ister. Gömülü ortam çevrimdışı, sürümlü ve imzalanabilir |
| whisper-server | Sabit bir whisper.cpp sürümünden Metal'li derlenip `Contents/Resources/bin` içinde, imzalı; Homebrew'e bağımlılık biter | Sürüm sabit kalır, korumalı profille aynı yol |
| Whisper modeli | Pakete girmez (574 MB). Kurulum sihirbazı onayla indirir, SHA-256'yı doğrular, `~/Library/Application Support/LAZIS/models/` altında tutar (bugünkü konum) | Paket küçük kalır; model profil verisinden ayrı |
| Ollama | Pakete girmez. Mevcut Homebrew kurulumu ve `com.lazis.ollama` LaunchAgent'ı aynen kalır; uygulama yalnızca varlığını, sürümünü ve modelin yüklü olduğunu denetler ve yol gösterir, kendiliğinden kurmaz | Ollama'nın kendi güncellemesi ve bellek yönetimi var; checkpoint 8 ayarı korunur |
| İzinler | Mikrofon (açıklama `Info.plist`'te var). Anahtar Zinciri erişimi (veritabanı anahtarı). Ek izin gerekmiyor: konuşma tanıma Whisper ile, ağ yalnızca loopback | Kullanıcıya az soru |
| İmzalama | Yerel ve kalıcı bir imzalama sertifikası ("LAZIS Local") ve sertleştirilmiş çalışma zamanı (hardened runtime) | macOS mikrofon izni ve Anahtar Zinciri erişimi uygulamanın imzasına bağlı; geçici (ad-hoc) imza her derlemede izinleri sıfırlar |
| Veri ve anahtarlar | Bugünkü düzen korunur: SQLCipher, anahtar Anahtar Zinciri'nde, kurtarma kodu, `data.noindex`, sahibine özel izinler, yedekler. Sihirbaz kurtarma kodunu ilk açılışta gösterir | Değişiklik gerektirmiyor; imza kararlılığı Anahtar Zinciri erişimini korur |
| Güncelleme | Yeni sürüm = yeni `.app`; veri `Application Support`'ta kaldığı için korunur; migration'lar mevcut yedekleme düzeniyle | Otomatik güncelleme sistemi gerekmiyor (tek kullanıcı) |

## 5. Performans ölçüm planı

**Kurallar (her adım için):**
- Adım başlamadan boş bellek ≥ %20 olmalı ve swap son ölçümden 512 MB'tan fazla artmamış olmalı; aksi hâlde adım başlamaz. Adım sırasında aşılırsa durdurulur ve model bellekten çıkarılır.
- Uygulamalarınız kapatılmaz. Her adım tek sefer ve kısa; toplam en çok 30 dakika.
- Sonuçlar `evals/reports/phase15/` altına yazılır. Model kullanan adımları siz başlatırsınız.

| Adım | Ne | Nasıl | Süre |
|---|---|---|---|
| M1 | Boşta RAM/CPU | Uygulama açık, model yok: kabuk, arka uç, ağ yardımcısı, WebContent süreçlerinin bellek izi (mevcut `process_metrics`) ve 60 sn işlemci; çekirdek görünür, odaksız, gizli | 3 dk |
| M2 | Gemma yüklüyken bellek ve swap | Tek kısa yazılı tur; toplam bellek izi, Ollama çalıştırıcısı, swap farkı, bellek baskısı | 2 dk |
| M3 | Whisper gecikmesi | Yelda'nın okuduğu 5/10/20 sn'lik üç Türkçe kayıt, kabuğun korumalı sunucusuyla; ms ve sunucu belleği | 2 dk |
| M4 | Yelda ilk ses | 10 farklı uzunlukta cümle; sentez süresi (Web Audio yolu) | 1 dk |
| M5 | Toplam sesli gecikme | Sizin üç cümlelik sesli oturumunuz: konuşmanın bitişi → yazı → ilk token → ilk ses (zaman damgası kaydı 15B'de eklenir) | 3 dk |
| M6 | Arayüz FPS ve GPU | Uygulama içi FPS kaydı (her 10 sn); görünür ve odakta, odaksız, gizli; WebContent işlemcisi | 3 dk |
| M7 | Uzun sohbet sıkıştırma | Mevcut sıkıştırma ölçüm aracıyla kısa döngü; sıkıştırma sırasında gönderilen turun ilk token süresi | 10 dk |

## 6. Önce çözülmesi gereken 5 konu

1. **P1-1: Pencere gizlenince sesli oturumu bitirmek** (mikrofon kapanır). Küçük, güvenlik değeri yüksek.
2. **P1-6: Ölçüm planı M1–M6.** Kaynak tüketimini ve sesli gecikmeyi bilmeden optimizasyon yapılamaz.
3. **P1-5: Sıkıştırmanın sohbeti bekletmesi.** 61,8 sn'ye varan bekleme günlük kullanımı en çok bozan sorun.
4. **P1-3 ve P1-4: REL-004 ve REL-002.** Kullanıcıya yanlış söz verilmesi ve kayıtlı bilginin bulunamaması güveni doğrudan etkiliyor.
5. **P1-2: Bağımsız uygulama paketi.** Gömülü Python, paketli whisper-server, kararlı imza, kurulum sihirbazı.

## 7. Faz 15B önerisi

**Faz 15B: Güvenlik düzeltmesi ve ölçüm.**

1. P1-1 düzeltmesi: pencere gizlenince veya simge durumuna küçültülünce oturum biter, mikrofon kapanır. Testli.
2. Ölçüm için gereken küçük kayıtlar: sesli tur zaman damgaları, uygulama içi FPS kaydı.
3. M1–M6 ölçümleri; model kullanan adımları siz başlatırsınız.
4. Sonuçlara göre 15C'nin (performans ve sıkıştırma) ve 15D'nin (paketleme) kapsamı.

REL-002, REL-003, REL-004 için yeni araştırma döngüsü önerilmiyor. Ölçüm sonrası, kanıtla seçilmiş tek ve küçük düzeltmeler 15C'de değerlendirilebilir.
