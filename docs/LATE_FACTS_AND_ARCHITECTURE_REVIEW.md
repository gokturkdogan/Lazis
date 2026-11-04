# LAZIS — Sonradan Gelen Bilgi Testi ve Mimari Değerlendirme

- **Tarih:** 2026-11-04, 18:56–19:03 (2 tohum, 4 özet sürümü, 16 soru)
- **Kod:** `s3-v5` (yeni bölüm sırası + talimat kuralı). Bu test için ürün kodu değişmedi. Öğrenme kapalı: yalnızca özet ölçüldü.
- **Ortam:** Geçici Ollama süreci, sınır 8. ChatGPT, Codex ve Cursor kapalıydı; diğer programlar 10,9 GB. Baskı hep normal, swap artışı yok, kesilen çıktı 0/8.
- **Ham veri:** `evals/reports/phase10/perf/late-facts/`. Araçlar: `p10p_late_facts.py`, `p10p_quote_replay.py`.
- **Sınır:** Eski bölüm sırasıyla bu senaryo koşulmadı. Aşağıdaki hatalar için "yeni sıranın regresyonu" diyemem; aynı senaryonun taban çizgisi yok.

## 1. Sonuç

**Özet yeni bilgiyi çoğunlukla alıyor, ama her yeniden yazımda güvenilmez biçimde kaybediyor. Asıl bulgu: kaybolan anlamın çoğu doğrulanmış alıntılarda duruyor, yalnızca yanıt istemine gönderilmiyor.**

**Öneri: C.** Bölüm sırası deneysel kalsın, kural metni kovalanmasın, bilgi koruma mekanizması önce tasarlansın.

## 2. Elle değerlendirme

| Senaryo | Tohum 7 | Tohum 11 |
|---|---|---|
| Yeni kişisel bilgi: kedi Tarçın, penisilin alerjisi | Doğru, korundu | Doğru, korundu |
| Yeni tercih: eş Derya vegan | **Kayıp:** yalnızca "Derya: eşi" | **Yanlış yerde:** yalnızca LAZIS notu olarak |
| "Yemek önerirken dikkat et" isteği | **Kayıp** | **Kayıp** |
| Değişen karar: Bodrum → Fethiye | Doğru (2–3); **4. sürümde Fethiye reddedildi** | Doğru (2); **3. sürümde Fethiye reddedildi** |
| Eski karar güncel kaldı mı? | Hayır, eski olarak işaretli | Hayır, eski olarak işaretli |
| Belirsiz → kesin: Burak | Belirsiz doğru; **kesinleşince plan tamamen kayboldu** | **Doğru:** kesin, belirsiz işareti gitti |
| Belirsiz → iptal: Deniz | Belirsiz doğru; **iptal bilgisi kayboldu** | **Doğru:** "iptal oldu" |
| Değişen bütçe: 25 → 30 bin | Doğru, eskisi yok | Doğru, eskisi yok |
| Hatırlatma talimatı | **Hedefe dönüştü** | **Karara dönüştü**, alıntı da değişti |
| Elif: ilişki, tarih, şehir | Doğru, yıl eklenmedi | Doğru, yıl eklenmedi |
| Uydurma yıl | Yok | Yok |
| Belirsizin haksız kesinleşmesi | Yok | Yok |

Bu senaryoda yıl uydurulmadı. Önceki olayda kullanıcı tarih biçimi talimatı vermişti; tetikleyici o olabilir.

**Kategori sorunu:** "Talimatlar" 8 özette de boş; ama bu kez açık hatırlatma ve "dikkat et" isteği de oraya girmedi. Sentetik denemede 3/4 girmişti. Kural belki fazla kısıtlıyor; bu kadar örnekle söylenemez.

**Sorular (16), elle:**

| | Tohum 7 | Tohum 11 |
|---|---|---|
| Doğru | 3 | 6 |
| Doğru ama eksik ("Bodrum geçerli değil"; Fethiye söylenmedi) | 1 | 1 |
| **Yanlış** | **4** | **1** |

