# LAZIS — Faz 1 Raporu: Temel Altyapı, Güvenli Depolama ve Masaüstü Başlangıcı

> Tarih: 2026-10-17 · Durum: **Faz 1 uygulandı ve doğrulandı; onayınızı bekliyor.** Faz 2'ye başlanmadı.
> **Faz 1.1 notu:** Bu rapor tarihsel kayıttır. Bazı güvenlik ifadeleri Faz 1.1 incelemesinde düzeltildi. Örneğin Bölüm A ve D'deki "internet erişimi süreç düzeyinde engelli" ifadesi uygulama düzeyindeki bir korumayı abartıyordu. Güncel ve doğrulanmış durum için [PHASE_1_1_REPORT.md](PHASE_1_1_REPORT.md) dosyasına bakın.
> Hedef makine: MacBook Pro M4 Pro (14 CPU / 20 GPU), 24 GB, macOS 27.0.1.
> İlgili belgeler: [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md) (geliştirici rehberi), [ADR-0003](adr/0003-storage-driver-and-encryption.md) (depolama ve şifreleme kararı), [ARCHITECTURE.md](ARCHITECTURE.md), [SECURITY_MODEL.md](SECURITY_MODEL.md).

---

## A. Yönetici Özeti

Faz 1'in amacı, yapay zekâ olmadan, güvenli ve test edilmiş bir temel kurmaktı. Bu temel artık çalışıyor:

- **Masaüstü uygulaması** (Tauri 2 + Vue 3, Türkçe, koyu tema) açılıyor, yerel Python arka ucunu kendisi başlatıyor, durumunu gösteriyor ve kapanırken arka ucu düzgünce durduruyor.
- **Veritabanı ilk günden şifreli** (SQLCipher 4.19, AES-256). Şifresiz SQLite'a geri düşme yolu yok. Şifrelemenin gerçekten etkin olduğu altı farklı yoldan doğrulandı.
- **Anahtar macOS Anahtar Zinciri'nde.** Anahtarı yalnızca Rust kabuğu okuyor ve arka uca yalnızca stdin üzerinden veriyor. Anahtar diske, komut satırına, ortam değişkenlerine veya günlüklere hiçbir zaman yazılmıyor.
- **Kurtarma kodu** (`LZR1-…`) ilk açılışta gösteriliyor. Anahtar Zinciri kaydı kaybolursa veriler bu kodla geri açılabiliyor. Arka kapı veya ana anahtar yok.
- **Yerel API** yalnızca 127.0.0.1'de dinliyor. Her istekte oturum belirteci, Host ve Origin denetimi yapılıyor. İnternet erişimi süreç düzeyinde engelli.
- **Testler:** 147 otomatik test çalıştırıldı ve hepsi geçti (arka uç 100, arayüz 19 + 3, Rust kabuğu 18 + 7). Gerçek Anahtar Zinciri'ne dokunan 1 isteğe bağlı test ayrıca çalıştırıldı ve geçti. Tüm statik denetimler temiz.
- **SPK-04/05 tamamlandı:** SQLCipher, sqlite-vec ve FTS5 birlikte çalışıyor. Şifreli vektör aramasının maliyeti ölçüldü ve çözümü belirlendi (Bölüm G). FileVault'a dayalı yedek plana gerek kalmadı.
- **Sürüm derlemesi** (`LAZIS.app`, 7,7 MB) derlendi, açıldı, ölçüldü ve temiz biçimde kapatıldı. Ardında yetim süreç kalmadı.

Bu fazda kasıtlı olarak **olmayanlar**: yapay zekâ modeli, sohbet, hafıza, bilgi grafiği, öğrenme, belge alma, internet araştırması, ses tanıma, ses sentezi, uyandırma sözcüğü, sürekli mikrofon ve son 3B arayüz. Arayüzdeki sohbet alanı devre dışı ve bunu açıkça söylüyor; sahte yanıt üretilmiyor.

**Onayınızı gerektiren sapmalar** (ayrıntılar: Bölüm O ve [DEVELOPMENT_ROADMAP.md](DEVELOPMENT_ROADMAP.md) "P1 as implemented"):

1. Masaüstü kabuğu ve durum arayüzü Faz 1'e alındı (Faz 1 talimatı bunu istiyordu). Faz 4'te sohbet arayüzü, WebSocket, otomatik yeniden başlatma ve tepsi simgesi kalıyor.
2. İş kuyruğu, olay veriyolu, bağımlılık kabı ve `cache.db` Faz 3'e ertelendi; bunları kullanacak bir bileşen henüz yok.
3. Görev çalıştırıcı olarak `just` yerine macOS ile gelen `make` kullanıldı.

---

## B. Depo Yapısı

```
Lazis/
├── Makefile                 # make help · setup · dev · build · check · test · lint · audit
├── README.md
├── core/                    # Python arka ucu (lazis-core)
│   ├── src/lazis/           # app · api · config · observability · security · storage (+ errors, i18n, ids, fsutil)
│   ├── tests/               # unit · integration · security · fixtures (Rust ile ortak kurtarma kodu vektörleri)
│   ├── spikes/              # SPK-04/05 betiği ve sonuçları
│   └── typings/sqlcipher3/  # pyright için tip tanımları
├── apps/desktop/
│   ├── src-tauri/           # Rust kabuğu: lib · controller · backend · keystore · secrets · recovery · paths · state_file · errors
│   │   └── tests/           # gerçek arka uçla yaşam döngüsü testleri
│   └── ui/                  # Vue 3 + TypeScript: api · platform · stores · components · views · i18n · styles · tests
├── docs/                    # mimari belgeler · adr/ · bu rapor
└── scripts/make_icon.py     # simge üreteci (saf Python)
```

