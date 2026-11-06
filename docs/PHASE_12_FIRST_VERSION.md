# Faz 12 ilk sürüm: İzinli internet araştırması

**Tarih:** 2026-11-06. **Dal:** `phase12/research`, `main`'den (`acb9b49`) açıldı. **Durum:** Sahibin kararıyla **Wikipedia tabanlı ilk sürüm tamamlandı** (2026-11-06) ve `main`'e alındı. Gerçek Wikipedia bağlantısı bir kez doğrulandı (bölüm 11). Gerçek Gemma ile ve masaüstü penceresinde **denenmedi**.

## 1. Davranış

1. Araştırma varsayılan olarak **kapalı**. Kullanıcı Ayarlar → "İnternet araştırması"ndan "Her aramada onayımla"yı seçer. Değişiklik denetim kaydına yazılır.
2. Açıkken sohbette "İnternette araştır" düğmesi görünür. Kullanıcı ne aramak istediğini yazıp düğmeye basar.
3. Arka uç, **gönderilecek aramayı tam olarak** gösterir. Kısıtlı veri (şifre, token, IBAN, TC kimlik, kart numarası) varsa arama gönderilemez. Hafızadaki bir kişinin adı geçiyorsa kullanıcı uyarılır. Kullanıcı aramayı düzenleyebilir.
4. Yalnızca "Onayla ve araştır" ile o tur başlar. Arka uç aramayı yeniden denetler, ağ yardımcısından Wikipedia sonuçlarını alır.
5. Sayfa metinleri o turun notuna numaralı kaynaklar olarak girer. Model kaynak numarası göstermeye, kaynakta olmayanı "kaynaklarda yok, genel bilgime göre" diye ayırmaya yönlendirilir.
6. Yanıtın sonuna **sabit metin olarak** kaynak listesi eklenir. Araştırma başarısızsa sabit bir not eklenir: "İnternet araştırması sonuç vermedi (neden); bu yanıt kaynağa dayanmıyor."

Normal mesajlar hiçbir zaman ağa çıkmaz. Bulunan sayfalar hafızaya yazılmaz; yanıt, normal yanıt gibi sohbet geçmişinde kalır.

## 2. Mimari (ADR-0009'a uygun)

| Süreç | Ağ izni | Neden |
|---|---|---|
| Arka uç (mevcut) | Yalnızca yerel Ollama ve **tek bir Unix soketi** (yardımcınınki) | İnternete hâlâ kapalı; hafıza, anahtar ve veritabanı bu süreçte |
| **Ağ yardımcısı** (yeni, `lazis.providers.web.helper`) | Yalnızca 443 portuna TCP ve sistem DNS'i | Gizli bilgi tutmaz, veritabanına ve arka ucun API'sine erişemez |

- Yardımcıyı masaüstü kabuğu kendi korumalı profiliyle (`sandbox/egress.sb`) başlatır. Arka uç alt süreç başlatamaz.
- Yardımcı başlamazsa uygulama normal çalışır; araştırma "bileşen çalışmıyor" der.
- Yardımcı, kabuk kapanınca (bağlantı borusu kapanınca) kendiliğinden kapanır ve soketini siler.

## 3. Ağ güvenliği

