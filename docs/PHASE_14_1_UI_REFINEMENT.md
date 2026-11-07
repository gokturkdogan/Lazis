# Faz 14.1: Arayüz ve kullanıcı deneyimi revizyonu

**Tarih:** 2026-11-07.
**Dal:** `phase14/ui-refinement`, `main`'den (`348e0b1`) açıldı.
**Durum:** **Tamamlandı ve sahibin görsel onayıyla kabul edildi** (2026-11-07). `main`'e birleştirildi ve GitHub'a gönderildi.
- Sohbet oku ve panelin kayması ayrıca kabul edildi.
- Çekirdek, WebKit önizlemesinden alınan görüntü ve videolarla onaylandı (bölüm 9).
- Açık riskler bölüm 10'da duruyor.

## 1. Yenilenen yapı

| Önce | Şimdi |
|---|---|
| Üstte sekmeler | Sol üstte menü düğmesi ve soldan kayan cam çekmece (`NavDrawer.vue`) |
| Sohbet ekranındaki ilk kurulum kartları (`IntakePanel.vue`) | Çekirdeğin üzerinde adım adım bir cam pencere (`OnboardingModal.vue`) |
| Büyük "Belge ekle" paneli (`DocumentPanel.vue`) | Mesaj alanının yanında ataç simgesi (`DocumentAttach.vue`) ve mesaj alanının üstünde küçük bir etiket (`DocumentChip.vue`) |
| Sohbetteki FileVault uyarısı | Kaldırıldı; durum Genel Bakış ve Ayarlar'da gösteriliyor |
| Karışık düğme ve kart stilleri | Ortak tema: cam kartlar, ince çerçeveler, duruma göre renk alan vurgular (`theme.css`) |
| Simge yok | Tek bir SVG simge seti (`Icon.vue`, Lucide çizimleri, ISC lisansı). Emoji yok. |
| Sahnenin sağ altında yazılı "Konuşmayı gizle" düğmesi | Sohbet panelinin başlık satırının sağında yazısız küçük bir ok; panel kapalıyken sahnenin sağ kenarında ince bir ok sekmesi (ek istek 1) |
| Çekirdeğin ortasında patlamış beyaz ışık | Durum renginin kendi tonları, katmanlar ve plazma görünür (ek istek 2, bölüm 7) |

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
- `ui/dev/core-preview.html` ve `ui/dev/core-preview.ts`: yalnızca geliştirme için, arka uçsuz çekirdek önizlemesi. Uygulama derlemesine girmez (doğrulandı).
- `scripts/core-snapshots.swift`: çekirdeği beş durumda WebKit ile çizip PNG olarak kaydeder.

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

## 3a. Sohbet panelini gizleme oku (ek istek 1)

- **Yer:** Sohbet panelinin başlık satırının sağı. Yazı yok, yalnızca 16 px'lik bir SVG ok.
- **Görünüm:** Sakin durumda çerçevesiz ve soluk. Üzerine gelince durum rengini alır, hafif bir çerçeve ve ışıma belirir, ok gideceği yöne 2 px kayar.
- **Kapanış:** Panel 380 ms'de sağa kayarak ve solarak kapanır.
- **Kapalıyken:** Sahnenin sağ kenarının ortasında ince bir cam sekme (26×64 px) kalır. Sola bakan okla sohbeti yeniden açar.
- **Ok yönü:** Açıkken sağa bakar (panelin gideceği yön), kapalıyken sola bakar (panelin geleceği yön).
- **Erişilebilirlik:**
  - Her iki düğmede `aria-label` ("Konuşmayı gizle" / "Konuşmayı göster"), `aria-expanded`, `aria-controls` ve `title` var.
  - Enter ve boşluk tuşuyla çalışır.
  - Tıklanınca odak diğer düğmeye geçer, böylece klavye kullanıcısı boşta kalmaz.
- **Değişmeyen:** Panelin açık/kapalı durumu önceki gibi hatırlanır.
- **Bilinen:** Panel kapandığında çekirdek, önceki gibi, kayma bittikten sonra sahnenin yeni ortasına geçer.

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
- **Çekirdek:** Beş ana durum rengi aynı. Geometri, halkalar, parçacıklar, arklar, hareket hızları ve sesin çekirdeği nasıl oynattığı aynı. Değişen yalnızca ışık değerleri (bölüm 7a).
- **Hafıza:** Elle hafıza işlemleri ve Unutma sözleşmesi korunuyor. Otomatik öğrenme kapalı.
- **Diğer özellikler:** Belgeler, Wikipedia araştırma izni ve üslup tercihleri.
- **Güvenlik:** Güvenlik sınırları değişmedi.
- **Dokunulmayanlar:** Arka uç, kabuk, veritabanı ve göç dosyaları değişmedi; yalnızca arayüz değişti. Gerçek profile, Ollama ve Whisper ayarlarına dokunulmadı.

