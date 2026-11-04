# LAZIS — Sınır 8 ile 40 Mesajlık Uzun Konuşma Testi

- **Tarih:** 2026-11-04, 12:20–13:20 (bir koşu, 40 mesaj, 60 s aralık, öğrenme açık)
- **Durum:** Tamamlandı. O tarihte gerçek servise uygulanmamıştı; sonraki durum için [MEMORY_DIAGNOSIS_REPORT.md](MEMORY_DIAGNOSIS_REPORT.md), Kapanış.
- **Ortam:** Yalnızca geçici Ollama süreci (port 11499). Ürün kodu, gerçek profil, gerçek servis ayarları, model, hafıza kuralları ve migration'a dokunulmadı.
- **Ham veri:** `evals/reports/phase10/perf/long-checkpoints/`. Araç: `evals/runners/p10p_long_checkpoints.py`.

## 1. Sonuç

| Konu | Değerlendirme |
|---|---|
| **Bellek** | **Çok iyi.** 59 dakikada hiç uyarı yok, swap artışı yok, model süreci en çok 5,3 GB |
| **Yanıt gecikmesi** | **Değişmedi.** Sıkıştırma beklemeleri taban çizgisi kadar kötü (en kötü 175 s). Sınır bunları çözmez, kötüleştirdiğine dair işaret de yok |
| **Bilgi koruma** | **Açık soru.** Bu koşuda, 9 taban çizgisi koşusunda hiç görülmeyen bir kayıp oldu. Sınırla bağı gösterilemedi ama dışlanamıyor |

**Değerlendirmem:** Sınır 8 bellek sorunu için uzun konuşmada da uygun görünüyor. Ancak bilgi kaybı açıklığa kavuşmadan gerçek servise uygulanmasını önermiyorum.

## 2. 60 saniyelik taban çizgisiyle karşılaştırma

Taban çizgisi sınır 32 ile çalıştı. Koşullar farklı: "Dolu" koşular 25 gündür açık bir Mac'te, 8–10 GB başlangıç swap'ıyla; "Boş" koşu uygulamalar kapalıyken. Bu koşuda günlük uygulamalar Codex dahil açıktı.

| | **Sınır 8** | Dolu 1 | Dolu 2 | Boş |
|---|---|---|---|---|
| Diğer programlar | 12,6–14,1 GB | Daha yüksek | Daha yüksek | 6,0–7,3 GB |
| Uyarıda geçen örnek | **0 / 705** | 287 / 775 | 548 / 705 | 224 / 703 |
| En yüksek baskı | **Normal** | Uyarı | Uyarı | Uyarı |
| Başlangıç swap → tepe | **2,4 → 2,4 GB** | 7,9 → 15,9 GB | 10,0 → 18,9 GB | 0,3 → 3,9 GB |
| Swap'a yazılan sayfa | **21 137** | 1 475 271 | 3 172 911 | 412 243 |
| Sıkıştırılmış bellek, tepe | **5,0 GB** | 7,0 GB | 7,0 GB | 8,0 GB |
| Model süreci ayak izi, tepe | **5,3 GB** | Ölçülmedi | Ölçülmedi | 13,0 GB |
| Medyan ilk token | 1,14 s | 3,61 s | 1,41 s | 1,24 s |
| En kötü ilk token | 175,4 s | 51,4 s | 192,7 s | 180,3 s |
| 15 s üstü mesaj | 9 | 19 | 10 | 12 |
| Tamamlanan sıkıştırma (s) | 54 + 162 | 181 | 51 + 178 | 166 + 59 |
| Mesaj bütünlüğü, kayıt = gösterilen | Tam | Tam | Tam | Tam |
| Kırpma, kapsanmayan geçmiş | Yok | Yok | Yok | Yok |
| Sorular (otomatik) | **7 / 10** | 10 / 10 | 10 / 10 | 9 / 10 |

**Bellek farkını yorumlarken:** En adil karşılaştırma "Boş" koşu. O koşuda programlar yaklaşık yarı yarıyaydı, yine de uyarı vardı; bu koşuda yoktu. Yine de tek koşudur.

## 3. Bellek ve checkpoint davranışı

