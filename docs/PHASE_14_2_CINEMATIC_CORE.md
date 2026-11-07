# Faz 14.2: Sinematik AI Çekirdeği

**Tarih:** 2026-11-07.
**Dal:** `phase14/cinematic-core`, `main`'den (`201bddf`, Faz 14.1 birleştirilmiş hali) açıldı.
**Durum:** **Tamamlandı ve sahibin görsel onayıyla kabul edildi** (2026-11-07); `main`'e birleştirildi ve GitHub'a gönderildi.
- Onay, WebKit önizlemesinden alınan önce/sonra görselleri ve videolarıyla verildi.
- Açık riskler bölüm 9'da duruyor.

**Kapsam:** Yalnızca merkezdeki çekirdek değişti. Arayüz, sohbet paneli, menü ve diğer ekranlar değişmedi.

**Değişen dosyalar:**
- `ui/src/core/` içinde: `scene.ts`, `shaders.ts`, `palette.ts`, `uniforms.ts`.
- Yeni dosya: `ui/src/core/lattice.ts`.
- Geliştirme araçları: `ui/dev/core-preview.ts`, `scripts/core-snapshots.swift`.

## 1. Çekirdek neden dijital ve parlak görünüyordu

| Sahne ve gölgelendiricide bulunan | Etkisi |
|---|---|
| Bütün katmanlar eklemeli (additive) karışımla çiziliyordu; hiçbir şey ışığı soğurmuyor ya da örtmüyordu. | Katmanlar üst üste toplanıp ışık kütlesine dönüşüyordu; derinlik yoktu. |
| Çekirdek, kenarı parlayan düz bir küreydi; "plazma" yalnızca yüzeyde 2B gürültüydü. | İçinde hacim ve yapı yoktu; "ışık topu" görünümü. |
| Görsel dili çoğunlukla arayüz grafiğiydi: 7 halka (çizgi, işaret, tarama), tel kafes, tarama çizgisi, ızgara. | Nesneden çok gösterge paneli hissi veriyordu. |
| Ses seviyesi yaklaşık 9 yerde doğrudan parlaklık ekliyordu: kabuk, merkez, ışıma, halkalar, parçacıklar, arka plan, dalga halkası. | Konuşurken her şey birlikte parlıyordu; yüksek seste iç yapı kayboluyordu. |
| Dalga halkasının iç ve dış kenarı sesle ters yönlere gidiyordu. | Yüksek seste ince çizgi kalın bir ışık bandına dönüşüyordu. |
| Arklar saniyede 14 kez rastgele yeniden çiziliyordu. | Sürekli rastgele titreşim. |
| Halkalar ve parçacıklar çekirdeğin önünden tam parlaklıkla geçiyordu. | Çekirdeği örtüyordu. |

## 2. Yeni görsel yapı (mevcut yapı korunarak)

İçten dışa:

1. **Kalp (merkez):** Daha küçük (0,27 → 0,16) ve daha düzgün yüzeyli. Ses onu çok az büyütüyor (0,35 → 0,10). Sesin rengine katkısı azaltıldı (0,6 → 0,2).
2. **Sinir ağı (yeni):** Çekirdeğin hacmine yayılmış yaklaşık 130 düğüm ve bunlar arasındaki ince, hafif kavisli bağlantılar (bölüm 3).
3. **Cam zar (kabuk):** Kenar ışığı daha ince (fresnel üssü 2,2 → 4); iç dolgu çok hafif. Ses kabuğa ışık eklemiyor, yalnızca yüzeyini biraz ve düzensizce oynatıyor.
4. **Gövde (yeni):** Çekirdeğin arka yarısı koyu, yarı saydam bir yüzey olarak çiziliyor ve derinlik bilgisi yazıyor. Arkadaki ışımayı soğuruyor; çekirdeğin arkasında kalan halka ve parçacık parçaları gizleniyor. Çekirdek ışık yığını değil, karanlık bir odada duran derin bir nesne gibi okunuyor.
5. **Dış katmanlar** (halkalar, parçacıklar, akış çizgileri, tel kafes):
   - Kamera açısından çekirdeğin önüne düştükleri yerde %60–80 soluklaşıyorlar; çekirdeği örtmüyorlar.
   - Ses, halkaların ve parçacıkların parlaklığına çok az ekliyor.
6. **Dalga halkası:** Hâlâ gerçek sesin şekliyle salınıyor, ama iki kenarı birlikte hareket ediyor; ince bir çizgi olarak kalıyor. Salınım genliği küçüldü.
7. **Arklar:** Yalnızca düşünme ve hata durumlarında, eskisi gibi. Titreşim artık rastgele sıçramıyor; sürekli ve yumuşak bir gürültüyle dolaşıyor.
8. **İç katmanların boyu:** Gövde, ağ, kabuk ve kalp ×1,18 büyütüldü, ağ görünsün diye. Dış halkalar yerinde.
9. **Renk tonları:** Beş ana renk aynı. Her durumun açık tonu daha az soluk, koyu tonu daha koyu; her durum tek bir rengin koyu, orta ve açık tonlarıyla derinlik kazanıyor.

