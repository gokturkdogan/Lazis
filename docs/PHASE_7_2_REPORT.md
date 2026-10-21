# LAZIS — Faz 7.2 Raporu: Kimlik Güvenliği, Adaş Ayrımı ve Açık Hafıza Komutları

- **Tarih:** 2026-10-21
- **Durum:** Uygulandı; gerçek Gemma 4 12B ile değerlendirildi. **Kullanıcı kabul testi ve açık onay bekleniyor.** Faz 8'e başlanmadı.
- **Karar:** [ADR-0018](adr/0018-namesakes-and-explicit-requests.md)
- **Mimari (uygulanmış hâli):** [MEMORY_ARCHITECTURE.md](MEMORY_ARCHITECTURE.md) Bölüm P7.2
- **Commit'ler (yerel, push edilmedi):**
  - `fda9813`: iç etiketler kişilik kurallarından çıkarıldı (sorun C)
  - `bcfad96`: adaşlar kullanıcının sözlerinden planlanıyor; "hangisi?" sohbette yanıtlanıyor; açık kayıt öğrenme talimatıyla yapılıyor (sorun A ve B)
  - `c128370`: zaten kayıtlı bir bilgi için "kaydedemedim" denmiyor; gerçek model değerlendirmesi
  - `8003c84`: "X ve Y benim iş arkadaşlarım" ve "X benim eski iş arkadaşım" kullanıcının dilbilgisinden okunuyor (gerçek modelle bulundu)
  - `b0e1947`: hangi kişi olduğu netleşmeden o ada ilişkin ilişki sorusu yanıtlanmıyor, yalnızca soruluyor (regresyonda bulundu)
  - `9da39c9`: "Atlas Yazılım'a geçtim" model tarafından şirketin kendisi hakkında yazılmışsa kullanıcının işyeri sayılıyor (regresyonda bulundu)
  - `700b4e0`: "Notumu aldım" da bir kayıt iddiası (3. turu elle okurken bulundu)
  - `d8998b5`: "kayıtlarım arasına ekledim" de bir kayıt iddiası; model öğe önermediğinde açık istek kullanıcının kendi sözlerini not olarak saklıyor (4. turu elle okurken bulundu)
  - `ecbc44d`: "not etmiş oldum" (geçmiş zamanın -miş oldum biçimi) da bir kayıt iddiası (Faz 7.1 değerlendirmesini elle okurken bulundu)
  - bu raporla birlikte: belgeler, ADR, ölçüm raporları

Bu bir özellik fazı değil, güvenilirlik fazı. Bütün testler **sentetik kişilerle**, geçici ve şifreli veritabanlarında (rastgele anahtar) yapıldı. Gerçek profilinize (`default`), `dev` profiline ve Ollama ayarlarına dokunulmadı. Migration yok; veritabanı yapısı değişmedi.

**Özet.**

- **A:** Aynı mesajda tanıtılan adaşlar artık ayrı kişiler. Belirsiz bir bilgi hiçbir kişiye yazılmıyor; LAZIS hangisi olduğunu soruyor, "Komşum olan." yanıtı da bilgiyi yanıttan önce doğru kişiye kaydediyor.
- **B:** "Lütfen şunu not al" ve diğer açık kayıt ifadeleri gerçekten kaydediyor. Daha önce açık kayıtlarda yanlış yazılan bilgiler (kira → kullanıcının "teknolojisi", araba sigortası → kullanıcının doğum günü) artık yazılmıyor.
- **C:** İç etiketler yanıtlarda görünmüyor.
- **Sonuç:** Son kodla gerçek modelde 48 konuşmanın **48'i** geçti; veritabanında yanlış kişiye kayıt yok. Bu fazda yanıtları elle okurken Faz 7.1 denetiminin kaçırdığı üç kayıt iddiası kalıbı daha buldum (dört yanıtta) ve düzelttim (§7). Son kodla yapılan koşularda kaçak yok.

---

## 1. Üç sorunun kök nedeni

Kod değiştirmeden önce her sorunu gerçek Gemma ile, modelin ham JSON çıktısını kaydederek yeniden ürettim.

### Sorun A — aynı mesajdaki adaşlar

"İki Ahmet tanıyorum: biri komşum, diğeri iş arkadaşım."

- **Model doğru çıkarıyordu.** Gemma'nın çıktısında iki ayrı ilişki vardı (komşu Ahmet, iş arkadaşı Ahmet); üç Ayşe ve iki Mehmet örneklerinde de durum aynıydı.
- **Hata bizdeydi.** Bir mesajdan çıkan her aday veritabanına karşı **tek tek** çözümleniyordu. İkinci Ahmet, aynı mesajdan bir an önce oluşturulan birinci Ahmet'le karşılaşıyordu. Sonuç ya "hangi Ahmet?" sorusu oluyordu ya da (ad slotlarda tekrar edilince) iki ilişki **tek bir Ahmet'e** bağlanıyordu, yani iki farklı insan birleştiriliyordu.
- **Aynı mekanizmanın başka sonuçları:**
  - "İki Mehmet: biri öğretmen, diğeri mühendis" tek Mehmet'te değer çatışmasına dönüşüyordu.
  - "Ahmet hem komşum hem iş arkadaşım" (tek kişi) gereksiz bir soru üretiyordu.
- **Sonraki yanlış kayıt:** "Ahmet'in doğum günü 5 Mayıs" sorulmadan kaydedildi. Çünkü depoda tek Ahmet vardı ve çözümleyici "tek eşleşme"yi kabul ediyordu.

### Sorun B — "Lütfen şunu not al"

