# LAZIS — Faz 1.1 Raporu: Güvenlik, Veri Bütünlüğü ve Güvenilirlik Sağlamlaştırması

> Tarih: 2026-10-17 · Durum: **Faz 1.1 tamamlandı; onayınızı bekliyor.** Faz 2'ye başlanmadı, model indirilmedi.
> Kapsam: Dış inceleme bulgularının kodla tek tek doğrulanması, doğrulanan zayıflıkların en küçük güvenilir düzeltmeyle giderilmesi, gerileme testleri ve belgelerin gerçek durumla eşitlenmesi.
> Tarihsel Faz 1 raporu yerinde duruyor: [PHASE_1_REPORT.md](PHASE_1_REPORT.md). Yalnızca başına bu rapora işaret eden bir not eklendi.

---

## A. Yönetici Özeti

**Genel durum:** Faz 1 temeli artık sağlam ve doğrulanmış bir başlangıç noktası. Bu turda yapılanlar:

- **İki önemli zayıflık giderildi:**
  - ağ kısıtlamasının yerel kodla atlanabilmesi;
  - geri yükleme sırasında son geçerli verinin kaybolabilmesi.
- **Bir gizli açık kapatıldı:** WebSocket bağlantıları API korumasını atlıyordu.
- **Belgeler düzeltildi:** Faz 1 belgelerindeki iki abartılı güvenlik iddiası gerçek durumla eşitlendi.

Bulgular kod incelemesi ve deneylerle doğrulandı; belgelere güvenilmedi.

**Öne çıkanlar:**

1. **Ağ yalıtımı artık işletim sistemi düzeyinde.**
   - *Faz 1'deki durum:* Python denetim kancası yalnızca Python'un `socket` modülünü görüyordu. Bu korumayı `ctypes` ile yapılan yerel bir `connect()` çağrısının ve bir `curl` alt sürecinin aştığını deneyle gösterdim.
   - *Düzeltme:* Arka uç artık macOS çekirdeğinin uyguladığı bir sandbox profiliyle çalışıyor. Başka bir makineye giden her bağlantı ve her DNS sorgusu, yerel kod ve alt süreçler dahil, çekirdek tarafından reddediliyor.
   - *Hata durumu:* Sandbox uygulanamazsa arka uç **başlamıyor** (fail closed).
2. **Geri yükleme artık veri kaybettirmiyor.**
   - *Faz 1'deki durum:* Eski kod, değiştirme adımından **önce** WAL dosyasını siliyordu. Değiştirme başarısız olursa son işlemler kayboluyordu.
   - *Yeni tasarım:* Kilit, doğrulama, hazırlama, eski dosyaları kenara taşıma, tek bir commit noktası ve açılışta otomatik kurtarma.
   - *Kanıt:* 36 hata enjeksiyonu testi. Her adımda gerçek süreç çökmeleri de dahil, orijinal veritabanı bayt bayt korunuyor.
3. **Bu Mac'te FileVault kapalı.** Güvenlik modeli FileVault'un açık olduğunu varsayıyordu ve Faz 1 bunu hiç göstermiyordu. Artık gizlilik kartında uyarı olarak görünüyor. Açıp açmamak sizin kararınız.
4. **Testler:** 197 otomatik testin hepsi geçti: arka uç 146, arayüz 21 + 3, Rust 19 + 7, isteğe bağlı Anahtar Zinciri testi 1. Atlanan test yok. Statik denetimler, sürüm derlemesi ve gerçek uygulama doğrulaması da tamam.
5. **Git:** Değişiklikler yerel bir commit olarak kaydedildi (Bölüm M). GitHub'a gönderilmedi.

**Faz 2 hazırlığı: SINIRLAMALARLA HAZIR** (gerekçe: Bölüm N).

---

## B. Bulgular

Sınıflar: **DZ** doğrulanmış zafiyet · **GZ** güvenilirlik zayıflığı · **BT** belge tutarsızlığı · **DS** derinlemesine savunma iyileştirmesi · **YA** yanlış alarm (sorun yok).