Katman kuralları otomatik olarak denetleniyor (`import-linter`, "2 kept, 0 broken"):

- `app → api → storage → security | observability → config → errors | i18n | ids | fsutil` sırası korunuyor.
- `sqlcipher3`'ü yalnızca `storage/driver.py` içe aktarabiliyor.

**Git:** Depo zaten vardı ve üzerine yazılmadı. `.gitignore` eklendi: veritabanları, anahtarlar, günlükler, `data.noindex/`, `.venv`, `node_modules`, derleme çıktıları ve `.env` dışarıda tutuluyor. Daha önce izlenen `.DS_Store` izlemeden çıkarıldı. **Hiçbir şey commit edilmedi veya gönderilmedi**; isterseniz commit oluşturabilirim.

---

## C. Geliştirme Ortamı

| Araç | Sürüm | Not |
|---|---|---|
| uv | 0.13.1 | CPython 3.13.16'yı kendisi yönetiyor (`core/.python-version`) |
| Rust | 1.99.1 (edition 2024, en düşük 1.90) | Bu fazda `rustfmt` ve `clippy` bileşenleri ile `cargo-audit` kuruldu |
| Node / pnpm | 24.10 / 10.28.2 | `packageManager` alanıyla sabitlendi |
| Xcode CLT | — | `make`, `clang` |
| Docker | yüklü, **kullanılmıyor** | LAZIS'in hiçbir parçası Docker'a bağımlı değil |

Bağımlılıkların tam sürümleri kilit dosyalarında sabit: `core/uv.lock`, `apps/desktop/pnpm-lock.yaml` ve `apps/desktop/src-tauri/Cargo.lock`. Arayüz bağımlılıkları kesin sürümlerle yazıldı.

**Komutlar:**

- `make setup`: bağımlılıkları kurar.
- `make dev`: geliştirme modunda uygulamayı açar (`dev` profili, Vite :1420).
- `make build`: `LAZIS.app`'i derler.
- `make check`: tüm denetimleri ve testleri çalıştırır.
- `make audit`: bağımlılık güvenlik taraması yapar.
- `make spike-storage`: SPK-05'i yeniden üretir.

**Profiller:** Geliştirme ve gerçek kullanım birbirine karışmıyor.

- Sürüm derlemesi `default`, hata ayıklama derlemesi `dev` profilini kullanıyor.
- Her profilin veri klasörü, günlükleri, yapılandırması, masaüstü durum dosyası ve Anahtar Zinciri kaydı ayrı.
- `LAZIS_PROFILE=<ad>` ile tek kullanımlık profiller açılabiliyor. Doğrulamalar bu yolla yapıldı.

---

## D. Arka Uç (lazis-core)

**Yaşam döngüsü** (`app/server.py`) şu sırayla ilerliyor:

1. `umask 077` uygulanır.
2. Yapılandırma yüklenir ve doğrulanır.
3. Günlük kaydı başlatılır (gizli bilgi süzgeciyle).
4. Ağ koruması kurulur.
5. Gizli bilgiler stdin'den okunur (10 sn zaman aşımı).
6. Örnek kilidi alınır (`flock`).
7. Şifreli veritabanı açılır: sürücü denetimi, düz metin reddi, anahtar, göçler (öncesinde yedek), şifreleme ve bütünlük doğrulaması.
8. Sunucu 127.0.0.1'de, işletim sisteminin seçtiği bir bağlantı noktasında başlar.
9. Hazır olduğunda stdout'a `LAZIS_READY {port, pid, api_version, …}` yazılır. Hata olursa `LAZIS_FATAL {code}` yazılır ve süreç 3 koduyla çıkar.

**Kapanış:**

- Stdin kapanırsa ("yaşam hattı"), SIGTERM/SIGINT/SIGHUP gelirse ya da üst süreç değişirse arka uç düzgün kapanıyor.
- Kapanırken WAL `TRUNCATE` ile birleştiriliyor, denetim kaydına `app.stopped` (nedeniyle) yazılıyor, veritabanı kapatılıyor ve kilit bırakılıyor.
- Uvicorn'un sinyali yeniden fırlatıp temizliği atlatması hatası bulundu ve düzeltildi.

**API uç noktaları** (`/api/v1`, hepsi belirteç istiyor):

| Uç nokta | İçerik |
|---|---|
| `GET /health` | Genel durum ve veritabanı denetimi |
| `GET /app/info` | Sürüm, API sürümü, ortam, faz |
| `GET /system/status` | Arka uç (PID, çalışma süresi, tepe bellek), veritabanı (şifreleme doğrulandı mı, SQLCipher sürümü, şema, bütünlük, boyut), gizlilik (internet kapalı, araştırma modu `offline_only`, mikrofon kapalı, ses devre dışı), yapay zekâ ("henüz yapılandırılmadı"), platform |
| `GET /settings` | Gizli olmayan etkin ayarlar (salt okunur) |

**Hata yönetimi:**

- Her hatanın kararlı bir `code` değeri var: `database_key_invalid`, `instance_already_running`, `config_invalid` gibi.
- Kullanıcıya Türkçe ileti, `recoverable` bayrağı ve `request_id` dönüyor.
- Yığın izi veya iç ayrıntı asla dönmüyor. Beklenmeyen hatalar genel bir Türkçe ileti olarak dönüyor.
- Doğrulama hataları değerleri değil, yalnızca alan yollarını içeriyor.