- **Algılama doğruydu;** "not al" ifadesi tanınıyordu. Aynı mesaj "Bunu unutma: …" diye yazıldığında da aynı şekilde başarısız oluyordu.
- **Sorun açık kayıt çağrısındaydı.** Bu çağrının talimatı, arka plan öğrenmesinin kurallarının örneksiz, kısaltılmış bir hâliydi. Gemma işe yaramaz öğeler döndürüyordu: Burak'ın düğünü için `predicate: "device"`, `relation: "attended"`. Doğrulama bunları atıyordu ve sonuç `nothing` oluyordu.
- **Daha kötüsü, geçen öğeler yanlıştı:**
  - "kira her ayın beşinde ödeniyor" → **kullanıcının** `technology` bilgisi;
  - "arabanın sigortası mart ayında bitiyor" → **kullanıcının** `birthday: mart` bilgisi. Tek değerli olduğu için gerçek doğum gününün yerine geçebilirdi.
  - Nedeni: küçük harfle başlayan bir "kişi" adı kullanıcı sayılıyordu.
- **Aynı mesajın arka plan çıkarımı doğruydu** (`event`, "düğünü haziranda"): aynı model ve aynı önek, ama tam öğrenme talimatı.

### Sorun C — "HAFIZA İŞLEMİ" etiketi

- Etiketin kaynağı kişiliğin kendi kuralıydı: "Hafızana kaydettiğini … yalnızca mesajdaki **'HAFIZA İŞLEMİ' bildirimi** bunu söylüyorsa söyle."
- Model, neleri hatırlayabildiği sorulduğunda bu kuralı kullanıcıya aktarıyordu. Bir yanıt, mesajda bildirim olmadığı hâlde "HAFIZA İŞLEMİ: …" diye başladı.
- Bildirimlerin kendisi yalnızca o anki mesajla gidiyor ve geçmişe hiç kaydedilmiyor (testlerle doğrulandı).

## 2. Değiştirilen dosyalar

| Dosya | Değişiklik |
|---|---|
| `core/src/lazis/memory/namesakes.py` (yeni) | Adaş ifadelerinin okunması, mesaj içi kimlik planı |
| `core/src/lazis/memory/commands.py` | Açık kayıt talimatı ve şeması, ifade sözlüğü, "hangisi?" yanıtı, iptal, yanlış kişi düzeltmesi, "zaten kayıtlı", doğal bildirim dili |
| `core/src/lazis/memory/extraction.py` | Doğrulama sıkılaştırması (nesne ≠ kullanıcı), "X ve Y benim …lerim" okuyucusu, talimata istek notu |
| `core/src/lazis/memory/models.py`, `resolver.py`, `service.py`, `relationships.py` | `EntityRef.planned`: planlanmış kimlik yeniden çözümlenmiyor |
| `core/src/lazis/conversation/engine.py` | Açık kayıt akışı, sohbette "hangisi?" yanıtı, son seçim (bellekte) |
| `core/src/lazis/conversation/learning.py` | Arka plan öğrenmesinde adaş planı |
| `core/src/lazis/memory/claims.py` | `save_cancelled` durumu, "choose" isteği |
| `core/src/lazis/memory/graph.py` | Belirsiz adla ilgili ilişki sorusunda cevap verilmiyor, önce soruluyor |
| `core/src/lazis/personality/persona.py`, `conversation/prompts.py` | Etiket adları kaldırıldı; notların görünmez olduğu ve hafızanın dürüst tarifi eklendi (`persona-v3`, `p72-v1`) |
| `core/tests/…` (5 yeni dosya, 4 güncellenen) | §8 |
| `evals/runners/p72_identity.py`, `p72_perf.py` (yeni) | Gerçek model ve maliyet ölçümü |
| `docs/adr/0018-…`, `MEMORY_ARCHITECTURE.md` (P7.2), `DEVELOPMENT_ROADMAP.md` | Belgeler |

**Değişmeyenler:**

- arka plan öğrenmesinin çıkarım politikası ve talimatı;
- öğrenme kuyruğu ve zamanlaması;
- grafik depolaması ve sorguları;
- hatırlama;
- veritabanı şeması;
- Faz 7.1 iddia denetimi.

## 3. Kimlik eşleştirme düzeltmesi

**İlke.** Hangi adaşın kastedildiğine modelin güveni değil, **kullanıcının sözleri** ya da **kullanıcının yanıtı** karar veriyor.

**Kullanıcının sözlerinden plan** (`namesakes.py`, model çağrısı yok). Her yazma işleminden önce mesaj okunuyor:

- **Sayılmış adlar:**
  - "iki/üç/dört X", "X adında/isminde iki …", "iki tane / farklı / ayrı X";
  - soyadlar ("İki Ahmet Yılmaz"), Türkçe harfler, takma adlar.
- **Slotlar:**
  - "biri …, diğeri …", "ilki …; ikincisi …", "kuzenim, komşum ve iş arkadaşım";
  - bir sonraki cümle "Biri …" diye devam ediyorsa o cümle de.
  - Slot sayısı kullanıcının söylediği sayıya eşit değilse slotlar kullanılmıyor.
- **Tek kişi, birden çok rol:** "X hem … hem …", "aynı zamanda".

Her slot ya kullanıcıyla bir ilişkidir ("komşum" → komşu, "eski iş arkadaşım" → iş arkadaşı, etiketi "eski iş arkadaşı") ya da bir tanımdır ("öğretmen").

**Planın kuralları:**

| Durum | Ne yapılıyor |
|---|---|
| Bir aday hangi slota ait? | Önce alıntısına, sonra ilişki türüne, sonra değerine bakılarak o slotun kişisine bağlanıyor |
| Slotun kişisi | Depodaki adaşlardan slotun sözlerinin tek başına tanımladığı kişi; yoksa kullanıcının sözlerinden yeni kişi |
| Slot kişileri birbirine göre | "Farklı kişiler" olarak işaretleniyor; bir daha birleştirilemiyorlar |
| Model bir slotu atladı | Kişi yine oluşturuluyor; depoda kullanıcının söylediğinden az kişi kalmıyor, çıplak "Ahmet" sonra soru soruyor |
| Hiçbir slota uymayan aday | Çözümleyiciye bırakılıyor; çözümleyici artık adaşları gördüğü için soruyor |
| Kişi sayısından fazla tanım, ya da bir slota birden çok kayıtlı adaş uyuyor | Plan yapılmıyor; eskisi gibi soruluyor |

Plan hem arka plan öğrenmesinde hem açık kayıtta çalışıyor ve kendi değişiklik kümesine yazılıyor (geri alınabilir).

