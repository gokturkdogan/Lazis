# Faz 14.1: Arayüz ve kullanıcı deneyimi revizyonu

**Tarih:** 2026-11-07.
**Dal:** `phase14/ui-refinement`, `main`'den (`348e0b1`) açıldı.
**Durum:** Geliştirme tamamlandı; modelsiz testler geçiyor. **Masaüstünde görsel onay bekleniyor.** Onay gelmeden `main`'e birleştirilmeyecek ve GitHub'a gönderilmeyecek.

## 1. Yenilenen yapı

| Önce | Şimdi |
|---|---|
| Üstte sekmeler | Sol üstte menü düğmesi ve soldan kayan cam çekmece (`NavDrawer.vue`) |
| Sohbet ekranındaki ilk kurulum kartları (`IntakePanel.vue`) | Çekirdeğin üzerinde adım adım bir cam pencere (`OnboardingModal.vue`) |
| Büyük "Belge ekle" paneli (`DocumentPanel.vue`) | Mesaj alanının yanında ataç simgesi (`DocumentAttach.vue`) ve mesaj alanının üstünde küçük bir etiket (`DocumentChip.vue`) |
| Sohbetteki FileVault uyarısı | Kaldırıldı; durum Genel Bakış ve Ayarlar'da gösteriliyor |
| Karışık düğme ve kart stilleri | Ortak tema: cam kartlar, ince çerçeveler, duruma göre renk alan vurgular (`theme.css`) |
| Simge yok | Tek bir SVG simge seti (`Icon.vue`, Lucide çizimleri, ISC lisansı). Emoji yok. |

**Yeni dosyalar:**
- `components/Icon.vue`
- `components/NavDrawer.vue`
- `components/OnboardingModal.vue`
- `components/DocumentAttach.vue`
- `components/DocumentChip.vue`
- `composables/focusTrap.ts`
- `navigation.ts`
- `stores/onboarding.ts`
- `stores/documentUi.ts`

**Kaldırılan dosyalar:** `IntakePanel.vue`, `DocumentPanel.vue`.

## 2. İlk kurulum penceresi

- **Ne zaman açılır:** Kendiliğinden yalnızca kurulum bitmemişse açılır.
- **Kayıt:** Durum, önceki fazlardaki yerel anahtarda (`lazis.intake.v1`) tutulur. Bu sayede önceki seçimler korunur. Bu anahtarda kişisel bilgi yoktur.
- **Adımlar:** Hitap adı, siz/sen, yanıt uzunluğu, ilgi alanı veya hedef. Bir ilerleme çizgisi var; adımlar arasında geçiş animasyonu var.
- **Hafıza:** Hiçbir yanıt kendiliğinden hafızaya yazılmaz.
  - Ad ve konu yalnızca "Hafızaya kaydet" düğmesiyle kaydedilir.
  - Hafıza bir yanıtı reddederse pencere bir sonraki adıma geçmez ve hatayı gösterir.
- **Atla:** Hiçbir şey kaydetmeden bir sonraki adıma geçer.
- **Sonra devam et (× ve Escape de aynı işi yapar):** Pencere bu çalışma boyunca kapanır. Uygulama bir sonraki açılışta aynı adımdan devam eder.
- **Bir daha gösterme ve Tamam:** Pencere bir daha kendiliğinden açılmaz.
- **Ayarlar → "İlk kurulumu aç":** Pencereyi her zaman yeniden açar.
- **Erişilebilirlik:**
  - Pencere `role="dialog"` ve `aria-modal` ile tanımlıdır; başlığı `aria-labelledby` ile bağlıdır.
  - Odak pencerenin içinde kalır; Tab tuşu düğmeler arasında döner.
  - Açılınca odak ilk soruya gider. Kapanınca önceki öğeye döner.

## 3. Menü

