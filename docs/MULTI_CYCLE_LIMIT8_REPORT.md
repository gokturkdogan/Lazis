# LAZIS — Sınır 8 ile Çoklu Sıkıştırma Kalite Karşılaştırması

- **Tarih:** 2026-11-04, 15:22–16:08 (46 dakika, 50 sıkıştırma, hiçbiri başarısız değil)
- **Durum:** Tamamlandı, otomatik durma olmadı. Gerçek servise ayar uygulanmadı; ürün kodu değişmedi. Karar sahibinde.
- **Ortam:** Yalnızca geçici Ollama süreci, öğrenme kapalı, sentetik veri, geçici profil.
- **Ham veri:** `evals/reports/phase10/perf/cycles-cp8/`. Araçlar: `p10p_cycles_checkpoints.py`, `p10p_cycles_limit_analysis.py`.

## 1. Sonuç

**Sınır 8 özetleri değiştirmiyor: 50 özetin 50'si sınır 32'deki eski testle bayt bayt aynı.** Bilgi kaybının nedeni checkpoint sınırı değil, özet yeniden yazımının kendisi.

**Öneri: Checkpoint bellek teşhisini kapatalım.** Sıradaki iş hafıza güvenilirliği, ardından C.

## 2. Sınır 32 ile karşılaştırma

| | Sınır 32 (eski) | Sınır 8 |
|---|---|---|
| Korunan bilgi, sürüm 1–5 (64 üzerinden) | 62, 61, 59, 59, 56 | **62, 61, 59, 59, 56** |
| Sessiz kayıplı konuşma, sürüm 1–5 | 0, 1, 3, 3, 4 | **0, 1, 3, 3, 4** |
| Özet metni | | **50/50 bayt bayt aynı** |
| Sıkıştırma süresi | 34–64 s | 34–63 s |
| Sorular | 28/32 | 28/32; **aynı 4 soru geçemedi** |
| Mehmet belirsizliği | Korundu | Korundu |
| Diğer programlar | 9,7–11,5 GB | **14,0–16,3 GB** (Codex, Cursor açık) |
| Model süreci ayak izi, tepe | 5,3 GB | 5,2 GB |
| Uyarı | Yok | 243 s, 10 kısa dönem, en uzunu 48 s |
| Swap artışı | Yok | Yok |
| Canlı checkpoint, en çok | Ölçülmedi | 5 |

**Karşılaştırma sınırları:**

- Program belleği bu koşuda 4–5 GB daha yüksekti. Sınır 8'deki kısa uyarılar büyük olasılıkla bundan geliyor; bu ayrı sınanmadı.
- Bu test çok az çağrı yaptığı için bellek birikimini sınamaz (iki koşuda da yaklaşık 5,3 GB). Bellek kazancının kanıtı uzun konuşma testidir.
- Checkpoint sınırına bu testte hiç varılmadı (en çok 5 canlı, 0 geri dönüş). Ama özet istemleri her seferinde baştan işleniyor. Sınırın özete etki edecek bir yol zaten yok.

## 3. Beş soru

### Soru 1: Sınır 8 bilgi korumayı değiştiriyor mu, yoksa doğal değişkenlik mi?

**Değiştirmiyor.** Aynı girdi ve tohumla 50 özet bayt bayt aynı çıktı.

Değişkenliğin nereden geldiği de netleşti:

- **Özetler bu koşullarda belirlenimci:** aynı girdi, aynı tohum, aynı çıktı.
- **Yanıtlar değil:** Aynı soruların yanıtları kelime kelime farklı. Yanıt isteklerinde sabit tohum yok.
- **Küçük girdi farkı büyük sonuç doğuruyor:** Tohum 7'de 1, tohum 11'de 7 bilgi kaybı.

**Uzun konuşmadaki `nakliye` kaybı için sonuç:** Orada özetin girdisinde modelin yanıtları da var ve yanıtlar her koşuda değişiyor. Yani her uzun konuşma farklı girdiyle özetleniyor. Kaybın en olası açıklaması bu doğal değişkenlik ve zaten bilinen REL-003. **Regresyon adayını sınırla ilgili olmaktan çıkarıyorum.** Kesin kanıt değil: uzun konuşmanın kendisi tekrarlanmadı.

### Soru 2: 1 200 tokenlik sınırın rolü ne?

**İki ayrı kayıp mekanizması var. Sınır yalnızca birini açıklıyor.**