| Katman | Kural |
|---|---|
| İşletim sistemi (yardımcı) | Yalnızca `*:443` ve DNS. Yerel servisler, 80 gibi diğer portlar, diğer Unix soketleri, dinleme soketi reddedilir |
| İşletim sistemi (arka uç) | Yalnızca Ollama ve yardımcının soketi; 443 dahil dışarıya hiçbir bağlantı yok |
| Yardımcının iç denetimi (bağlanma anında) | Yalnızca **genel** IP adresine 443. Yerel, özel (10/8, 172.16/12, 192.168/16), link-local (169.254, bulut meta verisi), CGNAT, IPv6 yerel ve IPv4'e eşlenmiş adresler reddedilir. DNS yeniden bağlama (rebinding) böylece etkisizdir. Program başlatma ve dinleme soketi açma reddedilir |
| URL kuralları (her istekte ve her yönlendirmede) | Yalnızca `https`, port 443, URL'de kullanıcı adı/parola yok, IP literal yok, `localhost` ve yerel adlar yok, yalnızca izinli alan adları (`tr.wikipedia.org`, `en.wikipedia.org`) |
| İstek sınırları | Bağlantı 5 sn, okuma 10 sn, araştırma başına toplam 20 sn; yanıt başına 2 MB; en çok 3 yönlendirme; yalnızca `application/json`; çerez yok, ortamdaki vekil sunucu ayarı kullanılmaz; programı adlandıran, kişiyi adlandırmayan sabit User-Agent |
| Oturum sınırları | Araştırma başına en çok 2 arama ve 3 sayfa; sayfa başına 20.000 karakter; nota en çok 9.000 karakter |

## 4. Arama ve sayfa okuma yöntemi

- **Wikipedia'nın herkese açık API'si** (önce Türkçe, sonuç yoksa İngilizce). Ücretsiz, anahtar ve hesap gerektirmez, programlar için resmî olarak sunulur.
- Sayfa metni API'den düz metin olarak gelir; HTML ayrıştırılmaz. Böylece sayfadaki betik, gizli metin veya biçim hilesi gelmez.
- Sorudaki kelimelerle en çok örtüşen paragraflar seçilir; sayfanın giriş paragrafı her zaman alınır.

**Genel web araması bu sürümde yok.** Anahtarsız, ücretsiz ve **resmî** bir genel arama API'si yok:

| Seçenek | Durum |
|---|---|
| DuckDuckGo (`ddgs`) | Resmî değil; sayfa kazıma tabanlı ve kırılabilir. Kullanılırsa tüm sayfaların HTML ayrıştırması ve genel alan adlarına izin gerekir |
| Brave, Mojeek ve benzeri | Kullanıcının kendi anahtarını gerektirir (ücretsiz katmanları var) |
| SearXNG | Ayrı, yerel kurulum gerektirir |

Bu seçim sahibin kararıdır, bu yüzden uygulanmadı.

## 5. Kaynak ve doğruluk sınırları

- Kaynak listesi modelden bağımsızdır ve her zaman doğru bağlantıyı gösterir. Ama yanıttaki **[1] gibi atıfların doğru kaynağa işaret ettiği denetlenmez**.
- Modelin kaynakta olmayanı ayırması, "bilmiyorum" demesi ve sayfa içindeki talimatlara uymaması **talimattır, denetlenmez; gerçek Gemma ile ölçülmedi**.
- Wikipedia güncel olaylarda geride kalabilir. "Dün maç kaç kaç bitti" gibi sorular çoğunlukla sonuçsuz kalır ve bu dürüstçe söylenir.
- "Güncel bilgi" ile "modelin kendi bilgisi" ayrımı not metniyle istenir; kaynaksız yanıtın sonundaki sabit not bu ayrımı garanti eden tek parçadır.

## 6. Denetim kaydı

Araştırmanın açılıp kapanması ve her arama (`category = research`) kaydedilir: sağlayıcı, sayfa sayısı, süre, başarısızlık nedeni, sorgu uzunluğu. **Sorgu metni kaydedilmez.** Kayıt sistemi içerik saklamaz; kullanıcı gönderilen aramayı onay anında görür. RES-12'nin "gönderilen metni günlükte göster" kısmı bu yüzden karşılanmadı.

## 7. Performans ve maliyet

- Normal sohbet: ek ağ isteği, ek model çağrısı veya ek bekleme yok (testle doğrulandı). Sistem istemi değişmedi.
- Araştırma turu: model çağrısı sayısı aynı (tek yanıt). Nota en çok yaklaşık 4.000 token eklenir; ilk token gecikmesi buna göre artar (ölçülmedi).
- Yardımcı süreç: boşta **34,6 MB** bellek, %0 işlemci (tek okuma). Kabuk açılırken beklenmeden başlatılır, açılışı geciktirmez.
- Yeni bağımlılık yok (`httpx` vardı). Ücretli servis, anahtar veya bulut modeli yok.