Yanlışlar kullanıcıya yanlış bilgi veriyor: "Bana herhangi bir şeyi hatırlatmamı istemediniz", "Deniz'in … bilgi paylaşmadınız", "Burak … bilgi paylaşmadınız". Otomatik denetim 8/16 sayıyor; "Burak 15 Haziran'da Trabzon'a geliyor" gibi doğru yanıtları kaçırıyor.

**Önceki kayıplar ve yeni bulgular:**

- **Önceden bilinen sınıf:** Yeniden yazımda bilgi düşmesi (REL-003, A); `dropped: 0` ile sessizlik; anlamın kaybolması.
- **Yeni görülen:** Kesinleşen plan ve iptal bilgisinin kaybı; **geçerli kararın kanıt denetimine takılması** (aşağıda); hatırlatmanın kaybı; alıntının yeniden yazımda değişmesi.

## 3. Ham çıktıdan üç önemli bulgu

**Bulgu 1: Kaybolan anlam çoğunlukla alıntıda duruyor.** Tohum 7, sürüm 3'te saklı maddeler:

| Yanıt isteminde görünen | Doğrulanmış alıntı (görünmüyor) |
|---|---|
| Derya: Kullanıcının eşi | "Eşim Derya vegan, yemek önerirken buna dikkat et." |
| Burak: Kullanıcının arkadaşı | "Burak'ın gelişi kesinleşti, 15 Haziran'da Trabzon'a geliyor." |
| Deniz: Kullanıcının kuzeni | "Deniz'in Van'a taşınması iptal oldu." |
| Cuma 11:00 veterinerle görüşme | "… görüşmemi bana hatırlat." |

Yanıt istemi yalnızca modelin yazdığı `text` alanını gösteriyor. Saklı çıktılarda, doğrulanmış alıntıda bulunan eksikler (`p10p_quote_replay.py`, modelsiz, kelime düzeyinde):

| Çalışma | Eksik | Alıntıda var |
|---|---|---|
| Eski sıra (50 özet) | 23 | 3 (`vejetaryen`) |
| Yeni sıra + kural (12 özet) | 4 | 3 (`vejetaryen`) |
| Sonradan gelen bilgi (8 özet) | 20 | 14 |

Yani **her kayıp böyle kurtarılamaz:** eski sırada eksiklerin çoğu alıntıda da yok (mekanizma A). Alıntılar özet metninin yaklaşık %36'sı kadar.

**Bulgu 2: Yeniden yazma kanıtı bozuyor.** Fethiye kararı doğru alıntıyla doğrulandı. Sonraki yazımda model alıntıyı "Tatil için Fethiye'ye gidiyoruz" diye yeniden yazdı, bu cümle mesajda yok, denetim doğru olarak reddetti (`dropped: 1`). Geçerli karar özetten düştü, geride yalnızca "Bodrum geçersiz" kaldı. **Denetim haklı; sorun, doğrulanmış kanıtın yeniden yazdırılması.**

**Bulgu 3: Yeniden yazılan alıntı denetimden sızabiliyor.** Tohum 11'de "… görüşmemi bana hatırlat" alıntısı "… görüşme yapılacak" oldu ve %85 benzerlik eşiğini geçti. Böylece hatırlatma anlamı kanıttan da silindi.

## 4. Mimari değerlendirme (kod yok)

### 1. Önemli bilgileri her sıkıştırmada modele yeniden yazdırmak zorunda mıyız?

**Hayır.** Doğrulanmış maddeler zaten saklı `content` içinde: metin, kaynak, atıf, alıntı, kesinlik. Model yalnızca **yeni mesajları** yorumlamalı. Bugünkü yöntem her seferinde üç riski yeniden alıyor: atlama, anlam değiştirme, kanıtı bozma. Bu üçü de yukarıda ölçüldü.

### 2. Kesin, belirsiz, değişmiş ve iptal edilmiş bilgi daha deterministik korunabilir mi?

**Evet, kısmen.** Varsayılan tersine çevrilir: **Model söylemezse madde durur.** Durum yalnızca yeni bir kullanıcı mesajının doğrulanmış alıntısıyla değişir.