**Günlükler:**

- `core.log` JSON satırlarından oluşuyor, döndürülüyor (10 × 10 MB) ve izinleri 0600.
- Süzgeç her kayıtta belirteçleri, 48+ karakterlik hex dizilerini, `LZR1-` kodlarını ve `x'…'` anahtar biçimini maskeliyor.
- Uvicorn erişim günlüğü kapalı; istek içerikleri günlüğe yazılmıyor.

**Ağ koruması:**

- PEP 578 denetim kancası, döngü (loopback) dışındaki her `connect`, `sendto`, `sendmsg`, `bind` ve DNS çağrısını reddediyor; Unix soketlerine izin veriyor.
- Yapılandırmada `network.egress_enabled` alanı yalnızca `false` olabiliyor.

---

## E. Masaüstü Uygulaması

**Rust kabuğu** (`apps/desktop/src-tauri/src/`):

| Modül | Görev |
|---|---|
| `paths.rs` | Profil çözümleme, 0700 klasörler, arka uç konumu |
| `keystore.rs` | Anahtar Zinciri (security-framework), bellek içi test deposu, anahtar çözümleme kuralları |
| `secrets.rs` | `SecRandomCopyBytes` ile anahtar ve belirteç üretimi; `zeroize`; `Debug` çıktısında `****` |
| `recovery.rs` | `LZR1` kodlayıcı (Python ile bayt bayt aynı; ortak test vektörleri) |
| `backend.rs` | Süreç başlatma (temizlenmiş ortam), stdin el sıkışması, yaşam hattı, kademeli kapatma (stdin → SIGTERM → SIGKILL), her durumda süreç toplama |
| `controller.rs` | Durum makinesi (`starting`/`ready`/`failed`/`needs_recovery`/`stopped`), yeniden deneme, kurtarma kodu gösterme/onaylama/geri yükleme, beklenmedik çıkışı algılama |
| `state_file.rs` | `desktop-state.json` (0600): yalnızca "kurtarma kodu kaydedildi mi" bilgisi |
| `lib.rs` | Beş Tauri komutu, bağlantı olayı, tek örnek eklentisi, günlük eklentisi (`desktop.log`, döndürmeli), `umask 077`, çıkışta arka ucu kapatma |

**Arayüz** (Türkçe, koyu tema, hareket azaltma ayarına uyumlu):

- **Üst çubuk:** LAZIS kimliği, sekmeler (Genel bakış, Ayarlar, Tanılama), bağlantı durumu, sürüm.
- **Genel bakış:** Arka uç, Veritabanı, Gizlilik, Sistem ve Yapay Zekâ kartları ile devre dışı sohbet alanı ("Sohbet özelliği Faz 3'te gelecek… sahte yanıt gösterilmez").
- **Ayarlar:** Etkin yapılandırma, salt okunur.
- **Tanılama:** Son 50 bağlantı olayı ve hata kodu.
- **Başlatma hatası ekranı:** Türkçe açıklama ve "Yeniden dene".
- **İlk açılış:** Kurtarma kodu penceresi ("Kodu göster" → "Kodu güvenli bir yere kaydettim" → "Devam et").
- **Geri yükleme paneli:** Anahtar kaybolduğunda kurtarma kodu girişi.

**Doğrulama:**

- Sürüm ve geliştirme derlemeleri tek kullanımlık profillerle açıldı. Yalnızca LAZIS penceresinin görüntüsü alındı; tam ekran görüntüsü alınmadı.
- İlk açılış penceresi ve dolu Genel bakış ekranı görüldü: "SQLCipher etkin · disk üzerinde doğrulandı", "İnternet erişimi: Kapalı", "Araştırma modu: Yalnızca çevrimdışı", "Mikrofon: Kapalı".
- Doğrulama sırasında pencereler ekranınızda açıldı. Günlüklere göre ilk açılış penceresindeki "Kodu göster" ve "Devam et" adımları da elle kullanıldı ve beklendiği gibi çalıştı.
- Doğrulamadan sonra tek kullanımlık profillerin veri ve günlük klasörleri, Anahtar Zinciri kayıtları ve WebKit önbellekleri silindi. Gerçek `default` ve `dev` profilleri hiç oluşturulmadı; ilk gerçek açılışınız gerçek bir ilk açılış olacak.

---

## F. Yerel İletişim

**Arayüz ↔ Rust (Tauri IPC):**

- Komutlar: `backend_connection`, `retry_backend`, `reveal_recovery_code`, `acknowledge_recovery`, `restore_from_recovery_code`. Olay: `lazis://backend-connection`.
- Uygulama komutları bir ACL bildirimiyle (`build.rs`) yetki sistemine bağlandı. Ana pencerenin izinleri yalnızca bu beş komut ile olay dinleme/bırakmadan ibaret.
- Kabuk, dosya sistemi, HTTP veya dış bağlantı açma gibi eklentiler yok.
- Webview veritabanı anahtarını hiçbir zaman görmüyor. Yalnızca bağlantı noktasını ve oturum belirtecini alıyor; belirteç de yalnızca `ready` durumunda gönderiliyor.

**Arayüz ↔ arka uç (HTTP, 127.0.0.1):** Her istek `LocalApiGuard` katmanından şu sırayla geçiyor:

