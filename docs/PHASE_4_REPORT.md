# LAZIS — Faz 4 Raporu: Masaüstü Deneyimi, Sistem Yönetimi ve Dayanıklılık

- **Tarih:** 2026-10-18
- **Durum:** Uygulandı ve doğrulandı. **Sahibin onayı bekleniyor.** Faz 5'e başlanmadı.
- **Kararlar:** [ADR-0012](adr/0012-desktop-experience-and-resilience.md)
- **Commit'ler (yerel, push edilmedi):**
  - `092d61c`: çekirdek, tanılama uç noktası
  - `64b8fa7`: kabuk, menü çubuğu ve otomatik yeniden başlatma
  - `2e829ae`: arayüz
  - `70c0e41`: gerçek uygulamada bulunan başlatma sırası hatası
  - Bu raporla birlikte: belgeler ve ölçümler

---

## A. Genel sonuç

Faz 4'ün beş hedefi tamamlandı. Tek asistan mimarisi ([ADR-0011](adr/0011-single-assistant-timeline.md)) korundu: sohbet listesi ve "yeni sohbet" yok.

| Hedef | Sonuç |
|---|---|
| 1. Gerçek zamanlı asistan durumları | Hazır (mavi), Düşünüyor (sarı), Yanıtlıyor (yeşil), Sorun var (kırmızı). Dinliyor (mor) yalnızca Faz 13 için ayrıldı; hiçbir şey üretmiyor. Durumlar yalnızca gerçek olaylardan türetiliyor, zamanlayıcı yok. Her durumun metin etiketi var. Animasyon yalnızca Düşünüyor ve Yanıtlıyor'da çalışıyor. |
| 2. Sistem durumu paneli | Tanılama sekmesinde model, arka uç, son yanıtın performansı, bağlam hazırlığı ve süreç başına bellek. Konuşma içeriği yok. Ölçüm yalnızca panel açıkken. |
| 3. Hata tespiti ve güvenli kurtarma | Çöken arka uç otomatik yeniden başlıyor: 60 sn'de en fazla 3 deneme; gerçek uygulamada 1,4–1,5 sn'de geri geldi. Ollama'ya ulaşılamazsa artan aralıklarla yeniden deneniyor; Ollama'ya dokunulmuyor. Yayın koparsa yarım yanıt korunuyor. Uykudan uyanınca bağlantılar yeniden denetleniyor. |
| 4. Tek asistan arayüzü | Güvenli Markdown, kod bloğu ve mesaj kopyalama. Eski mesajları okurken ekran aşağı çekilmiyor. Ayarlar ekranı düzenlenebilir hâle geldi. |
| 5. macOS entegrasyonu | Menü çubuğu simgesi ve menüsü. Pencere kapatılınca menü çubuğunda kalma (tercih). Dock'tan yeniden açma. Temiz çıkış. Mikrofon, global kısayol veya yeni izin yok. |

**En büyük kazanç boşta maliyet.** Görünür ve boştaki pencerede CPU kullanımı:

- Faz 3: kabuk %4,8, WebContent %6,1
- Faz 4: kabuk %0,02, WebContent %0,07
- Pencere gizliyken: ≈ %0

Model yanıt süreleri Faz 3 ile aynı (§E.2).

Gerçek uygulama denetiminde testlerin kaçırdığı bir hata bulundu ve düzeltildi. `main.ts` uygulamayı bağlantı deposundan önce bağlıyordu; bu yüzden menü çubuğu gezinmesi, `--show`, tercihlerin yüklenmesi ve ilk menü çubuğu durumu gerçek uygulamada çalışmıyordu. Düzeltmeyle birlikte bu sırayı sınayan bir test eklendi.

## B. Mimari

Ayrıntılar: ADR-0012, ARCHITECTURE §3.2, §8.1 ve §9.

**Rust kabuğu (`src-tauri`)**

