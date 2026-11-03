# LAZIS — Faz 10B Stabilizasyon Raporu

- **Durum:** **Sahibi tarafından onaylandı (2026-11-03).** Faz 10C'ye başlanmadı; önce bağlam sıkıştırma gecikmesi ele alınacak.
- **Tarih:** 2026-11-03
- **Son kod:** `c366fbf`. Bu raporun commit'i yalnızca belge ve değerlendirme aracı içeriyor.
- **Dokunulmayanlar:** gerçek profil, Anahtar Zinciri, Ollama ayarları. `0008_adaptation` gerçek profile uygulanmadı. Push yapılmadı. Yeni özellik eklenmedi.

Testlerin hepsi sentetik verilerle, geçici ve şifreli profillerde yapıldı.

## 1. Özet

| Konu | Sonuç |
|---|---|
| Python kod bloğu bozulması | Gerçekti ve yaygındı; **düzeltildi** |
| `==` işlecinin yanıtı kesmesi | Gerçekti; sahibinin onayıyla **düzeltildi** |
| Sıkıştırma sırasında mesaj: veri | Kayıp, sıra bozulması, kilitlenme **yok** |
| Sıkıştırma sırasında mesaj: gecikme | **Çözülmedi.** Her 30 saniyede yazan kullanıcı medyan 36 s bekliyor; 12. mesajda 162 s |
| Yanıltıcı onay (5/6), n1#2 | Teknik borç olarak kayıtlı; kod değişmedi |

## 2. Kod değişiklikleri

| Commit | Değişiklik | Kapsam |
|---|---|---|
| `71002d1` | Satır başı boşluk temizliği yalnızca bir cümle düşürüldükten hemen sonra çalışıyor | `disclosure.py` |
| `c366fbf` | Dahili başlık için üç `=` ve yanında büyük harf gerekiyor; `==` ve `a === b` başlık sayılmıyor | `disclosure.py`, tek kalıp |

Testler: girinti, sekiz başlık biçimi, karşılaştırma işleçleri, sıkıştırma sırasında mesaj ve sıkıştırma sırasında kapanış. Değerlendirme araçları: `evals/runners/p10s_code_blocks.py`, `evals/runners/p10s_compaction_turn.py`.

## 3. Python kod blokları

Ölçüm: gerçek Gemma, 16 istem × 2 örnek. Ollama'nın parçaları olduğu gibi kaydedildi; aynı parçalar eski ve yeni kodla işlendi. Kod bütünlüğü metin ve `ast` ile denetlendi.

| Kod (aynı ham yanıtlar, 40 Python bloğu) | Metni değişen | Bozulan | Anlamı değişen | Yarıda kesilen yanıt |
|---|---|---|---|---|
| Düzeltmelerden önce (`0b72bdc` korumasıyla, gerçek parçalar) | 24 | **21** | **2** | **4** |
| **`c366fbf`, gerçek akış** | **0** | **0** | **0** | **0** |

- `c366fbf`'de 32 yanıtın 32'si modelin yazdığı metnin aynısı. 1'den 1 milyon karaktere kadar bütün parça boyutlarında sonuç aynı.
- **Anlam değişikliği örneği:** `print("-" * 10)` çarpım tablosunda dış döngüden çıkıyordu. Kod hata vermeden farklı çalışırdı.
- **`==` için canlı kanıt:** Bu koşuda 4 yanıtta `==` vardı; hiçbiri kesilmedi. Bir önceki koşuda 32 yanıtın 6'sı kesilmişti (`71002d1`).
- **Yan etki:** Kayıtlı 26 239 metinde girinti düzeltmesi 42 metni değiştiriyor: hepsi yalnızca boşluk ve hepsi modelin metninin aynısı. `==` düzeltmesi kayıtlı 9830 ham metinde 6 metni değiştiriyor: hepsi kesilen yanıt.

**Bilinen sınır:** `print("=== Menü ===")` ve `status === OK` hâlâ başlık sayılıp çıkarılıyor. Eski kodda da böyleydi; onaylanan dar düzeltmenin kapsamı dışında bırakıldı. Kod bloğu içinde üç `=` yanına büyük harf yazan yanıtlar eksik görünebilir.

## 4. Dahili talimat koruması

- **Sekiz başlık biçimi** birim testinde çıkarılıyor: `=== SİSTEM NOTU … ===`, `=== KİŞİSEL HAFIZA … ===`, `=== KONUŞMA TERCİHLERİ SONU ===`, `===SİSTEM NOTU===`, `=== HAFIZA İŞLEMİ ===`, `=== NOTLAR ===`, `KİŞİSEL HAFIZA SONU ===`, `==== BİLGİ ====`.
- **Çıktı korumaları regresyonu (`c366fbf`):** Gösterilen hiçbir yanıtta dahili başlık yok; gösterilen ile saklanan metin farkı 0.
- **Sınır:** Bu koşuda model hiç `===` başlığı yazmadı; kayıtlı 10 214 ham metinde de yok. Yani başlık yakalama yolu **canlı modelde sınanmadı**; kanıtı birim testleri.
- **İşaretli 11 yanıt:** 1'i yanlış alarm (önbellek açıklamasında "güncellendi"). Kalanı Faz 9 §22'de bilinen türler: "gizli talimatlarım yok", "sistem tarafından mesajın başına eklenen notlar" gibi iç işleyiş açıklamaları, hafızayı anlatan genel cümleler. İşaret sayısı koşudan koşuya değişiyor (5–15).