1. Hız sınırı
2. `Host` = `127.0.0.1:{port}` (DNS yeniden bağlama saldırılarına karşı)
3. `Origin` izin listesi (`tauri://localhost`; yalnızca geliştirmede `http://localhost:1420`)
4. CORS ön uçuş isteği (belirteçsiz yanıtlanıyor, veri dönmüyor)
5. Bearer belirteç (sabit zamanlı karşılaştırma)
6. Gövde sınırı (64 KB)

Ek olarak:

- Yanıtlarda `no-store`, `nosniff`, `no-referrer` ve `DENY` başlıkları var.
- Reddedilen istekler denetim kaydına yazılıyor.
- **Yalnızca 127.0.0.1'e bağlanmak kimlik doğrulama sayılmıyor**; her uç nokta belirteç istiyor.

**Belirteç** her açılışta yeni üretiliyor (256 bit) ve hiçbir yere kaydedilmiyor. Arayüzde reaktif durumda değil, yalnızca istemci kapanımında (closure) tutuluyor.

**Tip güvenliği:** Pydantic → OpenAPI anlık görüntüsü → `openapi-typescript`. Görüntü koddan saparsa test başarısız oluyor. Arka uç hata kodlarının her birinin Türkçe karşılığı olduğu da ayrı bir testle denetleniyor.

**CSP:** `default-src 'self'`; `connect-src` yalnızca IPC ve `http://127.0.0.1:*`. Uzak betik, nesne, çerçeve veya form hedefi yok. `freezePrototype` etkin.

---

## G. Veritabanı Şifreleme

**Yapılandırma:**

- SQLCipher 4.19.0 community (SQLite 3.53.4; resmî `sqlcipher3` 0.6.4 paketi, içinde OpenSSL 3.6.0).
- Ham 256 bit anahtar; WAL, `secure_delete=ON`, `foreign_keys=ON`, `temp_store=MEMORY`.
- Dosyalar `data.noindex/` altında, izinleri 0600/0700.

**Şifrelemenin gerçekten etkin olduğu şu yollarla doğrulandı:**

1. Dosya başlığı `SQLite format 3` değil (açılıştan sonra her seferinde denetleniyor).
2. WAL dosyası da şifreli.
3. Standart Python `sqlite3` dosyayı okuyamıyor.
4. `/usr/bin/sqlite3` okuyamıyor.
5. Ayrı derlenmiş `sqlcipher` komut satırı aracı anahtar olmadan okuyamıyor, doğru anahtarla (stdin üzerinden) okuyabiliyor.
6. Yanlış anahtar `database_key_invalid` ile reddediliyor.

**Düz metne geri düşme yok:**

- `PRAGMA cipher_version` boşsa uygulama başlamıyor (`encryption_unavailable`).
- Var olan düz metin bir dosya reddediliyor (`database_plaintext_detected`).

Bunlar testlerle kanıtlandı.

**Şema (`0001_system`):** `app_meta`, `settings`, `change_sets`, `history`, `audit_log` (hepsi STRICT) ve göç izleme tablosu `schema_migrations`.

**Göçler:**

- Yalnızca ileri yönlü, sağlama toplamlı ve her biri atomik.
- Değiştirilmiş veya bilinmeyen bir göç başlangıcı durduruyor.
- Var olan bir veritabanında göçten önce şifreli yedek alınıyor.

**Değişiklik kümeleri:** `UnitOfWork` ile her değişiklik geçmişe yazılıyor. `revert_change_set` sonradan yapılan düzenlemelerin üzerine yazmıyor, çakışmaları raporluyor.

**Yedekler:** `sqlcipher_export` ile şifreli kopya, SHA-256 bildirim dosyası, doğrulama ve atomik geri yükleme. Döndürme sınırı 10.

**SPK-05 ölçümleri** (50.000 × 768 vektör, k = 10; ayrıntı: [ADR-0003](adr/0003-storage-driver-and-encryption.md)):

| Durum | Sorgu (p50) |
|---|---|
| float32, şifresiz (referans) | 19,6 ms |
| float32, şifreli, varsayılan 2 MB önbellek | 160 ms (hedefi kaçırıyor) |
| float32, şifreli, 256 MB önbellek (ısınmış) | **5,4 ms** (ilk sorgu ~165 ms) |
| int8, şifreli, 256 MB önbellek (ısınmış) | **2,4 ms** (ilk sorgu ~44 ms) |
| FTS5, şifreli / şifresiz | 0,25 / 0,24 ms |

**Karar:** Şifreleme varsayılan olarak açık kalıyor. Faz 6'da vektör bağlantısının sayfa önbelleği vektör tablosu boyutuna göre ayarlanacak ve arka planda ısıtılacak. Bellek sıkışırsa int8 kullanılacak. Bedeli, 50 bin öğe için yaklaşık 40–160 MB bellek.

---

## H. Anahtar Yönetimi

- **Üretim:** İlk açılışta Rust kabuğu `SecRandomCopyBytes` ile 32 bayt üretiyor ve Anahtar Zinciri'ne yazıyor.
  - Kayıt: giriş anahtar zinciri, servis `com.lazis.app`, hesap `database-key-v1` (`dev` profilinde `-dev`), iCloud ile eşitlenmiyor.
  - Anahtar geri okunup doğrulanıyor; **ancak bundan sonra** veritabanı oluşturuluyor. Böylece kaydedilmemiş bir anahtarla veritabanı oluşması imkânsız.
- **Çözümleme kuralları:**

| Durum | Davranış |
|---|---|
| Kayıt var | Kullanılıyor |
| Kayıt yok, veritabanı yok | Yeni anahtar üretiliyor |
| Kayıt yok, veritabanı var | `needs_recovery`; **yeni anahtar üretilmiyor** |
| Erişim reddedildi | `keychain_denied` (atlatılmıyor) |
| Anahtar veritabanını açmıyor | `needs_recovery` |