- **`controller.rs`: sınırlı otomatik yeniden başlatma**
  - `RestartPolicy`: 60 sn'de en fazla 3 deneme, 1/2/4 sn bekleme.
  - Bütün başlatmalar aynı kilitten geçiyor, bu yüzden aynı anda iki arka uç olamaz.
  - Uygulama kapanırken yeniden başlatma yapılmıyor. Kapanmayla yarış koşulu, bayrağın durum kilidi altında okunmasıyla kapatıldı.
  - Bütçe dolunca `backend_restart_limit` hatası; elle yeniden deneme bütçeyi sıfırlıyor.
  - Masaüstü durum dosyasına yazımlar sıraya alındı.
- **`desktop.rs`:** gezinme koruması, dış bağlantı doğrulaması, uyku tespiti, menü çubuğu durum metinleri ve kodla çizilen şablon simge.
- **`metrics.rs`:** süreç başına `phys_footprint` (libproc). Okunan süreçler: kabuk, arka uç, Ollama sunucusu ve model süreçleri.
- **`lib.rs`**
  - Ana pencere artık kodla oluşturuluyor (gezinme koruması için).
  - Menü çubuğu, pencere kapatma davranışı ve Dock'tan yeniden açma.
  - Uyku dedektörü iş parçacığı.
  - `--show=<görünüm>` ile ikinci açılış.
  - 5 yeni komut, hepsi yetki listesinde (ACL) ve Rust'ta doğrulanıyor: `get_preferences`, `set_preferences`, `set_tray_status`, `open_external_url`, `process_metrics`.
- **`state_file.rs`:** `preferences` alanı eklendi. Bozuk bir tercih nesnesi tek başına varsayılana dönüyor; kurtarma kodu onayını asla sıfırlamıyor.

**Python çekirdeği**

- `GET /api/v1/diagnostics` (içeriksiz).
- `prewarm_status` artık kapsamı da bildiriyor: `context` veya `model_only`.
- Son yanıtın ölçümleri (`last_turn`) kaydediliyor; başarısız turlar `failed` ve hangi aşamada kaldıklarıyla.
- `scheduler.holds()`: yalnızca sistem istemiyle yapılan ön ısıtma artık "sıcak konuşma" sayılmıyor. Bu, Faz 3 raporundaki §13.D sorununun düzeltmesi.
- Durum görünümündeki `quick_check` 10 dk önbelleğe alınıyor. Açılıştaki tam bütünlük denetimi aynen duruyor.
- Ayarlarda yedek model gösteriliyor (yalnızca bilgi; otomatik geçiş yok).
- Şema değişikliği ve göç yok. Sahibin veritabanına dokunulmuyor.

**Vue arayüzü**

- **Depolar:**
  - `stores/presence.ts`: durum türetme
  - `stores/preferences.ts`
  - `markdown.ts` ve `MarkdownContent.vue`
  - `PresenceIndicator.vue` (eski `CoreGlyph.vue` silindi)
- **Bağlantı deposu:**
  - Sağlık kontrolü 15 sn'de bir, yalnızca `/health`, pencere gizliyken duruyor.
  - Pencere görünür olunca ve uyandıktan sonra hemen kontrol ediyor.
  - `connectionEpoch` ile yeni arka uç oturumu tespit ediliyor.
- **Asistan deposu:**
  - Ollama yeniden denetimi 2/4/8/15/30 sn aralıklarla.
  - Uyandıktan sonra yeniden ısıtma.
  - Yayın koparsa yarım yanıt `interrupted` olarak korunuyor.
  - Yeniden başlatmadan sonra zaman çizelgesi yeniden yükleniyor.

**Yeni bağımlılık:** `markdown-it` 14.1.0. Alt bağımlılıkları: argparse, entities, linkify-it, mdurl, punycode.js, uc.micro. Geliştirme bağımlılığı olarak `@types/markdown-it` 14.1.2.

- Gerekçe: doğru CommonMark ve tablo desteği. Elle yazılmış bir ayrıştırıcı XSS açısından daha riskli olurdu.
- Rust tarafında yalnızca tauri'nin `tray-icon` özelliği açıldı. `Cargo.lock`'a yeni paket girmedi; PNG çözücü özelliği gerekmesin diye simge kodla çiziliyor.