## 8. Değişen dosyalar

| Dosya | Değişiklik |
|---|---|
| `core/src/lazis/providers/web/` | **Yeni.** `guard.py` (URL ve bağlantı kuralları), `wikipedia.py`, `helper.py` (yardımcı süreç), `client.py` (arka uç tarafı) |
| `core/src/lazis/research/__init__.py` | **Yeni.** İzin, sorgu önizlemesi, not, sabit kaynak metni |
| `core/src/lazis/api/research.py` | **Yeni.** `GET/PUT /research/settings`, `POST /research/plan` |
| `core/src/lazis/conversation/engine.py` | `research_query`, "araştırılıyor" aşaması, not, kaynak metni, denetim kaydı |
| `core/src/lazis/{api/*,app/*,config/model.py,errors.py,i18n.py}` | `--egress-socket`, `research_query` alanı, hata kodları |
| `core/src/lazis/documents/library.py` | `best_passages` (sayfadan paragraf seçimi) |
| `apps/desktop/src-tauri/sandbox/egress.sb` | **Yeni.** Yardımcının profili |
| `apps/desktop/src-tauri/sandbox/backend.sb` | Yalnızca yardımcının soketine izin |
| `apps/desktop/src-tauri/src/{egress.rs,backend.rs,lib.rs}` | Yardımcıyı başlatma, soket yolunu arka uca verme |
| `apps/desktop/ui/src/components/{ResearchPanel,ResearchPrompt}.vue` | **Yeni.** Ayar ve onay penceresi |
| `apps/desktop/ui/src/{components/AssistantThread.vue,views/SettingsView.vue,stores/assistant.ts,api/client.ts,i18n/tr.ts}` | Düğme, aşama, metinler |
| Testler | `test_web_guard.py`, `test_web_wikipedia.py`, `test_research.py` (birim ve entegrasyon), `security/test_os_sandbox.py` (3 yeni), `research_support.py`, `research.spec.ts`, Rust `tests/egress.rs` |

## 9. Testler (modelsiz)

`make check` geçti (çıkış kodu 0): 3.491 çekirdek, 137 arayüz, 8 arayüz–arka uç, 40 Rust testi; ruff, biçim, pyright, vue-tsc, clippy ve 4 içe aktarma kuralı temiz.

| Konu | Doğrulanan |
|---|---|
| İzin | Kapalıyken araştırma turu reddedilir, hiçbir istek gitmez, mesaj saklanmaz; açıkken normal mesajlar yardımcıya hiç ulaşmaz |
| Kısıtlı veri | IBAN ve şifre içeren arama önizlemede engellenir, turda reddedilir, gönderilmez |
| Kişi uyarısı | Hafızadaki kişinin adı geçen arama önizlemede belirtilir |
| Ağ güvenliği | 17 reddedilen URL türü, 18 adres durumu, her yönlendirme adımı, döngü, boyut, içerik türü, zaman aşımı, ağ hatası; gerçek korumalı profillerle işletim sistemi ve iç denetim |
| Kaynak doğruluğu | Notta ve yanıt sonunda aynı numaralar ve bağlantılar; ekranda görünen ile saklanan aynı |
| Ağsız sohbet | Yardımcı hiç yokken normal sohbet çalışır; yardımcı çalışmıyorsa araştırma turu dürüst bir notla biter |
| Gizlilik | Hafıza kaydı oluşmaz; araştırma turunda kişisel hafıza nota eklenmez; denetim kaydında sorgu metni yok; sayfa metni notu kapatamaz |
| Arayüz | Kapalıyken düğme yok; önizleme, düzenleme, onay, engelli arama, vazgeçme, ayar |