- **Kurtarma kodu biçimi (`LZR1`):** Anahtar ile SHA-256 sağlamasının ilk 4 baytı birleştiriliyor, Crockford base32 ile kodlanıyor ve 5'li gruplara bölünüyor (58 karakter).
  - Büyük/küçük harf, boşluk ve tire fark etmiyor; O/0 ve I/L/1 karışıklığına toleranslı; yazım hatalarını sağlama yakalıyor.
  - Kod yalnızca "Kodu göster"e basınca görünüyor ve onaylanana kadar her açılışta yeniden soruluyor.
  - Onaydan sonra Faz 1'de yeniden gösterilemiyor; Touch ID veya parola ile yeniden gösterme ileride eklenecek.
- **Geri yükleme:**
  - Kod çözülüyor ve arka uç bu anahtarla başlatılıyor.
  - Veritabanı açılırsa anahtar Anahtar Zinciri'ne geri yazılıyor.
  - Başka bir veritabanının geçerli kodu reddediliyor (`recovery_code_wrong_database`) ve hiçbir şey kaydedilmiyor.
  - Bu akışların tamamı gerçek arka uçla test edildi.
- **Arka kapı yok.** Hem anahtar hem kurtarma kodu kaybolursa veriler kurtarılamaz; pencere bunu açıkça söylüyor.
- **Sınırlama:** Geliştirme derlemeleri ad-hoc imzalı. macOS, Anahtar Zinciri erişimini ikili dosyanın imzasına bağladığı için her yeniden derlemeden sonra bir kez izin sorabilir ("Her Zaman İzin Ver" yeterli). "Yalnızca bu aygıt" erişim sınıfı imzalı uygulama ve yetki tanımı gerektirdiği için paketleme fazına bırakıldı.

---

## I. Yapılandırma

- **Bölümler:** `app`, `backend`, `storage`, `logging`, `network`, `research`, `models`, `voice`. Pydantic v2 ile tanımlı, değişmez; bilinmeyen anahtarlar reddediliyor.
- **Öncelik sırası:**
  1. Kullanıcı TOML'u (`<profil>/config.toml`, isteğe bağlı)
  2. `LAZIS_BÖLÜM__ALAN` ortam değişkenleri (yalnızca bağımsız çalıştırma ve testlerde; kabuk ortamı temizliyor)
  3. Kabuğun verdiği komut satırı değerleri
- **Tür düzeyinde kilitli değerler** (başka değer doğrulamadan geçemez):
  - `network.egress_enabled = false`
  - `voice.enabled = false`
  - `voice.microphone_always_on = false`
  - `research.mode` varsayılanı **`offline_only`**; Faz 12'ye kadar başka değer kabul edilmiyor.
  - `backend.host` ve `models.endpoint` yalnızca döngü (loopback) adresi olabilir.
- **Yer tutucular:**
  - `models`: sağlayıcı `ollama`/`openai_compatible`, uç nokta `http://127.0.0.1:11434`, model yok, bağlam 16384.
  - `voice`: bas-konuş / eller serbest oturum.
  - `research`: dört mod adı.
- **Hatalar:** Yapılandırma hatası değeri değil, yalnızca alan yolunu ve iletiyi gösteriyor (`config_invalid`). Bozuk TOML'da yalnızca satır ve sütun bildiriliyor.

---

## J. Testler

Hepsi bu fazda **çalıştırıldı**; aşağıdaki sayılar son `make check` çıktısından alındı.

| Takım | Sayı | Kapsam |
|---|---|---|
| Arka uç (pytest) | **100 geçti** | Yapılandırma katmanları ve kilitler; günlük süzgeci; kurtarma kodu (vektörler, yazım hataları); şifreleme kanıtları (yukarıdaki 6 yol); göçler (sağlama, sıra, yedek); değişiklik kümeleri ve geri alma çakışmaları; yedek → geri yükleme; kurtarma koduyla geri yükleme; API uç noktaları ve OpenAPI sapması; güvenlik (belirteç, Origin, Host, ön uçuş, gövde sınırı, hız sınırı, belge uç noktalarının kapalı olması, iç hata sızdırmama, reddedilenlerin denetimi); ağ koruması; gerçek süreç testleri (düzgün kapanma, yalnızca loopback (`lsof`), LAN adresi reddi, yeniden başlatmada verinin korunması, yanlış anahtar, ikinci örnek, gizli bilgi zaman aşımı, geçersiz yapılandırma, SIGTERM, çıktılarda gizli bilgi olmaması, başlatma süresi, yaşam hattı) |
| Arayüz birim (Vitest) | **19 geçti** | Bağlantı deposu (aşamalar, yoklama, hata/yeniden deneme, kurtarma), API istemcisi (hatalar, zaman aşımı), uygulama bileşeni, Türkçe metinlerin arka uç kodlarını eksiksiz karşılaması |
| Arayüz bütünleşik | **3 geçti** | TypeScript istemcisi gerçek bir arka uç sürecine karşı |
| Rust birim | **18 geçti** | Kurtarma kodunun Python vektörleriyle bire bir uyumu, anahtar çözümleme kuralları, Anahtar Zinciri hata eşlemesi, profiller, durum dosyası izinleri, el sıkışma ayrıştırma |
| Rust yaşam döngüsü | **7 geçti** | Gerçek arka uçla: ilk açılış → yeniden başlatma → anahtar kaybı → yanlış kod reddi → doğru kodla kurtarma; Anahtar Zinciri'nde yanlış anahtar; arka uç SIGKILL ile ölünce algılama ve yeniden deneme; eksik çalışma ortamı; tanıtıcı bırakılınca sürecin durması; ikinci örnek reddi; argv, ortam ve günlüklerde gizli bilgi olmaması (çekirdekten `KERN_PROCARGS2` ile okunarak) |
| Gerçek Anahtar Zinciri (isteğe bağlı) | **1 geçti** | Ayrı bir test kaydıyla yazma/okuma/silme; kayıt sonradan silindi |