## C. Kullanıcı arayüzü

- **Durum göstergesi (sol üst)**
  - Halka ve çekirdek biçiminde; yanında metin etiketi (`aria-live`).
  - Hazır'da hareketsiz. Düşünüyor'da halkalar döner, Yanıtlıyor'da çekirdek atar.
  - Hata etiketleri sorunu söylüyor: "Sorun var: arka uç çalışmıyor", "…yerel modele (Ollama) ulaşılamıyor", "Arka uç yeniden başlatılıyor (1/3)".
  - Durdurma bir hata değil: doğrudan Hazır'a dönüyor.
- **Yanıtlar**
  - Tamamlanan yanıtlar Markdown olarak gösteriliyor: başlık, kalın/eğik, liste, kod bloğu, satır içi kod, alıntı, bağlantı, tablo.
  - Yayın sürerken düz metin, böylece yarım sözdizimi titremiyor.
  - Kod bloğunda dil etiketi, yatay kaydırma ve "Kopyala" düğmesi. Her mesajda da kopyalama düğmesi var.
  - Bağlantıya tıklayınca tam adres gösterilip onay isteniyor; onaylanırsa varsayılan tarayıcıda açılıyor.
- **Kaydırma**
  - Yalnızca en alttaysanız yeni metni takip ediyor.
  - Yukarıda okurken ekran yerinde kalıyor ve "Yeni mesaj ↓" düğmesi çıkıyor.
  - Eski mesajlar yüklenince okuduğunuz yer korunuyor.
- **Ayarlar › Genel**
  - "Pencere kapatılınca menü çubuğunda çalışmaya devam et" (varsayılan açık).
  - "Açılışta pencereyi gösterme".
  - "Hareketleri her zaman azalt". Kapalıyken macOS'un "Hareketi azalt" ayarı izleniyor.
  - Bildirimler ve oturum açılışında başlatma için dürüstçe "bu sürümde yok" yazıyor.
  - Model, Gizlilik (yerel, SQLCipher ve Anahtar Zinciri, telemetri yok, FileVault durumu ve yönergesi; hiçbir şey otomatik değiştirilmiyor) ve salt okunur Yapılandırma bölümleri.
- **Tanılama (sekme):** Asistan, Arka uç, Model, Son yanıtın performansı, Bağlam hazırlığı ve Bellek kartları, ayrıca son olaylar.
  - Ön ısıtma yalnızca konuşma bağlamı hazırlandıysa "Bağlam hazırlandı" olarak gösteriliyor.
  - Boş oturumda "Model belleğe yüklendi; hazırlanacak konuşma bağlamı yoktu" yazıyor.
  - "Önbellek kesinlikle hazır" gibi bir ifade hiç yok. Sonraki yanıt için yalnızca bir beklenti gösteriliyor: "…kullanılması bekleniyor (Ollama bunu doğrulamaz)".
- **Menü çubuğu:** durum satırı, "LAZIS'i aç", "Sistem durumu", "Ayarlar", "LAZIS'ten çık".

## D. Sistem yönetimi ve dayanıklılık