## 10. Açık eksikler ve riskler

- ~~Gerçek internetle denenmedi.~~ Bir kez doğrulandı (bölüm 11); başka sorgularla, ağ kesintisinde veya Wikipedia yavaşken denenmedi.
- **Gerçek Gemma ile denenmedi:** kaynağa sadakat, atıf doğruluğu, sayfa içi talimatlara direnç ölçülmedi.
- **Masaüstü penceresi açılmadı:** düğme, onay penceresi ve kabuğun yardımcıyı başlatması gerçek uygulamada görülmedi (Rust testi yardımcının profiliyle başladığını doğruluyor).
- **Yalnızca Wikipedia:** genel web araması için sahibin sağlayıcı kararı gerekiyor.
- **Sorgu temizleme:** Kişi adları uyarılır ama otomatik çıkarılmaz; kullanıcının kendi adı, sağlık, hukuk ve para gibi hassas konular ayrıca algılanmaz. Kullanıcı gönderilecek metni her zaman görüp onaylar.
- **Denetim kaydı sorgu metnini tutmuyor** (RES-12'den bilinçli sapma).
- **Kelimeye dayalı paragraf seçimi** farklı kelimelerle anlatılan bilgiyi kaçırabilir.
- **Yardımcının iç denetimi** Python soketleri içindir. İşletim sistemi profili 443 dışını zaten kapatıyor; 443'te özel adres engeli yalnızca iç denetimdedir. Bugün yardımcıda yerel kodla bağlantı kuran bir bileşen yok.

## 11. Gerçek Wikipedia bağlantı testi (2026-11-06, sahibin onayıyla, tek istek)

Kabuğun kullandığı düzen: yardımcı `egress.sb` altında, istemci `backend.sb` altında; istek yalnızca yardımcının soketinden. Sorgu: "İstanbul tarihi". Model yüklenmedi.

| Kontrol | Sonuç |
|---|---|
| Arka uç profili internete doğrudan ulaşabiliyor mu | Hayır: DNS reddedildi, `185.15.59.224:443` bağlantısı işletim sistemince reddedildi (EPERM) |
| DNS (yardımcı) | Çalıştı |
| HTTPS/TLS (yardımcı) | Kuruldu; sertifika doğrulandı |
| Wikipedia API yanıtı | Alındı; 1 arama ve 3 sayfa isteği, toplam 2,1 sn |
| Sınırlar | 3 sayfa (sınır 3); 2. sayfa 20.000 karakter sınırında kesildi; not 8.725 karakter (sınır 9.000) |
| Kaynaklar | [1] İstanbul tarihi, [2] İstanbul, [3] Fatih; bağlantılar `https://tr.wikipedia.org/wiki/...`; notta ve yanıt sonundaki listede aynı numara ve bağlantı |
| İlk sayfanın başı | "İstanbul tarihi, günümüzde Türkiye toprakları üzerinde bulunan İstanbul şehrinin tarihini anlatır…" (sorguyla ilgili) |

Bağlantılardaki Türkçe harfler URL kodlamasıyla gösterilir (`%C4%B0stanbul`); bağlantı doğrudur, ama okunması zordur.

## 12. Kapanış ve ertelenen kapsam

- **Arayüz:** Ayarlar'da ve onay penceresinde "Wikipedia genel bir internet arama motoru değildir…" açıklaması var.
- **Ertelenen:** Genel web araması (DuckDuckGo, Brave, Mojeek, SearXNG) sonraki geliştirme kapsamındadır; sağlayıcı kararı sahibindir. Sorgu sınıflandırması (hassas konular), araştırma önbelleği ve gönderilen metnin denetim görünümü de ertelendi.
- **Açık teknik borç:** gerçek Gemma ile kaynak sadakati ve atıf doğruluğu, sayfa içi talimatlara direnç, masaüstü penceresinde düğme, onay penceresi ve kabuğun yardımcıyı başlatması.