| | Sınıra ulaşan yazımlar | Ulaşmayan yazımlar |
|---|---|---|
| Yazım sayısı | 16 | 24 |
| Kelime denetiminde kayıplı yazım | 1 (%6) | 3 (%13) |
| Kaybolan bilgi (kelime) | 1 | **5** |
| Elle: gerçek bilgi içeren kayıp satır | 4 | 6 |
| Sondaki bölüme ulaşan | 3 / 16 | Hepsi |

**Mekanizma A: Bütçe varken model bilgiyi atlıyor (ana neden).** 6 kelime kaybının 5'i böyle: `vejetaryen` (739 token), `cuma` (601), `Kaş`, `Mavi Koy`, `35 bin` (593). Sınırın yarısındayken oldu. **Sınırı yükseltmek bunları çözmez.** Uzun konuşmadaki `nakliye` de büyük olasılıkla bu sınıfta: o özette son bölüm duruyor ama kararlar yok, ve 50 ham çıktının hepsi aynı bölüm sırasını izliyor.

**Mekanizma B: Çıktı sondan kesiliyor ve sessizce kurtarılıyor.** 16 özet (`done_reason: length`) kesildi, hiçbir yerde bildirilmedi. Model bölümleri sabit sırada yazıyor:

`goals → topics → decisions → open_questions → constraints → people → instructions → assistant_notes`

Yani önce sorular yazılıyor, kişiler ve talimatlar sonra. Kesilen 16 özetin:

- 12'si **kullanıcı talimatlarına,**
- 9'u **kişilere,**
- 8'i **önemli kısıtlamalara** hiç ulaşamadı.