| Durum | Davranış | Doğrulama |
|---|---|---|
| Arka uç çöktü | Kabuk çıkışı anında görüyor ve arayüze bildiriyor ("yeniden başlatılıyor 1/3"). 1 sn sonra yeni arka uç ve yeni oturum anahtarı geliyor; arayüz yeniden bağlanıp zaman çizelgesini yeniliyor. | Gerçek uygulama, `kill -9`: üç ölçümde 1,46 / 1,50 / 1,41 sn'de Hazır, eski süreç yok. Rust yaşam döngüsü testleri. |
| Kısa sürede 4. çökme | Döngüye girmiyor: `backend_restart_limit` ve "Yeniden dene" düğmesi. Elle deneme bütçeyi sıfırlıyor. | `restart_budget_is_bounded_and_manual_retry_resets_it` |
| Uygulama kapanıyor | Yeniden başlatma yok, elle deneme de çalışmıyor. ⌘Q veya menüden çıkışta arka uç düzgün kapanıyor. | `no_restart_once_the_app_is_quitting`; gerçek uygulamada 0,36–0,43 sn'de çıkış, arka uç kalmıyor |
| Ollama'ya ulaşılamıyor | "Sorun var" durumu ve açıklayıcı bant. Pencere görünürken 2/4/8/15/30 sn aralıklarla yeniden deneniyor, gizliyken duruyor. Ollama dönünce oturum yeniden ısıtılıyor. Ollama'ya, LaunchAgent'a veya ayarlarına dokunulmuyor; otomatik model değişimi yok. | `resilience.spec.ts`, çekirdekte runtime-down testleri |
| Yanıt yayını koptu | Yarım metin ekranda kalıyor ve `interrupted` olarak işaretleniyor; mesaj çoğalmıyor. Arka uç dönünce kaydedilen hâli yükleniyor. | `presence.spec.ts` (çökme senaryosu) |
| Uyku ve uyanma | Monoton ve duvar saati arasındaki fark ile tespit: 15 sn'de bir, eşik 30 sn. Uyanınca sağlık, Ollama ve ön ısıtma yeniden yapılıyor. | Birim testleri. **Gerçek uyku denenmedi**: Mac'i uyutmadım, sizin doğrulamanız gerekiyor (§I). |

## E. Performans

Bütün ölçümler: M4 Pro, 24 GB, macOS 27, Ollama 0.40.4 (LaunchAgent ayarları değiştirilmedi), `gemma4:12b-it-qat`.

### E.1 Gerçek uygulama, boşta

Yöntem:

- Release derlemesi, geçici profil.
- 60 sn boyunca birikimli CPU süresi (`ps`).
- Uyanma sayısı `top` ile.
- Bellek `phys_footprint` ile.
- İki tur ölçüm alındı.
- Faz 3 karşılaştırması aynı yöntemle: `0850d7d` ayrı bir çalışma ağacında derlendi.