## 3. Sinir ağı ve enerji akışı nasıl kuruldu

**Yapı (`lattice.ts`):**
- Sabit tohumlu bir rastgele sayı üreteci kullanılıyor; yapı her açılışta aynı, GPU olmadan test edilebiliyor.
- Düğümler çekirdeğin hacmine eşit yoğunlukta, birbirinden en az 0,075 uzaklıkta yerleştiriliyor (yarıçap 0,10–0,56).
- Her düğüm en yakın 3 komşusuna bağlanıyor:
  - En yakındakine her zaman bağlanıyor; böylece yalnız kalan düğüm olmuyor.
  - Diğerlerine yalnızca 0,36'dan kısaysa bağlanıyor; böylece yıldız biçimli uzun çizgiler oluşmuyor.
- Her bağlantı 8 parçalı, uzunluğunun %4–14'ü kadar yana kavisli bir çizgi.

**Çizim:** Bütün bağlantılar tek bir çizgi çizimi, bütün düğümler tek bir nokta çizimi; iki çizim çağrısı. Yüksek kalitede 130, düşük kalitede 70 düğüm.

**Hareket (tamamı gölgelendiricide):**
- **Enerji paketleri:** Her bağlantıda kendi hızında (0,3–1,1) ve kendi yönünde ilerleyen, kuyruklu ışık paketleri var.
- **Açılıp sönme:** Her bağlantı ve düğüm, kendi yavaş gürültü ritmine göre bir süre açık kalıp sönüyor; bağlantılar sırayla canlanıyor. Durumun etkinliği ve gerçek ses eşiği düşürüyor; daha çok bağlantı açılıyor ve enerji ağa yayılıyor.
- **Düğüm ateşlemesi:** Hızlı bir parlama, yavaş bir sönüm. Yalnızca açık düğümlerde.
- **Organik akış:** Bütün ağ geniş ve yavaş bir gürültüyle akıyor. Bağlantıların uçları düğümlerinde kalıyor, çünkü düğümler ve bağlantılar aynı bükme işlevini kullanıyor.
- **Paralaks:** Ağ, kabuktan farklı hız ve eksende dönüyor.
- **Derinlik gölgelemesi:** Arkadaki bağlantı ve düğümler koyu tona ve %30 parlaklığa iniyor, öndekiler tam parlaklıkta.

**Akış hızı:** İşlemci her karede yalnızca iki sayı ilerletiyor: `uFlow` ve `uVoice`. Akış hızı durumun kendi temposundan ve gerçek sesten geliyor: `0,22 + durum hızı × 0,42 + ses × 1,5`. Bekleme yavaş ve sakin; düşünme hızlı.

**Bekleme durumu:** Hareket dekoratif ve sakin. Düşük etkinlik yüzünden bağlantıların çoğu kapalı, paketler seyrek; "işlem yapılıyor" izlenimi vermiyor.

## 4. Konuşurken parlaklık nasıl denetlendi

- **Ses ışığa dönüşmüyor:** Sesin parlaklığa katkısı şu katmanlardan kaldırıldı ya da çok azaltıldı: kabuk, ışıma, arka plan, halkalar, parçacık boyu, kalp ve dalga halkası.
- **Ses ağa gidiyor:** Daha çok bağlantı açılıyor, akış hızlanıyor, düğümler parlıyor ve yüzey biraz oynuyor.
- **Bloom:** Faz 14.1'deki ayar korunuyor. Parlak durum renklerinde (sarı, yeşil) ve ses yükseldikçe kendini azaltıyor.
- **Ölçüm:** Yüksek sesle sessizlik arasında merkezin toplam parlaklığı yalnızca yaklaşık %10 değişiyor (88 → 79).
- **Önce/sonra, yüksek ses:** Merkezdeki ayrıntı ölçüsü 6,4'ten 22,6'ya çıktı (yaklaşık 3,5 kat). Parlaklık 162'den 76'ya indi.

## 5. Gerçek sese tepki

- **Kaynak aynı:** Ses seviyesi önceki gibi gerçek mikrofondan (dinlerken) ve Yelda'nın gerçek çıkışından (konuşurken) geliyor. Diğer durumlarda sıfır.
- **`uVoice`:** Ağın kullandığı ses değeri, ölçülen seviyeyi hızla izliyor (saniyede 14) ve yavaşça bırakıyor (saniyede 2,4). Ses kesilince ağ yaklaşık bir saniyede yumuşakça sakinleşiyor; ses hiç yoksa değer tam sıfır. Testli.
- **Hareketi azaltma:** Bu tercih açıkken ses etkisi 0,4 ile sınırlı, akış ve bükülme yavaşlıyor.
- **Ölçülmeyen:** Gerçek mikrofon ve Gemma çalıştırılmadı. Görseller, önizlemede konuşmaya benzer yapay bir seviye eğrisiyle üretildi.

## 6. Önce/sonra ölçümleri

Görüntüler, `main`'deki ve daldaki aynı kodla, aynı kameradan, WebKit önizlemesinde alındı. Ölçüm alanı çekirdeğin çevresi.

