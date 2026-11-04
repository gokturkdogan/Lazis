# LAZIS — Güvenli Bilgi Koruma: Uygulama Planı

- **Durum:** Yalnızca öneri. Ürün kodu yazılmadı. Yön kabul edildi, uygulama onaylanmadı.
- **Dayanak:** [SAFE_CARRY_DESIGN.md](SAFE_CARRY_DESIGN.md). Simülasyondaki sıfır kayıp Gemma başarısı sayılmaz.
- **Karar gereken:** Yalnızca §2'deki 1. adım.

## 1. Tasarımda değişenler

Sahibin kararları tasarımı üç noktada değiştiriyor:

1. **Taşınan bilgi "güncel" diye sunulmaz.** Simülasyondaki "Kararlar" gibi başlıklar kalkar. Her satır, kullanıcının ne zaman ne dediğini anlatır: `#5'te kullanıcı: «…»`. Değişiklik yakalanamasa bile eski söz kesin güncel gerçek gibi görünmez.
2. **Kod hiçbir bilgiyi kapatmaz, silmez, kesinleştirmez.** Değişiklik algılayıcısı yalnızca "değişmiş olabilir" notu ekler. Güvenilirliği yeterli olmadan bu not da gösterilmez.
3. **Algılayıcı ilk adımda yok.** 17 değişiklikten 4'ünü kaçırması ve 6 ilgisiz örnekten 3'ünde yanlış alarm vermesi kabul edilmedi. Ayrı adımda, ayrı kabul ölçütüyle ele alınır.

## 2. Önerilen ilk küçük adım

**Taşıma defterinin saf işlevleri ve testleri. Hiçbir yere bağlı değil, davranış değişmez.**

- **Dal:** `main` üzerinden yeni `experiment/rel003-carry`.
- **Yeni dosyalar:** `core/src/lazis/conversation/carry.py` ve birim testleri. Tahmini 120–150 satır.
- **İçerik:**
  - `CarriedItem`: mesaj numarası, özgün cümle, cümle özeti, bölüm, kesinlik, kaynak, ilk sürüm, güncelleme bağlantıları.
  - `bind_source`: doğrulanmış alıntıdan saklı mesajdaki özgün cümleyi bulur; bulamazsa bağlamayı reddeder.
  - `merge`: önceki defter ile yeni doğrulanmış maddeleri birleştirir.
  - `check_attribution`: maddedeki ad, sayı ve tarihin kaynak cümlede olup olmadığına bakar.
- **Bilerek dışarıda:** `engine.py`, `prompts.py`, şema, kanıt denetimi, migration, hafıza, değişiklik algılayıcısı, bütçe, geri getirme, model çağrısı.

**Neden bu kadar küçük:** Sekiz şartınızın çoğu bu katmanda, modelsiz sınanabilir. Bir hata ürünü etkilemez ve geri alması bir dalı bırakmak kadar kolaydır.

**Bilinen sonuç:** Bu adım tek başına yayına uygun değil. Algılayıcı olmadığı için simülasyonda eski ifadeler işaretsiz görünecek (S3: 17 ölçüm). Bu yüzden bağlanmıyor.

### 1. adımın kabul kriterleri

| # | Kriter | Sınama |
|---|---|---|
| 1 | Taşınan her cümle saklı mesajın **birebir** parçasıdır | 88 saklı çıktı ve özellik testi; istisna 0 |
| 2 | Değiştirilmiş alıntı özgün cümleye döner; belirlenemiyorsa reddedilir ve sayılır | "…görüşme yapılacak" örneği dahil |
| 3 | Kanıt denetimi gevşemez | `verify_items` ve eşik farksız |
| 4 | Kesinlik birleştirmede hiç değişmez; çekinceli cümle kesin olamaz | Art arda birleştirme testi |
| 5 | Kapatma, silme veya kesinleştirme yolu yoktur | Her birleştirmeden sonra önceki maddelerin tümü aynen durur |
| 6 | Kaynak, kesinlik ve bağlantılar birleştirmelerde korunur | 10 ardışık birleştirme |
| 7 | LAZIS'in sözü deftere girmez | LAZIS cümlesini kullanıcı gibi gösteren çıktı dahil |
| 8 | Yanlış kişi ve yanlış olay kabul edilmez | §3'teki bozuk çıktı seti |
| 9 | Sır ve kural geçersiz kılma denemeleri taşınmaz | Mevcut `secret_kind`, `instruction_like` |
| 10 | Girdi değişmez, çıktı aynı girdide aynıdır | Eski özet nesnesi değişmiyor; iki koşu aynı |
| 11 | Ürün davranışı değişmez | `carry.py` hiçbir yerden çağrılmıyor; `prompts.py` `c366fbf` ile aynı; `make check` geçer |