| Senaryo | Kabuk CPU | WebContent CPU | GPU süreci | Arka uç | Kabuk uyanma/sn |
|---|---|---|---|---|---|
| **Faz 3**, pencere görünür, boşta | %4,83 / %4,79 | %6,14 / %6,13 | %0,37 | %0,29 / %0,27 | 25,6 / 32,2 |
| **Faz 4**, pencere görünür, boşta | %0,02 / %0,02 | %0,07 / %0,07 | %0,00–0,07 | %0,22–0,24 | 2,2 / 4,0 |
| Faz 4, pencere gizli (menü çubuğunda) | %0,0–0,02 | %0,0 | %0,0 | %0,20 | 0,6–1,8 |
| Faz 4, Tanılama açık (5 sn'de bir ölçüm) | %0,12–0,13 | %0,40–0,42 | %0,10–0,15 | %0,30–0,32 | 2,6–4,4 |

- **Boşta maliyetin nedeni:** Faz 3'teki logo animasyonu sürekli dönüyordu, üstüne 5 sn'de bir iki istek gidiyordu ve bunlardan biri her seferinde `quick_check` çalıştırıyordu.
- **Arka ucun kalan ≈ %0,2'si:** Python olay döngüsü ve bakım döngüsü; Faz 3'te de aynıydı.
- **Bellek (phys_footprint):** iki fazda benzer.
  - Kabuk 27–33 MB, arka uç ≈ 50 MB.
  - WebContent 56–124 MB (Tanılama açıkken ≈ 121 MB).
  - Faz 3'te WebContent 48–95 MB.
- **Tek seferlik gözlem:** başlatma sırası hatasının bulunduğu ara derlemede (hata o derlemede vardı), WebKit pencere öne gelince mesaj kutusuna odaklanmıştı. O turda görünür boşta değerler kabuk %1,3, GPU %1,6, WebContent %1,3 çıktı.
  - En olası neden yanıp sönen imleç, ama kanıtlanmadı: odak durumunu girdi izni olmadan yeniden üretemedim.
  - Bu değerler bile Faz 3'ün çok altında. Not: odaklanmış bir metin kutusunda imlecin yanıp sönmesi WebKit'in standart davranışı.

### E.2 Model yanıt süreleri (Faz 3 düzeneği Faz 4 koduyla yeniden çalıştırıldı)

`p3_assistant.py --out evals/reports/phase4/assistant_perf_rerun.json`; yanıtlar 200 token ile sınırlı. İlk token süresi (TTFT) ve toplam süre ayrı ayrı veriliyor.

| Senaryo | Faz 3 TTFT / toplam | Faz 4 TTFT / toplam |
|---|---|---|
| Ollama yeniden başlamış, hemen gönder (soğuk, model yükleniyor) | 28,20 / 29,65 sn | 26,51 / 32,94 sn (178 token; Faz 3'te 38 token) |
| Açtıktan 10 sn sonra gönder | 18,66 / 22,51 | 17,28 / 24,38 |
| Ön ısıtma bittikten sonra gönder | 0,39 / 8,14 | 0,37 / 7,55 |
| Aynı oturumda 2. mesaj | 1,25 / 5,48 | 1,18 / 4,69 |
| Aynı oturumda 3. mesaj | 0,96 / 5,42 | 0,77 / 4,17 |
| Uygulamayı kapatıp açma (Ollama açık) | 0,41 / 3,00 | 0,37 / 3,20 |
| 20.040 mesajlık geçmişten sonra ilk mesaj | 0,72 / 2,32 | 0,69 / 1,93 |
| Teknik oturum değişimi, ön ısıtmasız | 1,90 / 2,85 | 1,79 / 2,83 |
| Teknik oturum değişimi, ön ısıtmalı | 1,88 / 2,57 ("sıcak" bildirildi) | 1,75 / 2,39 ("soğuk" bildirildi) |
| Zaman çizelgesi sayfası (50 mesaj), 20.040 mesajda | ilk 0,3 ms, eski sayfalar 0,2 ms | aynı |

- **Sonuç:** model yolu değişmedi, süreler ölçüm gürültüsü içinde aynı.
- **Toplam süre farkları:** çoğunlukla yanıt uzunluğundan (token sayısı) kaynaklanıyor.
- **Son satırdaki "soğuk", bilinçli düzeltme.** Faz 3, boş oturumun yalnızca sistem istemiyle ısıtılmasını "sıcak" sayıyordu, oysa TTFT kazancı yoktu (Faz 3 raporu §13.D). Faz 4 bunu dürüstçe "soğuk" bildiriyor. Bu yüzden "ön ısıtmadan sonra sıcak bildirilen tur" sayısı 3/3'ten 2/3'e indi; süreler aynı.

### E.3 Faz 4'e özgü maliyetler (`p4_desktop.py`, yanıt sınırı üretim değeri 1024 token)

| Ölçüm | Sonuç |
|---|---|
| Normal yanıtlar, ≈ 7 bin token'lık oturum, 5 tur | TTFT medyan 1,14 sn (en az 0,39, en çok 1,40). Toplam medyan 8,4 sn; 72–195 token, uzunluğa bağlı. |
| Uzun yanıt (1007 token) | TTFT 0,91 sn, toplam 37,5 sn, 27,6 token/sn |
| Uzun yanıt, Tanılama 0,5 sn'de bir sorgulanırken (panelin 10 katı hızla, 84 çağrı) | 27,2 token/sn: **üretim hızı etkilenmedi**. Tanılama çağrısı medyan 5,6 ms (en çok 12,2 ms). |
| Boştayken tanılama çağrısı | medyan 1,5 ms |
| Bütünlük denetimi: ilk çağrı (`quick_check`) / önbellekten | 3,1 ms / 0,2 ms (küçük test veritabanında; büyük veritabanında ilk çağrı daha uzun sürer, artık 10 dk'da bir) |
| Arka uç çökmesinden sonra Hazır'a dönüş (gerçek uygulama) | 1,41–1,50 sn |
| Açılışta arka ucun hazır olması (gerçek uygulama) | ≈ 2,0 sn |

**Bulgu (Faz 4 kapsamı dışında, kaydedildi):** uzun bir yanıttan (≈ 1000 token) sonraki turun TTFT'si 4,7–5,1 sn'ye çıkıyor.

- Tanılama sorgusu olmadan yapılan kontrol turunda da 5,1 sn ölçüldü; yani neden tanılama değil.
- En olası neden: önceki yanıtın token'ları bir sonraki istemde yeniden işleniyor (önek önbelleği yanıtı kapsamıyor olabilir).
- Faz 3 ölçümleri 200 token'lık yanıtlarla yapıldığı için bu görünmemişti.
- Ayrıca incelenmeli (§J).

### E.4 Arayüz çizim maliyeti (yalnızca gösterge; Node içinde happy-dom, WebKit değil)

| Ölçüm | Sonuç |
|---|---|
| 11.491 karakterlik Markdown yanıt | medyan 0,39 ms |
| 200 mesajlık (100 Markdown yanıt) zaman çizelgesinin yüklenmesi | 123 ms |
| Yayın sırasında her güncelleme, ekranda 200 mesaj varken | medyan 9,6 ms, en çok 20 ms (tokenler ≈ 37 ms'de bir geliyor) |

Liste sanallaştırma gerekmedi: sayfalama ekrandaki mesaj sayısını sınırlıyor.

## F. Testler

| Katman | Faz 3 | Faz 4 | Yeni testler |
|---|---|---|---|
| Python (`make test-core`) | 307 | **315** | `test_diagnostics.py`: içeriksiz tanılama, runtime kapalı, ön ısıtma kapsamları, boş oturum ön ısıtması, iptal ve hata kaydı, bütünlük denetimi önbelleği |
| Arayüz birim (`make test-ui`) | 36 | **96** (+1 isteğe bağlı ölçüm, atlandı) | `presence.spec.ts` (19), `markdown.spec.ts` (21), `resilience.spec.ts` (10), `panels.spec.ts` (10) |
| Arayüz ↔ gerçek arka uç | 5 + 3 canlı | **6 + 3 canlı** | tanılama; canlı testte gerçek tur süreleri ve gerçek Gemma Markdown yanıtı |
| Rust birim | 19 | **30** | gezinme koruması, URL doğrulama, uyku tespiti, menü çubuğu simgesi ve durumları, phys_footprint, tercihler |
| Rust yaşam döngüsü (gerçek arka uç) | 7 | **9** | otomatik yeniden başlatma, sınırlı bütçe ve elle deneme, kapanırken yeniden başlatma yok |

- **`make check`:** çıkış kodu 0 (kontrol edildi). Lint, ruff, pyright strict, import-linter, vue-tsc ve clippy (`-D warnings`) temiz.
- **Gerçek modelle (Gemma) testler:**
  - `LAZIS_TEST_MODEL=gemma4:12b-it-qat make test-ui-integration` → 9/9.
  - `make test-ollama` → 3/3.
  - Sahte modelle çalışan testler gerçek model doğrulaması olarak sunulmadı. Gerçek modeli kullananlar yalnızca yukarıdaki canlı testler ve §E ölçümleri.
- **Gerçek uygulama denetimi (release derlemesi, geçici profil):**
  - gizli başlama;
  - `--show` ile görünüm açma (Tanılama ve Ayarlar ekran görüntüsüyle doğrulandı);
  - çökme ve otomatik dönüş;
  - temiz çıkış;
  - `desktop.log`'da uyarı yok.
- **Testlerin yakaladığı iki gerçek hata:**
  - Yanıt bitince durum bir an "Düşünüyor"a dönüyordu: tur, aşamadan önce temizleniyordu. Düzeltildi.
  - Bağlantı koptuktan sonra eski hata kırmızı durumu sürdürüyordu. Yeni arka uç oturumunda artık temizleniyor.

## G. Güvenlik

Ayrıntılar: SECURITY_MODEL §5.15.

- **Değişmeyenler:** bulut API, telemetri ve dışa aktarım yok. SQLCipher, Anahtar Zinciri, API kimlik doğrulaması ve işletim sistemi ağ kısıtı aynen duruyor. Yeni ağ izni yok.
- **Model çıktısı güvenilmeyen metin olarak ele alınıyor:**
  - Ham HTML metin olarak gösteriliyor; görsel yok.
  - Yalnızca http(s) bağlantılar; tıklamada onay isteniyor.
  - Kabukta ikinci doğrulama: kimlik bilgisi, kontrol karakteri ve uzunluk denetimi.
  - Pencerenin gezinme koruması ve yeni pencere reddi.
  - CSP ikinci savunma katmanı.
  - XSS vektörleri testlerde.
- **Tanılamada içerik ve sır yok:**
  - Tohumlanan gizli metin hem çekirdek testinde hem canlı testte yanıtta bulunmadı.
  - Bellek bilgisi yalnızca sayı; komut satırı veya ortam değişkeni okunmuyor.
  - Açılan bağlantının günlüğe yalnızca şeması yazılıyor.
- **Yeni komutlar:** 5 komut, ACL'de ve Rust'ta türü ve girdisi doğrulanıyor.
- **Kendiliğinden yapılmayanlar:** Ollama ve sistem ayarlarına dokunulmuyor, FileVault yalnızca açıklanıyor, otomatik model değişimi yok.
- **Sahibin verisine dokunulmadı:**
  - Ölçümler `p4verify` ve `p3base` geçici profilleriyle yapıldı; işten sonra dizinleri ve `database-key-v1-<profil>` anahtarları silindi.
  - `default` ve `dev` profillerine dokunulmadı.
  - Ekran görüntüleri yalnızca LAZIS penceresinden alındı ve inceledikten sonra silindi.

## H. Bilinen eksikler

1. **Uyku ve uyanma** gerçek donanımda denenmedi; yalnızca birim testleriyle doğrulandı.
2. **Menü çubuğu simgesinin görünümü ve tıklamalar** benim tarafımdan görsel olarak doğrulanamadı.
   - macOS 27'de menü çubuğu öğeleri uygulamaya ait pencere olarak listelenmiyor; MenuBarAgent barındırıyor.
   - Simge oluşturma hatasız tamamlandı; başarısız olsaydı uygulama açılmazdı.
3. **Arayüzde tıklama ve yazma gerektiren adımlar** (pencereyi kapatma, Dock, bağlantı onayı, kopyalama, gerçek sohbet) girdi iznim olmadığı için sizin doğrulamanıza bırakıldı. Mantıkları birim testlerinde sınanıyor.
   - **WKWebView'da pano erişimi** (`navigator.clipboard`) gerçek uygulamada denenmedi. Çalışmazsa "Kopyalanamadı" yazar.
4. **Ollama kapalıyken gerçek uygulama** denenmedi: Ollama'nızı durdurmadım. Bu davranış çekirdek ve arayüz testleriyle sınanıyor.
5. **Yapılmayanlar:**
   - oturum açılışında başlatma (SMAppService ve imzalı paket gerekiyor);
   - bildirimler;
   - sözdizimi renklendirme;
   - liste sanallaştırma;
   - arka uç durum WebSocket'i (Faz 13'e kaldı);
   - otomatik yedek model geçişi (bilinçli olarak);
   - menü çubuğu simgesinin renkle durum göstermesi: şablon simge kullanıldı, durum menü satırında ve ipucunda metin olarak gösteriliyor.
6. **Uzun yanıttan sonraki TTFT** (≈ 5 sn, §E.3): Faz 3'ten gelen bağlam/önbellek davranışı; çözülmedi, yalnızca kaydedildi.
7. **Yeniden derlenen uygulama** ilk açılışta Anahtar Zinciri erişimini yeniden soracak (§I).

## I. Sizin doğrulamanız için adımlar

Uygulamayı derleyin: `make build`, sonra `apps/desktop/src-tauri/target/release/bundle/macos/LAZIS.app`; ya da `make dev`.

1. **İlk açılış:** imza değiştiği için macOS, `database-key-v1` anahtarına erişim isteyecek. "Her zaman izin ver"i seçin.
   - Şema değişikliği yok; verileriniz göç edilmiyor.
2. **Durumlar:** bir mesaj gönderin. Sol üstte "Düşünüyor" (sarı, halkalar döner), ilk kelimelerle "Yanıtlıyor" (yeşil, çekirdek atar), sonra "Hazır" (mavi, hareketsiz) görünmeli. "Durdur" doğrudan "Hazır"a dönmeli.
3. **Markdown:** "Markdown ile bir tablo, bir liste ve bir Python kod bloğu yaz" yazın.
   - Tablo, liste ve kod bloğu düzgün görünmeli.
   - "Kopyala" düğmesi panoya kopyalamalı.
   - Bir bağlantıya tıklayınca onay kutusu çıkmalı.
4. **Kaydırma:** uzun bir yanıt sırasında yukarı kaydırın. Ekran aşağı çekilmemeli ve "Yeni mesaj ↓" düğmesi çıkmalı.
5. **Menü çubuğu:**
   - Halka ve nokta simgesi görünmeli; menüde durum satırı ve dört öğe olmalı.
   - Pencereyi kırmızı düğmeyle kapatın: LAZIS menü çubuğunda kalmalı.
   - Menüden ya da Dock'tan yeniden açın.
   - "LAZIS'ten çık" ya da ⌘Q tamamen kapatmalı.
6. **Tanılama:** model ve Ollama bilgisi, son yanıtın süreleri, "Bağlam hazırlandı" ve süreç bellekleri görünmeli. Hiçbir konuşma metni görünmemeli.
7. **Uyku:** LAZIS açıkken Mac'i birkaç dakika uyutun ve uyandırın. Tanılama › Son olaylar'da "Mac uykudan uyandı" görünmeli ve LAZIS "Hazır" olmalı.
8. **Ayarlar › Genel:** "Hareketleri her zaman azalt"ı açın; durum göstergesi bir mesaj sırasında da hareketsiz kalmalı.

## J. Sonraki fazlara etkisi

- **Faz 5 (kişilik motoru):**
  - Tanılamadaki son yanıt ölçümleri ve Markdown görüntüleme, kişilik değerlendirmelerini kolaylaştırır.
  - Kişilik istemi S0'a eklenirse önek değişir; ön ısıtma kapsamı (`context`) ve "sıcak/soğuk" beklentisi bunu dürüstçe gösterecek.
- **Uzun yanıt sonrası TTFT (§E.3):** gerçek kullanımda uzun yanıtlar sık olacak. Faz 5 öncesinde ya da Faz 5'in başında incelenmesini öneririm: istem ve önbellek hizalaması, yanıtın sohbet şablonunda nasıl yeniden token'landığı.
- **Faz 6+ (bellek):** tanılama kartları genişletilebilir; içerik göstermeme ilkesi aynen geçerli.
- **Faz 13 (ses):**
  - Dinliyor durumu ve mor renk hazır, `derivePresence` genişletilecek.
  - Arka uç durum kanalı (WebSocket) o zaman eklenecek.
  - Uyku/uyanma ve otomatik yeniden başlatma ses oturumunu da kapsamalı.
- **Faz 14 (son arayüz):** `PresenceIndicator` düşük güç ve "hareketi azalt" yedeği olarak kalacak. Boşta maliyetin ≈ 0 olması korunmalı (animasyon yalnızca etkin durumlarda).

**Onayınızı bekliyorum. Faz 5'e başlanmadı.**