| Durum | Kural |
|---|---|
| Yeni | Model önerir, kod doğrular, eklenir |
| Değişmedi | Kod aynen taşır, model yazmaz |
| Belirsiz → kesin | Yeni mesajdan alıntıyla model önerir, kod eski maddeyi kapatır |
| Değişti | Aynı şekilde; eski madde "geçerli değil" olarak kalır veya kapanır |
| İptal | Aynı şekilde; "iptal" durumu görünür kalır |

**Deterministik olmayan kalır:** Yeni bir mesajın hangi eski maddeyi değiştirdiğini anlamak modele aittir. Model "değişti" demezse eski bilgi kalır. Bunu soru 4 yönetir.

### 3. Kanıt denetimini gevşetmeden kaynak doğruluğu nasıl korunur?

Gevşetmeye gerek yok, **sıkılaştırılabilir:**

- **Doğrulanmış kanıt değişmez:** Taşınan maddenin alıntısı yeniden üretilmez. Fethiye sorunu böylece doğrudan kalkar.
- **Kullanıcının kendi sözü gösterilir:** Yanıt isteminde kullanıcı maddelerinin doğrulanmış alıntısı da görünür. Bu, model metninden daha güvenilirdir ve yeni bilgi üretmez.
- **Metin alıntıyla denetlenir:** Metindeki sayı, tarih ve yıl kaynakta yoksa madde işaretlenir. "2024" böyle yakalanırdı.
- **Yeni madde dışında fuzzy gerekmez:** Bulgu 3 için, taşınan madde hiç yeniden yazılmaz.
- **LAZIS koruması aynen kalır:** Kullanıcı maddesi yalnızca kullanıcı mesajından alıntılanabilir.

Mekanizma C (`Kuzey`) bu tasarımla kendiliğinden çözülmez; ayrı kayıt olarak kalır.

### 4. Kodla taşımada eski bilgiyi yaşatma riski nasıl yönetilir?

Bu, tasarımın en zor noktası. Sınırlar:

1. **Yalnızca kullanıcı maddeleri taşınır.** LAZIS notları taşınmaz.
2. **Kapatma için kanıt zorunlu:** Madde ancak yeni bir kullanıcı mesajının doğrulanmış alıntısıyla kapanır.
3. **Çelişki görünür kalır:** Aynı konu ve yeni değer varsa ikisi de atıflarıyla durur, en yenisi "güncel" sayılır. Sessizce seçim yapılmaz.
4. **Silme yok:** Kapanan madde özette işaretlenir veya çıkar, ama kayıtlar değişmez; özgün mesajlar durur.
5. **Üst sınır:** Taşınan maddeler sınırlı. Sınır aşılırsa ne düştüğü sayılır ve görünür. Öncelik sırası sizin belirlediğiniz sıradır.
6. **Test zorunlu:** Bu test kabul ölçütüdür. Bodrum, 25 bin, Burak ve Deniz senaryolarında eski değer güncel görünmemeli.

**Kalan risk:** Model değişikliği fark etmezse eski değer güncel kalır. Bugünkü sistemde karşı risk bilginin kaybolması. Bu iki risk arasında tercih bir ürün kararıdır; önerim, eski değer görünür ve atıflı kalsın, çünkü kaynağa dönülebilir.

### 5. Hafıza ile özetin sorumlulukları yeterince ayrılmış mı?

**Hayır.** İkisi de kullanıcı gerçeği taşıyor, ama kimin sahip olduğu belli değil.

| Bilgi | Bugün | Olması gereken |
|---|---|---|
| Kalıcı gerçek ve tercih (vegan, alerji) | İkisi de, tutarsız | **Hafıza** sahibi; özet yalnızca konuşmada geçtiğini bilir |
| Konuşmaya özgü plan, karar, açık konu | Özet | **Özet** |
| Kişi ilişkileri | İkisi de | **Hafıza**; özet kısa referans |
| Kullanıcının LAZIS'e talimatı | Özet, ayrıca tercih sistemi | Yanıt biçimi **tercih**; bu konuşmaya özgü olan **özet** |
| Hatırlatma isteği | **Sahibi yok** | Ayrı konu (aşağıda) |

**Dikkat:** Bu testte öğrenme kapalıydı. Hafıza açıkken vegan bilgisi hafızadan gelebilirdi; ölçülmedi. Ancak hassas kategoriler inceleme kutusuna gidiyor (uzun konuşmada `nakliye`), tek seferlik planlar düşüyor (`policy.py`). Yani hafıza özetin eksiğini güvenilir biçimde kapatmıyor.