## 7a. Çekirdeğin ışığı (ek istek 2 ve 3)

**Sorun ne idi:** Ölçüm, çekirdeğin ortasında (yarıçapı ekran yüksekliğinin %22'si olan dairede) beyaza yakın piksellerin payına baktı. Eski kodla sonuçlar:

| Durum | Ortadaki beyaz alan | Renk doygunluğu |
|---|---|---|
| Bekleme | %5,7 | 0,58 |
| Dinleme (normal ses) | **%86** | 0,02 |
| Dinleme (yüksek ses) | **%100** | 0,00 |
| Düşünme | %23 | 0,22 |
| Konuşma (normal ses) | %33 | 0,18 |
| Konuşma (yüksek ses) | **%99,7** | 0,00 |
| Hata | %8,8 | 0,44 |

Yeni kodla yedi durumun hepsinde ortadaki beyaz alan **%0**; renk doygunluğu 0,50–0,85.

**Nedenler ve değişiklikler:**

| Neden | Değişiklik |
|---|---|
| Çekirdeğin merkezi (nucleus) rengini %55–80 saf beyazla karıştırıp 3 kata kadar parlatıyordu. | Merkez artık durum renginin üç tonundan oluşuyor: koyu ton çukurlarda, ana renk gövdede, açık ton tepelerde. Yalnızca tam ortadaki küçük bir nokta açılıyor ve o da rengini koruyor. İkinci, ince bir gürültü katmanı ayrıntı ekliyor. |
| Bloom 0,14 eşikle neredeyse her şeyi parlatıyordu; geniş yarıçapı bütün sahneye sis yayıyordu. | Bloom gücü 0,9'dan 0,5'e, yarıçapı 0,7'den 0,1'e indi; eşik 0,14'ten 0,55'e çıktı. |
| Sarı ve yeşil, aynı güçte mordan ve kırmızıdan çok daha parlak algılanır (parlaklık: sarı ~0,69, yeşil ~0,58, mor ~0,21). Bloom parlaklığa baktığı için bu iki durumda bütün çekirdeği yakıyordu. | Bloom, durum renginin parlaklığına göre kendini ayarlıyor: parlak renklerde biraz daha zayıf ve daha yüksek eşikli. Renklerin kendisi değişmedi. |
| Ses yükseldikçe kabuk, dalga halkası ve büyük ışımalar çok fazla ışık ekliyordu. Gerçek konuşma seviyesi 0,5–1,0 arasında. | Sesin ışığa katkısı azaltıldı. Bloom da ses yükseldikçe yumuşakça azalıyor (yüksek seste %55'e kadar). **Sesin şekle ve harekete etkisi aynı:** halkanın salınımı, merkezin büyümesi ve parçacıklar değişmedi. |
| Ton eşleme yoktu: 1'i aşan renkler tek tek kanallarda kırpılıp beyaza kayıyordu. | Son geçiş, aynı vinyet formülünü korurken parlak renkleri en güçlü kanallarına göre yumuşakça sıkıştırıyor. Kanallar arasındaki oran korunduğu için sarı sarı kalıyor. Bu geçiş eski vinyet geçişinin yerini aldı; geçiş sayısı artmadı. |

**Performans:**
- Ek kütüphane yok, ek geçiş yok.
- Merkeze bir gürültü çağrısı eklendi; bu küçük bir yüzeyde çalışıyor.
- Kare başına işlemciye birkaç çarpma eklendi.
- Gerçek pencerede FPS ölçülmedi.

**Görsel doğrulama nasıl yapıldı:**
- `ui/dev/core-preview.html`, çekirdeği arka uç, model ve mikrofon olmadan uygulamadaki kodun aynısıyla çiziyor.
- `scripts/core-snapshots.swift` bu sayfayı **WebKit** ile (LAZIS penceresinin motoru) ekran dışı bir pencerede açıp beş durumu PNG olarak kaydediyor. Dinleme ve konuşma, normal (0,35–0,4) ve yüksek (0,85) ses seviyesiyle de çekildi.
- Her değişiklik görüntülere bakılarak değerlendirildi; sayılar yalnızca destek.
- `--clip=N` ile aynı sayfadan 30 fps'lik kareler alınabiliyor; bunlardan yan yana önce/sonra videoları yapıldı (sahibin değerlendirmesi için, depoda değil).
- **Canlılık ölçümü:** Çekirdeğin çevresinde kareden kareye ortalama değişime bakıldı. Bu ölçü görünür hareketi yaklaşık olarak gösteriyor.
  - Yedi durumun altısında görünür hareket öncekinden fazla, en çok iki katı. Beyaz patlama plazmanın ve halkaların hareketini örtüyormuş.
  - Düşünmede hareket aşağı yukarı aynı (16,6 → 15,7).
  - Orta bölgenin ortalama parlaklığı yaklaşık yarıya indi.
  - Hız ve hareket kodu değişmedi.
- **Sınır:** Bunlar gerçek LAZIS penceresinden değil, aynı motor ve aynı kodla çizilmiş görüntüler. Gerçek pencerede sahibin bakması gerekiyor (bölüm 9).

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
- `core.spec.ts`: Gizleme oku yazısız; `aria-label` ve `aria-expanded` doğru; ok yönleri doğru; kapanınca kenar sekmesi çıkıyor ve odak ona geçiyor; açılınca odak başlıktaki oka dönüyor.

## 9. Görsel kontrol (sahip)

**Durum:** Sahip son görselleri inceledi ve tasarımı onayladı (2026-11-07).
- Çekirdeğin onaylanan görselleri WebKit önizlemesinden alındı: beş durumun görüntüleri ve önce/sonra videoları.
- Çekirdeğin gerçek LAZIS penceresinde Gemma, Whisper ve Yelda ile birlikte çalışırken görülüp görülmediği bu kayıtta yok; bu açık risk olarak duruyor (bölüm 10).

**Nasıl bakılır:** `make dev` geliştirme profilini kullanır, gerçek profili kullanmaz.

**Düzeltme:** İlk raporda "Gemma yalnızca mesaj gönderilirse yüklenir" yazılmıştı; bu yanlıştı. Ön ısıtma (`prewarm`) varsayılan olarak açık ve LAZIS açılınca modeli ısıtır. Yani `make dev` ile Gemma geliştirme profilinde yüklenir.

**Gemma'sız bakmak için:** Yalnızca çekirdek için, `pnpm vite` çalışırken `http://localhost:1420/dev/core-preview.html?state=thinking` adresi açılabilir. Durumlar: `idle`, `listening`, `thinking`, `speaking`, `error`. Ses seviyesi `&level=0.8` ile verilir.

**Bakılacaklar:**
- Çekmecenin açılışı ve kapanışı.
- İlk kurulum penceresi. Penceredeki "Sonra devam et" yalnızca o çalışma için kapatır; tamamen kapatmak için "Bir daha gösterme" seçilmelidir.
- Ataç ve belge etiketi.
- Ekran geçişleri.
- Küçük pencere genişliği.
- Hareketi azaltma ayarı.
- Sohbet panelini gizleme oku ve kenar sekmesi.
- Çekirdek: beş durumda, özellikle sarı ve yeşilde ortanın beyaza dönmemesi; yüksek seste konuşurken ayrıntının kalması; çekirdeğin sönük durmaması.

## 10. Açık riskler ve borçlar

- **Çekirdek:** Onaylanan görüntüler WebKit ile ama gerçek pencere dışında çekildi. Gerçek pencerede FPS ve GPU ölçülmedi. Işık değerleri sahibin gözüne göre yeniden ayarlanabilir: bloom değerleri `scene.ts` başında adlandırılmış sabitler; katman değerleri `shaders.ts` içinde "Phase 14.1" notuyla işaretli.
- **Görünüm:** Gerçek pencerede görünüm, performans ve bulanıklığın GPU maliyeti ölçülmedi. Cam paneller ve üst çubuk sürekli bulanıklık kullanıyor; arka planın bulanıklaşması yalnızca çekmece veya pencere açıkken oluyor.
- **Ekran okuyucu:** VoiceOver ile gerçek bir deneme yapılmadı; erişilebilirlik öznitelikleri yalnızca testlerle doğrulandı.
- **Önceki fazlardan süren açık borçlar:**
  - REL-001…004.
  - Sıkıştırma takılması.
  - M2, M5 ve M7 ölçümleri.
  - Mikrofonun kayıtla doğrulanması.
  - Ekran kilidi algısı.
- **Faz 15D (paketleme):** Bekliyor.