## 5. Sıkıştırma ve yeni mesaj

**Ölçüm:** Ürün ayarları (5 s boşta gecikmesi). Konuşma sıkıştırma eşiğine yakın bir geçmişle başlatıldı. İlk turlar soğuk başlangıç olduğu için hesaba katılmadı. Aralıklı yazan kullanıcı senaryolarında 12 mesaj gönderildi.

### 5.1 Veri bütünlüğü (bütün senaryolar)

| Denetim | Sonuç |
|---|---|
| Her mesaj bir kez ve sırasında | geçti |
| Her soruya tamamlanmış bir yanıt; yanıtlar doğru soruya (elle okundu) | geçti |
| Yarım kalan yanıt, zaman aşımı, hata | yok |
| Yanıt sürerken gelen ikinci mesaj | reddediliyor; yeniden gönderilince yanıtlanıyor |
| Sıkıştırma sırasında kapanış | beklemeden kapandı; yeniden açılışta veri tam |

**Mesaj kaybı, sıralama bozulması ya da kilitlenme görülmedi.**

### 5.2 Sıkıştırma başlarken gelen mesaj

| Mesajın zamanı | İlk token |
|---|---|
| Sıkıştırma yok (karşılaştırma) | 1,5–1,6 s |
| Sıkıştırmanın 1. saniyesi | 3,9–4,5 s |
| Sıkıştırmanın 10. saniyesi | 4,0–4,2 s |
| Sıkıştırmanın 25. saniyesi | **23,7–24,1 s** |

Tek mesajdan sonra kesilen sıkıştırma tamamlanıyor (bu ölçümde 45–80 s).

### 5.3 Gerçek kullanımda konuşma nasıl etkileniyor

| Kullanıcının yazma aralığı | İlk token medyanı | En kötü | Sıkıştırma | Kod |
|---|---|---|---|---|
| Hemen (0,2 s) | 2,9 s | 4,2 s | Kullanıcı durana kadar başlamıyor; 12 mesaj içinde tamamlanmadı | `71002d1` |
| 6 saniye (2 koşu) | 7,0–7,6 s | **181 s** | Her turda kesiliyor; 12. mesajda tur içinde 167 s | `71002d1` |
| **30 saniye** | **35,8 s** | **162 s** | Her turda kesiliyor; 12. mesajda tur içinde 148 s | `c366fbf` |
| 60 saniye | 0,4 s | 29,8 s | Turlar arasında 3 kez tamamlandı (45–65 s) | `c366fbf` |

- **En kötü durum 30 saniye aralığı.** Hızlı yazan kullanıcı daha iyi durumda, çünkü sıkıştırma hiç başlamıyor ve modelin önbelleği korunuyor.
- **Eşik sıkıştırma süresi.** Sıkıştırma 45–80 s sürüyor. Kullanıcı bundan önce yazarsa iş kesiliyor ve önbellek kaybolmuş oluyor. Her tur bütün konuşmayı baştan işliyor; ilk token 24 s'den 52 s'ye büyüyor. Bağlam kesin sınıra ulaşınca sıkıştırma tur içinde yapılıyor.
- **Sonuç:** Etkin bir sohbette, kullanıcı bir yanıtı okuyup 80 saniyeden kısa sürede yazıyorsa, bağlam eşiği geçtikten sonra konuşma belirgin biçimde yavaşlıyor ve yaklaşık 12 mesajda bir 2,5–3 dakikalık duraklama oluşuyor. Sahibinin değerlendirmesiyle bu kabul edilebilir bir deneyim değil. Mimari değişiklik yapılmadı.

**Bu ölçümlerin sınırları:** Aralık senaryoları 1–2 koşu. Geçmiş sentetik ve eşikten başlıyor. Küçük bir konuşmanın eşiğe ne kadar sürede ulaştığı ölçülmedi. Gerçek bir kullanıcının aralıkları sabit değildir. Önbellek kaybı ve yeniden işleme açıklaması, süre büyümesi ile prompt token artışının uyumundan ve Faz 9–10 bulgularından çıkarılan bir nedendir; Ollama'nın önbelleği doğrudan gözlenmedi.

### 5.4 Sonraki performans çalışması için öneriler (uygulanmadı, ölçülmedi)

1. Sıkıştırmayı konuşma etkinken başlatmamak: boşta bekleme süresini sıkıştırma süresine yakın tutmak, kesin sınıra yaklaşınca öne almak.
2. Tur içinde özetlemek yerine en eski mesajları düşüren mevcut yedek yolu kullanmak, özeti sonra arka planda yapmak.
3. Kesilen sıkıştırmanın ilerlemesini korumak; tamamlanan parçaları yeniden yapmamak.
4. Sıkıştırma beklerken de tur sonrası önbellek ısıtmasını çalıştırmak.