Bunların yerini çoğunlukla tekrarlı dolgu soruları aldı (bölümde 8'e kadar madde). "Ayşe: kız kardeşi" bu yüzden kayboldu (iki tohumda da 3. sürümde). Kelime denetimi bunu saymıyor.

**Ek:** `8 bin` ilk bölümdeydi, yani kesilme değil; 1 200'e ulaşan bir yazımda atlandı. Çıktı dolu olduğunda modelin önceliklendirmesi mi yoksa başka bir etki mi olduğu bilinmiyor.

**Çıktıyı ne dolduruyor:** Sınıra ulaşan özetlerde maddelerin yarısından fazlası (17,1'in 9,6'sı) yalnızca dolguya ait. Atıflar çıktının %12'si (en çok %19), alıntılar %26'sı.

**Çıktı sınırını yükseltmeyi şu an önermiyorum:** Yalnızca B'ye yardım eder, A'ya etmez. Her 300 token sıkıştırmaya yaklaşık 10 s ekler (ölçülen 34,4 ms/token; hesap), bu da C'nin çözmek istediği beklemeyi büyütür.

### Soru 3: Özet talimatı ve koruma mekanizmasındaki eksikler

**Talimat (`SUMMARY_INSTRUCTIONS`):**

1. **"Koru" yalnızca rica:** Madde 9 önceki maddeleri korumayı istiyor, ama önceki özet her seferinde modele yeniden yazdırılıyor. Kod kopyalamıyor.
2. **Çelişen istekler:** "Önemli bilgiler önce" diyor, ama şema soruları kişilerin ve talimatların önüne koyuyor. Model şema sırasını izliyor.
3. **Önem ölçütü yok:** Genel sorular ve bilgilendirme yanıtları, kullanıcının kendisine dair bilgiyle aynı bütçeyle yarışıyor. Uzun konuşmada 17 maddenin 5'i genel bilgiydi.
4. **"Bölümde en çok 6 madde" uygulanmıyor:** 8 maddeye kadar görüldü, kod denetlemiyor.
5. **Atıflar sürekli büyüyor:** Korunan her madde refs'i yeniden yazıyor.

**Koruma (kod):**

1. **`dropped_items` kaybı ölçmüyor:** Yalnızca kanıt denetiminden geçemeyeni sayıyor.
2. **Sürümler karşılaştırılmıyor.**
3. **Kesilme görünmüyor:** `done_reason` kullanılmıyor, kurtarma kaydı yok.
4. **Anlam denetlenmiyor:** `text` ve `certain` alıntıyla karşılaştırılmıyor. "Taşınma planı toplantısı" bu yüzden geçti.
5. **Madde metni 300 karakterde sessizce kesiliyor.**

**Bu testte iyi olan:** Ham çıktıda aynı alıntılı maddenin kesinliği hiç değişmedi; belirsizlik kelimesi içeren alıntı `certain: true` yazılmadı. Ancak belirsiz bilgi örneği çok az, güçlü kanıt değil.

### Soru 4: Bellek kazancını koruyan en düşük riskli düzeltmeler

Hiçbiri yapılmadı; her biri ayrı onay ister. Checkpoint ayarıyla etkileşmezler. Riski en düşükten yükseğe:

| # | Düzeltme | Çözdüğü | Risk | Ölçüm |
|---|---|---|---|---|
| 1 | **Görünürlük:** Kesilmeyi, kurtarmayı ve sürümler arası kaybolan maddeleri kaydetmek | Sessizlik | Çok düşük; davranış değişmez | Özet istemi aynı kalır |
| 2 | **Küçük iddia seti** (planlı, 20 iddia, model yok) | Ölçüm | Çok düşük; yalnızca değerlendirme | Saklı özetlerle |
| 3 | **Bölüm sırası:** Kişiler, kısıtlamalar, talimatlar ve kararlar sorulardan önce | B | Düşük; özet biçimi değişir | Çoklu test, 62→56 sınırı |
| 4 | **Kullanıcı maddelerini kodla taşımak:** Önceki özetteki kullanıcı maddesi yeni özette yoksa kod onu geri ekler; yalnızca kullanıcı onu değiştirdiyse düşer | A | Orta; özet büyüyebilir, eski bilgi kalabilir | Önce saklı özetlerde modelsiz deneme, sonra çoklu test |
| 5 | **Genel bilgi yanıtlarını özette sınırlamak** | Yer kapma | Orta; talimat değişir | Çoklu test |

**Öncelik önerim:** 1, 2, 3, ardından 4. Kaybın ana nedeni A olduğu için asıl etkiyi 4 yapar; 1–3 onu güvenle ölçülebilir kılar.

### Soru 5: C'den önce kritik bir güvenilirlik engeli var mı?

**Evet. Sessiz bilgi kaybı (REL-003) C'den önce ele alınmalı.**

- **C bu kaybı ne yaratıyor ne çözüyor.** Hızı düzeltir; önemli bilgi yine sessizce kaybolur.
- **Sıra önemli:** C'nin kabulü "taban çizgisinden kötü değil" ölçütüne bağlı. Düzeltme 3–4 özet davranışını değiştirir. C önce gelirse taban çizgisi sonra geçersiz olur ve C yeniden ölçülmek zorunda kalır.
- **Görünürlük olmadan C'nin kabulü zayıf kalır:** Kelime denetimi gerçek kayıpları kaçırıyor.

**Önerilen sıra:** Düzeltme 1–2, ardından 3–4, ardından C. Gerçek profile geçiş için REL-001 de ayrıca engeldir.

## 4. REL kayıtları

- **REL-001:** Bu testte öğrenme kapalı, ölçülmedi. Özet belirsizliği korudu. Açık.
- **REL-002:** Hatırlama bu testte ölçülmedi. Mehmet sorusu iki tohumda da doğru. "Restoran" sorusunda özette olan vejetaryen bilgisinin yanıtta kullanılmaması iki sınırda da aynı. Açık.
- **REL-003:** Sınırdan bağımsız olduğu gösterildi. Neden iki mekanizmaya ayrıldı (A, B). Yeni kayıp yok, çünkü özetler aynı. Açık, öncelikli.

## 5. Checkpoint teşhisi için öneri

**Teşhisi kapatalım.** Gerekçe:

| Soru | Yanıt | Kanıt |
|---|---|---|
| Neden büyüyordu? | Context checkpoint'ler | Bellek teşhisi |
| Sınır 8 belleği tutuyor mu? | Evet; 5,3 GB, uyarı ve swap artışı yok | Uzun konuşma |
| Hızı bozuyor mu? | Hayır | Kısa ve uzun testler |
| Özetleri değiştiriyor mu? | Hayır; 50/50 aynı | Bu test |
| Yanıt kalitesini bozuyor mu? | Görülmedi; aynı 4 soru geçemedi | Bu test |

**Bu, bütün bellek sorununun çözüldüğü anlamına gelmez:**

- Program belleği 16 GB'a yaklaşınca kısa uyarılar yine görüldü.
- 13 dakikalık ekran kapanmasından sonraki uyanma ve 30 s aralıklı kesintiler sınırla ölçülmedi.

**Gerçek servis:** Sınır 8, ölçtüğümüz her konuda sınır 32'den iyi ya da onunla eşit. Gerçek servis bu sırada 32 ile bellek riski taşıyor. Ayrı onayınızla `scripts/ollama-agent.sh` üzerinden uygulanmasını öneriyorum; geri dönüşü tek ayar. Uygulanmadı.