- **Menü düğmesi:** `aria-expanded` ve `aria-controls` öznitelikleri var.
- **Çekmece:** Soldan kayarak açılır. Arkadaki uygulama hafifçe bulanıklaşır ve kararır.
- **Bölümler:** Her bölümün kendi simgesi var. Açık olan bölüm `aria-current="page"` ile işaretlenir, ışıklı bir çizgiyle gösterilir ve odağı alır.
- **Kapanış:** Escape, dışarı tıklama veya × ile kapanır; odak menü düğmesine döner.
- **Görüntüleme:** Çekmece kapalıyken hiç çizilmez. Genişliği `min(300px, 86vw)`, bu yüzden küçük pencerede de sığar.
- **Ekranlar arası geçiş:** Kısa bir saydamlık ve kayma geçişi var. Gizli ekranlar çizilmez.
- **Sayfa başlıkları:** Sohbet dışındaki ekranların üstünde simge, başlık ve tek satırlık açıklama bulunan bir başlık var.

## 4. Ataç akışı

1. Ataç simgesine tıklayın; üzerine gelince parlar. Dosya seçici açılır ve yalnızca TXT, PDF, DOCX kabul edilir.
2. Seçilen dosyanın baytları önceki gibi arka uca gider.
3. Belge okunurken "Belge okunuyor…" etiketi görünür ve ataç devre dışı kalır.
4. Açılan belge, mesaj alanının üstünde küçük bir etiket olarak görünür: ad, tür, sayfa sayısı, gerekirse "baş kısmı", **Özetle** düğmesi ve tek tıkla kaldırma (×).
5. Hata olursa etiket kırmızı olur ve hatanın Türkçe açıklamasını gösterir. Örnekler: 10 MB üstü dosya, metin katmanı olmayan PDF.

**Değişmeyen sınırlar:**
- Belge en fazla 10 MB olabilir.
- Aynı anda tek belge açık olabilir; yeni belge eskisini kapatır.
- Belge yalnızca bu oturumun belleğinde tutulur. Diske ve hafızaya yazılmaz.

## 5. FileVault

**Kaldırılan:** Yalnızca sohbet ekranındaki uyarı bandı.

**Değişmeyenler:**
- Kabuktaki gerçek FileVault denetimi.
- Genel Bakış'taki gizlilik kartı ("Kapalı — Sistem Ayarları…").
- Ayarlar'daki gizlilik satırı.

Tanılama ekranında FileVault bilgisi önceden de yoktu; eklenmedi.

## 6. Tasarım dili

- **Renk:** Vurgu rengi (`--accent`) çekirdeğin durumundan gelir: boşta mavi, dinlerken mor, düşünürken sarı, konuşurken yeşil, hatada kırmızı. Kart çerçeveleri, odak halkaları, birincil düğmeler, menüdeki etkin bölüm ve belge etiketi bu rengi kullanır. Sabit mavi tonlar bu değişkene çevrildi.
- **Paneller:** Hafif bulanık, ince çerçeveli cam paneller. Üzerine gelince çerçeve vurgu rengini alır.
- **Ortak bileşenler:** Düğme, simge düğmesi, giriş alanı, onay kutusu ve kaydırma çubuğu tek tiptir.
- **Ekranlar:** Genel Bakış, Hafıza, Ayarlar ve Tanılama ortalanmış, en fazla 1080 px genişliğinde bir sayfa düzeninde. Sohbet, çekirdek sahnesini tam ekran kullanmaya devam ediyor.
- **Hareket:** Hareketler kısa (150–400 ms), yalnızca CSS ile. Animasyon kütüphanesi eklenmedi. Sahte "dinliyor" veya "düşünüyor" göstergesi yok: ses ve çekirdek yalnızca gerçek durumları gösteriyor.
- **Hareketi azaltma:** Sistemdeki ayarla ve uygulamadaki seçenekle bütün geçişler ve animasyonlar 1 ms'ye iner.

## 7. Korunanlar

- **Ses:** Whisper, Yelda, kullanıcının başlattığı sesli oturum, mikrofon güvenliği (Faz 15B) ve gerçek mikrofon ile konuşma eşlemesi.
- **Çekirdek:** Beş durum rengi korunuyor. Çekirdek gölgelendiricilerine (`scene.ts`) dokunulmadı.
- **Hafıza:** Elle hafıza işlemleri ve Unutma sözleşmesi korunuyor. Otomatik öğrenme kapalı.
- **Diğer özellikler:** Belgeler, Wikipedia araştırma izni ve üslup tercihleri.
- **Güvenlik:** Güvenlik sınırları değişmedi.
- **Dokunulmayanlar:** Arka uç, kabuk, veritabanı ve göç dosyaları değişmedi; yalnızca arayüz değişti. Gerçek profile, Ollama ve Whisper ayarlarına dokunulmadı.