- **Sınırın kanıtı:** Ollama kaydı "of 8"; süreç ortamında `LLAMA_ARG_CTX_CHECKPOINTS=8`; en yüksek numara 7. Gerçek serviste bu ayar yok.
- **Zaman içinde:** Ayak izi 3. mesajdan sonra 5,3 GB'ta sabitlendi. Sıkıştırmalar sırasında 3,2–3,9 GB'a indi, sonra 5,0 GB'ta sabitlendi. Büyüme yok.
- **Boşta:** 2 dakikada ayak izi aynı kaldı (4,9 GB).
- **Checkpoint sayımı:** 299 oluşturma, 208 geçersiz kılınma, 75 yakınlık silmesi, 9 yerine yazma, 7 canlı; hesap tutuyor. "En eskiyi sil" yine 0.
- **Yeniden kullanım:** 33 geri dönüş. 150 istemin 22'sinde tam yeniden işleme oldu; **hepsi sıkıştırma dönemlerinde.** Sıkıştırma dışında ilk token 0,5–1,5 s.
- **Prompt işleme toplamı:** 190 564 token, 729 s. Taban çizgisinde bu kayıt yok, karşılaştırılamaz.
- **Ekran:** 12:50:08 kapandı, 12:50:25 açıldı (17 s), 13:00:43 kapandı. Açılışta kablolu bellek +1,3 GB, sıkıştırılmış +2,1 GB; **baskı normal kaldı, swap artmadı.** Tetiklemedim. Kısa ve tek bir olay; 13 dakikalık kapanmadan sonraki uyanmayı temsil etmez.
- **Sistem yanıtı:** Program başlatma en çok 5,6 ms, disk yazma 1,4 ms. Hiç işaret yok.

## 4. Sıkıştırma ve ilk token

| Dönem | Mesaj | İlk token |
|---|---|---|
| Sıkıştırma öncesi | 2–18 | 0,6–1,5 s |
| İlk sıkıştırmadan hemen sonra | 19 | 12,8 s |
| Sonra | 20–22 | 0,5–0,7 s |
| **Kesilen sıkıştırma dönemi** | **23–30** | **25,6 → 50,5 s** |
| **Tur içinde sıkıştırma** | **31** | **175,4 s** |
| Sonra | 32–40 | 0,6–1,1 s |

- **Boşa giden iş:** 13 sıkıştırma çağrısının 9'u 55 s sonra sonraki mesajla kesildi, yani yaklaşık 495 s model zamanı ilerleme üretmedi.
- **Sonra:** Bağlam 13 971 tokene çıktı ve 3 parça tur içinde özetlendi.
- Bu tablo taban çizgisiyle neredeyse aynı (Boş: 26,9 → 53,2 s, ardından 180,3 s). **Bu, C'nin konusudur; sınırın sonucu değildir.** C hâlâ gereklidir.
- **Çıktı sınırı sorusu çözüldü:** Tamamlanan 4 çağrının 3'ü tam 1 200 tokende durdu (`summary_max_tokens`), biri 1 153. Yani 60–64 s'lik süre gerçekten çıktı sınırına dayanıyor ve özet çıktısı sessizce kesiliyor. Taban çizgisi bu sayıyı kaydetmediği için sınır 8'e özgü sayılamaz.

| Model süresi | Çağrı | Süre |
|---|---|---|
| Yanıt | 40 | 837,5 s |
| Sıkıştırma | 13 (4 tamam) | 710,9 s |
| Öğrenme | 33 | 349,6 s |
| Yeniden ısıtma | 64 | 74,7 s |

**Öğrenme:** 33 çağrının 22'si hiçbir şey çıkarmadı (her biri yaklaşık 8,7 s, toplam yaklaşık 192 s, öğrenme süresinin %55'i). 12:45–13:07 arasında öğrenme hiç çalışmadı, sıkıştırma önceliği yüzünden bekledi; iş sonunda bitti (40/40).

## 5. Bilgi koruma ve doğruluk

### Yeni bulgular (bu koşuda; 9 taban çizgisi koşusunda görülmedi)

| Bulgu | Ayrıntı |
|---|---|
| **`20 bin` kaybı** | İlk özette "Taşınma Planı" gibi genel bir maddeye dönüştü, hiçbir sürümde yok. Elle sayım: 18/19; taban çizgisinin üç 60 s koşusunda 19/19 |
| **`nakliye` kararı kaybı** | 1. sürümde var, **2. sürümde "Kararlar" bölümünün tamamı gitti** (`dropped: 0`, 21 → 17 madde). 9 koşunun hepsinde son özette vardı |
| **Yanlış yönlendirme yok ama yanıt yok** | "Nakliye firması tutmaya karar vermiş miydik?" → "hatırlamıyorum". 9 koşunun hepsinde doğru yanıtlandı. Özgün mesaj kayıtlı ama özette yok; öğrenme onu inceleme kutusuna koyduğu için etkin hafızada da yok |
| **Anlam değişimi** | Özgün "Planlama toplantısı", 4 sürümde de "Taşınma planı toplantısı" oldu. Son özetlerin hiçbirinde daha önce görülmedi. Hafıza kaydı doğru ("Planlama toplantısı") |