Sonuç raporu 88 saklı çıktıdaki sayıları, her gerilemeyi tek tek ve reddedilen maddeleri içerir. Model çağrılmaz.

## 3. Sekiz şartın karşılığı

| Şart | Karşılığı | Adım | Kanıt |
|---|---|---|---|
| 1. Alıntılar bozulmaz | Gösterilen metin her zaman saklı mesajdan alınır | 1 | Kriter 1–2 |
| 2. Eski karar kesin güncel görünmez | "Güncel" başlığı yok; her satır zamanıyla kullanıcı sözü | 1, 3 | Bilgi ölçümü modelsiz; sonucu Gemma testinde |
| 3. Yanlış kapatma veya kesinleştirme yok | Kodda bu yol yok; algılayıcı yalnızca not ekler | 1, 2 | Kriter 4–5 |
| 4. Kaynak ve ilişki korunur | `CarriedItem` alanları | 1 | Kriter 6 |
| 5. LAZIS sözü kullanıcıya mal edilmez | Yalnızca kullanıcı mesajından bağlanır | 1 | Kriter 7 |
| 6. Yanlış kişi veya olay | `check_attribution` ve ayrı test | 1, 5 | Aşağıda |
| 7. Hafıza ile özet çelişmez | Defter hafızaya yazmaz; çelişki iki kaynağı adıyla gösterir | 5 | Çelişki senaryosu |
| 8. Bağlamdan çıkan silinmez | Yalnızca istemden çıkar; defter ve mesajlar kalır | 4 | Sayım ve geri getirme |

**Şart 6'nın testi.** Modele hiç gerek kalmadan, elle bozulmuş çıktılar kullanılır:

- Yanlış kişi: `Burak vegan`, alıntı "Eşim Derya vegan…"
- Yanlış olay: tatil bütçesi, alıntı taşınma bütçesinden
- Benzer ad: `Ali Bey'in kedisi`, alıntı "Komşum Ali'nin…"
- Yanlış mesaj: doğru bilgi, başka mesajın alıntısı
- Yanlış sayı: `30 bin`, alıntı "25 bin"
- LAZIS sözü: kullanıcı kaynağı yazılmış LAZIS cümlesi

**Sınırı:** Bu set, kuralın yakalayabildiğini ölçer. Modelin hangi sıklıkla böyle hata yaptığını ölçmez; o oran 5. adımda ham çıktılardan elle okunur.

**Şart 7'de yeni bulgu.** Hafızada "kullanıcının unutmanı istediği konular" kuralı var. Defter özgün cümleleri taşıyacağı için, kullanıcının unutturduğu bir bilgi defterden isteme geri dönebilir. Bu, 5. adımda zorunlu test olur.

## 4. Sonraki adımlar (her biri ayrı onaylı)

| Adım | İş | Model |
|---|---|---|
| 2 | Değişiklik algılayıcısı: yeni, ayarlamada kullanılmayan örnek seti ve ölçüt | Yok |
| 3 | Gösterim metni ve Gemma'nın bunu okuması için çok kısa deney | Kısa, ayrı onay |
| 4 | Bütçe, koruma sınıfları, geri getirme; 800 ve 1 200 modelsiz karşılaştırma | Yok |
| 5 | Motora bağlama (deneysel dalda), hafıza çelişkisi, unutma, yanlış bağlama | Kısa, ayrı onay |
| 6 | 800 ve 1 200 Gemma karşılaştırması | Ayrı onay |
| 7 | Tam çoklu sıkıştırma testi | Ayrı onay |

**2. adım için önerilen ölçüt, onayınıza:** Ayarlamada kullanılmayan en az 60 yeni örnekte gerçek değişikliklerin en az %90'ı yakalanmalı, ilgisiz örneklerin en fazla %10'unda alarm olmalı. Bu oranlara ulaşılabileceğini bugün bilmiyorum. Ulaşılamazsa uyarı gösterilmez; yalnızca zamanlı kullanıcı sözleri kalır ve seçim modele bırakılır. Bunun yeterli olup olmadığı Gemma testiyle ölçülür. Modelin önerdiği değişikliği kodun doğruladığı ikinci yol da orada denenebilir.