## 8. Testler

`make check` geçti:
- Python: 3497 test.
- Arayüz: 189 test geçti, 1 test atlandı.
- Bütünleşme: 8 test geçti, 3 test atlandı.
- Rust testleri geçti.
- ruff, pyright, import-linter, vue-tsc ve clippy temiz.

Üretim derlemesi (`vite build`) de geçti. Büyük parça uyarısı mevcut three.js parçası için; bu uyarı önceden de vardı.

**Yeni ve güncellenen testler (modelsiz):**
- `onboarding.spec.ts`:
  - İlk açılışta pencere açılıyor; erişilebilirlik öznitelikleri ve ilerleme çizgisi doğru, odak ilk soruda.
  - Kurulum bittiyse veya "Bir daha gösterme" seçildiyse açılmıyor.
  - Hafızaya yalnızca düğmeyle kaydediliyor; reddedilen yanıtta pencere ilerlemiyor.
  - Atlamak hiçbir şey kaydetmiyor.
  - Hitap seçimi kaydediliyor.
  - "Sonra devam et" bu çalışma için kapatıyor, sonraki açılışta aynı adımdan sürüyor.
  - Escape "sonra" anlamına geliyor, "bir daha gösterme" değil.
  - Ayarlar'dan yeniden açılabiliyor; sohbette kurulum kartı kalmadı.
- `nav.spec.ts`:
  - Çekmece kapalıyken çizilmiyor.
  - Simgeler, etkin bölüm ve odak doğru.
  - Bölüm seçilince çekmece kapanıyor ve gizli ekranlar çizilmiyor.
  - Escape, dışarı tıklama ve × kapatıyor; odak menü düğmesine dönüyor.
  - Emoji yok ve simgeler tek setten.
- `documents.spec.ts`:
  - Ataç simgesi ve dosya türü kısıtı.
  - Belge yokken etiket çizilmiyor.
  - Okuma durumunda ataç kilitleniyor.
  - Yeni belge eskisini kapatıyor.
  - Yeni dosya seçilince eski hata temizleniyor.
  - Önceki dört test de korunuyor.
- `app.spec.ts`: FileVault sohbette yok, Genel Bakış ve Ayarlar'da var. Menüyle gezinme.

## 9. Görsel kontrol (sahip)

**Durum:** Masaüstünde henüz bakılmadı.

**Nasıl bakılır:** `make dev` geliştirme profilini kullanır, gerçek profili kullanmaz. Gemma yalnızca bir mesaj gönderilirse yüklenir.

**Bakılacaklar:**
- Çekmecenin açılışı ve kapanışı.
- İlk kurulum penceresi. Penceredeki "Sonra devam et" yalnızca o çalışma için kapatır; tamamen kapatmak için "Bir daha gösterme" seçilmelidir.
- Ataç ve belge etiketi.
- Ekran geçişleri.
- Küçük pencere genişliği.
- Hareketi azaltma ayarı.

## 10. Açık riskler ve borçlar

- **Görünüm:** Gerçek pencerede görünüm, performans ve bulanıklığın GPU maliyeti ölçülmedi. Cam paneller ve üst çubuk sürekli bulanıklık kullanıyor; arka planın bulanıklaşması yalnızca çekmece veya pencere açıkken oluyor.
- **Ekran okuyucu:** VoiceOver ile gerçek bir deneme yapılmadı; erişilebilirlik öznitelikleri yalnızca testlerle doğrulandı.
- **Önceki fazlardan süren açık borçlar:**
  - REL-001…004.
  - Sıkıştırma takılması.
  - M2, M5 ve M7 ölçümleri.
  - Mikrofonun kayıtla doğrulanması.
  - Ekran kilidi algısı.
- **Faz 15D (paketleme):** Bekliyor.