**Ek dilbilgisi okuyucusu** (gerçek modelle bulundu, §7): "Ahmet ve Mehmet benim iş arkadaşlarım" cümlesinde model yalnızca Ahmet'i çıkardı. "Mehmet benim eski iş arkadaşım, bunu unutma" cümlesine "Mehmet — ex_partner — Mehmet" yanıtını verdi. `stated_predicate`:

- ad listesini ("Ahmet, Mehmet ve Ali"), "benim" sözcüğünü ve "eski / en iyi" gibi niteleyicileri okuyor;
- tümcenin sonundaki birinci şahıs ilişki adını ("arkadaşlarım", "kuzenim") okuyor;
- modelin yanıtı listedeki adlardan birini anıyorsa, listedeki her ada o ilişkiyi veriyor;
- bir kişiyi kendisiyle ilişkilendiren okumanın yerine bunu koyuyor.

**Sohbette "hangisi?"** Belirsiz bir açık kaydın bildirimi seçenekleri listeliyor ("Ahmet (komşusu); Ahmet (iş arkadaşı)"). Model de şöyle soruyor:

> "Hangi Ahmet'ten bahsediyorsunuz efendim? Komşunuz olan mı, iş arkadaşınız olan mı?"

Kayıt bekleyen kutusunda (`memory_inbox`) duruyor. Bir sonraki mesaj:

| Mesaj | Sonuç |
|---|---|
| Kısa bir yanıt (en çok 7 sözcük), içerik sözcükleri tek bir seçeneği gösteriyor ve fazlası yok ("Komşum olan.", "Mühendis olan Mehmet.") | Kayıt, Hafıza ekranının kullandığı yolla (`service.resolve_inbox`) **yanıttan önce** doğru kişiye yazılıyor; model çağrısı yok |
| "Vazgeç / hiçbiri / iptal" | Bekleyen kayıt iptal ediliyor; "kaydetmedim" deniyor |
| Birden çok seçeneğe uyuyor | Yeniden soruluyor |
| Yeni bir cümle ("Komşum Ahmet yarın gelecek.") | Yanıt sayılmıyor; soru açık kalıyor |
| Başka bir konuşmadan gelen ya da 30 dakikadan eski bir soru | Hiçbir zaman tahminle uygulanmıyor; Hafıza ekranında kalıyor |
| Bir yanıtın hemen ardından "Hayır, iş arkadaşım olan." | Bilgi yanlış kişiden siliniyor ve doğru kişiye yazılıyor (iki ayrı değişiklik kümesi) |

**Belirsiz adla ilişki sorusu** (`b0e1947`, regresyonda bulundu):

- Durum: "İş ortağımın adı da Ahmet." dendikten sonra "Ahmet'in kardeşi kim?" soruluyor.
- Grafik daha önce kayıtlı Ahmet'in cevabını ("Mehmet") bir uyarıyla birlikte veriyordu. Bir regresyon koşusunda model uyarıyı yok sayıp sormadan cevapladı.
- Artık cevap, hangi Ahmet olduğu netleşene kadar bloğa hiç konmuyor. Bloğa yalnızca "Cevap verme; önce hangisini kastettiğini sor: kayıtlı olan (Ahmet (çocukluk arkadaşı)) mı, yoksa başka biri mi?" satırı giriyor.
- Kullanıcı hangisi olduğunu söyleyince bir sonraki soru normal yanıtlanıyor.

**Yeniden başlatma:**

- Soru veritabanında kaldığı için yeniden başlatmadan sonra korunuyor ve süre içinde verilen yanıt çalışıyor.
- Yeniden başlatma hiçbir şeyi otomatik kaydetmiyor.
- Yanlış kişi düzeltmesi için son seçim yalnızca bellekte tutuluyor; kapanmış bir kutu öğesi gizlilik gereği metin saklamıyor. Yeniden başlatmadan sonra bu düzeltme normal yoldan yapılır.

## 4. Açık kayıt komutları düzeltmesi

| Değişiklik | Ayrıntı |
|---|---|
| **Talimat** | Açık "kaydet" isteği artık arka plan öğrenmesinin talimatını kullanıyor: Faz 6 altın setinde 40/41 ölçülen kurallar ve örnekler, bilinen kişiler ve açık sorular. Başına bunun açık bir istek olduğunu söyleyen kısa bir not ekleniyor. Model önce `action` ("remember" / "none") alanını yazıyor, böylece "Kaydet butonuna bastım" gibi mesajları reddedebiliyor. Düzeltme ve silme eski talimatla devam ediyor. |
| **Çıplak istek** | "Bunu unutma." tek başına yazılırsa bir önceki kullanıcı mesajı kaydediliyor ve o mesajın arka plan işi atlanıyor. Öncesinde mesaj yoksa model çağrısı yapılmadan "neyi kaydetmemi istersiniz?" yolu izleniyor. |
| **Desteklenen ifadeler** | Görevdeki 11 ifadenin tamamı, artı "not alır mısın", "kaydeder misin", "kayda geçir", "kayıt altına al", "aklının bir köşesinde olsun", "bir kenara yaz", "hatırlayın", "kaydını tut", "kaydetmelisin"… "Bu bilgiyi unutmanı istemiyorum" artık silme değil kayıt. |
| **Kayıt sayılmayanlar** | Tırnak içi metin ("'Bunu not al' ifadesini çevir"), "toplantı notu hazırla", "not almak için uygulama", "dosyayı kaydettim", "nereye kaydetsem", "kaydetme", "kaydetmeliyim". |
| **Doğrulama** (iki yolda da) | Bir nesne ("kira", "araba sigortası") hiçbir zaman kullanıcının kendi bilgisi olarak yazılmıyor, kullanıcının notu oluyor. Kullanıcının tek değerli profil bilgisi (doğum günü, şehir, meslek) mesajda birinci şahıs gerektiriyor: "doğum günü 5 Mayıs" sahipsizdir, "doğum günüm 5 Mayıs" değildir. Açık istekte alıntısı doğru ama yüklemi yanlış bir öğe atılmıyor, not olarak saklanıyor. |
| **Zaten kayıtlı** | Arka planda az önce öğrenilmiş bir bilgi için "Bunu unutma." dendiğinde "kaydedemedim" değil, "kaydedildi (zaten kayıtlıydı)" deniyor. |
| **Bildirim dili** | "teknik bir hata nedeniyle yapılamadı" yerine "Bunu şu anda kaydedemedim efendim". |