| # | Bulgu | Sınıf | Önem | Durum |
|---|---|---|---|---|
| 1 | Ağ koruması (denetim kancası) yerel kodla (`ctypes`/C eklentisi/Rust tabanlı HTTP istemcisi) ve alt süreçlerle atlanabiliyordu; deneyle gösterildi | DZ | **Orta** (şu an böyle bir bağımlılık yok; P12'de `ddgs` tam olarak böyle bir kütüphane) | Düzeltildi: OS sandbox + fail closed (ADR-0009) |
| 2 | Faz 1 raporu ve güvenlik modeli "internet erişimi süreç düzeyinde engelli" diyordu; gerçekte uygulama düzeyindeydi | BT | Orta | Düzeltildi: 4 katman ayrı ayrı belgelendi |
| 3 | Geri yükleme, değiştirmeden önce hedefin `-wal`/`-shm` dosyalarını siliyordu; başarısız bir değiştirmede son işlemler kaybolur | GZ | **Yüksek** (Faz 1'de kullanıcıya açık bir geri yükleme yolu yoktu) | Düzeltildi |
| 4 | Geri yükleme eski veritabanını saklamıyor, `fsync` yapmıyor, kesintiden kurtarma yolu sunmuyor, açık veritabanını denetlemiyordu | GZ | Yüksek | Düzeltildi |
| 5 | Geri yüklemede manifest isteğe bağlıydı, `cipher_integrity_check` ve şema sürümü denetimi yoktu (yeni şemalı yedek uygulamayı açılamaz hale getirirdi) | GZ | Orta | Düzeltildi |
| 6 | Yedek oluşturma başarısız olursa yarım dosya kalıyordu; manifest atomik yazılmıyordu; etiket doğrulanmıyordu | GZ | Düşük | Düzeltildi |
| 7 | `LocalApiGuard`, WebSocket bağlantılarını Host/Origin/belirteç denetimi olmadan uygulamaya geçiriyordu | DZ (gizli) | Orta (Faz 1'de rota yok; P3'te Yüksek olurdu) | Düzeltildi: WebSocket bağlantıları P3'e kadar reddediliyor |
| 8 | Arka uç her açılışta `uname -p` alt sürecini çalıştırıyordu (`platform.platform()`) | DS | Düşük | Düzeltildi: alt süreç yok; süreç başlatma artık engelli |
| 9 | Soket adreslerinde "localhost" gibi adlar kabul ediliyordu; `connect()` adı ayrı bir denetim olayı olmadan çözümlediği için denetlenemiyordu | DS | Düşük | Düzeltildi: yalnızca loopback IP literal |
| 10 | Gerçek uygulamada kabuk, arka uca 2 dosya tanımlayıcısı sızdırıyordu (Apple grafik çatısının açtığı salt okunur Metal dosyaları) | DS | Düşük (bu ikisi zararsız; sınıfı riskli) | Düzeltildi: arka uç başlangıçta devralınan tanımlayıcıları kapatıyor |
| 11 | SEC-01 ve güvenlik modeli "FileVault denetlenir" diyordu; denetim yoktu. Bu Mac'te FileVault **kapalı** | BT + ortam bulgusu | Orta | Görünürlük eklendi; açma kararı sizde |
| 12 | Kurtarma kodu penceresinde pano riskine dair uyarı yoktu | DS | Düşük | Düzeltildi |
| 13 | Rust, geri yükleme formundan gelen kodun kopyasını sıfırlamıyordu | DS | Düşük | Düzeltildi (`Zeroizing`) |
| 14 | Yanlış veya bozuk kurtarma kodunun veritabanına dokunmadığı test edilmemişti | DS (kapsam) | Düşük | Test eklendi; sorun çıkmadı |
| 15 | SEC-05 "satır sayısı + sağlama ile özdeş" kriterinin testi yalnızca tek değer karşılaştırıyordu | DS (kapsam) | Düşük | Test eklendi; geçti |
| 16 | Dinleme adresi işletim sistemi düzeyinde kısıtlanamıyor (Seatbelt'te yerel "localhost" her yerel adres demek) | Kalan risk | Düşük | Belgelendi; uygulama düzeyinde zorunlu |
| 17 | Kurtarma kodu üretimi, kodlama, günlük, argv, ortam, yapılandırma, ön uç durumu | YA | — | Doğrulandı, sorun yok |
| 18 | Belirteç, Host, Origin, CORS, gövde ve hız sınırları; port çakışması; çift örnek | YA | — | Doğrulandı, sorun yok |
| 19 | `cargo audit` uyarıları (`glib`, `proc-macro-error`) | YA | — | Yalnızca Linux'ta derlenen bağımlılıklar; macOS derlemesinde yoklar |

---

## C. Ağ Yalıtımı

**Gerçek garantiler: dört ayrı katman.** Faz 1 belgeleri bunları tek bir "süreç düzeyi" iddiasında birleştiriyordu.

| Katman | Kim uyguluyor | Ne sağlıyor | Ne sağlamıyor |
|---|---|---|---|
| 1. Uygulama koruması (PEP 578 denetim kancası) | Python yorumlayıcısı | Loopback dışı IP'ye `connect`/`connect_ex`/`sendto`/`sendmsg`/`bind`; loopback dışı DNS; adlarla soket adresi; **her türlü süreç başlatma** (`subprocess`, `os.system`, `exec`, `posix_spawn`, `spawn`, `fork`) reddediliyor | Yerel kod, devralınmış bağlı soketler |
| 2. **İşletim sistemi ağ sandbox'ı** (yeni) | macOS çekirdeği | Arka uçtan ve başlattığı her süreçten başka bir makineye giden bağlantı ve paketler; DNS çözümlemesi | Dinleme adresi (Seatbelt kısıtı); kabuk ve WebKit süreçleri (ağ kodları yok, CSP ile sınırlı) |
| 3. Yalnızca loopback sunucu | Doğrulanan yapılandırma + katman 1 | API soketi 127.0.0.1'de, OS'nin seçtiği portta | Yerel bir bileşenin kendi dinleyicisini açması |
| 4. Kimlik doğrulama | `LocalApiGuard` | API'yi kimin kullanabileceği | — |

**Doğrudan yanıtlar:**

1. *Ne engelleniyor?* Bölüm B ve yukarıdaki tablo.
2. *Hangi Python API'leri kapsanıyor?* `socket` modülünün tamamı: `connect`, `connect_ex`, `sendto`, `sendmsg`, `bind`, `getaddrinfo`, `gethostbyname(_ex)`, `gethostbyaddr`, `getnameinfo`. Bunların üstüne kurulu her şey de kapsanıyor (`urllib`, `http.client`, `asyncio`, `httpx`).
3. *Alt süreçler atlatabilir mi?* Katman 1 artık alt süreç başlatmayı reddediyor. Katman 2 alt süreçlere de miras kalıyor; `curl` ve Python alt süreçleriyle test edildi.
4. *Yerel eklentiler atlatabilir mi?* Katman 1'i atlatabilir; katman 2'yi atlatamaz. `ctypes` ile `libc.connect()` çekirdekte EPERM aldı.
5. *Devralınan tanımlayıcılar?* Gerçek risk; gerçek uygulamada 2 sızıntı bulundu. Artık başlangıçta kapatılıyor ve test ediliyor.
6. *IPv4 ve IPv6?* İkisi de kapsanıyor. IPv4-mapped (`::ffff:127.0.0.1`) ve kapsam kimlikli (`::1%lo0`) adresler testli; `2001:db8::1` reddediliyor.
7. *DNS?* Katman 1 Python çözümlemesini, katman 2 çözümleyici artalan sürecine giden yolu reddediyor.
8. *Loopback dışında dinleyebilir mi?* Uygulama düzeyinde hayır (yapılandırma doğrulaması, açık bind ve kanca). İşletim sistemi düzeyinde kısıtlanamıyor (kalan risk 16).
9. *Gelecekteki kütüphaneler?* Yerel ağ kodu içeren bir kütüphane katman 1'i atlatır, katman 2'yi atlatamaz. P12'de internet araştırması ayrı bir yardımcı süreçte, kendi daha dar profiliyle çalışmalı (ADR-0009).
10. *Belgeler abartıyor muydu?* Evet (bulgu 2). Güvenlik modeli §5.3'te düzeltildi.

**Hata durumu:**

- `sandbox-exec` yoksa kabuk arka ucu başlatmıyor.
- Arka uç sandbox'ı kendisi de doğruluyor (`--require-os-sandbox`). Yöntem: yerel DNS artalan sürecinin Unix soketine bağlanmayı deniyor; bu deneme makineden dışarı hiçbir şey göndermiyor. EPERM alırsa sandbox etkin demektir; yoksa `network_sandbox_unavailable` ile durur.
- Durum sistem durumunda ve arayüzde görünüyor.

**Testler.** Hiçbiri başka bir makineye bağlanmıyor; hedefler TEST-NET-1 (`192.0.2.1`), `2001:db8::/32` ve `.invalid` alan adı.

- `test_os_sandbox.py` (5 test):
  - yerel `libc`, Python soketi, UDP, alt süreç ve DNS denemelerinin çekirdekçe reddedilmesi;
  - loopback'in çalışması;
  - gerçek arka ucun sandbox altında çalışıp durumu `enforced` bildirmesi;
  - sandbox olmadan başlatmayı reddetmesi.
- `test_network_guard.py`: 23 farklı girişim ve devralınan tanımlayıcının kapatılması.
- Rust yaşam döngüsü testi: gerçek başlatma yolunda `enforced` doğrulandı.
- Gerçek sürüm uygulaması:
  - günlükte `os_network_sandbox: enforced` ve `inherited_descriptors_closed: 2` kaydı;
  - arayüzde "İşletim sistemi ağ kısıtı: Etkin".

**Not:** İlk keşif denemesi, sandbox'sız karşılaştırma yapmak için bir kez 1.1.1.1 ve example.com'a gerçek bağlantı açtı. Bu bir keşifti; kalıcı testlerin hiçbiri dışarı bağlanmıyor.

---

## D. Veritabanı Yedekleme ve Geri Yükleme

**Eski uygulamanın sorunları (bulgu 3–6):**

- `restore_snapshot`, yan dosyaları silip `os.replace` yapıyordu.
- Tek dosyalık atomik bir yeniden adlandırma, ana dosya + WAL + SHM'den oluşan bir SQLite durumunu atomik yapmaz.
- Hiçbir adımda geri alma yolu yoktu.

Bir test, son işlemin yalnızca WAL'da bulunduğunu ve ana dosya tek başına açıldığında görünmediğini kanıtlıyor.

**Yeni protokol** (`core/src/lazis/storage/backup.py`, ADR-0003 Ek 1):

1. **Kilit.** Veri klasörü kilidi artık veritabanı açık olduğu sürece tutuluyor. Arka uç çalışırken geri yükleme `instance_already_running` ile reddediliyor; aynı süreç içinde de geçerli.
2. **Kesintiden kurtarma.** Önceki yarım kalmış bir geri yükleme varsa önce o tamamlanıyor ya da geri alınıyor.
3. **Doğrulama:**
   - manifest zorunlu ve SHA-256 tutmalı;
   - yedek anahtarla açılmalı;
   - `quick_check` ve `cipher_integrity_check` geçmeli;
   - LAZIS şeması bulunmalı ve uygulamadan yeni olmamalı.
4. **Hazırlama.** Aynı dosya sistemi içinde `.restore/staged.db` oluşturuluyor (0600, `F_FULLFSYNC`) ve yeniden doğrulanıyor.
5. **Kenara taşıma.** Mevcut `lazis.db` ve `-wal`/`-shm`/`-journal` dosyaları siliniyor değil, `.restore/previous/` içine taşınıyor.
6. **Kurulum ve doğrulama.** Hazırlanan kopya yerine konup bir kez daha doğrulanıyor.
7. **Commit noktası.** `previous` klasörü `backups/pre-restore-<zaman>/` adına atomik olarak taşınıyor; son 3 kopya tutuluyor. *(Sonradan düzeltildi: commit noktası artık işlem günlüğünün `committed` durumuna atomik olarak yazılması; bkz. Bölüm O.)*
8. **Temizlik.**

7. adımdan önceki her hata hemen geri alınıyor. Çökme olursa bir sonraki açılış (`open_storage`) geri alıyor; durum hangi dosyaların bulunduğundan çıkarıldığı için kurtarma deterministik ve tekrarlanabilir. Kurtarma denetim kaydına yazılıyor (`backup/restore_recovered`).

**Hata enjeksiyonu sonuçları** (`test_restore_safety.py`, 36 test, hepsi geçti, yalnızca sentetik veri):

| Senaryo | Sonuç |
|---|---|
| Başarılı geri yükleme | Yeni veri geldi; eski veritabanı WAL'ıyla birlikte `pre-restore-*` içinde saklandı ve açıldığında en yeni değeri verdi; izinler 0700/0600 |
| Boş klasöre geri yükleme | Çalıştı |
| Geçersiz yedekler (rastgele bayt, manifest korunmuş bit hatası, manifesti yeniden yazılmış bit hatası, eksik manifest, kesik dosya, şifresiz SQLite, LAZIS dışı veritabanı, yeni şema) | 8'i de reddedildi; orijinal bayt bayt aynı |
| Yanlış anahtar | Reddedildi; orijinal aynı |
| Hata enjeksiyonu: hazırlama (ENOSPC), hazırlama sonrası, her dosya taşınırken (EACCES/EIO), kurulum sonrası, doğrulama sonrası | 7 noktanın hepsinde geri alındı; orijinal bayt bayt aynı |
| Gerçek çökme (`os._exit`) aynı 7 noktada | Bir sonraki açılışta geri alındı; orijinal aynı; kurtarma ikinci kez çalıştırıldığında yapacak iş kalmıyor |
| Commit sonrası çökme | Geri yüklenen veri korundu; temizlik tamamlandı |
| Veri klasörü gerçekten salt okunur oldu | Orijinal korundu; geri alma eksik kaldığı açıkça bildirildi; sonraki açılış temizledi |
| Veritabanı açıkken geri yükleme | Reddedildi |
| SEC-05: yedek → geri yükleme | Her tabloda (geçmiş ve denetim kaydı dahil) satır sayısı ve sağlama aynı |
| Kalıntı Faz 1 geçici dosyası, başarısız yedek | Temizleniyor; yarım dosya kalmıyor |

**Sınırlar:**

- Gerçek bir elektrik kesintisi test edilmedi.
- Garanti, veri klasörünün tek bir yerel APFS biriminde olmasını varsayıyor; bu birimde yeniden adlandırma atomiktir.
- Geri yükleme için arayüz henüz yok; işlev kütüphane düzeyinde. Arayüzü P6'da gelecek.
- Disk dolu durumu gerçek bir doluluk yaratılarak değil, enjekte edilen ENOSPC hatasıyla test edildi.

---

## E. Kurtarma Kodu

**Doğrulananlar** (sorun bulunmadı, bulgu 17):

- Kod, `SecRandomCopyBytes` ile üretilen anahtardan türetiliyor; hiçbir yerde saklanmıyor ve yalnızca kurtarma bekliyorken üretiliyor.
- Python ve Rust kodlayıcıları ortak test vektörleriyle bire bir uyumlu; 32 bitlik sağlama yazım hatalarını yakalıyor.
- Kod günlüklerde (süzgeç + test), argv'de ve ortam değişkenlerinde (çekirdekten okuyan test) görünmüyor.
- Yapılandırmada ve `desktop-state.json` dosyasında yok; o dosyada yalnızca bir zaman damgası var.
- Arayüzde yalnızca pencerenin yerel durumunda tutuluyor; Pinia'ya hiç girmiyor (yeni test). Onaylanınca siliniyor.
- Gizli bir kurtarma yolu, ana anahtar veya yükleme yok.

**Düzeltmeler:**

- *Pano uyarısı (bulgu 12):* Kopyala düğmesi bilerek yok. Pencere artık şunu söylüyor: Kodu kopyalarsanız, pano geçmişi uygulamaları ve Evrensel Pano kodu başka yerlere taşıyabilir; parola yöneticisine yapıştırdıktan sonra panoya başka bir şey kopyalayın.
- *Rust tamponu (bulgu 13):* Formdan gelen kodun Rust'taki kopyası `Zeroizing` ile sıfırlanıyor. WebKit ve IPC katmanının kendi kopyaları denetimimiz dışında; bu kalan risk olarak belgelendi.

Kullanıcı deneyimi değişmedi: Kod ilk kurulumda açıkça gösteriliyor. Pencere, anahtar ve kod birlikte kaybolursa verinin kurtarılamayacağını söylüyor.

**Testler:**

- Geçerli kod, büyük-küçük harf ve boşluk karışık yazılmış kod: kurtarma başarılı.
- Biçimi bozuk kod: `recovery_code_invalid`.
- Tek karakteri değiştirilmiş kod: sağlama yakalıyor.
- Başka veritabanının kodu: `recovery_code_wrong_database`.
- Eksik Anahtar Zinciri kaydı: `needs_recovery`, yeni anahtar üretilmiyor.
- Başarılı kurtarma: anahtar yeniden kaydediliyor.
- Başarısız her denemeden sonra veritabanı dosyaları bayt bayt aynı (yeni Rust testi).
- Anahtar Zinciri'nde yanlış anahtar varken de veritabanı aynı kalıyor.

---

## F. Yerel API

**Doğrulananlar:**

- Yalnızca loopback'e bağlanılıyor (`lsof` testi; LAN IP'sine bağlanma reddediliyor).
- Her açılışta yeni üretilen 256 bitlik belirteç sabit zamanlı karşılaştırılıyor.
- Host denetimi DNS yeniden bağlama saldırısını, Origin izin listesi tarayıcı kaynaklı istekleri engelliyor.
- CORS ön uçuş istekleri veri döndürmüyor.
- Gövde sınırı (64 KB), hız sınırı ve eşzamanlılık sınırı çalışıyor.
- Hatalarda yığın izi dönmüyor; reddedilen istekler denetim kaydına yazılıyor.
- Belirteç yalnızca süreç ömrü boyunca geçerli; yeniden başlatmadan sonra eski belirteç reddediliyor (test var).

**Düzeltme:** WebSocket bağlantıları artık reddediliyor (bulgu 7; 1008 kodu; belirteçli ve belirteçsiz test edildi). P3'teki WebSocket uç noktası, ilk mesajda belirteç ve Origin denetimiyle birlikte tasarlanacak.

**Aynı kullanıcıyla çalışan süreçlere karşı gerçekçi sınırlar:**

- API, kişiyi değil *masaüstü uygulamasını* doğruluyor.
- Aynı macOS kullanıcısıyla çalışan bir süreç belirteci argv'den, ortamdan, günlüklerden, diskten veya API'den öğrenemez; belirteçsiz 401 alır ve hız sınırına takılır.
- Ama böyle bir süreç portu doldurarak arayüzü kilitleyebilir.
- Ek yetkilerle uygulamanın üzerinden iş yapabilir ya da veriyi okuyabilir. Bu yetkiler:
  - süreçlerimize hata ayıklayıcı erişimi (ad-hoc derlemelerde güçlendirilmiş çalışma zamanı yok);
  - pencereyi yönetmek için Erişilebilirlik izni ya da okumak için Ekran Kaydı izni;
  - kabul edilmiş bir Anahtar Zinciri izni.

Bu, kabul edilmiş "kullanıcı olarak çalışan kötü amaçlı yazılım" riski. Güçlendirilmiş çalışma zamanı ve Developer ID imzası (P15) hata ayıklayıcı yolunu daraltır; kullanıcı alanında tamamen kapatılamaz.

---

## G. Uygulama Yaşam Döngüsü

**Gözden geçirilenler ve sonuçları:**

| Konu | Sonuç |
|---|---|
| Başlatma ve hazır olma denetimi | El sıkışmasında protokol, API sürümü ve port doğrulanıyor; zaman aşımı 30 sn |
| Kapanış | Önce lifeline (stdin) kapatılıyor, ardından SIGTERM, sonra SIGKILL; süreç her durumda toplanıyor |
| Beklenmedik çıkış | Algılanıyor (`backend_exited`) ve "Yeniden dene" sunuluyor; otomatik yeniden başlatma P4'te |
| Çift örnek ve port çakışması | Tek örnek eklentisi, veri klasörü kilidi ve OS'nin seçtiği port; port bilgisi diske yazılmıyor |
| Eskimiş dosyalar | Kilit `flock` olduğu için eskimez; yarım kalmış geri yükleme açılışta kurtarılıyor; durum dosyasının geçici kopyası bir sonraki kayıtta üzerine yazılıyor |
| Anahtar Zinciri ve veritabanı başlatma hataları | Kodla ve Türkçe iletiyle görünür; sessiz hata yok |

**Yeni durumlar:**

- `network_sandbox_unavailable` ve `restore_failed` kodları Türkçe iletileriyle eklendi. Arayüzdeki çeviri testi, arka ucun her hata kodunun bir Türkçe karşılığı olduğunu denetliyor.
- Kabuk, FileVault durumunu `fdesetup isactive` ile okuyor ve gizlilik kartında gösteriyor.

**Gerçek uygulama ölçümleri (sürüm derlemesi):**

| Ölçüm | Sonuç |
|---|---|
| Arka uç hazır olma süresi | 340 ms (sandbox ile; Faz 1'de 230–335 ms) |
| Kapanış | Düzgün kapanma, 156 ms |
| Süreç kalıntısı | Yok |
| Ağ | Arka uç yalnızca `127.0.0.1:<port>` dinliyor |

---

## H. Dosya İzinleri ve Gizli Bilgiler

| Dosya | İzin | Kanıt |
|---|---|---|
| Veri, yedek ve günlük klasörleri | 0700 | Testler + çalışan uygulama |
| `lazis.db`, `-wal`, `-shm` | 0600 | Testler |
| Yedek dosyası ve manifest | 0600 (umask 022 olsa bile) | Yeni test |
| Kilit dosyası | 0600 (`fchmod`; umask 022 olsa bile) | Yeni test |
| `.restore/` hazırlama dosyaları | 0600/0700 (`O_EXCL`, 0600 ile oluşturuluyor) | Kod + test |
| `pre-restore-*` kopyaları | 0700/0600 | Yeni test |
| `core.log`, `desktop.log`, `desktop-state.json` | 0600 | Faz 1 testleri + umask 077 |
| Port veya soket meta verisi | Diske yazılmıyor | — |

**Gizli bilgiler şu yerlerde yok:**

- günlükler;
- hata iletileri (API genel ileti dönüyor);
- argv ve ortam (çekirdekten okuyan test);
- stdout ve stderr;
- ön uç durumu ve konsolu (konsola hiçbir şey yazılmıyor);
- test çıktıları (yalnızca sentetik anahtarlar; geri yükleme çökme testleri anahtarı stdin'den veriyor).

Çökme raporları yalnızca argv içerebilir; argv'de gizli bilgi yok.

**Secret taraması:**

- Bütün depoda ve commit edilecek dosyalarda yapıldı. Eşleşenlerin hepsi sentetik değerler: yer tutucu `LZR1-XXXXX`, `LZR1-TEST0-CODE0`, `"a".repeat(64)` ve deterministik test vektörleri.
- Veritabanı, anahtar, günlük veya `.env` dosyası izlenmiyor.

---

## I. Bağımlılıklar

**Taramalar:** Bağımlılık sürümleri değişmedi; kilit dosyaları aynı. Bağımlılık eklenmedi, Docker ve bulut bağımlılığı yok.

| Denetim | Sonuç |
|---|---|
| `pip-audit` (yerel paket hariç) | Bilinen açık yok |
| `pnpm audit` | Bilinen açık yok |
| `cargo audit` | Açık yok; 2 uyarı yalnızca Linux'ta derlenen bağımlılıklarda (bulgu 19) |

**Paket ve yetkiler:**

- SQLCipher 4.19.0, resmî `sqlcipher3` 0.6.4 paketiyle geliyor.
- Tauri yetkileri değişmedi: yalnızca 5 uygulama komutu ve olay dinleme.
- macOS yetkileri (entitlements) yok; uygulama paketi gizlilik izni (mikrofon gibi) istemiyor.
- Yeni sistem bağımlılıkları yalnızca macOS'un kendi araçları: `/usr/bin/sandbox-exec` ve `/usr/bin/fdesetup`.

**Uyumluluk notları:**

- `sandbox-exec` Apple tarafından kullanımdan kaldırılmış olarak işaretli, ama macOS 27'de çalışıyor ve testlerle her seferinde doğrulanıyor. Kaldırılırsa uygulama güvensiz çalışmak yerine başlamıyor (R31).
- Starlette'in test istemcisi bir kullanımdan kaldırma uyarısı veriyor; yalnızca testleri etkiliyor ve sürüm değiştirilmedi.

---

## J. Testler

**Ortam:**

- Donanım ve sistem: MacBook Pro M4 Pro, 24 GB, macOS 27.0.1 (FileVault kapalı).
- Araç sürümleri:
  - Python 3.13.16 (uv 0.13.1);
  - Node 24.10 ve pnpm 10.28.2;
  - Rust 1.99.1.

**Komutlar ve sonuçlar** (`make check`, çıkış kodu 0):

| Takım | Komut | Toplam | Geçti | Kaldı | Atlandı |
|---|---|---|---|---|---|
| Arka uç: birim, bütünleşik, güvenlik | `make test-core` | 146 | 146 | 0 | 0 |
| Arayüz birim | `make test-ui` | 21 | 21 | 0 | 0 |
| Arayüz bütünleşik (gerçek arka uç) | `make test-ui-integration` | 3 | 3 | 0 | 0 |
| Rust birim | `make test-shell` | 19 (+1 isteğe bağlı) | 19 | 0 | 1 (`#[ignore]`, aşağıda ayrıca çalıştırıldı) |
| Rust yaşam döngüsü (gerçek arka uç, gerçek sandbox) | `make test-shell` | 7 | 7 | 0 | 0 |
| Gerçek Anahtar Zinciri | `make test-keychain` | 1 | 1 | 0 | 0 |
| **Toplam** | | **197** | **197** | **0** | **0** |

Faz 1'e göre 49 yeni test eklendi:

- arka uç +46;
- arayüz +2;
- Rust +1.

**Statik denetimler ve doğrulamalar:**

- ruff ve ruff format temiz; pyright strict 0 hata; import-linter 2/2.
- vue-tsc, rustfmt ve clippy `-D warnings` temiz.
- Sürüm derlemesi `LAZIS.app` 7,68 MB, başarılı.
- Gerçek uygulamada doğrulananlar: sandbox `enforced`, FileVault "Kapalı" uyarısı, düzgün kapanış.
- Gerçek uygulama doğrulaması `p11verify` adlı tek kullanımlık profille yapıldı. Ardından profilin klasörleri, Anahtar Zinciri kaydı ve paylaşılan WebKit önbellekleri silindi. Sizin `default` profilinize ve onun Anahtar Zinciri kaydına dokunulmadı.

**Sınırlar:**

- Gerçek elektrik kesintisi ve gerçek disk doluluğu test edilmedi; disk doluluğu enjekte edilen ENOSPC hatasıyla test edildi.
- Playwright uçtan uca testleri P4'te.
- Tam uygulama penceresi elle ve ekran görüntüsüyle doğrulandı.

### J.2 Faz 1 kabul kriterleri

| Kriter | Sonuç | Kanıt |
|---|---|---|
| SEC-01 Yerel veri, 0700/0600, FileVault denetimi | **Geçti** (denetim var; FileVault'un kendisi bu Mac'te kapalı → uyarı) | İzin testleri, gizlilik kartı |
| SEC-02 / SEC-12 Varsayılan şifreleme, düz metne düşmeme, anahtar yalnızca stdin, argv/ortam/günlükte yok | **Geçti** (`documents.db` ve `cache.db` henüz yok) | 6 yollu şifreleme testleri, çekirdek düzeyi argv ve ortam testi |
| SEC-05 Şifreli, döndürmeli yedek; özdeş geri yükleme | **Geçti** | `test_restore_safety.py` (36 test, SEC-05 testi dahil) |
| SEC-06 Belirteç ve Origin reddi; başka makineden erişilemez | **Geçti** | API güvenlik testleri, `lsof` ve LAN testleri |
| SEC-07 (iskelet) Çıkış trafiği tamamen kapalı | **Geçti** (P1 kapsamı: uygulama + OS katmanı). Politika ağ geçidi P12'de | `test_network_guard.py`, `test_os_sandbox.py` |
| SEC-10 Günlüklerde içerik ve gizli bilgi yok | **Geçti** (içerik günlüğü özelliği henüz yok) | Süzgeç testleri, gerçek gizli bilgi taramaları |
| SEC-13 (P1 kısmı) Kurtarma kodu ve yeni Anahtar Zinciri ile geri yükleme | **Geçti**; anahtar döndürme **test edilmedi** (P15) | Rust yaşam döngüsü, Python kurtarma testleri |
| SEC-14 (altyapı) Denetim kaydı | **Kısmen doğrulandı**: P1 olayları yazılıyor (başlama, durma, reddedilen istek, yedek, kurtarma). "İçerik yok" garantisi tasarımla sağlanıyor ama satırları tarayan özel bir test yok | Denetim testleri |
| ENG-01 Modül sınırları zorunlu | **Geçti** | import-linter |
| ENG-02 Sıkı tipleme | **Geçti** | pyright strict, TS strict, clippy |
| ENG-03 Sürümlü göçler | **Geçti** (tek sürüm var: sıfırdan ve sağlama testli) | Göç testleri |
| ENG-04 Katmanlı, doğrulanan yapılandırma | **Kısmen**: yapılandırma tamam; politika dosyaları henüz yok | Yapılandırma testleri |
| ENG-05 / ENG-06 Testler çalıştırıldı, dürüst rapor | **Geçti** | Bu bölüm |
| ENG-07 Varsayımlar belgelendi | **Geçti** | ADR-0003, ADR-0009 |
| ENG-08 Mühendislik standartları | **Kısmen**: ESLint kurulu değil (TS'de vue-tsc ve sıkı mod var) | — |
| ENG-09 Tekrarlanabilir ortam, lisans politikası | **Kısmen**: kilit dosyaları ve Python/pnpm sürümleri sabit; Rust araç zinciri dosyası (`rust-toolchain.toml`) ve otomatik lisans denetimi yok | — |
| BST-06 Kaynakta ve fixture'larda kişisel veri yok | **Geçti** | Secret ve veri taraması |

---

## K. Değişiklikler

**Yeni dosyalar:**

| Dosya | Neden |
|---|---|
| `apps/desktop/src-tauri/sandbox/backend.sb` | OS ağ sandbox profili (Rust ve Python testleri ortak kullanıyor) |
| `apps/desktop/src-tauri/src/system.rs` | FileVault denetimi |
| `core/src/lazis/storage/lock.py` | Veri klasörü kilidi `storage` katmanına taşındı (geri yükleme de kullanıyor) |
| `core/tests/integration/test_restore_safety.py` | 36 hata enjeksiyonu ve SEC-05 testi |
| `core/tests/security/test_os_sandbox.py` | OS sandbox testleri |
| `core/tests/unit/test_data_dir_lock.py` | Kilit davranışı ve izinler |
| `docs/adr/0009-backend-network-sandbox.md` | Sandbox kararı ve kanıtları |
| `docs/PHASE_1_1_REPORT.md` | Bu rapor |

**Değişen kod:**

| Dosya | Değişiklik |
|---|---|
| `core/src/lazis/security/network_guard.py` | IP literal zorunluluğu, IPv4-mapped adresler, süreç başlatma engeli, sandbox yoklaması, devralınan tanımlayıcıların kapatılması |
| `core/src/lazis/storage/backup.py` | Yedekleme sağlamlaştırması ve çökmeye dayanıklı geri yükleme protokolü |
| `core/src/lazis/storage/database.py`, `storage/__init__.py` | Kilit veritabanı açık kaldıkça tutuluyor; açılışta kesinti kurtarması ve denetim kaydı |
| `core/src/lazis/app/server.py`, `app/cli.py` | Başlangıç sırası, `--require-os-sandbox`, eski kilit sınıfı kaldırıldı |
| `core/src/lazis/api/security.py` | WebSocket reddi, sınırların belgelenmesi |
| `core/src/lazis/api/app_factory.py`, `api/schemas.py` | Alt süreçsiz platform etiketi; `os_network_sandbox` alanı |
| `core/src/lazis/errors.py`, `i18n.py` | `restore_failed`, `network_sandbox_unavailable` |
| `apps/desktop/src-tauri/src/backend.rs` | `sandbox-exec` ile başlatma; aracın yokluğunda fail closed |
| `apps/desktop/src-tauri/src/controller.rs`, `lib.rs`, `errors.rs` | FileVault alanı, kodun sıfırlanması, hata iletisi |
| `apps/desktop/ui/src/…` | Gizlilik kartında sandbox ve FileVault satırları, pano uyarısı, Türkçe metinler, yeniden üretilen API tipleri |

**Değişen testler:**

- `core/tests/security/test_network_guard.py`, `test_api_security.py`;
- `core/tests/integration/test_api_endpoints.py`, `core/tests/process_helpers.py`;
- `apps/desktop/src-tauri/tests/lifecycle.rs`;
- `apps/desktop/ui/tests/unit/app.spec.ts`, `fixtures.ts`.

**Belgeler:**

- Güncellenenler: `SECURITY_MODEL.md` (§5.1, §5.2, §5.3, §5.7, §5.11, yeni §5.12), `ARCHITECTURE.md`, `DEVELOPER_GUIDE.md`, `TESTING_STRATEGY.md` (yeni §11), `RISK_ASSESSMENT.md` (R31, R32), `DEVELOPMENT_ROADMAP.md`, `README.md`, ADR-0003 (Ek 1).
- `PHASE_1_REPORT.md`'ye yalnızca bir başlık notu eklendi.

**Toplam:** 45 dosya (37 değişen, 8 yeni); 2.331 satır eklendi (yeni testler ve bu rapor dahil), 164 satır silindi.

---

## L. Kalan Riskler

| Risk | Önem | Not |
|---|---|---|
| Dinleme adresi işletim sistemi düzeyinde kısıtlanamıyor | Düşük | Uygulama düzeyinde zorunlu: yapılandırma + açık bind + kanca |
| `sandbox-exec` ileride kaldırılabilir (R31) | Düşük–Orta | Uygulama güvensiz çalışmak yerine başlamıyor; uzun vadede App Sandbox (P15) |
| FileVault kapalı (R32) | **Orta** | Veritabanı SQLCipher ile korunuyor, ama günlükler, takas dosyası ve diğer dosyalar diskte şifresiz. **Kararınız gerekiyor** |
| Aynı kullanıcıyla çalışan kötü amaçlı yazılım | Orta (kabul edildi) | Bölüm F; P15'te güçlendirilmiş çalışma zamanı ve imza |
| WebKit ve IPC katmanındaki kurtarma kodu kopyaları | Düşük | Denetimimiz dışında; kod yalnızca istendiğinde ve kısa süre bellekte |
| Gerçek elektrik kesintisi test edilmedi | Düşük | Protokol yeniden adlandırma ve `F_FULLFSYNC` üzerine kurulu; enjekte çökmeler test edildi |
| Ad-hoc imza: her yeniden derlemede Anahtar Zinciri izni | Düşük (geliştirme) | P15'te Developer ID |
| Bağımsız paket değil (arka uç `core/.venv`'den çalışıyor) | Orta (dağıtım) | P15 |
| ESLint, `rust-toolchain.toml` ve lisans denetimi eksik | Düşük | Faz 2 başında eklenebilir |

---

## M. Git Başlangıç Noktası

- **Başlangıç:** Çalışma alanı temizdi; `main` ile `origin/main` aynıydı (`cce73ac faz-1`). Benimle ilgisi olmayan bir değişiklik yoktu.
- **`.gitignore` gözden geçirildi:**
  - veritabanları, anahtarlar, günlükler, `data.noindex/`, `.env`, `.venv`, `node_modules` ve derleme çıktıları dışarıda tutuluyor;
  - `zip/` ve `*.zip` dışarıda tutuluyor;
  - derleme çıktısı kuralları her konumda geçerli.
- **Commit edilen dosyalar** tek tek incelendi; secret taraması temiz (Bölüm H).
- **Commit:**
  - mesaj: `chore: harden LAZIS phase 1 security and reliability`;
  - içerik: bu rapor dahil bütün değişiklikler;
  - hash: aşağıda, bu rapora ikinci küçük bir commit ile eklendi.
- **Push yapılmadı;** uzak depo oluşturulmadı.

Commit hash: **`6d18a4f434163b8d0f765d3763a427f0b333a7ee`** (`6d18a4f`). Bu satır, raporun kendi commit'inde bilinemediği için ayrı bir küçük commit ile eklendi.

---

## N. Faz 2 Hazırlığı

### Karar: **SINIRLAMALARLA HAZIR (READY WITH LIMITATIONS)**

**Neden hazır:**

- Doğrulanan bütün zayıflıklar giderildi ve gerileme testleriyle kilitlendi.
- 197 testin tamamı çalıştı ve geçti; atlanan test yok.
- Şifreleme, anahtar yönetimi, kurtarma, yerel API, yaşam döngüsü ve ağ yalıtımı gerçek uygulamada doğrulandı.
- Faz 2'nin ihtiyaç duyduğu şeyler engellenmiyor:
  - Ollama'ya loopback erişimi (`127.0.0.1:11434`), hem uygulama korumasında hem sandbox profilinde izinli;
  - yapılandırmadaki `models` bölümü;
  - sağlayıcı arayüzleri için gereken altyapı.

**Sınırlamalar (Faz 2'ye engel değil, bilinmesi gereken):**

1. **FileVault kapalı.** Faz 2 kişisel veri işlemiyor; ama Faz 3'te konuşmalar kaydedilmeye başlamadan önce FileVault'u açmanızı öneririm.
2. **SEC-14 ve ENG-04/08/09 kısmen doğrulandı** (Bölüm J.2): denetim içeriği taraması, ESLint, araç zinciri sabitleme ve lisans denetimi.
3. **Model indirmede ağ erişimi.** `sandbox-exec` arka ucu kısıtlıyor. Faz 2'de model indirmek ağ ister; bu iş yol haritasındaki gibi arka uçtan değil, açık bir kurulum betiğiyle ve sizin izninizle yapılmalı.
4. **Bağımsız ve imzalı paket P15'te.**

**Faz 2 için onayınız gereken konular:**

- Faz 1 ve 1.1'in onayı;
- yaklaşık 30–40 GB'lık model indirme izni;
- FileVault kararınız.

**Faz 2'ye başlamadım; açık onayınızı bekliyorum.**

---

## O. Ek: Bağımsız inceleme sonrası düzeltme (geri yükleme commit durumu)

Faz 1.1 kaynak kodunun bağımsız incelemesi, `recover_interrupted_restore()` ve `restore_snapshot()` içinde bir sınır durumunun kontrol edilmesini istedi. Kodu değiştirmeden önce sorunu gerçek süreç çökmeleriyle (`os._exit`) doğruladım.

### O.1 Doğrulanan davranış (düzeltmeden önce)

| Senaryo | Kurtarmanın kararı | Sonuç | Değerlendirme |
|---|---|---|---|
| Boş profil (`lazis.db` yok); `staged.db` yerleştirildikten sonra, commit'ten önce çökme (`installed` ya da `verified` adımı) | `cleaned` | Commit edilmemiş ve son doğrulaması yapılmamış kopya `lazis.db` olarak **kabul edildi** | "Commit öncesi çökme geri alınır" garantisine **aykırı** |
| Ana dosya yok ama sahipsiz `-wal`/`-shm` dosyaları var; kurulumdan sonra çökme | `rolled_back` (yanıltıcı) | Geri yüklenen `lazis.db` kaldı ve eski WAL **yanına geri konuldu** | SQLite yabancı WAL'ı yeni dosyaya uygulayabilir; **bozulma riski** |
| Var olan veritabanı; yalnızca bazı dosyaları taşınmışken çökme | `rolled_back` | Bütün orijinaller bayt bayt geri geldi | Doğru çalışıyordu |

**Kök neden:** Durum dosyaların varlığından çıkarılıyordu ve commit noktası "`previous/` klasörünü `backups/` içine taşımak"tı. Taşınacak dosya olmadığında `previous/` boş kalıyordu. Bu durumda "kurulum yapıldı mı, commit edildi mi?" sorusunun cevabı dosyalardan okunamıyordu.

### O.2 Sorulan sorular ve yanıtları

- **Önceki veritabanı yokken kurtarma ne yapıyordu?** Yerleştirilmiş kopyayı olduğu gibi bırakıyor ve kabul ediyordu.
- **İşlem tamamlanmamışken yeni veritabanı kabul edilebiliyor muydu?** Evet; boş profilde ve sahipsiz WAL durumunda.
- **Bu, atomiklik garantisiyle tutarlı mıydı?** Hayır. Garanti "commit'ten önceki her çökme geri alınır" diyordu.
- **Açık bir commit durumu veya işlem günlüğü gerekli mi?** Evet. Yalnızca dosyalara bakılarak bu durumlar ayırt edilemiyor.
- **Kısmi taşıma sırasındaki çökme doğru kurtarılıyor muydu?** Var olan bir veritabanı için evet. Sahipsiz WAL ile kurulum sonrası çökmede hayır.

### O.3 Düzeltme (mimari korundu, en küçük güvenilir değişiklik)

1. Hiçbir dosya taşınmadan önce kalıcı bir işlem günlüğü yazılıyor: `.restore/journal.json`. Atomik yazılıyor ve `F_FULLFSYNC` ile diske işleniyor. İçeriği:
   - durum: `swapping`;
   - **taşınacak dosyaların tam listesi**;
   - önceki kopyanın adı.
2. **Commit noktası:** Yerleştirilen dosya doğrulandıktan sonra günlüğün atomik olarak `committed` durumuna yeniden yazılması.
3. Kurtarma, dosyalardan tahmin yürütmek yerine günlüğe göre karar veriyor:
   - **`committed`:** işlem tamamlanıyor (`completed`).
   - **Commit yapılmamış:** `lazis.db` konumundaki dosya, taşınacak listede olup henüz taşınmamışsa orijinaldir; aksi halde geri yüklenen kopyadır. Geri yüklenen kopya ve onun yan dosyaları siliniyor; bütün orijinaller geri taşınıyor (`rolled_back`).
   - **Günlük yok ve hiçbir şey taşınmamış:** yalnızca hazırlama kalıntıları temizleniyor (`cleaned`).
   - **Günlük okunamıyorsa:** hedefteki dosya yalnızca orijinal ana dosyanın `previous/` içinde güvende olduğu kanıtlanabiliyorsa siliniyor. Orijinali kaybetme riski hiçbir zaman alınmıyor.

Değişen dosyalar:

- `core/src/lazis/storage/backup.py`;
- `core/tests/integration/test_restore_safety.py`;
- belgeler: ADR-0003 Ek 2, `SECURITY_MODEL.md` §5.1, `ARCHITECTURE.md`, `DEVELOPER_GUIDE.md`, `TESTING_STRATEGY.md`.

### O.4 Regresyon testleri (gerçek süreç çökmesi, `os._exit`)

Yeni testlerin 4'ü düzeltmeden önce kırmızıydı; düzeltmeden sonra hepsi geçiyor. Bu dosyada toplam 52 test var; 16'sı yeni.

| Test | Çökme noktaları | Beklenen ve doğrulanan |
|---|---|---|
| Boş profil, commit öncesi | `staging`, `staged`, `journal`, `installed`, `verified` | Veritabanı yok; sonraki açılış boş bir veritabanı oluşturuyor |
| Boş profil, commit sonrası | `committed` | Geri yüklenen veri korunuyor; temizlik tamamlanıyor |
| Sahipsiz WAL/SHM | `journal`, her iki taşıma, `installed` | Orijinal sahipsiz dosyalar bayt bayt geri geliyor; `lazis.db` yok |
| Var olan veritabanı, kısmi taşıma | `journal`, her dosyanın taşınmasından sonra, `installed` | Bütün orijinal dosyalar bayt bayt aynı; en yeni (yalnızca WAL'da bulunan) değer okunuyor |
| Bozuk günlük | `installed` + bozulmuş `journal.json` | Orijinal korunuyor |

### O.5 `make check` sonucu (çıkış kodu 0)

| Takım | Sonuç |
|---|---|
| Arka uç | **162 geçti** (önceki 146 + 16 yeni) |
| Arayüz birim | 21 geçti |
| Arayüz bütünleşik | 3 geçti |
| Rust birim | 19 geçti (1 isteğe bağlı test ayrıca çalıştırıldı: geçti) |
| Rust yaşam döngüsü | 7 geçti |
| **Toplam** | **213 / 213**; başarısız yok, atlanan yok |

Statik denetimler de temiz: ruff, ruff format, pyright strict, import-linter, vue-tsc, rustfmt ve clippy `-D warnings`.

### O.6 Faz 2 kararı (güncel): **SINIRLAMALARLA HAZIR (READY WITH LIMITATIONS)**

Bu sınır durumu bir veri bütünlüğü açığıydı ve kapatıldı. Faz 2'yi engelleyen bilinen bir hata kalmadı.

Sınırlamalar Bölüm N'dekilerle aynı:

1. FileVault kapalı; Faz 3'ten önce açılması öneriliyor.
2. SEC-14 ve ENG-04/08/09 kısmen doğrulandı.
3. Model indirme arka uçtan değil, açık bir kurulum adımıyla ve sizin izninizle yapılmalı.
4. İmzalı ve bağımsız paket P15'te.

Bunlara iki doğrulama sınırı da ekleniyor:

- Gerçek elektrik kesintisi test edilmedi. Protokol, atomik yeniden adlandırma ve `F_FULLFSYNC` üzerine kurulu.
- Geri yükleme için hâlâ arayüz yok.

