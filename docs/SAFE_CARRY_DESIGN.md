# LAZIS — Güvenli Bilgi Koruma Tasarımı ve Modelsiz Değerlendirme

- **Durum:** Tasarım ve simülasyon. Ürün kodu değişmedi, model çağrılmadı, gerçek profile ve servise dokunulmadı.
- **Araç ve veri:** [p10p_carry_replay.py](../evals/runners/p10p_carry_replay.py), [tr_carry_claims_v1.json](../evals/datasets/tr_carry_claims_v1.json), [tr_change_detect_v1.json](../evals/datasets/tr_change_detect_v1.json), [sonuçlar](../evals/reports/phase10/perf/carry-replay/)

## 1. Sonuç

**Tasarım saklı verideki kayıpların hepsini kapatıyor, ama bu Gemma'nın doğru yanıt vereceğini kanıtlamıyor.** Bilginin isteme ulaştığını ölçtük; modelin onu doğru kullandığını ölçmedik. Karar için kısa bir Gemma testi gerekir.

| Saklı 88 özet | Bugünkü özet | Önerilen tasarım (S7) |
|---|---|---|
| Kaybolan güncel bilgi (588 ölçüm) | **70** | **0** |
| Kaybolan belirsiz bilgi (36 ölçüm) | **6** | **0** |
| Belirsizin kesin görünmesi | 0 | 0 |
| Eski değerin işaretsiz güncel görünmesi (76 ölçüm) | 0 | 0 |
| Bugünkünün doğru, tasarımın yanlış olduğu ölçüm | — | **0** |
| Ortalama özet boyutu (tahmini token) | 623 | 491 |
| En büyük özet | 845 | 785 |

Bu tablodaki "0" değerleri genel başarı oranı değildir. §6'daki zayıf noktalar daha önemlidir: değişiklik kontrolü zor örneklerin 4'ünü kaçırdı (17 örnek); ipucu içermeyen bilgilerde modelsiz seçim 12'nin 12'sini kaçırdı.

## 2. Tasarım

**Temel fikir:** Doğrulanmış bir kullanıcı maddesi bir kez deftere girer. Sonra model onu yeniden yazmaz.

1. **Model yalnızca yeni mesajları okur** ve yeni madde önerir. Mevcut kanıt denetimi aynen çalışır, gevşetilmez.
2. **Kod, geçen maddeyi deftere ekler** ve kullanıcının saklı mesajındaki özgün cümleyi bulur. İstemde modelin yazdığı metin değil, bu cümle görünür.
3. **Eski maddeler kod tarafından taşınır.** Model bir maddeyi yazmadı diye madde kaybolmaz.
4. **Değişiklik kontrolü kodla yapılır.** Yeni kullanıcı cümlesi eski maddeyi değiştiriyor gibiyse, eski maddenin yanına kullanıcının cümlesi eklenir. Hiçbir şey silinmez veya kendiliğinden kesinleşmez.
5. **Atıfsız cümleler korunur.** Hiçbir maddenin kaynak göstermediği, tarih, ad veya istek içeren kullanıcı cümleleri de taşınır.
6. **Bütçe aşılırsa** madde istemden çıkar, kayıtta kalır, sayısı görünür ve gerektiğinde geri getirilir.
7. **LAZIS'in sözleri taşınmaz.** Yalnızca son çıktıdan en fazla 3 not, ayrı başlık altında gösterilir.

Örnek (Tohum 7, sonradan gelen bilgi senaryosu; bugünkü özet bu bilgilerin çoğunu kaybetmişti):

```text
- Tatil için Bodrum'a gitmeye karar verdik. [#5] ⚠ #33 değişmiş olabilir: «Tatil için fikrimizi değiştirdik, Bodrum yerine Fethiye'ye gidiyoruz.»
- Kuzenim Deniz galiba temmuzda Van'a taşınacak, daha belli değil. (belirsiz) [#9] ⚠ #53 iptal edilmiş olabilir: «Deniz'in Van'a taşınması iptal oldu.»
- Eşim Derya vegan, yemek önerirken buna dikkat et. [#29]
- Cuma günü saat 11:00'de veterinerle görüşmemi bana hatırlat. [#11]
```

## 3. Modelsiz değerlendirme

Daha önce Gemma'nın ürettiği 88 çıktı, ürünün kendi `parse_summary` ve `verify_items` işlevlerinden yeniden geçirildi. Her biri saklı özetle **bayt bayt aynı** çıkmasa çalışma durdurulacaktı; 88'i de aynı çıktı. 60 iddia, bu özetler üzerinde toplam 700 ölçüm üretti.