**Akış** (görev §2.3):

1. içerik belirleniyor;
2. içerik yoksa soruluyor;
3. varlıklar çözümleniyor;
4. adaş belirsizliği kontrol ediliyor;
5. gizli bilgi kuralı (şifre, kart, IBAN) model çağrısından önce uygulanıyor;
6. hassas bilgi, istendiğinde kaydediliyor;
7. yazma işlemi;
8. başarı ancak commit'ten sonra bildiriliyor (Faz 7.1 denetimi bunu yanıt metninde de güvenceye alıyor).

**Korunan Faz 6–7 politikaları:**

- güvenilmeyen model yazmıyor;
- alıntı kanıtı kontrol ediliyor;
- unutulan konular yeniden öğrenilmiyor;
- belirsizlikte bekleniyor.

## 5. İç etiket sızıntısı düzeltmesi

**Kökten düzeltme, filtre yok:**

- Kişilik artık "mesajın başındaki sistem notu" diyor ve etiket adını hiç kullanmıyor.
- Yeni kural: "Sistemin mesajlara eklediği notlar ve hafıza kayıtları kullanıcıya görünmez: başlıklarını, adlarını ya da biçimlerini yanıtında anma; içeriklerini kendi doğal cümlelerinle kullan. Kullanıcı teknik yapını sorarsa dürüstçe ve genel hatlarıyla anlatabilirsin."
- Hafıza sorulduğunda dürüst tarif: "kullanıcının paylaştığı kişisel bilgileri zamanla hafızana alırsın, 'bunu unutma' gibi isteklerde hemen kaydedersin, kayıtlar Hafıza ekranında görülüp düzeltilebilir."
- Konuşma kuralları da hatırlama bloğunun adını anmıyor.
- Bildirim başlığı "=== SİSTEM NOTU (kullanıcıya görünmez) ===".

Yanıtlardan etiket silen bir filtre eklemedim. Sorunun kaynağı istemdeydi; o düzeltilince gerçek model testlerinde etiket görünmedi (§7). Bir filtre, sorun yeniden ortaya çıkarsa onu görünmez kılardı.

**Örnek** (gerçek model, "Tariflerimi hatırlar mısın?"):

> "Şu ana kadar bana herhangi bir tarif paylaşmadınız, bu yüzden hatırladığım bir kayıt bulunmuyor. Eğer tariflerinizi paylaşırsanız onları hafızama alabilir ve dilediğiniz zaman size yardımcı olabilirim."

## 6. Veritabanı bütünlüğü

- **Migration yok;** tablolar aynı. `EntityRef.planned` yalnızca bellekteki aday nesnesinde.
- **Değişiklik kümeleri:** her plan, kayıt, iptal ve düzeltme bir değişiklik kümesinde yazılıyor; geçmişte görünüyor ve geri alınabiliyor.
- **Ayrı kişiler:** kullanıcının ayrı dediği kişiler `memory_entity_distinctions` tablosuna yazılıyor. "Bu iki Ahmet aynı kişi" isteği reddediliyor (test edildi).
- **Bekleyen kayıt:** `memory_inbox` içinde duruyor; kapanınca metni siliniyor (Faz 6 kuralı).
- **Gerçek model değerlendirmesi** her konuşmayı veritabanının son durumuyla ölçtü: kaç kişi var, hangi ilişkiyle, bilgi hangi kayıtta (kimlik numarasıyla), belirsizken hiçbir yere yazıldı mı.

## 7. Gerçek Gemma testleri

`evals/runners/p72_identity.py`. 48 sentetik konuşma, her biri kendi geçici profilinde, üretim motoruyla:

| Kategori | Konuşma | İçerik |
|---|---|---|
| Adaş | 18 | iki/üç adaş, iki cümleli tanıtım, meslekle ayrım, farklı adlar, aynı kişinin iki rolü, farklı mesajlarda adaş, iptal, yanlış kişi düzeltmesi, belirsizken bilgi bildirimi, soyad, Türkçe harf, "adında", alakasız yeni cümle, **yeniden başlatma**, aynı ilişkide iki kişi |
| Açık kayıt | 18 | görevdeki ifadeler, nesneler (kira, sigorta), çıplak "Bunu unutma", ilişki kaydı, kayıt dışı "not" ifadeleri (3), şifre, kayıt hatası (komut modelinin yanıtı bilerek bozuldu), boş içerik |
| İç etiket / doğal yanıt | 12 | tarif, hafıza ve yetenek soruları, teknik mimari sorusu, ilişki, proje ve tercih hatırlama, hata bildirimi, boş istek, tarif kaydı |

**Her turda ayrıca kontrol edilenler:**

- Faz 7.1 iddia denetimi: akışın hiçbir anında izinsiz kayıt iddiası yok, gösterilen ile saklanan metin aynı;
- iç etiket taraması.

| Koşu | Geçen | Gösterilen yanlış iddia | Etiket | Gösterilen ≠ saklanan | Yanlış kişiye kayıt |
|---|---|---|---|---|---|
| 1. tur (`c128370`) | 44/48 | 0 / 74 tur | 0 | 0 | **0** |
| 2. tur (`8003c84`) | 48/48 | 0 / 74 tur | 0 | 0 | 0 |
| 3. tur (`9da39c9`) | 48/48 | **2 / 74 tur** (elle bulundu) | 0 | 0 | 0 |
| 4. tur (`700b4e0`) | 48/48 | **1 / 74 tur** (elle bulundu) | 0 | 0 | 0 |
| 5. tur (`d8998b5`) | 48/48 | 0 / 74 tur (elle de okundu) | 0 | 0 | 0 |
| **6. tur (son kod, `ecbc44d`)** | **48/48** | **0 / 74 tur** (elle de okundu) | **0** | **0** | **0** |