## 5. Bütçe: 800 ilk deneysel aday

Bugünkü aktif bağlam bütçesi değişmez. 800 yalnızca deneysel dalda ve testlerde kullanılır.

### Koruma sınıfları ve yeni ölçüm

Sınıfları sizin listenize göre genişlettim ve saklı veride boyutlarını ölçtüm. Bu ölçüm geçici bir betikle yapıldı, ürün kodu değişmedi.

| Grup | Tek konuşma (22 konuşma) | Birleştirilmiş zorlama (88–99 madde) |
|---|---|---|
| Alerji, beslenme, kalıcı talimat, hatırlatma | — | 352 |
| Kişi ilişkisi | — | 519–579 |
| Açık talimat bölümü | — | 90 |
| Aktif karar | — | 335–379 |
| Belirsiz bilgi (sorular hariç) | — | 415–474 |
| **Tümü (çakışmalar bir kez)** | **ortalama 184, en fazla 423** | **1 334–1 377** |

**Bulgu:** Olağan konuşmada 800 yetiyor. Bilgi çok biriktiğinde koruma sınıflarının tümü 800'e de 1 200'e de sığmıyor. "Hepsi her zaman istemde" sözü bu yüzden verilemez. "Sessizce kaybolmaz" ise verilebilir.

### Önerilen kural

1. **Her zaman istemde:** alerji, beslenme, açık talimat, hatırlatma isteği (bu grup ölçümde 352 token).
2. **Yerleşene kadar istemde, yeniden eskiye:** değişmiş olabilir notu olanlar, aktif kararlar, belirsiz bilgiler, kişi ilişkileri.
3. **Sığmayan koruma maddesi sessiz kalmaz:**
   - İstemde sayısı ve kısa bir dizin görünür: `Kayıtta ayrıca: Elif, Burak, Deniz…`
   - Sayıları günlüğe yazılır, metni yazılmaz.
   - Adı veya konusu geçince geri getirilir.
   - Silinmez.

**Sınır:** Kelime eşleşmesine dayanan geri getirme dolaylı soruda çalışmıyor. Örneğin "Akşama ne pişireyim?" bu yüzden 1. grup zorunlu.

Dizin satırı henüz ölçülmedi; bütçeye dahildir.

### 800 ve 1 200 nasıl karşılaştırılacak

**Önemli sınır:** 88 saklı özetin hiçbiri 800'ü aşmadı. Bu testleri iki bütçeyle koşmak fark göstermez. Karşılaştırma ancak bilgi biriken yeni bir konuşmayla anlamlı olur; bu yeni veri seti 4. adımda hazırlanır.

| Boyut | Ölçüm |
|---|---|
| **Geri çağırma** | Doğrudan ve dolaylı sorularda bilginin isteme gelmesi. Koruma sınıfı başına: istemde, geri geldi, gelmedi. Sessiz kayıp 0 olmalı |
| **Yanıt kalitesi** | Elle okunur: doğru, eksik, yanlış. Eski değeri güncel diye söyleme, belirsizi kesinleştirme, "bana söylemediniz" türü yanlış ayrı sayılır |
| **Kaynak** | Gerçek istem tokenı, tahminle farkı, ilk token süresi (önbellekli ve önbelleksiz), istem işleme süresi, sıkıştırma süresi, en yüksek bellek, swap artışı, bellek baskısı |
| **Koşul** | Aynı veri, aynı tohumlar (7 ve 11), özel çalışma ortamı, checkpoint 8, benzer makine yükü |

**Karar kuralı:**

- Varsayılan 800'dür.
- 1 200, ancak korunan bilgide veya elle okunan yanıtta 800'ün kaçırdığı gerçek hatayı gidermesi ve kabul edilmiş günlük kullanım hedeflerini aşmaması halinde önerilir.
- Toplam puan tek başına karar vermez. Bir bilgideki kayıp başka bilgideki kazançla telafi edilmez.
- Fark yoksa veya iki seed çelişirse 800 kalır, sonuç "ayrım yapılamadı" diye raporlanır.

Ürün varsayılanına geçiş ayrı bir karardır.

## 6. Kapsam dışı

Gerçek profil, Ollama servisi, checkpoint ayarı (8), model, migration, push, hatırlatma özelliği, REL-001, REL-002, C optimizasyonu ve Faz 10C. REL-004 açık kalır. 5. adımda taşınan hatırlatma cümlesinin yanlış söze dönüşmediği ayrıca sınanır.