### Kademeli sonuç

Kayıp ve eski bilgi riski ayrı sayıldı, birbirini telafi edemez. "Gerileme", bugünkü özetin doğru, seçeneğin yanlış olduğu ölçümdür; başka kazanımla silinmez.

| Seçenek | Güncel bilgi kaybı | Yanlış kapanan | Belirsiz kaybı | Eski değer güncel görünüyor | Gerileme |
|---|---|---|---|---|---|
| S0 Bugünkü özet | 70 | 0 | 6 | 0 | — |
| S1 Yalnızca alıntıyı göstermek | 28 | 0 | 0 | 6 | 6 |
| S2 Model metniyle taşımak, kapatma yok | 46 | 10 | 6 | **18** | 28 |
| S3 Özgün cümleyle taşımak | 15 | 5 | 0 | 17 | 27 |
| S4 + Değişiklik kontrolü | 15 | 5 | 0 | 0 | 10 |
| S5 + Atıfsız cümleler | 0 | 5 | 0 | 0 | 5 |
| S6 Hiç model çıktısı yok | 0 | 0 | 0 | 0 | 0 |
| **S7 S5, modelin kapatması yalnızca şüphe** | **0** | **0** | **0** | **0** | **0** |

Çıkan dersler:

- **Yalnızca taşımak tehlikeli (S2).** Eski değer hatası 0'dan 18'e çıkıyor. Değişiklik kontrolü zorunlu.
- **Yalnızca alıntı göstermek yetmiyor (S1).** Önceki raporda önerdiğim adım tek başına gerileme yapıyor.
- **Cümle düzeyinde kapatmak yanlış (S5).** Model "9:00" değerini eski saydı; "Ali Bey ile pazartesi toplantım var" cümlesinin tamamı "artık geçerli değil" altına düştü. Bu yüzden S7'de model kapatma yapamaz, yalnızca şüphe bildirir.

### İstediğiniz sekiz kontrol

| Durum | Bugünkü özet | S7 | Not |
|---|---|---|---|
| Vejetaryen ve vegan | 34 ölçümde 15 kayıp | 0 | Kaynak cümle görünüyor |
| Değişen şehir, bütçe, saat | 80 ölçümde 4 kayıp; eski değer güncel görünmüyor | 0 kayıp; 68 eski değer işaretli | Bugünkü özet eski değeri çoğu kez siliyor (47) |
| Kesinleşen ve iptal edilen | 8 ölçümde 4 kayıp | 0 | Kesinleşme kendiliğinden yapılmıyor, kullanıcının cümlesi görünüyor |
| Belirsiz üçüncü kişi | 28 ölçümde 6 kayıp; yanlış kesinlik 0 | 0; 0 | Bazen fazla işaretler (§6) |
| Açık hatırlatma | 22 ölçümde 14 kayıp | 0 | Bu, özelliğin çalıştığı anlamına gelmez ([REL-004](RELIABILITY_ISSUES.md)) |
| Kaynakta olmayan tarih, sayı | 88 özetin 6'sında uydurma yıl | 0 | `05.04.2024`, `12.03.2024`. Diğer 5 aday yalnızca biçimdi (`9:30`→`09:30`) |
| Yanlış kanıtla doğrulanan | 4 değiştirilmiş alıntı (2 farklı); biri anlamı bozuyor | Görünmez | "…hatırlat" → "…görüşme yapılacak" özgün cümleye geri döner |
| LAZIS çıkarımı kullanıcıya mal edilmiş | Elle okununca 0 | 0 | Tek aday yanlış alarmdı. Veride gerçek örnek yok, tasarımın yapısı dışında kanıt da yok |

Ayrıca reddedilen doğru bilgiler (`Kuzey`, `15 Aralık`) atıfsız cümle olarak geri geliyor.

### Boyut ve bütçe

Taşıma bu testlerde küçük kaldı: 88 özetin hiçbiri 800 token bütçesini aşmadı. Ama bu sonuç fazla iyimser: dolgu mesajları aynı soruları tekrar ediyor ve bunlar tek maddede birleşiyor. §1'deki küçülmenin bir kısmı da LAZIS notlarının 3 ile sınırlanmasından ve uzun atıf listelerinin kısalmasından geliyor; taşımanın kendisi özeti küçültmez. Bu yüzden her tohumdaki konuşmaları tek konuşmada birleştirip zorladım: 88–99 madde, 3 046–3 296 tahmini token.