**1. turdaki 4 başarısızlık** (hepsini veritabanı durumundan inceledim):

- **n06** "Ahmet ve Mehmet benim iş arkadaşlarım.": model yalnızca Ahmet'i çıkardı; Mehmet hiç oluşmadı. Yanlış birleştirme yok, ama bilgi eksik. → `8003c84` ile kullanıcının dilbilgisinden okunuyor.
- **c12** "Mehmet benim eski iş arkadaşım, bunu unutma.": açık kayıt çağrısı "Mehmet — ex_partner — Mehmet" döndürdü, kayıt yapılmadı, LAZIS doğru biçimde "kaydedemedim" dedi. Arka plan öğrenmesi ilişkiyi sonradan doğru yazdı. → `8003c84` ile düzeltildi.
- **c10** (kedinin adı): bilgi ilişki olarak (Selin → Duman) doğru kaydedildi. Değerlendirmem yalnızca bilgilere bakıyordu; ilişkileri de kapsayacak biçimde düzelttim.
- **c17** (bilerek bozulmuş kayıt): yanıt doğru biçimde "Bunu şu anda kaydedemedim efendim" dedi. Bilgiyi arka plan öğrenmesi sonradan kaydetti. Bu, Faz 6'dan beri tasarım gereği. İlk ölçütüm bunu hata sayıyordu; ölçütü "istek kayıt yapmadı ve yanıt bunu söylüyor" olarak düzelttim. Sonradan öğrenildiği raporda ayrıca yazılı.

**Örnekler** (gerçek model, 1. tur):