| Durum | Beyaz % | Doygunluk | Parlaklık | Ayrıntı | Hareket |
|---|---|---|---|---|---|
| Bekleme | 0 → 0 | 0,88 → 0,85 | 79 → 57 | 14,0 → 18,7 | 3,4 → 3,8 |
| Dinleme | 0 → 0 | 0,54 → 0,57 | 100 → 59 | 16,6 → 19,9 | 7,9 → 6,7 |
| Düşünme | 0 → 0 | 0,54 → 0,46 | 139 → 100 | 17,5 → 24,8 | 17,2 → 17,2 |
| Konuşma, orta ses | 0 → 0 | 0,76 → 0,81 | 136 → 72 | 13,5 → 21,5 | 9,2 → 8,7 |
| Konuşma, yüksek ses | 0 → 0 | 0,74 → 0,81 | 162 → 76 | 6,4 → 22,6 | 7,8 → 11,0 |

Ayrıntı, merkezdeki kenar keskinliğinin ortalaması; iç yapının seçilebilirliği için kaba bir ölçü. Görseller ve videolar sahibin değerlendirmesi için ayrı bir klasörde; depoda değiller.

## 7. Performans

Ölçüm WebKit önizlemesinde, 1350×1050 piksel çözünürlükte yapıldı; GPU'nun işi bitene kadar beklendi ve 10 karelik gruplar halinde iki tur alındı.

| | Önce | Sonra |
|---|---|---|
| Kare süresi (medyan) | 1,1–1,2 ms | 1,1–1,2 ms |
| Çizim çağrısı | 48 | 51 |
| Üçgen | 121.853 | 122.833 |
| Nokta | 4.200 | 4.330 |
| Çizgi parçası | 285 | 2.245 |

- Fark ölçüm gürültüsü içinde.
- Parçacık sayısı (4.200) aynı. Yeni kütüphane ya da yeni son işlem aşaması eklenmedi.
- Otomatik kalite düşürme, gizliyken çizmeme ve odak dışında 24 fps davranışları `CoreCanvas.vue`'da değişmedi. Düşük kalitede ağ 70 düğüme iniyor.
- **Ölçülmeyen:** Gerçek LAZIS penceresinde, Gemma, Whisper ve Yelda çalışırken FPS, GPU zamanı ve enerji tüketimi.

## 8. Testler

- `make check` geçti:
  - Python: 3497 test.
  - Arayüz: 196 test geçti, 1 test atlandı.
  - Bütünleşme: 8 test geçti, 3 test atlandı.
  - Rust testleri geçti; ruff, pyright, import-linter, vue-tsc ve clippy temiz.
- Yeni `lattice.spec.ts` (7 test):
  - Yapı her açılışta aynı.
  - Düğümler hacme yayılıyor.
  - Bütün düğümler bağlı; tekrar ya da uzun çizgi yok.
  - Çizgi sayısı sınırlı.
  - Ses hızla izleniyor, yavaş bırakılıyor; ses yokken hiçbir etkinlik yok.
  - Akış hızı durum ve gerçek sesle değişiyor.
  - Beş ana renk aynı.
- Gölgelendiricilerin görsel sonucu birim testlerle değil, görüntülere bakılarak değerlendirildi.

## 9. Açık eksikler ve riskler

- **Gerçek pencere:** Gerçek LAZIS penceresinde, gerçek mikrofon ve Yelda sesiyle görülmedi. Önizlemedeki ses eğrisi yapay.
- **Parlaklık:** Çekirdek öncekinden belirgin biçimde daha koyu ve sakin (merkez parlaklığı %30–55 daha düşük). Bekleme ve dinlemede tam ekranda daha küçük ve daha az baskın görünüyor. Sahip "güçlü" bulmazsa ayarlanacak değerler:
  - ağın dinlenme parlaklığı (`rest`)
  - kalbin boyu
  - iç katmanların büyütmesi (`INNER_SCALE`)
  - bloom
- **Doygunluk:** Düşünme durumunda ölçülen doygunluk biraz düştü (0,54 → 0,46); koyu ton turuncu-kahveye kaydı.
- **Çizgi kalınlığı:** WebGL çizgileri 1 piksel. Bağlantıların kalınlığı ekranın piksel yoğunluğuna bağlı; düşük kalitede ya da düşük piksel oranında daha ince görünebilirler.
- **Gövde kenarı:** Gövdenin arkasında kalan parçacıklar, gövdenin kenarında keskin biçimde kayboluyor; kabuğun kenar ışığı bunu büyük ölçüde örtüyor.
- **Ses verisi:** Önizleme ses eğrisi düzenli; gerçek konuşmanın ani yükselişleri denenmedi.
- **Önceki fazlardan süren borçlar:**
  - REL-001…004
  - sıkıştırma takılması
  - M2, M5 ve M7 ölçümleri
  - mikrofonun kayıtla doğrulanması
  - ekran kilidi algısı
- **Faz 15D (paketleme):** Bekliyor.