| Bütçe | 60 iddiadan istemde | Adıyla sorulan 28 soru | Dolaylı sorulan 8 soru: bulunamayan |
|---|---|---|---|
| 800 | 26 | 28 | 3 |
| 800 + koruma | 31 | 27 | 1 |
| 1 200 | 42–43 | 28 | 1 |
| 1 200 + koruma | 43–44 | 28 | 0 |

- **Eski değer hatası** tüm bütçelerde 0.
- **Geri getirme yalnızca kelime eşleşirse çalışıyor.** "Akşama ne pişireyim?" sorusu vegan cümlesiyle kelime paylaşmıyor, bütçede yoksa bulunamıyor.
- **Bu yüzden koruma sınıfı gerekli:** alerji, beslenme, hatırlatma, kalıcı talimat ve açık reddetme bütçe yüzünden önce çıkmaz.
- **Bu koşular yalnızca istemi ölçüyor;** 28 sorunun "bulunması" doğru yanıt demek değil.

### Değişiklik kontrolü: zor örnekler

Bu 30 örneği kuralın ilk çalışmasından önce elle yazdım, sonra değiştirmedim.

| Tür | İlk kural | Düzeltilmiş kural |
|---|---|---|
| Değişti | 8/10 | 8/10 |
| İptal edildi | 3/4 | 3/4 |
| Kesinleşti | 1/3 | 2/3 |
| Yalnızca tartışıldı | 7/7 | 7/7 |
| İlgisiz | 3/6 | 3/6 |
| **Toplam** | **22/30** | **23/30** |

Saklı 88 özette düzeltilmiş kural 6 uyarı verdi; hepsi doğru. İlk kural 8 uyarı verdi; 2'si yanlıştı. Düzeltmeyi veriyi gördükten sonra yaptım, bu yüzden iyileşme kanıt sayılmaz.

Kaçırdıkları: "Toplantıyı çarşambaya aldık", "Spor salonunu bıraktım", "Düğün ertelendi, gitmiyoruz", "Mehmet İzmir'e gidiyor, bileti aldı". Yanlış alarmları: "Patronum Ali Bey toplantıyı iptal etti" (Komşu Ali ile karıştı), "Tatil bütçemizi 30 bin TL'ye çıkardık" (taşınma bütçesiyle karıştı).

### Elle okuyunca düzelttiklerim

İlk koşu olduğu gibi saklı ([first_run.json](../evals/reports/phase10/perf/carry-replay/first_run.json)).

- **Bugünkü özetin aleyhine puan hatası.** "React yerine Vue" eski değer sayılmıştı. Düzeltince bugünkü özetin eski değer hatası 10'dan 0'a indi. Bu hata düzelmese tasarım haksız yere iyi görünecekti.
- `fıstığa` ile `fıstık` aynı kelime sayılmamıştı.
- LAZIS notları boyuta dahil değildi; dahil edildi.
- Kurala iki düzeltme: cümle başındaki ad artık sayılıyor; farklı sayı yalnızca aynı tür değerde uyarı veriyor. "Toplam" ile "toplantı" karışıyordu.
- Modelin kapatması bir ara yanlış cümle ekledi ("Komşum Ali…", "Ali Bey" maddesine). Bu ekleme kaldırıldı.

## 4. Tasarım soruları

### 1. Hangi bilgi nerede tutulmalı?

| Bilgi | Yer | Neden |
|---|---|---|
| İlişki, kalıcı tercih, sağlık ve beslenme | Hafıza; konuşmada defter de tutar | Konuşmalar arası gerekli |
| Yazım ve üslup talimatı | Hafıza (`pinned`) | Her yanıtı etkiler |
| Plan, karar, bütçe, randevu, tarih | Konuşma defteri | Değişir, konuşmaya bağlı |
| Üçüncü kişinin belirsiz planı | Konuşma defteri | Hafızaya yazılması REL-001 riski taşır |
| Hatırlatma isteği | Defterde yalnızca metin | Özellik yok ([REL-004](RELIABILITY_ISSUES.md)) |
| LAZIS'in önerisi | Yalnızca son özet | Kullanıcının sözü değil |

**Hafıza şu an bu boşluğu kapatamaz.** 40 mesajlık koşuda, öğrenme açıkken hafıza 23 iddianın 8'ini içermiyordu (bütçeler, otel adı dahil). Mevcut kurallar tek seferlik planları düşürüyor ve hassas bilgiyi onay kutusuna gönderiyor. Bu yönlendirme doğru, ama defteri gerekli kılıyor. Hafıza kuralları değişmiyor.

### 2. Madde nasıl kimliklendirilir?

Kimlik: `konuşma + mesaj numarası + cümle sırası + cümlenin normalleştirilmiş özeti`. Kod her gösterimde cümlenin saklı mesajda olduğunu doğrular.