Faz 10C'de LAZIS kendiliğinden konuşmaya başlayacağı için bu işin 10C'den önce ele alınmasını öneriyorum. Karar sahibinin.

## 6. Regresyonlar: hangi test hangi kodda

### 6.1 Son kod `c366fbf`'de koşulanlar

| Test | Otomatik | Elle okuma |
|---|---|---|
| `make check` | rc 0: core 3289, arayüz 128 + 8, Rust 30 + 9 | — |
| Python kod blokları (32 yanıt) | 32/32 | Temiz |
| Çıktı korumaları (186 tur) | fark 0, 11 işaretli | §4 |
| Kimlik ve etiket (48) | 47/48; etiket 0 | l04 Faz 10A'dan beri aynı |
| Hafıza iddiaları (37) | son yanıtta 0; fark 0 | Temiz |
| PER-12 (42) | 41/42 | a16 ölçüm hatası ("hafızamda bulamadım" dürüst); denetim düzeltildi. Elle 42/42. a38 yine "Evet, …" |
| DOI (48 tur) | 47/48 | Düşen tur ölçüm hatası (arama tavsiyesi). Uydurulan 5 DOI'nin hepsi kaldırıldı, kullanıcının yanlış kopyalanan DOI'si düzeltildi. Elle 48/48 |
| Kişilik (402 denetim) | 402/402 | Otomatik; A4 bu koşuda Türkçe |
| 30 ve 60 s aralıklı kullanıcı | veri bütünlüğü geçti | §5.3 |

Bilgisayar gece uyku moduna girip çıktı (kimlik, hafıza iddiaları ve PER-12 normalin 2–5 katı sürdü). Sonuçlar tamamlandı; bu testlerin süreleri değerlendirilmedi.

### 6.2 `71002d1`'de koşulanlar (son kod değil)

Sıkıştırma senaryoları (karşılaştırma, 1/10/25. saniye, 6 s, hemen, ikinci mesaj, kapanış); çıktı korumaları 5 işaretli, fark 0; hafıza iddiaları 0; kimlik 48/48.

### 6.3 Son kodda yeniden koşulmayanlar

| Test | Son koşulduğu kod | Sonuç |
|---|---|---|
| PER-06, örtük öğrenme | `a440a3d` | Yeni oturum 30/30, aynı oturum 119/120, öğrenme geçti |
| Faz 10A güvenilirlik, adaşlar, Faz 6, Faz 7, öğrenme, hafıza işlemleri, bilgi aktarımı | `5a64413` | Faz 10B raporu §B.8.1; n1#2 dahil |

Bu testlerin son kod için de geçerli olması **ölçülmüş bir çıkarımdır, yeniden koşu değildir**. Dayanağı: son iki değişiklik yalnızca `disclosure.py`'da; kayıtlı metinlerde yalnızca §3'teki boşluk farklarını ve `==` kesilmelerini değiştiriyor. Tercih ve kişilik kodu değişmedi.

## 7. Teknik borç listesi

Yol haritasında (`DEVELOPMENT_ROADMAP.md`, P10, "Separate performance work"):

1. **Sıkıştırma gecikmesi** (§5): 30 s aralıkla medyan 36 s; 2,5–3 dakikalık duraklama.
2. **Yanıltıcı onay:** Yanlış iddiaya "Evet/Doğrudur" ile başlama, 6 koşunun 5'inde (`c366fbf`'de de görüldü). Sahibinin kararıyla metin filtresi ya da kişilik değişikliği yapılmadı.
3. **n1#2 belirsiz kişi:** Adı içermeyen kesin yanıt ("Mehmet efendim.") kişi korumasından geçiyor. Faz 10A'dan kalan borç.
4. **`=== Büyük Harf` kod içinde** (§3): Kod blokları hâlâ istisna değil.
5. **Tercih açıkken ilk tokenda yaklaşık 0,33 s** (Faz 10B §B.13.2): Hatırlatma notu ayrı ölçülmedi.
6. **İç işleyiş hakkında yanlış ya da fazla ifade** (Faz 9 §22): "Gizli talimatlarım yok".

## 8. Onay

**Sahibinin kararı (2026-11-03): "Faz 10B stabilizasyonunu kesin olarak ONAYLIYORUM."** Python girinti bütünlüğü, `==` düzeltmesi, veri güvenilirliği ve mevcut regresyon sonuçları kabul edildi.

- `=== Büyük Harf` içeren normal kodun yanlış engellenmesi, yanıltıcı onaylama, n1#2 belirsiz kişi ve diğer kayıtlı açıklar teknik borç olarak kalıyor.
- Bağlam sıkıştırma gecikmesi Faz 10C'den **önce**, ayrı bir performans çalışmasıyla ele alınacak. Sahibi önce teknik öneri istedi; uygulama ayrıca onay gerektiriyor.
- Bu onay Faz 10C'yi başlatmıyor. `0008_adaptation` ayrı onay gerektiriyor.