**Ayrı ürün açığı:** LAZIS "Cuma 11:00 için hatırlatırım" diyebiliyor, ama hatırlatma özelliği yok. Bu yanıt kullanıcıyı yanıltıyor. Bu, REL-003 değil; ayrı kayıt gerekiyor.

### 6. Daha az model çağrısıyla daha güvenilir bir yapı mümkün mü?

**Evet, ama kazançlar henüz hesap.**

- **Özet çıktısı küçülür:** Model yalnızca yeni maddeleri yazar. Bugün çıktının çoğu tekrar. Sıkıştırma kısalır ve C'nin yükü azalır. Ölçülmedi.
- **1 200 sınırı önemini yitirir:** Kesilme riski azalır, çünkü eski maddeler çıktıdan geçmez.
- **Kesilen iş kaybolmaz:** Uzun konuşmada 495 s boşa gitti. Küçük artımlı adım bunu azaltır.
- **Öğrenme:** Ön denetim, boş çağrıların (%54–58) çoğunu azaltabilir. Ayrı iş, kaçırma oranı ölçülmeli.

## 5. En küçük güvenli yön

Büyük yeniden yazım yok, migration yok; `content` zaten JSON. Her adım ayrı onaylı ve ölçülü:

| Adım | Ne | Çözdüğü | Risk |
|---|---|---|---|
| **1** | Yanıt isteminde kullanıcı maddelerinin **doğrulanmış alıntısını** göstermek | Anlam kaybının alıntıda kalan kısmı | Düşük; özet yaklaşık %36 uzar |
| **2** | Kullanıcı maddelerini **kodla taşımak**; model yalnızca yeni madde ve kapatma önerir | A, kanıt bozulması, kesilme | Orta; eski bilgi riski |
| **3** | Metin–alıntı denetimi: kaynakta olmayan sayı ve yıl | Uydurma ayrıntı | Düşük |
| **4** | Hafıza ve özet sorumluluklarını netleştirmek | Tutarsızlık | Sonraki iş |

**Önce modelsiz:** Adım 1 ve 2 saklı ham çıktılarda yeniden oynatılır; ardından bu test, 20 iddialık set ve çoklu test. Alıntının yanıtlara etkisi modelle ölçülür.

## 6. Düzeltme 3 için öneri: C

| Seçenek | Değerlendirme |
|---|---|
| **A. Küçük genel değişiklik** | **Hayır.** İki deneme gösterdi: tek cümle özeti baştan değiştiriyor, sonuç oynak. Kelime ayarı olaya göre uyum sağlar, sorunun kaynağı yeniden yazmak |
| **B. Sırayı geri al** | **Hayır, şimdi değil.** Sıra gerçek bir kazanç sağlıyor: kesilen çıktı 38 çıktıda 0; eski sırada 50'de 16, kişiler ve talimatlar kaybolabiliyordu. Geri almak bunu kaybettirir |
| **C. Sırayı deneysel tut, mekanizmayı tasarla** | **Önerim.** Kesilme kazancı korunur, kabul verilmez, asıl neden çözülür. Tasarım kabul edildiğinde sıra da onunla birlikte ölçülür |

**C'nin bir bedeli:** Bölüm sırası ve talimat kuralı `main` üzerinde. Gerçek uygulama bu koddan derlenirse, kabul edilmemiş `s3-v5` özetleri üretir. Şu an gerçek profil ve uygulama test edilmiyor, ama bilinçli bir karar gerekir: kabule kadar gerçek uygulamayı bu koddan çalıştırmamak ya da değişiklikleri ayrı bir dala almak.

## 7. Sınırlar

Tek senaryo, 2 tohum, 8 özet, öğrenme kapalı, tekrarlı dolgu, sentetik metin. Eski sırayla karşılaştırma yok. Kullanılan ortam daha boş (10,9 GB). Modelsiz sayımlar kelime düzeyindedir; alıntının yanıtı nasıl etkileyeceğini göstermez. Tasarım kazançları hesaptır, ölçüm değil.