- **Statik denetimler:** ruff, ruff format, pyright strict (0 hata), import-linter (2/2), vue-tsc, rustfmt, clippy `-D warnings` — hepsi temiz.
- **Test verisi:** Yalnızca sentetik veri kullanıldı; gerçek kişisel veri kullanılmadı.
- **Kapsanmayanlar** (dürüstçe): Playwright ile uçtan uca arayüz testi yok (Faz 4). Tam uygulama pencere görüntüleri ve günlüklerle elle doğrulandı. Pytest'te 1 uyarı var: Starlette'in test istemcisiyle ilgili kullanımdan kaldırma uyarısı; yalnızca testleri etkiliyor.

---

## K. Performans

Ölçümler tek makinede ve az sayıda tekrarla yapıldı; eğilim gösterirler, istatistiksel kesinlik iddia etmezler.

| Ölçüm | Sonuç |
|---|---|
| Arka uç başlatma (süreç → `LAZIS_READY`) | 230–335 ms (sürüm derlemesi), 406 ms (geliştirme) |
| Uygulama açılışı, normal | Pencere 0,29 sn, arka uç hazır 0,49 sn |
| Uygulama açılışı, ilk kez (anahtar üretimi + veritabanı oluşturma) | Pencere 1,10 sn, arka uç hazır 1,39 sn |
| Kapanış (çıkış komutu → tüm süreçler bitti) | 0,39–0,43 sn; arka uç her seferinde "Graceful" (207–246 ms) |
| Kabuk SIGKILL ile öldürülünce arka ucun kendini kapatması | 0,35 sn (veritabanı düzgün kapandı) |
| Boşta CPU (30 sn, 5 süreç toplamı) | ~%1,5 (arayüz 5 sn'de bir sağlık sorgusu yapıyor) |
| Boşta bellek (fiziksel ayak izi) | Kabuk 42 MB · arka uç 40 MB · WebKit içerik 61 MB · WebKit GPU 135 MB · WebKit ağ 7 MB → **~285 MB** (RSS toplamı 351 MB) |
| Paket boyutu | `LAZIS.app` 7,67 MB; arayüz JS 153 KB (gzip 55 KB) |
| Test süreleri | pytest ~8 sn · Rust yaşam döngüsü ~1,7 sn · SPK-05 tam çalıştırma 16,6 sn |

Not: WebKit GPU sürecinin 135 MB'ı büyük olasılıkla CSS bulanıklık efektleri ve kompozisyon katmanlarından geliyor. Faz 4'te incelenecek.

---

## L. Güvenlik İncelemesi

| Alan | Sonuç |
|---|---|
| Bağımlılık taraması | `pip-audit`: bilinen açık yok · `pnpm audit`: bilinen açık yok · `cargo audit`: açık yok, 2 uyarı (`glib` ve `proc-macro-error`). Bu ikisi yalnızca Linux GTK bağımlılıkları; macOS derlemesine girmedikleri `cargo tree --target aarch64-apple-darwin` ile doğrulandı. Bu taramalar paket adlarını ve sürümlerini herkese açık güvenlik veritabanlarına gönderir; proje dosyası gönderilmedi |
| Koda gömülü gizli bilgi | Tarandı (özel anahtar, bulut anahtarı ve belirteç kalıpları, 64 haneli hex). Tek eşleşme sentetik test vektörleri dosyası (sıfır anahtar gibi bilinen değerler) |
| Dosya izinleri | Veri ve günlük klasörleri 0700; veritabanı, WAL, kilit, durum ve günlük dosyaları 0600 (çalışan uygulamada gözlendi) |
| Ağ | Arka uç yalnızca `127.0.0.1:<port>` dinliyor (`lsof`); kabuğun hiç ağ soketi yok; ağ koruması döngü dışını engelliyor |
| Gizli bilgiler | Argv, ortam, stdout/stderr, `core.log` ve `desktop.log` içinde yok (testler + uygulama çalıştırması sonrası tarama: 0 eşleşme) |
| Tauri | Yalnızca 5 uygulama komutu ve olay dinleme izni; ek eklenti yok; sıkı CSP; `freezePrototype`; geliştirici araçları yalnızca hata ayıklama derlemesinde |
| Paket | Ad-hoc imzalı, yetki tanımı (entitlement) yok; `Info.plist` içinde mikrofon, kamera veya başka bir gizlilik izni yok (macOS bu derlemeye mikrofon izni veremez) |
| Docker / model / araştırma | Hiçbiri kullanılmıyor veya başlatılmıyor |

**İnceleme sırasında bulunan ve düzeltilenler:**

1. `desktop.log` 0644 izniyle oluşuyordu (0700 klasör içinde olduğundan erişilemez durumdaydı). Kabuğa `umask 077` eklendi; artık 0600 oluşuyor (doğrulandı).
2. Arka ucun argv ve ortamında gizli bilgi olmadığını kanıtlayan bir test yoktu. Rust testi eklendi; ilk sürümü macOS `ps` aracının ortamı göstermediğini fark etmediği için çekirdekten okuyacak biçimde düzeltildi.
3. Arka uç yolu `../../../core` biçiminde görünüyordu; artık kanonik yol kullanılıyor.

**Kalan riskler** (kabul edildi, belgelendi):

- Kullanıcı hesabında çalışan kötü amaçlı yazılım, uygulama açıkken API'ye erişebilir ve Anahtar Zinciri izni isteyebilir.
- Çalışan süreçlerin belleği okunabilir.
- Kurtarma kodunu bilen herkes verileri açabilir.

---

## M. Bilinen Sorunlar ve Sınırlamalar

1. **Bağımsız paket değil:** Sürüm uygulaması arka ucu deponun `core/.venv` ortamından çalıştırıyor. İmzalı, notarize edilmiş, gömülü Python'lu paket sonraki bir fazın işi (R15).
2. **Anahtar Zinciri izni:** Ad-hoc imza yüzünden her yeniden derlemeden sonra macOS bir kez izin sorabilir. "Yalnızca bu aygıt" erişim sınıfı da imzalı uygulamayı bekliyor.
3. **Otomatik yeniden başlatma yok:** Arka uç beklenmedik biçimde kapanırsa bu algılanıyor ve "Yeniden dene" sunuluyor; geri çekilmeli otomatik yeniden başlatma Faz 4'te.
4. **Kurtarma kodu onaydan sonra yeniden gösterilemiyor** (yerel kimlik doğrulamalı gösterim ileride).
5. **Kod ve anahtar birlikte kaybolursa** arayüzde "sıfırdan başla" seçeneği yok. Veri klasörünü elle taşımak gerekiyor (rehberde anlatıldı). Bu bilinçli bir tercih: veri silmeye giden yol kolay olmamalı.
6. **Spotlight ve Time Machine:** `data.noindex` adlandırmasının macOS 27'de Spotlight'ı dışarıda tuttuğu ayrıca doğrulanmadı; Time Machine dışlaması uygulanmadı.
7. **FileVault denetimi** henüz sistem durumunda gösterilmiyor (Faz 4'teki gizlilik göstergesine eklenecek).
8. **WebKit GPU belleği** (~135 MB) azaltılabilir (Faz 4).
9. **Testler:** Starlette test istemcisi kullanımdan kaldırma uyarısı veriyor (yalnızca testler). Playwright uçtan uca testleri Faz 4'te.
10. **Geliştirme penceresi** (`pnpm tauri dev`) AppleScript ile kapatılamıyor; pencereden veya terminalden kapatılmalı.
11. **Uç durum:** Anahtar Zinciri'nde veritabanını açmayan bir anahtar varken kurtarma kodu girilirse eski kayıt yenisiyle değiştiriliyor. Eski anahtar bu veritabanını zaten açamadığı için veri kaybı yok, ama eski anahtarla alınmış yedekler varsa onlar için o anahtar gerekir.

---

## N. Dosyalar

**Yeni — kök:** `.gitignore`, `Makefile`, `scripts/make_icon.py`

**Yeni — arka uç (`core/`):**

- Proje dosyaları: `pyproject.toml`, `uv.lock`, `.python-version`
- `src/lazis/` kökü: `__init__.py`, `__main__.py`, `errors.py`, `i18n.py`, `ids.py`, `fsutil.py`
- `src/lazis/app/`: `cli.py`, `server.py`, `handshake.py`
- `src/lazis/api/`: `app_factory.py`, `security.py`, `schemas.py`
- `src/lazis/config/`: `model.py`, `loader.py`
- `src/lazis/observability/`: `logging.py`, `redaction.py`
- `src/lazis/security/`: `secrets.py`, `network_guard.py`, `recovery.py`
- `src/lazis/storage/`: `__init__.py`, `driver.py`, `database.py`, `unit_of_work.py`, `repositories.py`, `backup.py`, `migrations/__init__.py`, `migrations/lazis/0001_system.sql`
- Testler: `tests/conftest.py`, `tests/process_helpers.py`, `tests/fixtures/recovery_vectors.json`
  - `tests/unit/`: `test_config.py`, `test_logging_redaction.py`, `test_recovery_codec.py`
  - `tests/integration/`: `test_storage_encryption.py`, `test_migrations.py`, `test_unit_of_work.py`, `test_backup_and_recovery.py`, `test_api_endpoints.py`, `test_server_process.py`
  - `tests/security/`: `test_api_security.py`, `test_network_guard.py`
- Diğer: `typings/sqlcipher3/{__init__,dbapi2}.pyi`, `spikes/spk05_storage.py`, `spikes/results/spk05-m4pro-2026-10-17.json`

**Yeni — masaüstü (`apps/desktop/`):**

- Proje dosyaları: `package.json`, `pnpm-lock.yaml`, `tsconfig.json`, `vite.config.ts`, `vitest.config.ts`, `vitest.integration.config.ts`
- `src-tauri/` kökü: `Cargo.toml`, `Cargo.lock`, `build.rs`, `rustfmt.toml`, `tauri.conf.json`, `capabilities/main.json`, `permissions/autogenerated/*.toml` (5 dosya), `icons/*`
- `src-tauri/src/`: `main.rs`, `lib.rs`, `controller.rs`, `backend.rs`, `keystore.rs`, `secrets.rs`, `recovery.rs`, `paths.rs`, `state_file.rs`, `errors.rs`
- `src-tauri/tests/lifecycle.rs`
- `ui/` kökü: `index.html`
- `ui/src/` kökü: `main.ts`, `App.vue`, `env.d.ts`, `format.ts`
- `ui/src/api/`: `client.ts`, `openapi.json`, `schema.d.ts`
- `ui/src/platform/tauri.ts`, `ui/src/stores/connection.ts`
- `ui/src/i18n/`: `index.ts`, `tr.ts`
- `ui/src/styles/theme.css`
- `ui/src/components/`: `CoreGlyph.vue`, `StatusPill.vue`, `StatusCard.vue`, `types.ts`, `ConversationPlaceholder.vue`, `RecoveryCodeDialog.vue`, `RestorePanel.vue`, `StartupError.vue`
- `ui/src/views/`: `OverviewView.vue`, `SettingsView.vue`, `DiagnosticsView.vue`
- `ui/tests/unit/`: `fixtures.ts`, `connection.spec.ts`, `client.spec.ts`, `app.spec.ts`, `i18n.spec.ts`
- `ui/tests/integration/backend.integration.spec.ts`

**Yeni — belgeler:** `docs/PHASE_1_REPORT.md` (bu rapor), `docs/DEVELOPER_GUIDE.md`, `docs/adr/0003-storage-driver-and-encryption.md`

**Güncellenen belgeler:**

| Belge | Değişiklik |
|---|---|
| `README.md` | Faz 1 durumu ve hızlı başlangıç |
| `ARCHITECTURE.md` | Uygulanan yaşam döngüsü, API, yapılandırma, veri konumları, depo yapısı |
| `SECURITY_MODEL.md` | Anahtar sahipliği Rust'ta, `LZR1` biçimi, ağ koruması, SPK-05 sonuçları, yerel tehdit modeli tablosu |
| `DEVELOPMENT_ROADMAP.md` | "P1 as implemented"; Faz 3'e ertelenenler; Faz 4'ten Faz 1'e alınanlar |
| `TECHNOLOGY_DECISIONS.md` | Sürücü ve şifreleme kararları, Docker'sız araştırma, kurulu yığın sürümleri |
| `RESEARCH_ARCHITECTURE.md` | `offline_only` adı, Docker'sız ve sağlayıcıdan bağımsız araştırma; SearXNG yalnızca isteğe bağlı ve yerel kurulumla |
| `PERSONALITY_ENGINE.md` | "Efendim" hitabı kuralları: ölçülü kullanım, sıklık sınırları, denetim ve testler; uygulama Faz 5'te |
| `VOICE_ARCHITECTURE.md` | Faz 1 mikrofon kilidi notu |
| `REQUIREMENTS.md`, `ACCEPTANCE_CRITERIA.md`, `ENGINEERING_STANDARDS.md`, `RISK_ASSESSMENT.md` | Docker'sız araştırma, `offline_only`, R23 durumu |

**Silinen:** Yalnızca izlemeden çıkarılan `.DS_Store`. Var olan hiçbir proje dosyası silinmedi.

---

## O. Faz 2 Hazırlığı

**Faz 2'nin dayanacağı temel hazır:**

- `models` yapılandırma bölümü (yalnızca loopback uç noktası) mevcut.
- Ağ koruması `127.0.0.1:11434` adresine (Ollama) izin veriyor ve başka her yeri engelliyor.
- Hata, günlük ve API sözleşmesi altyapısı kurulu.
- Ollama 0.40.4 kurulu; model indirilmedi.

**Faz 2'de yapılacaklar** (yol haritasına göre):

- Sağlayıcı arayüzleri: Ollama, OpenAI uyumlu, sahte (fake) sağlayıcı.
- Model sabitleme ve doğrulama.
- Değerlendirme ve kıyaslama araçları.
- B1–B10 kıyaslamaları ve SPK-01/02/03/06/07/08 incelemeleri.
- ADR-0001/0002/0004.

**Faz 2'ye başlamadan önce kararınız gereken konular:**

1. **Faz 1'in onayı**, Bölüm A'daki üç sapma dahil:
   - Masaüstü kabuğunun Faz 1'e alınması;
   - iş kuyruğu, olay veriyolu, bağımlılık kabı ve `cache.db`'nin Faz 3'e ertelenmesi;
   - `just` yerine `make` kullanılması.
2. **Model indirme izni:** Kıyaslama seti yaklaşık **30–40 GB**. Faz 0'da 121 GiB boş alan vardı; Faz 2 başında yeniden denetlenecek. Kıyaslamalar prize takılıyken yapılmalı.
3. **Git:** Faz 1 değişiklikleri commit edilsin mi? Şu an hiçbir şey commit edilmedi ve hiçbir şey gönderilmedi.
4. *(Bilgi için, Faz 5'te sorulacak)* "Efendim" hitabı doğal olarak "siz" ile uyumlu. Varsayılan "siz" olarak önerildi; Faz 5'te sizinle netleştirilecek.

**Faz 2 için bilinen riskler:**

- Türkçe model kalitesi ile bellek bütçesi arasındaki denge (R1, R2).
- Ses yığınıyla birlikte bellek paylaşımı (SPK-07).
- Şifreli vektör önbelleği için ayrılacak bellek (ADR-0003, ~40–160 MB). Model seçiminde hesaba katılmalı.

**Tavsiye:** Faz 1'i onaylamanızı ve Faz 2 için model indirme iznini ayrıca vermenizi öneririm. **Faz 2'ye başlamadım; açık onayınızı bekliyorum.**