- Mesaj düzenleme işlevi yok. Konuşma silinince defter de silinir (`CASCADE`).
- `reset_context` özetleri geçersiz kılar, defter de onlarla gider.
- Yeni sürüm ayrı satırdır; eski satır değişmez.
- `content_json` içinde bir alan yeterli, **migration gerekmez.**

### 3. Güncellendi, iptal edildi, tartışıldı ayrımı

Kod üç şeye bakar: aynı konu mu, değişiklik sözcüğü var mı, soru veya çekince var mı.

| Yeni cümle | Sonuç |
|---|---|
| "Bodrum yerine Fethiye'ye gidiyoruz" | Değişmiş olabilir |
| "Van'a taşınması iptal oldu" | İptal edilmiş olabilir |
| "Gelişi kesinleşti" | Kesinleşmiş olabilir |
| "Bodrum yerine Fethiye'ye gitsek nasıl olur?" | Tartışıldı, karar yok |
| "Deniz Van'a taşınmayı iptal edebilir" | Tartışıldı, karar yok |
| "Toplam bütçemiz 35 bin" (aynı tür değer, farklı sayı) | Çelişiyor olabilir |

Sonuç hep "olabilir"dir. Kod yalnızca kullanıcının cümlesini yanına koyar; karar kod tarafından verilmez.

### 4. Yanlış kesinlik nasıl önlenir?

- Kesinlik yalnızca ilk yazımda okunur. Sonradan hiçbir model çıktısı yükseltemez.
- Kaynak cümlede çekince varsa madde kesin olamaz.
- Kesinleşme yalnızca kullanıcının cümlesiyle görünür: `(belirsiz) ⚠ kesinleşmiş olabilir: «…»`.
- Yeni cümle eskiyle çelişiyorsa ikisi yan yana durur.

### 5. Madde büyüyünce

| Sıra | Grup |
|---|---|
| 1 | Değişiklik uyarısı olanlar |
| 2 | Koruma sınıfı: alerji, beslenme, hatırlatma, kalıcı talimat, açık reddetme |
| 3 | Kararlar, kısıtlamalar |
| 4 | Kişiler, hedefler |
| 5 | Konular, sorular, atıfsız cümleler |

Her grupta yeniden eskiye gider. **Başlangıç önerim: 800 tahmini token.** Bugünkü özetin en büyük boyutuna (845) yakın, yani yanıt süresini büyütmez. 300 ve 500 çok dardı. Dışarıda kalanlar, kullanıcı mesajıyla kelime eşleşince 200 token içinde geri gelir. Bu, hafızadaki geri getirme bütçesiyle aynıdır.

**Bilinen açık:** uyarılı maddeler sürekli önde kalır. Eskitme kuralı tasarlanmadı ve ölçülmedi.

### 6. Model çağrısı olmadan ne kadar çalışır?

| İş | Kim yapar |
|---|---|
| Taşıma, kimlik, özgün cümle, bütçe, gösterim | Kod |
| Değişiklik kontrolü, atıfsız cümleler | Kod; hatalı olabilir |
| Sır ve kural geçersiz kılma denemelerini eleme | Kod (mevcut `secret_kind`, `instruction_like`) |
| İpucu içermeyen yeni bilgiyi anlamak | **Model** |

S6 saklı veride hatasız görünüyor, ama bu **yanıltıcı**: veri seti tarih ve ad içeren kısa cümlelerden oluşuyor. "Patlıcan sevmem", "Eşim hamile", "Arabamı sattım" gibi 12 örneğin **12'sini de kaçırdı**, 9 gereksiz cümleden 3'ünü aldı. Model tamamen kaldırılamaz, ama yükü azalır:

- İlk özetten sonraki 66 çıktıda yazılan karakterlerin **%72'si** zaten özetlenmiş mesajları yeniden yazıyordu.
- Yalnızca yeni mesajlar yazılsaydı en büyük çıktı yaklaşık 762 token olurdu. Bugün sınır 1 200 ve 66 çıktının 16'sı bu sınıra çarpıyor.
- Bunlar tahmin. Süre kazancı ölçülmedi ve C optimizasyonunun gereksiz olduğu anlamına gelmez.

### 7. En küçük uygulama yolu

Yeniden yazım yok. Tahmini 200–250 satır ürün kodu ve testleri:

| Dosya | Değişiklik |
|---|---|
| `compaction.py` | Özgün cümle, defter birleştirme, değişiklik kontrolü, gösterim. Saf işlevler |
| `engine.py` | `_compact` içinde defteri bağlamak; sayılardan oluşan günlük |
| `prompts.py` | İstem: yalnızca yeni mesajlar; yeni sürüm etiketi |
| Şema, kanıt denetimi, migration, hafıza | **Değişmez** |

Eski konuşmalar, ilk sıkıştırmada önceki özetin doğrulanmış kullanıcı maddeleriyle deftere geçer. Daha önce kaybolmuş bilgi geri gelmez.

Her adım ayrı onaylıdır:

1. `main` üzerinden ayrı dalda saf işlevler ve testler; davranış değişmez.
2. Motora bağlama.
3. **Kısa Gemma testi:** sonradan gelen bilgi (yaklaşık 7 dk), kısa set (10 dk), talimat seti (6 dk). Yaklaşık 23 dakika; özel çalışma ortamı, sınır 8.
4. Kabul olursa 46 dakikalık tam test.

## 5. Kabul ölçütleri

1. **Yanıtlar elle okunur.** Sonradan gelen bilgi senaryosunda bilinen yanlış yanıtlar düzelir, yenisi çıkmaz.
2. **İddia başına gerileme yok.** Toplam iyi olsa da her gerileme tek tek raporlanır.
3. Eski değer güncel diye yanıtlanmaz, belirsiz bilgi kesinleştirilmez.
4. Özet ve istem boyutu bütçeyi aşmaz, dışarıda kalanlar sayılır.
5. Bir özet sürümünde önceki doğrulanmış kullanıcı maddesi sessizce kaybolmaz; denetim bunu gösterir.
6. Eski özet sürümleri ve konuşma kayıtları değişmez.
7. Günlüğe kullanıcı metni yazılmaz.

## 6. Dürüst sınırlar: bu tasarımın çözemedikleri

**Hiç ölçülmeyenler**

- **Gemma'nın okuması.** İstem kullanıcının birinci tekil sözlerini içeriyor ("Kız kardeşim"). Model bunu kendi sözü sanabilir veya `⚠` satırlarında güncel değeri seçemeyebilir. Bu en büyük bilinmeyen.
- **Yeni istemin etkisi.** Saklı çıktılar eski istemle, yeniden yazarken üretildi. Model yalnızca yeni mesajı görünce daha iyi veya daha kötü yazabilir.
- **Gerçek kullanıcı dili.** Veriler kısa ve kurgusal. Uzun anlatımlar, gönderimler ("Onu iptal ettik") ve yazım hataları denenmedi. Çok uzun cümlelere sınır gerekecek.
- **Gerçek uzun konuşma.** 40 mesajlık koşuda ham çıktı saklanmadığı için yalnızca S6 denenebildi. Büyüme verisi birleştirilmiş ve yapay.
- **Gecikme.** Süre ölçülmedi.

**Bilinen zayıflıklar**

- **Değişiklik kaçabilir.** Zor örneklerde 17 gerçek değişikliğin 4'ü yakalanmadı. Bu durumda eski ve yeni cümle işaretsiz yan yana durur; hangisinin seçileceği modele kalır. Eski değer riski tamamen kalkmıyor.
- **Yanlış alarm olabilir.** 6 ilgisiz örneğin 3'ünde uyarı verdi. Yanlış uyarı bilgi silmez ama modeli şüpheye düşürebilir.
- **Hiç yakalanmayan bilgi kaybolur.** Modelin yazmadığı ve ipucu içermeyen bilgi deftere girmez. Saklı 60 iddiada bu olmadı çünkü iddialar ipuçlu cümlelerden seçildi.
- **Fazla belirsizlik.** "İş arkadaşım Mehmet galiba…" cümlesinde ilişki de belirsiz görünür. Güvenli yönde bir hata, ama hata.
- **Kurallar bu veriyi görerek yazıldı.** Kurallar ilk koşudan önce donduruldu, ama kayıplar zaten biliniyordu. Rakamlar başka veriyi öngörmez.
- **Hafıza etkisi ölçülmedi.** Hafızayla defter aynı bilgiyi çelişkili gösterebilir. Bu testin dışında.
- **Metin sürekli istemde kalır.** Sır ve kural geçersiz kılma denemeleri 5 örnekte doğru ayrıldı (4 elendi, 1 normal talimat kaldı), ama bu çok küçük bir sınama.

## 7. Dokunulmayanlar

Gerçek profil, gerçek Ollama servisi, checkpoint sınırı (8), model, migration, Düzeltme 4 ürün kodu, C optimizasyonu, REL-001, REL-002 ve Faz 10C. Yeni Gemma testi yok. Push yok.