**Sınırla bağı:** Gösterilemedi. Özet isteği checkpoint'e bağlı değil; checkpoint yalnızca hesaplanmış durumu saklar ve metin üretim koşullarını değiştirmesi beklenmez. Ayrıca yanıtlar her koşuda farklı olduğu için özet girdisi de farklıdır. Ama bu bir akıl yürütmedir: 1/10 koşu, tek koşudan neden çıkarılamaz. **Bu yüzden bunu "sınırla ilgisiz" diye kapatmıyorum; regresyon adayı olarak tutuyorum.**

**Çıktı sınırıyla bağı:** 2. sürüm çıktısı 1 200 tokende kesildi. Ancak o sürümde son bölüm olan LAZIS notları duruyor, kararlar yok; bu, yalnızca sondan kesilme ile açıklanmıyor. Ham çıktı saklanmadığı için kesin değil.

### Önceden bilinen hatalar

- **REL-001:** Mehmet kaydı yine kesin: "10 Kasım'da İzmir'e gidecek." Artık 10 koşunun 6'sında. Özet ve yanıt belirsizliği koruyor.
- **REL-002:** Mehmet sorusu doğru yanıtlandı, özet satırı 4 sürümde de duruyor. Bu koşuda yinelenmedi. Ama "Araba kiralayacak mıyız?" sorusu "hatırlamıyorum" yanıtı aldı, oysa hem özette hem hafızada otobüs bilgisi var. Bu, kayıtlı bilgiyi yanıtta kullanmama sınıfından; 9 koşuda benzeri bir kez görülmüştü (30 s, koşu 2).
- **REL-003:** Yukarıdaki iki kayıp bunun yeni örnekleridir, `dropped: 0`. Tekrarlı dolgu yokken oluştu. Ayrıca genel sorular da 5 madde ile özette yer kapladı (17 maddenin 5'i). Bu, dolgu etkisinin yalnızca test yapaylığı olmadığını gösteriyor.

### Sorular, elle okuma

Otomatik 7/10, **elle 8/10.** Mehmet yanıtı ("gitme ihtimali var") belirsizliği koruyor; denetleyici "ihtimal" kelimesini tanımıyor. Gerçek hatalar: Nakliye ve Araba.

**Kayıt güvenliği:** 80 mesaj sırasında ve birer kez; kayıt = gösterilen; 4 özet sürümü saklı; kırpma yok. Konuşma verisi değiştirilmedi.

**Sonradan:** Çoklu sıkıştırma karşılaştırması 50/50 aynı özet verdi; sınır 8 şüpheli olmaktan çıktı: [MULTI_CYCLE_LIMIT8_REPORT.md](MULTI_CYCLE_LIMIT8_REPORT.md).

## 6. Sınırlar

Tek koşu. Taban çizgisi koşulları farklı. Kesinti yalnızca 60 s aralıkla sınandı. Bilgi ölçümü 19 kelime ve elle okuma; iddia seti henüz yok. Uzun süreli kullanım ve model boşaltma sınanmadı. 13 dakikalık ekran kapanması sonrası uyanma sınanmadı.

## 7. En düşük riskli sonraki adım (onay bekliyor, başlatılmadı)

**Çoklu sıkıştırma kalite testi, sınır 8, geçici süreç (yaklaşık 46 dakika).** Bu test öğrenme kapalı, kullanıcı yanıtı konuşma sonunda ve özet tohumu sabit. Girdiler taban çizgisiyle aynı olduğundan, sınırın özetleri etkileyip etkilemediğini en doğrudan bu gösterir. 62→56/64 sınırıyla ölçülür; regresyon adayını ayırır.

Sonra gerekirse, ayrı onayla: aynı uzun konuşmanın tekrarı (bu kez özet ham çıktısı test kaydına alınarak). Gerçek servis, ancak bunlardan sonra ve ayrı onayla.