- "İki Ahmet tanıyorum. Biri komşum, diğeri iş arkadaşım." → veritabanında Ahmet (komşusu) ve Ahmet (iş arkadaşı), "farklı kişiler" işaretli.
- "Ahmet'in doğum günü 5 Mayıs, bunu unutma." → "Hangi Ahmet'ten bahsettiğinizi netleştirebilir miyim efendim? Komşunuz olan Ahmet'in mi, yoksa iş arkadaşınız olan Ahmet'in mi doğum günü 5 Mayıs?" (hiçbir Ahmet'e yazılmadı)
- "Komşum olan." → "Kaydettim efendim. Komşunuz olan Ahmet'in doğum gününün 5 Mayıs olduğunu hafızama ekledim." (yalnızca komşu Ahmet'te; 2 ms, model çağrısı yok)
- "Hayır, iş arkadaşım olan." → bilgi taşındı.
- "Ayşe'nin doğum günü 1 Ocak, not al." → model "Anladım efendim, not aldım. Ancak … hangisi?" yazdı; kullanıcı "Anladım efendim, **henüz kaydetmedim**. Ancak … hangisi?" gördü (Faz 7.1 denetimi).
- "Not al: banka kartımın şifresi 4471." → kaydedilmedi, model çağrısı yapılmadı.

**2. tur (kabul ölçümü):** 18 adaş, 18 açık kayıt ve 12 iç etiket konuşmasının hepsi geçti. Bütün yanıtları tek tek okudum.

- Model ham metninde 9 yanıtta izinsiz "not ettim / kaydettim" yazdı. Faz 7.1 denetimi hepsini yeniden ifade etti; kullanıcıya ulaşan 0.
- Belirsiz her kayıtta LAZIS doğru seçeneklerle sordu ve hiçbir kişiye yazmadı. Yanıttan sonra bilgi yalnızca kastedilen kişiye yazıldı (kimlik numarasıyla doğrulandı).
- "Ahmet ve Mehmet benim iş arkadaşlarım" iki kişi oldu. "Mehmet benim eski iş arkadaşım, bunu unutma" kaydedildi ve ancak bundan sonra "kaydettim" dendi.
- c17: bozuk kayıt isteğinde yanıt "Bunu şu anda kaydedemedim efendim" idi; bilgi sonradan arka plan öğrenmesiyle kaydedildi (§11-5).

**3. turdaki kaçak.** Son iki düzeltmeden sonra (`b0e1947`, `9da39c9`) koşuyu tekrarladım: yine 48/48. Ancak yanıtları tek tek okurken iki bekleyen kayıtta (n04, n14) kullanıcının şunu gördüğünü fark ettim:

> "Anladım efendim, **notumu aldım**. Ancak … hangi Ayşe?"
> "**Notumu aldım** efendim. Bu doğum günü hangi Çağla'ya ait?"

Kayıt yapılmamıştı. Birinci şahıs iyelik eki ("notumu") ne Faz 7.1 kurallarında ne de değerlendirmenin sözcük listesinde vardı, bu yüzden otomatik sayım 0 gösterdi.

- `700b4e0`: "not" ve "kayıt" sözcüklerinin bütün iyelik ve belirtme biçimleri kapsandı; değerlendirmenin sözcük listesi de aynı biçimde genişletildi.
- Bütün önceki koşular (1.–3. tur, Faz 7.1 koşuları) genişletilmiş listeyle yeniden tarandı. Başka kaçak yalnızca bu iki yanıttı.
- Düzeltilmiş kodla 4. turu koştum.

**4. turdaki kaçak ve eksik kayıt.** 4. tur da 48/48 ve otomatik sayımda 0 gösterdi. Elle okurken iki sorun daha buldum:

- **Kaçak (n03, kayıt bekliyor):** "Anladım efendim, **kayıtlarım arasına ekledim**. Ancak … hangi Mehmet?" Depolama sözcüğü ile fiil arasına bir edat ("arasına") girince kural tanımıyordu. → `d8998b5`: edatlı depolama yerleri ("kayıtlarım arasına", "hafızamın bir köşesine") kapsandı. Değerlendirme listesine bunlar ve genel olarak "ekledim" de eklendi (LAZIS'in bir şey ekleyebileceği tek yer hafızası).
- **Eksik kayıt** (Faz 7.1 değerlendirmesinde): "Aklında olsun, hafta sonu annemlere gideceğim." Model isteği kabul etti ama öğe önermedi (geçici plan saydı). Kayıt yapılmadı ve LAZIS doğru biçimde "kaydedemedim" dedi. → `d8998b5`: model isteği kabul edip hiçbir öğe önermezse kullanıcının kendi sözleri not olarak saklanıyor. Not da her öğe gibi denetleniyor: alıntı, gizli bilgi, talimat.
- Bütün koşular genişletilmiş listeyle yeniden tarandı. Kaçak yalnızca yukarıda sayılan yanıtlardı (Faz 7.1'in 1. turundaki "Notunuzu aldım" o raporda zaten yazılı).

**5. tur ve bir kaçak daha.** 5. tur 48/48; yanıtları tek tek okudum, kaçak yok. Aynı kodla koşulan Faz 7.1 iddia değerlendirmesinde ise bozuk bir kayıttan sonra şu yanıt kullanıcıya ulaştı:

> "Bunu şu anda kaydedemedim efendim. Ancak … dişçi randevunuzun … olduğunu **not etmiş oldum**."

Geçmiş zamanın "-miş oldum" biçimi kapsanmıyordu. → `ecbc44d`: bir hafıza fiilinin "-miş oldum / -miş olduk" biçimi tamamlanmış eylem sayılıyor; değerlendirme listesine de genel biçimde eklendi.

**Son durum (kabul ölçümü, `ecbc44d`):**

- 6. tur 48/48: 0 gösterilen iddia, 0 etiket, gösterilen ile saklanan her turda aynı, yanlış kişiye kayıt yok.
- Faz 7.1 iddia değerlendirmesi: 44 turda 0 gösterilen iddia; ham metindeki 7 iddianın hepsi yeniden ifade edildi.
- Her iki koşunun bütün yanıtlarını tek tek okudum; kaçak görmedim.

## 8. Otomatik testler

`make check`: **yeşil** (son çalıştırma `ecbc44d` üzerinde: Python 1347, UI 113 + 7, Rust 30 + 9). Not: bir çalıştırmada, gerçek model değerlendirmesi aynı anda çalışırken, zamanlamaya duyarlı bir ön ısıtma testi (`test_prewarm_warms_the_cache_and_the_next_turn_reports_warm`) bir kez başarısız oldu. Tek başına 3/3 geçti; tam çalıştırma yeniden yapıldı ve yeşil.

| Grup | Sayı | Dosya |
|---|---|---|
| **Adaş testleri** | **139** | `test_namesakes.py` (114: 54 cümle tablosu, 48 üretilmiş iki-adaş bileşimi, etiketler, "X ve Y benim …lerim" okuyucusu), `test_namesakes_in_chat.py` (25 uçtan uca, veritabanı durumuyla) |
| **Açık kayıt testleri** | **109** | `test_memory_requests.py` (77: 34 kayıt ifadesi, 20 kayıt dışı ifade, çıplak istek, şema, doğrulama, kendi öznesi olan işyeri), `test_memory_requests_in_chat.py` (32 uçtan uca) |
| **İç etiket testleri** | **31** | `test_internal_labels.py` (30 konuşma senaryosu + saklanan mesajlar) |
| Kişilik metni | güncellendi | `test_personality.py`: sistem isteminde hiçbir iç etiket yok |
| Faz 7.1 iddia denetimi | 278 (önce 263) | `test_memory_claims.py`: bu fazda bulunan bütün kalıplar ("notumu aldım", "kayıtlarım arasına ekledim", "not etmiş oldum", "Not defterime … ekledim") ve akış testleri |

**Uçtan uca testlerin kapsadığı durumlar:**

- iki ve üç adaş;
- modelin atladığı slot;
- model hiçbir şey döndürmediğinde kullanıcının sözleri;
- meslekle ayrım;
- tek kişinin iki rolü;
- farklı adlar;
- kayıtlı komşunun yeniden kullanılması;
- belirsiz kayıt;
- beş farklı yanıt biçimi;
- iptal;
- yanlış kişi düzeltmesi;
- yanıt sayılmayan yeni cümle;
- süresi geçmiş soru;
- **yeniden başlatma**;
- başka konuşmadaki soru;
- belirsizken bilgi bildirimi;
- "aynı kişi" isteğinin reddi.

## 9. Regresyon sonuçları

| Değerlendirme | Önceki (Faz 7.1) | Faz 7.2 | Yorum |
|---|---|---|---|
| Faz 5 kişilik (111 yanıt) | 108/111 | **110/111** | Kişilik metni değişti; sonuç daha iyi |
| Faz 5 kimlik soruları | 10/12 | 9/12 | Başarısızlıklar her zamanki gibi I1 ("neler yapabilirsin"); Faz 7'de de 9/12 |
| Faz 6 çıkarım altın seti | 40/41 (1 yanlış kayıt) | 38/41 → 40/41 → `9da39c9` ile **40/41** | 0 yanlış, 0 kritik (üç koşuda da); kalan E4 Faz 7.1'de de başarısızdı |
| Faz 6 oturumları | 53/56 | **55/56** | Kalan hata bilinen kararsız adım (restoran) |
| Faz 7 ilişki altın seti | 44/50 | **46/50** | 0 yanlış ilişki, 0 kritik |
| Faz 7 kabul oturumları | 54/54 | 51/54 → 53/54 → `9da39c9` ile **54/54** | aşağıda |
| Faz 7.1 erken kayıt filtresi | 0 gösterilen | Son kodla **0 gösterilen** (7 ham iddia, 7 yeniden ifade) | Ara bir koşuda 1 kaçak ("not etmiş oldum") bulundu ve düzeltildi (§7) |
| `make check` | yeşil | **yeşil** | §8 |

**İki zayıf sonucun incelenmesi.** İlk koşuda Faz 6 çıkarım 38/41, Faz 7 oturumları 51/54 çıktı. Başarısız vakaların hepsini modelin ham JSON'undan inceledim:

- Faz 6'daki üç vakada (E4, J1, S3) modelin kendisi eksik ya da farklı çıktı verdi. E4 Faz 7.1'de de başarısızdı. Yeni doğrulama kurallarının hiçbiri devreye girmedi.
- Faz 7'deki üç hatanın üçü de tek bir adımdaydı ("Artık Kervan'da çalışmıyorum, Atlas Yazılım'a geçtim."). Model bu kez hiç ilişki önermedi.

Değişen tek şey modelin önündeki kişilik metni olduğu için, iki değerlendirmeyi tekrar koştum ve eski kişilik metniyle bir karşılaştırma hazırladım:

- **Tekrar sonuçları:** Faz 6 çıkarım **40/41** (Faz 7.1 ile aynı, 0 yanlış kayıt). Faz 7 oturumları **53/54**; iş değişikliği adımı bu kez geçti, tek hata başka bir adımdaydı.
- **Karşılaştırma koşusu:** ilk denemem betiğimdeki bir yol hatası yüzünden çalışmadı. Düzelttikten sonra iş değişikliği senaryosunu eski ve yeni kişilik metniyle altışar kez sırayla koştum:
  - eski kişilik metni: **2/6** geçti;
  - yeni kişilik metni: **4/6** geçti.

  Yeni kişilik metni çıkarımı kötüleştirmiyor; bu adım modelin kendisine bağlı olarak oynuyor.
- **Bu adımın kalıcı düzeltmesi** (`9da39c9`): başarısız koşularda model iş değişikliğini "Atlas Yazılım — çalıştığı yer: Atlas Yazılım" (şirket kendi öznesi) diye yazıyordu ve bu öğe atılıyordu. Kullanıcı birinci şahısla konuşuyorsa ("geçtim", "çalışıyorum"; "Yazılım" gibi bir isim değil) bu artık kullanıcının işyeri sayılıyor ve mevcut yoldan iş ilişkisine dönüşüyor. Aksi hâlde eskisi gibi atılıyor; şirket adında bir kişi asla oluşmuyor. Düzeltmeden sonra aynı senaryo **6/6** geçti.
- **Tekrardaki hata gerçek bir sorundu:** "İş ortağımın adı da Ahmet." → "Ahmet'in kardeşi kim?" sorusuna model, kod "önce sor" demesine rağmen sormadan "Mehmet" dedi. Bu, fazın konusu olan kimlik güvenliğiyle ilgili. `b0e1947` ile cevap belirsizken hiç verilmiyor (§3). Düzeltmeden sonraki üç koşuda da LAZIS hangi Ahmet olduğunu sordu. Ancak model, kayıtlı Ahmet'in diğer kayıtlarından "kardeşi Mehmet" bilgisini yine de yanıtına ekleyebiliyor (§11-8).

## 10. Performans

| Ölçü | Sonuç |
|---|---|
| Normal sohbette ilk metin (denetim açık, ortanca) | 1.021 ms (TTFT 898 ms + 106 ms denetim). Faz 7.1: 1.099 ms; artış yok |
| Açık kayıt isteği (model çağrısı) | 8,3–16,3 sn (2. tur, 26 istek; ortanca ~13 sn). Faz 7.1'deki eski çağrı ~14 sn. Doğruluk için hızdan ödün verilmedi, süre de artmadı |
| Adaş belirsizliğinin tespiti | Belirsiz açık kayıtta toplam 15,8–16,5 sn; bunun neredeyse tamamı aynı model çağrısı. Belirlenimci plan ve çözümleme 1.000 kişilik depoda ortanca **0,24 ms**, en çok 1,35 ms |
| Bekleyen kaydın tamamlanması ("Komşum olan.") | **0–3 ms** (2. tur, 8 yanıt; model çağrısı yok) |
| Sıradan bir mesajda adaş okuması | ~10 µs |
| Yanıt eşleştirme | ~85 µs |
| Bellek | Adaş okuması en çok ~10 KiB (tracemalloc); süreç RSS'i Faz 7.1 ile aynı aralıkta |
| Her normal mesaj için ek model çağrısı | **yok** |
| Senkron öğrenme | **yok** |

## 11. Bilinen sınırlamalar

0. **İddia denetimi kalıplara dayanıyor.** Bu fazda gerçek modelde üç yeni kalıp daha bulundu ("notumu aldım", "kayıtlarım arasına ekledim", "not etmiş oldum"). Üçü de otomatik sayımda görünmedi; yanıtları elle okurken buldum. Kurallar ve değerlendirme listesi genişletildi, ama modelin yeni bir söyleyişi yine kaçabilir. Bu yüzden her gerçek model turunun yanıtları elle de okunmalı; bu fazda okundu.
1. **Açık kayıt yavaş:** 8–16 saniye. Süreyi model çağrısının kendisi belirliyor (uzun talimat ve JSON). Faz 7.1'deki eski çağrıyla aynı aralıkta. Kısaltmak ayrı bir iş (ör. talimatın önbelleğe alınması).
2. **Adaş okuması belirli Türkçe kalıpları tanıyor.** Kalıp dışı anlatımlar ("Ahmet'lerden biri", adı söylenmeyen ikinci kişi) çözümleyiciye düşüyor ve soru soruluyor; tahmin yapılmıyor.
3. **"Hangisi?" yanıtının sınırları:**
   - 30 dakika ve aynı konuşma sınırı var;
   - "ilki / ikincisi" gibi sıra sözcükleri seçenek seçmiyor (yanıttaki sıra modele bağlı);
   - yanlış kişi düzeltmesi yalnızca yeniden başlatmadan önce çalışıyor.
4. **Aynı ilişkide iki adaş** ("ikisi de iş arkadaşım"): ayrı kişiler olarak oluşturuluyor ama sözle ayırt edilemiyor. Belirsiz bilgi yazılmıyor; ayırt etmek için Hafıza ekranı gerekiyor.
5. **Bozuk açık kayıttan sonra arka planda öğrenme.** Açık kayıt başarısız olursa LAZIS bunu söylüyor, ama bilgi sonradan arka plan öğrenmesiyle kaydedilebiliyor (Faz 6 tasarımı). Kullanıcı bunu Hafıza ekranında görür.
6. **Üslup:** gizli bilgi yanıtı "kaydedemedim" diyor ("kaydetmem" daha doğru olurdu). Bir yetenek yanıtı "hatırlatabilirim" diyor (hatırlatıcı yok). Faz 7.1 denetiminin değiştirdiği bazı cümleler biraz yapay ("zamanla anladım").
7. **Model değişkenliği:** Faz 6 çıkarım ve Faz 7 oturumlarında tek koşuda 2–3 vaka oynayabiliyor (§9). Yanlış kayıt ya da kritik hata görülmedi. Kişilik metninin etkisi yalnızca iş değişikliği senaryosunda ölçüldü (eski metin 2/6, yeni 4/6).
8. **Belirsiz adla ilişki sorusu:** LAZIS hangi Ahmet olduğunu soruyor, ama model kayıtlı Ahmet'in cevabını ("kardeşi Mehmet") sorunun yanında söyleyebiliyor. Bu bilgi, o Ahmet'in hatırlanan diğer kayıtlarından geliyor. Yanlış bir kayıt yapılmıyor; yalnızca yanıt gereğinden fazla bilgi veriyor.

## 12. Kullanıcı kabul testleri

Uygulamayı yeniden başlatın (migration yok). Her adımdan sonra Hafıza ekranından veritabanı durumunu kontrol edebilirsiniz.

| # | Siz yazın | Beklenen |
|---|---|---|
| 1 | "İki Ahmet tanıyorum. Biri komşum, diğeri iş arkadaşım." | Hafıza ekranında **iki ayrı** Ahmet: komşusu ve iş arkadaşı |
| 2 | "Ahmet'in doğum günü 5 Mayıs, bunu unutma." | "Hangi Ahmet? Komşunuz mu, iş arkadaşınız mı?" sorusu; **hiçbir Ahmet'te doğum günü yok** |
| 3 | "Komşum olan Ahmet." | "Kaydettim"; doğum günü **yalnızca** komşu Ahmet'te |
| 4 | "Lütfen şunu not al: Murat'ın doğum günü 12 Haziran." | Tek bir Murat varsa (ya da hiç yoksa) kayıt başarılı; Murat'ın doğum günü görünür |
| 5 | "Bana toplantı notu hazırla." | Bir not taslağı ya da ayrıntı sorusu; **hafızaya kayıt yok** |
| 6 | "Tariflerimi hatırlar mısın?" | Doğal Türkçe yanıt; "HAFIZA İŞLEMİ" ya da başka bir iç etiket yok |
| 7 | "Mehmet benim eski iş arkadaşım, bunu unutma." | "Kaydettim" ancak kayıt yapıldıktan sonra; Mehmet eski iş arkadaşı olarak görünür |
| 8 | Adım 2'yi yeni bir adla tekrarlayın (ör. "İki Ece var: biri kuzenim, diğeri komşum." → "Ece'nin doğum günü 1 Ekim, not al."); soru gelince uygulamayı kapatıp açın; "Kuzenim olan." yazın | Kapatıp açınca hiçbir Ece'ye otomatik kayıt yok; soru Hafıza ekranında duruyor; yanıttan sonra doğum günü yalnızca kuzen Ece'de |
| Ek | Adım 3'ten sonra "Hayır, iş arkadaşım olan." | Doğum günü komşu Ahmet'ten kaldırılıp iş arkadaşı Ahmet'e taşınır |

## Kesin kabul koşulları

| Koşul | Durum |
|---|---|
| Aynı mesajdaki iki adaş ayrı kişiler | ✅ gerçek modelde ve testlerde |
| Aynı mesajdaki üç adaş | ✅ |
| Aynı kişinin birden çok rolü bölünmüyor | ✅ ("hem … hem", "aynı zamanda") |
| Belirsiz kişi bilgisi otomatik kaydedilmiyor | ✅ (veritabanında doğrulandı) |
| Kullanıcıdan açıklama isteniyor | ✅ (seçeneklerle) |
| Açıklama sonrasında doğru kişiye kayıt | ✅ (kimlik numarasıyla doğrulandı; yeniden başlatma dahil) |
| Yanlış kişi eşleştirmesi gerçek model testlerinde sıfır | ✅ 0 (altı tur, 288 konuşma) |
| "Lütfen şunu not al" çalışıyor | ✅ |
| Diğer desteklenen açık kayıt komutları çalışıyor | ✅ (görevdeki 11 ifade ve fazlası; testlerde gerçek yazma doğrulandı) |
| Kayıt dışı "not" ifadeleri yanlış algılanmıyor | ✅ |
| İç sistem etiketleri normal yanıtlarda görünmüyor | ✅ 0 (altı turda 444 gerçek model turu) |
| Faz 7.1 filtresi korunuyor; akışta yanlış iddia yok; gösterilen = saklanan | ✅ son kodla (6. tur ve Faz 7.1 değerlendirmesi, elle de okundu). Ara turlarda elle okumayla 4 kaçak bulundu ve düzeltildi (§7); gösterilen = saklanan her turda sağlandı |
| ≥ 100 adaş testi | ✅ 139 |
| ≥ 60 kayıt komutu testi | ✅ 109 |
| ≥ 30 iç etiket testi | ✅ 31 (+ gerçek modelde 12 konuşma) |
| ≥ 40 gerçek Gemma konuşması | ✅ 48 (altı tur) |
| Önceki fazların regresyonları | ✅ tamamlandı (§9). Faz 5–7 regresyonları `c128370`–`9da39c9` üzerinde koşuldu; sonraki commit'ler yalnızca iddia kurallarını ve açık kayıttaki not yedeğini değiştirdi, bunlar 6. turda ve Faz 7.1 değerlendirmesinde ölçüldü |
| `make check` başarılı | ✅ (Python 1347, UI 113 + 7, Rust 30 + 9) |
| Performans ölçümleri raporlandı | ✅ (§10) |
| Kullanıcının gerçek verileri değiştirilmedi | ✅ |
| Kodlar yerel commit edildi; push yok | ✅ |
| Faz 8'e başlanmadı | ✅ |

Onayınızı bekliyorum. Faz 8'e onayınız olmadan başlamayacağım.
