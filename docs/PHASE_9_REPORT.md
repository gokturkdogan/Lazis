# LAZIS — Faz 9 Raporu: Gelişmiş Otomatik Öğrenme, Hafıza Kalitesi ve Güvenilir Kişisel Bağlam

- **Durum:** Uygulandı ve gerçek modelle doğrulandı — **sahibinin kabul testi ve onayı bekleniyor.** Faz 10'a başlanmadı. Hiçbir şey push edilmedi.
- **Tarih:** 2026-10-28 / 29
- **Karar kaydı:** [ADR-0020](adr/0020-advanced-learning.md). Modüller, migration ve API: [MEMORY_ARCHITECTURE.md](MEMORY_ARCHITECTURE.md) Part P9. Geliştirici notları: [DEVELOPER_GUIDE.md §18](DEVELOPER_GUIDE.md).
- **Yerel commit'ler:**

| Commit | İçerik |
|---|---|
| `eec1ede` | Listeler eksiksiz okunuyor; geçmiş / güncel / gelecek; "X değil Y" düzeltmeleri; kanıt; JSON kurtarma; önem dereceleri; kalite önerileri; migration `0007_quality`; API |
| `57946fa` | Arayüz: öneriler, önem ve kaynak rozetleri, "Son 7 günde öğrenilenler" |
| `7cb916d` | A–F test grupları (bulduğu beş hatanın düzeltmesiyle), ADR-0020, belgeler, gerçek model çalıştırıcıları |
| `0381451` | Gerçek model değerlendirmesinin 1. turunda bulunanlar (Kervan/Atlas, ayrılınan yer, "bugün", tarihli niyet, içe aktarmada adaş satırı) |
| `3c7e1ef` | 2. turda bulunanlar: biten ilişki yalnızca kendisini kapatıyor; "bıraktım" bir değişiklik değil; ölçüm betiğinde sıkıştırma ayarı |
| `ee2c36a` | Düzeltilen ismin eki yeni isme uyuyor ("Eskişehir'da" → "Eskişehir'de") |
| `3fea95d` | 3. turda elle okurken bulunan: bir kişi hakkındaki geçmiş zaman, o kişiyle ilişkiyi bitirmiyor ("Kız kardeşim Elif eskiden İzmir'de yaşıyordu") |
| `87f3c97` | 3. turun Faz 7 oturum regresyonunda bulunan: "çalışmıyorum" ile söylenen işyeri hiçbir zaman güncel değil |
| `f0e682c` | Son koşuda bulunan: "Bilgiyi güncelledim" bir kayıt iddiası (Faz 7.1 koruyucusu) |
| son commit (`docs: phase 9 report …`) | belgeler, ölçüm raporları, bu rapor |

Bütün testler **sentetik kişi ve bilgilerle**, geçici ve şifreli veritabanlarında (rastgele anahtar, Anahtar Zinciri'ne yazılmadan) yapıldı. `default` ve `dev` profillerine, Anahtar Zinciri öğelerine ve Ollama ayarlarına dokunulmadı. Bulut API, telemetri ya da ikinci bir model eklenmedi.

---

## 1. Yönetici özeti

Faz 9, LAZIS'in sohbetten öğrendiklerinde **kimin, neyin ve ne zamanın** doğru olmasıyla ilgili. Değişiklikten önce talimattaki cümleleri gerçek Gemma ile arka plan öğrenmesinden geçirip veritabanını okudum (§2). Bulunan altı sorunun altısı da giderildi:

| Cümle | Faz 9'dan önce | Şimdi |
|---|---|---|
| "Ahmet'in iki kardeşi var: Mehmet ve Ali." | yalnızca Mehmet | Mehmet ve Ali |
| "Annemin üç kardeşi var: Ayşe, Fatma ve Zeynep." | kullanıcının üç kardeşi | annenin kardeşleri (teyze/dayı) |
| "Geçen yıl Kervan'da çalışıyordum, artık Pusula'dayım." | Kervan güncel, Pusula geçmiş (**ters**) | Pusula güncel, Kervan geçmiş |
| "Gelecek yıl İzmir'e taşınacağım." | güncel şehir İzmir | plan, zamanı "Gelecek yıl" |
| "Mehmet Ankara'da yaşıyor." → "Mehmet İstanbul'da yaşıyor." | Ankara sessizce değişti | LAZIS hangisinin doğru olduğunu soruyor |
| "Hayır, Ahmet değil Mehmet demek istedim." | ikisinde de doğum günü | doğum günü Mehmet'te |

Yeni olanlar kısaca:

- **Listeler:** Model bir listeyi yarım okursa, yalnızca eksik isimleri soran tek bir ek okuma yapılıyor. Söylenen sayı isimlerle uyuşmazsa ("üç kardeşi var: Mehmet ve Ali") kimse uydurulmuyor; sizin sözünüz not olarak kalıyor.
- **Zaman:** Cümlenin zamanı (eskiden / artık / -acağım) neyin bugün, neyin geçmiş, neyin plan olduğunu belirliyor. Söylediğiniz zaman ifadesi ("geçen ay", "2024'te") olduğu gibi saklanıyor, tarihe çevrilmiyor.
- **Çelişki:** "Artık", "taşındı" gibi bir değişiklik sözcüğü yoksa farklı bir değer eskisinin üstüne yazılmıyor; LAZIS soruyor.
- **Düzeltme:** "Hayır, X değil Y" son mesajın öğrettiğini düzeltiyor; Y birden fazla kişi olabiliyorsa soruyor.
- **Tekrar:** Kanıt olarak sayılıyor ama hiçbir zaman kesinlik vermiyor (güven en çok 0,95). Aynı mesajın yeniden okunması ikinci kanıt değil.
- **Önem dereceleri:** Hesaplanıyor; hiçbir zaman bir bilgiyi yazma nedeni değil.
- **Kalite önerileri:** Hafıza ekranında yalnızca öneri olarak gösteriliyor; hiçbir şeyi kendiliğinden değiştirmiyor.

**Kritik güvenlik koşulları — son kodla (`f0e682c`) yapılan koşularda sağlandı, ama değerlendirme sırasında üç ihlal görüldü.** Bu yüzden Faz 9'u "tamamlandı" olarak değil, **onayınıza sunulmuş** olarak bildiriyorum. Kabul kriterlerinin tamamı §17 sonundaki tabloda.

Son kodla:

- gerçek Gemma ile 68 konuşmada yanlış kişiye kayıt **0**, yanlış ilişki **0**, onaysız kayıt **0**, yanlış güncel değer **0** (çelişki konuşmaları koruyucu düzeltmesinden sonra yeniden: 10/10);
- Faz 7 oturumları 54/54, Faz 7.2 kimlik 48/48, Faz 8 içe aktarma 56/56 güvenli;
- kullanıcıya ulaşan dayanaksız kayıt iddiası **0** (Faz 7.1), iç etiket **0**.

Değerlendirme sırasında görülen ihlaller (her biri §13.3'te):

1. **Yanlış güncel işyeri** (Faz 7 oturumları, 3. tur): "Artık Kervan Lojistik'te çalışmıyorum, Atlas Yazılım'a geçtim" sonrasında Kervan yeniden güncel oldu, Atlas bitti. Faz 9'dan önce de var olan bir kod yolu; düzeltildi (`87f3c97`), gerçek modelde doğrulandı.
2. **Kullanıcıya ulaşan kayıt iddiası** (Gemma değerlendirmesi, son koşu, c07): "Bilgiyi güncelledim efendim", oysa hiçbir şey güncellenmemişti. Faz 7.1 koruyucusunda bir boşluk; düzeltildi (`f0e682c`), gerçek modelde doğrulandı.
3. **İç katmana gönderme** (Faz 7.2, 3. tur, l06): "… sistem notlarında belirttiğim gibi …". Model değişkenliği; aynı konuşma beş koşunun dördünde geçti. **Bunu deterministik olarak önleyen bir kural yok.**

Ayrıca bir **sınır durumu** var: c07'nin yeniden koşusunda model "Kervan bilgisini düzelterek bunu esas alıyorum" dedi. Bu bir iddia sayılmıyor ama yanıltıcı olabilir (§17-10).

Otomatik testler: **638 yeni test** (635 çekirdek, 3 arayüz); `make check` rc = 0.

**Doğrudan söylemem gerekenler:**

- Gerçek model değerlendirmesi üç tur ve son kodla bir koşu yaptı. Her koşudan sonra sonuçları elle okudum ve bulduklarımı düzelttim (§13.3). **İkinci turda düzeltmelerimden birinin yan etkisini buldum:** "Derya ile Kaan boşandılar" sonrasında evlilik bitmiyordu. Faz 7 ilişki altın setinde iki senaryo bu yüzden düştü. Kural daraltıldı ve üçüncü turda doğrulandı.
- **Değerlendirmenin denetimlerinin kaçırdığı bir hatayı ancak 3. turda gördüm:** "Kız kardeşim Elif eskiden İzmir'de yaşıyordu, artık Muğla'da" sonrasında **kardeşlik ilişkisi "bitti"** olarak yazılıyordu.
  - Üç turun üçünde de böyleydi. 1. ve 2. turda tabloları okudum ama bu konuşmanın ilişki durumunu gözden kaçırdım. Çalıştırıcı da bunu denetlemiyordu.
  - Bu, Faz 7.2 anlamında bir **yanlış ilişki durumu**; kişi doğru, ilişki türü doğru, ama durumu yanlış.
  - Düzeltildi (`3fea95d`), çalıştırıcıya bu konuşma için denetim eklendi. Son kodla doğru (§13.2).
- **Yukarıdaki 1. ihlali Faz 9'un kendi değerlendirmesi değil, Faz 7 regresyonu yakaladı:** Değerlendirmede bu tür bir olumsuz cümle yoktu.
- **İlk performans ölçümü geçersizdi:** 100 bilgilik ölçümde öğrenme hiç ilerlemedi. Neden ürün değil, ölçüm profilimdi: değerlendirme profili uzun sohbetin sıkıştırılmasını bir saat erteliyor, öğrenme de sıkıştırmanın arkasında bekliyordu. Ölçüm uygulamanın kendi ayarıyla yeniden yapıldı (§12).
- **Yoğun yükte sohbet yavaşlıyor:** 500 bilgilik yükte sohbetin ilk tokenı medyan 8 sn, en kötüsü 195 sn (§12). 20 ve 100 bilgide medyan 2–2,5 sn. Neden dökümlü yeniden koşuda öğrenmenin arkasındaki turlar en kötü 3,4 sn; yavaş turların hepsi arka plan sıkıştırmasının arkasındaydı (en kötü 62 sn). İlk koşunun 195 sn'sinin nedeni kaydedilmedi.
- **Kalan eksikler güvenli tarafta:** Model bazı bilgileri hiç önermiyor (§13.2, §17). Yanlış değil, eksik kayıt.
- **Aynı tercihin farklı sözlerle tekrarı** bazen 2–3 ayrı kayıt oluşturuyor. Kalite önerileri bunları "tekrar" olarak gösteriyor; LAZIS kendisi birleştirmiyor.

---

## 2. Mevcut sistem analizi

Faz 8 sonunda öğrenme hattı şuydu:

1. Model çağrısı (sohbetin önbellekteki öneki üzerinde).
2. Doğrulama: alıntı, isimler, ilişki sözcükleri (Faz 6–7.2).
3. Adaş planlaması.
4. Yazma: politika, tekrar, çelişki ve geçmiş.

Talimatın cümlelerini değişiklikten önce **gerçek modelle** arka plan öğrenmesinden geçirdim (geçici profiller) ve veritabanını okudum:

| Mesaj | Saklanan |
|---|---|
| "Ahmet'in iki kardeşi var: Mehmet ve Ali." (ve iki başka söyleyiş) | yalnızca Mehmet |
| "Annemin üç kardeşi var: Ayşe, Fatma ve Zeynep." | kullanıcının üç kardeşi |
| "Geçen yıl Kervan'da çalışıyordum, artık Pusula'dayım." | Kervan güncel, Pusula geçmiş |
| "Gelecek yıl İzmir'e taşınacağım." | güncel şehir İzmir |
| "İstanbul, Ankara ve İzmir'de yaşadım." | güncel şehir İstanbul |
| "Mehmet Ankara'da yaşıyor." → "Mehmet İstanbul'da yaşıyor." | Ankara sessizce değişti |
| "… sabah çalışmayı seviyorum" üç farklı söyleyişle | üç kayıt |
| "Hayır, Ahmet değil Mehmet demek istedim." | ikisinde de doğum günü |
| "Annemin üç kardeşi …" (başka bir koşu) | iş üç kez başarısız: modelin JSON'u sonuna doğru bozuldu, mesajdan hiç öğrenilmedi |

**Teşhis:** Sorunlar doğrulamada değildi. İkisi modelin listeler ve zamanla ne yaptığındaydı, diğerleri doğrulama ile yazma arasında olanlardaydı:

- Model, listelerin bir kısmını atlıyordu.
- Zaman kipi hiç okunmuyordu; "eskiden" ile "artık" aynı muameleyi görüyordu.
- Modelin "değişti" işareti, kullanıcının sözcükleri bunu söylemese de kabul ediliyordu.
- "X değil Y" bir istek olarak tanınmıyordu.
- Bozulan JSON, işin tamamen kaybedilmesine yol açıyordu.

**Mimari karar** ([ADR-0020](adr/0020-advanced-learning.md)): Doğrulamayla yazma arasına, **kullanıcının kendi sözlerinden** çalışan bir *iyileştirme* adımı eklendi. Bu adım hiçbir zaman bilgi ya da ilişki eklemiyor; yalnızca *ne zaman* ve *kimin* olduğuna karar veriyor. Model çağrısı sayısı yalnızca bir liste yarım okunduğunda artıyor.

```
1 çıkarım (tek model çağrısı, önbellekteki önek üzerinde)
2 bozuk JSON'un tam nesnelerinin kurtarılması          extraction.salvage
3 doğrulama (değişmedi)                                 extraction.validate*
4 liste bütünlüğü: yarım okunan liste için tek ek okuma (iş başına ≤ 2)   lists
5 iyileştirme: zaman, değişiklik sözcükleri, zaman ifadesi,
  başkasının akrabaları, geçici durumlar, bekleyen düzeltmeler           refine, temporal, corrections
6 adaş planlaması (Faz 7.2), sonra yazma                namesakes, orchestrator, service
```

---

## 3. Çoklu bilgi çıkarımı

**`memory/lists.py`:**

- **Listeyi bulma:** Listeler kullanıcının sözlerinde aranıyor: virgül ve "ve / ile / veya" ile bağlanan isimler ya da kısa değerler, öncesinde bir sayı ("iki kardeşi", "üç proje").
- **Ek okuma:** Model listenin bazı üyeleri hakkında bir şey çıkarıp diğerlerini atladıysa, öğrenme işi modele bir kez daha soruyor. Odaklı talimat listeyi, bulunanları ve eksikleri adıyla söylüyor. Yalnızca **eksik üyeler** hakkındaki yanıtlar tutuluyor ve olağan doğrulamadan geçiyor. İş başına en fazla iki ek okuma yapılıyor.
- **Sayı uyuşmazlığı:** "Üç kardeşi var: Mehmet ve Ali" gibi durumlarda kimse uydurulmuyor. Kullanıcının sözü o kişiyle ilgili bir not olarak kalıyor.
- **Reddedilen yol:** Bir ilişkiyi kuralla her isme yaymak. Liste başka bir şeyin nesnesiyse ilişki uyduruyor: "Ahmet'in kardeşi Mehmet ve Ali'yle tanıştım" cümlesinde Ali'yi de kardeş yapardı.

**Bozuk JSON:** Gemma'nın JSON'u sonuna doğru bozulduğunda, bozulmadan önceki tam nesneler kurtarılıyor (`extraction.salvage`). Düşen öğe ek okumayla geri gelebiliyor. Modelin cümle sonuna eklediği kalıntılar ("….causal_link_id_1") temizleniyor.

**Başkasının akrabaları:**

- "Annemin / babamın kardeşleri" → `parent_sibling` (teyze, dayı, hala, amca).
- Diğer "-(ı)mın X'i" kalıpları ("arkadaşımın kardeşi") kullanıcının ilişkisi sayılmıyor ve bırakılıyor.

**Sonuç:**

- Gerçek Gemma'nın 14 liste konuşmasının **14'ü** güvenli ve eksiksiz (§13).
- Gerçek modelde (3. tur), 14 liste konuşmasında 6 kez liste eksik okundu; ek okuma 4'ünü tamamladı. 1 kez sayı uyuşmazlığı not edildi; kimse uydurulmadı.
- Test grubu A: **184 test** (§14).

---

## 4. Zaman ve güncellik

**`memory/temporal.py` + `memory/refine.py`.** Alıntının içinde bulunduğu yan cümlenin zamanı okunuyor:

- **Yan cümle sınırları:** Yan cümle nokta ile ya da başka bir zamana dönen virgül / "ama" ile bitiyor; bir liste içinde bölünmüyor.
- **Geçmiş** ("eskiden", "önceden", "geçen yıl … -yordum", "-mıştım", "yaşadım / çalıştım") → **geçmiş kayıt**:
  - Bugünün değerinin yerini hiçbir zaman almıyor.
  - Aynı değer şu an güncelse, şimdi sona eriyor.
  - Bitiş tarihi uydurulmuyor.
- **Ayrılınan şey** ("Kervan'dan ayrıldım", "istifa ettim", "sigarayı bıraktım") → geçmiş.
  - Bu bir *değişiklik sözcüğü* değil. Gerçek modelde iki kez yanlış çıktı (§13.3).
- **Gelecek** ("-acağım", "gelecek yıl", "seneye", "yakında") → **plan**.
  - Tarihli bir niyet ("Seneye emekli olacağım") zamanıyla birlikte plan oluyor.
  - Tarihsiz bir dilek hedef olarak kalıyor.
- **Güncel:** Diğer her şey, olmuş bir değişiklik dahil ("taşındım", "geçen ay başlattım").
- **İlişkiler:** Geçmiş → `ended`, gelecek → `planned`.
  - Biten bir işyeri ya da yer yalnızca kendisini kapatıyor. "Artık Kervan'da çalışmıyorum, Atlas'a geçtim" sonrasında Atlas güncel kalıyor.
  - Aynı iki kişi arasındaki bir düzeltme ya da değişiklik ilişkiyi yine bitiriyor (boşanma, "aslında arkadaş değiliz").
  - **"Değil" ile söylenen işyeri, şehir ya da meslek hiçbir zaman güncel değil:** Değerin hemen ardından olumsuz sözcük geliyorsa ("Artık Kervan'da çalışmıyorum", "öğretmen değilim"), model onu bilgi olarak önerse bile "artık" ile geçmiş, onsuz hiç yazılmıyor (`87f3c97`).
  - **İki kişi arasındaki ilişki, cümle geçmiş zamanda diye bitmiyor:** "Kız kardeşim Elif eskiden İzmir'de yaşıyordu" cümlesindeki geçmiş, Elif'in nerede yaşadığıyla ilgili. İlişki ancak ilişki sözcüğünün kendisi geçmişteyse ("Ahmet eskiden komşumdu", "eski komşum") ya da kullanıcı birlikte ne olduklarını geçmiş zamanla söylüyorsa ("Burak'la arkadaştık", "birlikte çalışıyorduk") bitiyor (`3fea95d`).
- **Zaman ifadesi:** Kullanıcının ifadesi ("2024'te", "geçen ay", "Üç yıl önce") olduğu gibi saklanıyor; **hiçbir zaman tarihe çevrilmiyor**.
- **Geçici durumlar:** "Bugün / şu an / bu akşam" bir tercih ya da notla birlikte geçiyor ve kalıcılık sözcüğü yoksa ("hiç", "her zaman", "genelde") saklanmıyor.
  - "Bugün" başka bir şeyle ilgiliyse ("Ahmet bugün aradı, satranç kulübüne yazılmış") bilgi düşmüyor. Faz 6 altın seti E5 bunu yakaladı.

**Arayüz:** Geçmiş değerler Hafıza ekranında "geçmişte" rozetiyle görünüyor. Hatırlama, sona ermiş değerleri zaten geçmiş olarak veriyordu.

**Sonuç:**

- Gerçek Gemma'nın 14 zaman konuşmasında (3. tur) **13'ü** güvenli; yanlış güncel değer ve zaman hatası **0**. Kalan t11 bir denetim katılığı (§13.3).
- Test grubu B: **162 test** (§14).

---

## 5. Hafıza önem derecesi

**`memory/importance.py`:** Beş derece, saklanandan hesaplanıyor:

| Derece | Ne |
|---|---|
| `critical_personal` | ad, doğum günü, aile, sağlık ve para (hassas), iletişim, adres, ilişkiler; kullanıcının açıkça "not al" dediği her şey |
| `high` | iş, şehir, hedefler, planlar, projeler, diller, beceriler |
| `medium` | tercihler, alışkanlıklar, ilgi alanları, başkaları hakkındaki bilgiler |
| `low` | çıkarımın kendisinin düşük önemde gördüğü notlar |
| `ephemeral` | geçici durum ("bugün çok yorgunum"); arka plan öğrenmesi saklamıyor |

**Kurallar:**

- Önem **hiçbir zaman bir yazma nedeni değil**; yazmaya öğrenme politikası karar veriyor.
- Önem yalnızca sıralıyor: hatırlamada eşitlikleri bozuyor, kalite önerilerini sıralıyor, Hafıza ekranındaki rozetleri belirliyor ("çok önemli", "önemli").
- Bağımsız kaynaklar bir `medium` tercihi `high`'a çıkarabiliyor.
- Hiçbir tekrar bir bilgiyi `critical_personal` yapmıyor.

API: kayıt modelinde yeni `tier` alanı.

---

## 6. Tekrarlardan öğrenme

| Durum | Ne oluyor |
|---|---|
| Aynı mesaj (ya da içe aktarma öğesi) yeniden okunuyor | **İkinci kanıt sayılmıyor** (`add_evidence` False döndürüyor) |
| Başka bir mesaj aynı bilgiyi söylüyor | Yeni kaynak ekleniyor; güven kaynak başına 0,03 artıyor, **en çok 0,95**, hiçbir zaman kesinlik değil |
| Tekrar ile çelişki | Tekrar bir çelişkiyi çözmüyor; çelişki kendi yolundan soruluyor |
| Tekrar ile düzeltme | Tekrar bir düzeltmeye üstün gelmiyor |
| Aynı şey başka sözlerle | Modele, mesajla kök paylaşan kayıtlı tercih ve alışkanlıklar gösteriliyor; aynı şeyi söylüyorsa kayıtlı değeri kullanması isteniyor (kural 15) |

**Dürüst sonuç:** Son satır kısmen işe yarıyor.

- "Mimarım" / "Mesleğim mimarlık" tek kayıt.
- "Sabah çalışmayı seviyorum" / "En verimli olduğum saatler sabah" / "Önemli işlerimi genellikle sabah yaparım" ise üç turun üçünde de 2–3 kayıt oldu (r01, §13).
- Kalite önerileri bunları "tekrar" olarak gösteriyor (§11). Birleştirmek ya da birini unutmak sizin kararınız.
- Anlamsal birleştirme için ikinci bir model eklemedim (talimat gereği). Modelin değerlendirmesine dayanarak otomatik birleştirmeyi de, yanlış birleştirme riski nedeniyle yapmadım.

Test grubu C: **52 test** (§14).

---

## 7. Kaynak güvenilirliği

**Kaynak ile konu ayrımı** (Faz 6–7 doğrulaması korunuyor; Faz 9'da gerçek modelle yeniden ölçüldü):

| Cümle | Saklanmaması gereken | Gemma 3. tur |
|---|---|---|
| "Arkadaşım bana İstanbul'a taşınmamı önerdi." | kullanıcının şehri İstanbul | hiçbir şey yazılmadı ✅ |
| "Ahmet bana öğretmen olduğunu söyledi." | kullanıcının mesleği öğretmen | Ahmet öğretmen ✅ |
| "Annem doktor olmamı isterdi." | kullanıcının mesleği doktor | hiçbir şey yazılmadı ✅ |
| "Bir gün Japonya'ya taşınsam nasıl olurdu?" | kullanıcının şehri Japonya | hiçbir şey yazılmadı ✅ |
| "Mehmet, Ali'nin avukat olduğunu söyledi." | Mehmet avukat | hiçbir şey yazılmadı (Ali'nin mesleği de eksik) |
| "Galiba Elif Bursa'da yaşıyor." | kesin bilgi | Elif Bursa, güven 0,55 ("kesin değil") ✅ |
| "Kitapta 'İzmir'de yaşıyorum' diye bir cümle vardı." | kullanıcının şehri İzmir | hiçbir şey yazılmadı ✅ |
| "Doktorum bana günde iki litre su içmemi söyledi." | kullanıcının alışkanlığı | hiçbir şey yazılmadı ✅ |

- **Kaynak sayısı:** Her kayıt bağımsız kaynak sayısını taşıyor (`sources`). Hafıza ekranında "N kaynak" rozeti var.
- **Kaynaksız bilgi:** Kalite önerilerinde "kaynaksız" olarak gösteriliyor.
- **Prompt injection:** Kaynak metinlerdeki talimatlar talimat olarak uygulanmıyor (Faz 6–8 doğrulaması, değişmedi).

---

## 8. Kimlik güvenliği

Faz 7.2'nin adaş planlaması ve "hangisi?" sorusu değişmedi. Faz 9'da eklenenler:

- **"Hayır, Ahmet değil Mehmet":**
  - kayıtlı tek bir Mehmet varsa ona taşınıyor;
  - kayıtlı Mehmet yoksa yeni bir kişi oluşuyor;
  - Ahmet yalnızca o mesaj yüzünden oluştuysa adı değiştiriliyor;
  - birden fazla Mehmet varsa ya da başka bir Mehmet hâlâ "hangisi?" yanıtını bekliyorsa **soruluyor**, hiçbir şey tahminle taşınmıyor.
- Düzeltme yalnızca **son** kullanıcı mesajının öğrettiğine uygulanıyor. İlk sürüm iki mesaj geriye bakıyordu ve eski bilgileri de taşıyordu. Test grubu D/E bunu yakaladı.
- **İçe aktarmada adaşlar:** Model ilişki sözcüklerini vermediğinde, bilginin ilişkisi kendi satırından alınıyor. "Komşum Ahmet mimar. İş arkadaşım Ahmet muhasebeci." iki kişi oluyor (Faz 8 bootstrap n04, 1. turda bulundu).

**Sonuç:**

- Gerçek Gemma'da **yanlış kişi 0** (68 konuşma × 4 koşu). **Yanlış ilişki** son kodla 0; ilk üç turda t12'de bir yanlış ilişki durumu vardı (kardeşlik "bitti", §1, §13.3).
- Faz 8 içe aktarma senaryolarında yanlış kişiye kayıt **0** (3. tur: 56/56 senaryo güvenli, güvenlik denetimlerinin hiçbiri düşmedi).
- Faz 7.2 kimlik: 3. turda 47/48 (adaş 18/18, komut 18/18; düşen l06 kimlikle değil, bir iç etiket göndermesiyle ilgili, §10). Son kodla **48/48**.
- Test grubu D: **60 senaryo** + içe aktarma adaşı 2 test; **yanlış kişiye kayıt 0, yanlış ilişki 0** (§14).

---

## 9. Çelişki yönetimi

**Çelişki ya da güncelleme:** Modelin "değişti" işareti yalnızca kullanıcının sözcükleri bunu söylüyorsa geçerli: "artık", "taşındı", "… beri", "aslında" vb. Böyle bir sözcük yoksa:

- tek değerli bir bilgide farklı bir değer **çelişki** sayılıyor;
- gelen kutusu soruyor;
- eski değer olduğu gibi kalıyor.

**Düzeltmeler** (`memory/corrections.py`): "Hayır / Yok / Pardon / Aslında …, X değil Y (demek istedim)" yanıttan önce, **model çağrısı olmadan** işleniyor. Yalnızca son kullanıcı mesajının öğrettiği düzeltiliyor:

- **X bir kişiyse:** kayıtlar Y'ye taşınıyor (§8).
- **X bir değer, işyeri ya da yerse:** değer (ve o varlık) düzeltiliyor. Düzeltilen ismin eki yeni isme uyuyor: "Bursa'da" → "Eskişehir'de".
  - Bu ek uyumu 3. turda elle okurken bulundu ve düzeltildi.
- **Mesaj henüz öğrenilmediyse:** düzeltme onu bekliyor. Bekleme bellekte tutuluyor; yeniden başlatmada kayboluyor (§17).
- Tek bir değişiklik kümesi oluşuyor; geçmiş, eski hâli tutuyor.
- Yanıt modele **gerçekte ne olduğunu** söylüyor: "düzelttim" ya da "hangisi?".
- "Hayır, vazgeç" bekleyen bir "hangisi?" sorusunu iptal ediyor.

**Mevcut hafıza sessizce değiştirilmiyor:** Gerçek modelde çelişki hatası **0** (10 çelişki konuşması × 3 tur).

Test grubu E: **78 + 2 test** (§14).

---

## 10. Açık kayıt ve otomatik öğrenme

Açık istekler ("Lütfen şunu not al…") ve arka plan öğrenmesi aynı iyileştirme adımından geçiyor. Zaman, liste ve başkasının akrabaları kuralları ikisinde de aynı. Faz 7.1–7.2 güvenceleri değişmedi:

- LAZIS bir kaydın gerçekleştiğini ancak yazma commit edildikten sonra söylüyor.
- İptal edilen ya da reddedilen bilgi sonradan yazılmıyor.
- Reddedilen bilgi **aynı kaynaktan yeniden öğrenilmiyor**.
- Hassas bilgi onaysız yazılmıyor.

Test grubu F: **45 + 16 test**: iptal, ret, başarısız yazma, yeniden deneme, arka plan öğrenmesi sırasında akış, erken kayıt iddiaları (§14).

**Gerçek modelde** (3. tur):

- onaysız kayıt **0**;
- gösterilen kayıt iddiası ile saklanan arasında fark **0**;
- iç etiket sızıntısı **0**;
- Faz 7.1 son kullanıcıya ulaşan dayanaksız iddia: 3. turda **0** (ham 9, dokuzu yeniden yazıldı); son kodla **0** (ham 6, altısı yeniden yazıldı).
- **Ancak Faz 9 Gemma değerlendirmesinin son koşusunda bir iddia kullanıcıya ulaştı** (c07, "Bilgiyi güncelledim"). Koruyucu düzeltildi (`f0e682c`); ayrıntı §13.3.

**İç etiket: bir kez göründü.** Faz 7.2 kimlik değerlendirmesinin 3. turunda (l06), "Teknik olarak nasıl çalışıyorsun, verilerim nerede saklanıyor?" sorusuna model şöyle yanıt verdi: "… **sistem notlarında belirttiğim gibi** kullanıcı tarafından görülebilir veya düzeltilebilir."

- Bu, ham bir etiket değil (`=== SİSTEM NOTU ===` gibi bir şey görünmedi). Ama kullanıcıya iç talimat katmanının varlığından söz ediyor; değerlendirme bunu doğru olarak sızıntı sayıyor.
- Hafıza işlemi olmayan bir kimlik sorusu. Kişilik istemi Faz 8'den beri değişmedi; aynı konuşma önceki dört koşuda (Faz 8'in iki koşusu, Faz 9'un 1. ve 2. turu) geçti. Model değişkenliği.
- Bu ifadeyi deterministik olarak yakalayan bir filtre **yok**; Faz 7.2 bunu istemle sağlıyor. Akan bir yanıtın ortasından ifade silmek kırılgan olduğu için Faz 9 sonunda eklemedim; Faz 10 için öneriyorum (§19).
- Son kodla Faz 7.2 yeniden koştu: 48/48, iç etiket 0. Gerçek Gemma öğrenme değerlendirmesinde (68 konuşma × 4 koşu) ve Faz 8 bağlam değerlendirmesinde iç etiket **0**.
- Yani etiket sızıntısı 5 koşunun birinde, 48 konuşmanın birinde görüldü; olasılık düşük ama sıfır değil.

---

## 11. Hafıza kalite kontrolü

**`memory/quality.py`, migration `0007_quality`.** Salt okunur bir tarama, öncelik sırasıyla (önce önem derecesi, sonra tür):

| Tür | Arayüzde |
|---|---|
| Bir bilginin iki güncel değeri | "çelişki" |
| Bekleyen çelişkiler | "çelişki" |
| Neredeyse aynı kayıtlar (çekim ekleri dahil) | "tekrar" |
| Değişebilen ve bir yıldır doğrulanmamış bilgi | "güncel mi?" |
| Ne ayrılmış ne birleştirilmiş, aynı adlı iki kişi | "aynı kişi mi?" |
| Hiç kaynağı olmayan bilgi | "kaynaksız" |
| Kesin olmayan ya da çıkarım olan bilgi | "kesin değil" |

**Kurallar:**

- Tarama **hiçbir şeyi değiştirmiyor, birleştirmiyor, silmiyor**.
- Siz düzeltiyor, unutuyor, birleştiriyor ya da "Bu öneriyi gizle" diyorsunuz.
- Gizlenen öneri içeriksiz bir parmak iziyle hatırlanıyor (tür ve kimlikler, özetlenmiş). Tek yeni tablo bu.

**Arayüz (Hafıza ekranı):**

- "Öneriler" bölümü;
- "Son 7 günde öğrenilenler" süzgeci;
- "geçmişte", "çok önemli / önemli" ve "N kaynak" rozetleri.

Var olan bölümler değişmedi: onay bekleyenler, çelişkiler ve belirsiz kişiler için gelen kutusu; düzeltme, reddetme ve unutma. Modelin tahmini kesin gibi gösterilmiyor ("kesin değil" rozeti). Yeni bir ekran eklenmedi.

Kalite ve arayüz testleri: **34 + 3 test** (§14).

---

## 12. Sohbet performansı

**Sohbetin önceliği korunuyor** (Faz 8 düzeltmesi):

- Öğrenme yalnızca kullanıcı 6 sn boşta kaldıktan sonra başlıyor.
- Bir sohbet turu öğrenmeyi en geç 2 sn içinde durduruyor.
- Öğrenme kaldığı yerden devam ediyor; iş kaybolmuyor.
- Yeni model çağrısı yalnızca bir liste yarım okunduğunda yapılıyor.
- İkinci model yüklenmiyor.

**Ölçüm** (`evals/runners/p9_perf.py`, M4 Pro 24 GB, Gemma 4 12B; her boyut kendi geçici profilinde):

- Her biri beş bilgi taşıyan mesajlar gönderiliyor.
- Her mesajdan sonra 9 sn bekleniyor; bu sürede öğrenme başlıyor.
- Ardından kısa bir sohbet sorusu öğrenmeyi bölüyor. Bu sorunun ilk token süresi "öğrenme sırasında sohbet" değeri.

| | 20 bilgi | 100 bilgi | 500 bilgi |
|---|---|---|---|
| Mesaj (her biri 5 bilgi) | 4 | 20 | 100 |
| **Boşta sohbet**, ilk token | 0,61 sn | 0,51 sn | 0,55 sn |
| **Öğrenme sırasında sohbet**, ilk token: medyan | 2,11 sn | 2,54 sn | **8,15 sn** |
| p90 | 2,15 sn | 3,06 sn | **54,0 sn** |
| en kötü | 2,22 sn | 28,2 sn | **195,5 sn** |
| Kuyruk gecikmesi (mesaj → öğrenildi): medyan | 117 sn | 587 sn | 3.447 sn |
| en kötü | 135 sn | 715 sn | 3.983 sn |
| Son mesajdan sonra kuyruğun boşalması | 117 sn | 664 sn | 2.719 sn |
| Model çağrısı: sohbet / çıkarım / liste ek okuması / sıkıştırma | 8 / 7 / 1 / 0 | 40 / 32 / 7 / 3 | 200 / 101 / 29 / 72 |
| Yazılan bilgi / ilişki | 16 / 4 | 80 / 18 | 388 / 83 |
| Tamamlanan öğrenme işi | 12 | 44 | 204 |

**Okuma:**

- **Boşta sohbet** her boyutta yarım saniye civarında; konuşmanın uzunluğu bunu değiştirmiyor.
- **20 ve 100 bilgide** öğrenme sırasında sohbetin ilk tokenı medyan 2–2,5 sn. Öğrenme en geç 2 sn içinde bırakıyor, ardından sohbet öneki yeniden işleniyor. (Faz 8'de içe aktarma sürerken atılan tek mesaj 4,1 sn ölçülmüştü.)
- **500 bilgide** sohbet belirgin biçimde yavaşlıyor: medyan 8 sn, onda biri 54 sn'nin üstünde, en kötüsü 3 dakikadan uzun. Aynı koşuda **72 sıkıştırma** çağrısı var (100 bilgide 3).
  - İlk ölçüm hangi turun neyin arkasında beklediğini kaydetmiyordu. Ölçüm betiğine bu döküm eklendi ve 500 bilgi yeniden koştu (`perf_gemma4_12b-it-qat_cause.json`):

    | 500 bilgi, yeniden koşu | Tur | Medyan | En kötü |
    |---|---|---|---|
    | Tüm turlar | 100 | 8,02 sn | 61,8 sn (p90 50,5 sn) |
    | **Öğrenme** sürerken gönderilen | 36 | 2,46 sn | **3,39 sn** |
    | **Arka plan sıkıştırması** sürerken gönderilen | 64 | 17,8 sn | 61,8 sn |
    | Tur içinde sıkıştırma yapılan | 0 | — | — |

  - **Yavaşlığın nedeni öğrenme değil, sohbetin arka plan sıkıştırması.** Öğrenme sürerken gönderilen turlar 500 bilgide de en kötü 3,4 sn'de başladı. Hiçbir tur yanıttan önce kendisi sıkıştırma yapmadı.
  - Sıkıştırma sürerken gelen tur sıkıştırmayı durduruyor (Faz 3 kuralı: sohbet her zaman kazanır). Ama modelin önbelleğinde artık sıkıştırma istemi var; tur uzun sohbet önekini baştan işlemek zorunda kalıyor. (Bu açıklama koddan; önek işleme süresini ayrıca ölçmedim.) Bu yükte 200 turluk sohbet sıkıştırma eşiğini sürekli aşıyor: 100 turun 64'ü bir sıkıştırmanın ortasına düştü (70 sıkıştırma çağrısı).
  - Sıkıştırma ve önbellek kodu Faz 9'da değişmedi; bu Faz 3/5 davranışı yoğun yükte görünür hale geldi.
  - Yeniden koşunun en kötü değeri 61,8 sn; ilk koşudaki 195 sn tekrar etmedi. İlk koşuda neden kaydedilmediği için o 195 sn'nin hangi işin arkasında olduğunu **bilmiyorum**.
- **Kuyruk gecikmesi:** Öğrenme yalnızca boşlukta çalıştığı için, ardı ardına gelen mesajlar beklemede birikiyor. 500 bilgide bir mesajın öğrenilmesi medyan 57 dakika sürdü. Hiçbir iş kaybolmadı: 204 işin tamamı bitti.
- **Yazılanlar:** Gönderilen bilgilerin %78–80'i yazıldı (her mesajda beş bilgi var; model bazılarını önermiyor). Bu yük için ayrıca bir doğruluk denetimi yapılmadı; doğruluk §13'teki değerlendirmede ölçülüyor.

**İlk ölçüm neden geçersizdi:**

- İlk koşuda 100 bilgilik ölçümde öğrenme hiç ilerlemedi: 40 iş kuyrukta kaldı, hiçbir bilgi yazılmadı. 500 bilgilik ölçüm süre sınırında kesildi.
- **Neden:** Ölçüm betiği, sohbet değerlendirmelerinin profilini kullanıyordu. O profil sohbet sıkıştırmasını **3600 sn** erteliyor; uygulamanın ayarı 5 sn. Uzun sohbet sıkıştırma eşiğini aşınca öğrenme sıkıştırmanın arkasında bekledi. Ölçüm de tam 3600 sn'de kesildi.
- **Düzeltme:** Betik artık uygulamanın kendi ayarıyla çalışıyor ve her boyuttan sonra sonucu yazıyor (`3c7e1ef`).
- Ürün kodunda bir değişiklik gerekmedi. Ancak bu bir özellik ortaya koydu: **uzun bir sohbette öğrenme, sohbetin gerektirdiği sıkıştırmadan sonra çalışıyor**. Kuyruk gecikmesi buna sıkıştırma süresi de dahil (§17).

---

## 13. Gerçek Gemma sonuçları

### 13.1 Değerlendirme

`evals/runners/p9_learning.py`:

- **68 sentetik konuşma**, 7 kategori.
- Her konuşma kendi geçici, şifreli profilinde, üretimdeki motorla ve arka plan öğrenmesiyle koştu.
- Yalnızca model çıktısı değil, **gerçek veritabanı durumu** okundu: bilgiler, ilişkiler, gelen kutusu, kişiler.

Ölçülenler:

- beklenen ve bulunan bilgiler ile ilişkiler;
- yanlış güncel değer, yanlış kişi ve yanlış ilişki;
- uydurulan değer: kullanıcının sözlerinde olmayan değer;
- onaysız (hassas) kayıt;
- zaman hatası ve çelişki hatası;
- gösterilen kayıt iddiası, gösterilen ile saklananın eşitliği, iç etiket.

**"Güvenli"** demek, o konuşmanın bütün denetimlerinin geçmesi demek. Eksik bir bilgi tek başına güvensiz sayılmıyor, ayrıca sayılıyor.

### 13.2 Üç turun sonuçları

| | 1. tur (`7cb916d`) | 2. tur (`0381451`) | 3. tur (`3c7e1ef`) | Son kod (`87f3c97`)* |
|---|---|---|---|---|
| Güvenli konuşma | 63/68 | 64/68 | 64/68 | 64/68 |
| Hatırlama eksiksiz | 64/68 | 64/68 | 64/68 | 65/68 |
| Bilgi (bulunan / beklenen) | 37/41 | 37/41 | 37/41 | 38/41 |
| İlişki (bulunan / beklenen) | 21/21 | 21/21 | 21/21 | 21/21 |
| **Yanlış kişi** | **0** | **0** | **0** | **0** |
| **Yanlış ilişki** (denetimin saydığı) | **0** | **0** | **0** | **0** |
| Yanlış ilişki **durumu** (elle okuma) | 1 (t12) | 1 (t12) | 1 (t12) | **0** |
| **Onaysız kayıt** | **0** | **0** | **0** | **0** |
| Yanlış güncel değer | 1 (t08) | 1 (t11) | **0** | **0** |
| "Uydurulan" değer | 1 (t09) | 2 (t11, r05) | 2 (t11, r02) | 2 (t11, r02) |
| Zaman hatası | 1 | 1 | **0** | **0** |
| Çelişki hatası | 0 | 0 | 0 | 0 |
| Gösterilen iddia ≠ saklanan | 0 | 0 | 0 | 0 |
| **Kullanıcıya ulaşan dayanaksız kayıt iddiası** | 0 | 0 | 0 | **1 (c07)** → düzeltildi (`f0e682c`) |
| İç etiket | 0 | 0 | 0 | 0 |

\* Son sütun `87f3c97` ile koştu. c07'de bulunan koruyucu açığı ondan sonra düzeltildi (`f0e682c`); çelişki konuşmaları o kodla yeniden koştu: **10/10 güvenli**, bütün denetimler geçti (c07 dahil).

3. turun ve son koşunun iki "uydurma" sonucu elle okunduğunda doğru:

- **t11**, "Eskiden sigara içerdim, bıraktım.": "sigara içmek" doğru biçimde **geçmiş**. Denetim "içmek" ile "içerdim"i aynı kök saymıyor.
- **r02**, "Filtre kahve olmadan güne başlayamam.": "filtre kahve ile güne başlama". Denetim "ile" sözcüğünü kullanıcının sözlerinde bulamıyor.

Kategoriye göre (güvenli / konuşma):

| Kategori | 1. tur | 2. tur | 3. tur | Son kod |
|---|---|---|---|---|
| Liste | 14/14 | 14/14 | 14/14 | 14/14 |
| Zaman | 12/14 | 13/14 | 13/14 | 13/14 |
| Tekrar | 5/6 | 4/6 | 4/6 | 4/6 |
| Kaynak | 8/8 | 8/8 | 8/8 | 8/8 |
| Kimlik | 8/10 | 9/10 | 9/10 | 10/10 |
| Çelişki | 10/10 | 10/10 | 10/10 | 9/10 (c07) |
| Geçici durum | 6/6 | 6/6 | 6/6 | 6/6 |

### 13.3 Elle okuyarak bulduklarım ve yaptıklarım

**1. tur:**

- **t08**, "Kervan'dan ayrıldım, artık Atlas'tayım.": Kervan güncel kaldı.
  - **Neden:** Yan cümlenin zamanı "artık" yüzünden *güncel* okunuyordu ve ayrılma fiili hesaba katılmıyordu.
  - **Düzeltme:** Ayrılınan şey geçmiş (`temporal.left`) (`0381451`).
- **t09**, "Seneye emekli olacağım.": "emekli olmak" güncel hedef oldu.
  - **Düzeltme:** Tarihli bir niyet zamanıyla plan oluyor (`0381451`).
- **i04**, "Komşum Ahmet'in kardeşi Elif." / "İş arkadaşım Ahmet'in kardeşi Zeynep.": Bir Ahmet ve gelen kutusunda "hangisi?" sorusu oluştu.
  - Bu ADR-0018'e uygun: kayıtlı bir adaş başka ilişki sözcükleriyle anıldığında soruluyor, birleştirilmiyor.
  - **Denetimi değiştirdim:** "iki kişi **ya da** bir kişi ve açık bir 'hangisi?' sorusu" artık geçerli. Bu, denetim ölçütünde bir değişiklik; açıkça belirtiyorum.
- **Faz 8 bootstrap n04:** İçe aktarmada adaş bilgisi yanlış Ahmet'e önerildi (§8; `0381451`).
- **Faz 7 ilişki C/O ve Faz 6 E5:** "Artık Kervan'da çalışmıyorum, Atlas'a geçtim" Atlas'ı da bitiriyordu. "Bugün" başka bir şeyle ilgiliyken bilgi düşüyordu. İkisi de düzeltildi (`0381451`).

**2. tur:**

- **Benim yan etkim:** 1. turun Kervan/Atlas düzeltmesi fazla geniş tuttu. "Biten ilişki hiçbir rakibi kapatmaz" kuralı yüzünden "Derya ile Kaan boşandılar" (T2) evliliği, "Burak'la aslında arkadaş değiliz" (C3) arkadaşlığı bitirmedi.
  - Faz 7 ilişki altın seti 46 → 44'e düştü.
  - **Kural daraltıldı:** Biten bir ilişki yalnızca *başka hedefleri* kapatmıyor. Aynı iki kişi arasındaki düzeltme ya da değişiklik ilişkiyi bitiriyor (`3c7e1ef`).
- **t11**, "Eskiden sigara içerdim, bıraktım.": Sigara alışkanlığı güncel kaldı.
  - **Neden:** "Bıraktım" bir değişiklik sözcüğü sayılıyordu.
  - **Düzeltme:** Ayrılma ve bırakma fiilleri değişiklik sözcüğü değil; bırakılan şey geçmiş (`3c7e1ef`).
- **r05**, "Her sabah koşarım.": "her sabah koşu yapmak" kaydı **uydurma sayıldı**. Bu bir **denetim hatası**:
  - Değer doğru; yalnızca kullanıcının söylemediği "yapmak" fiili denetimin kök eşleştirmesine takılıyor.
  - Değerlendirme sürerken denetimi değiştirmedim; ham sonucu olduğu gibi veriyorum.
- Üç düzeltmenin testleri eski kodda başarısız, yeni kodda geçiyor (her biri ayrı ayrı denendi).

**3. tur:**

- **t12**, "Kız kardeşim Elif eskiden İzmir'de yaşıyordu, artık Muğla'da.": **Kardeşlik ilişkisi "bitti" olarak yazıldı.** 1. ve 2. turda da aynıydı; ilk iki turda gözümden kaçtı, çalıştırıcı da denetlemiyordu.
  - **Neden:** İlişkinin zamanı, alıntının içinde bulunduğu yan cümleden okunuyordu. Oradaki geçmiş zaman Elif'in şehri için.
  - **Düzeltme:** İki kişi arasındaki ilişki yalnızca ilişkinin kendisi geçmişte söyleniyorsa bitiyor (§4; `3fea95d`). Yeni testlerin üçü eski kodda başarısız, yenide geçiyor.
  - Çalıştırıcıya bu konuşma için "kardeşlik bitmemeli" denetimi eklendi.
  - Değerlendirme ve Faz 7 ilişki altın seti son kodla yeniden koştu.
- **t11 ve r02:** denetim katılığı (yukarıda).
- **i05**, "Berk'in eşi Selin veteriner.": Selin'in mesleği `event` yüklemiyle yazıldı. Bilgi doğru kişide, yüklem yanlış (§17).
- **i02:** LAZIS yanıtında "Hangi Ahmet?" diye sordu, ama model bilgiyi çıkarmadığı için gelen kutusunda bekleyen bir soru yok. Yanıttan sonra Ahmet'lerden birini söylerseniz bilgi kaydedilmez; yeniden söylemeniz gerekir.
- **c08**, "Hayır, Bursa değil Eskişehir.": Düzeltme doğru uygulandı, ama kayıt metni "Ece Eskişehir'da yaşıyor" oldu (2. turda da aynıydı).
  - **Düzeltme:** Ek yeni isme uyuyor (`ee2c36a`). Testi eski kodda başarısız.
  - 3. tur bu düzeltmeden önce başladığı için c08 son kodla yeniden koştu: kayıt **"Ece Eskişehir'de yaşıyor"**, düzeltme yanıtı doğru.

**3. turun regresyonları (Faz 7 oturumları, 52/54):**

- "Kervan Lojistik'te çalışıyorum." → "Artık Kervan Lojistik'te çalışmıyorum, Atlas Yazılım'a geçtim." sonrasında veritabanında: eski Kervan **bitti**, Atlas **bitti**, yeni bir Kervan **güncel**. Hemen ardından "Şu an nerede çalışıyorum?" sorusu yine "Atlas" yanıtını aldı, ama ilişki grafiği yanlıştı. Bu bir **yanlış güncel değer**; 2. turda aynı adım doğruydu.
  - **Neden:** Model bu kez olumsuz yan cümleyi ("Artık Kervan Lojistik'te çalışmıyorum") ayrıca bir `employer = Kervan Lojistik` bilgisi olarak da önerdi. Faz 7'den beri işyeri bilgisi bir `works_at` ilişkisine de dönüşüyor. Bu olumsuzluk taşımayan ilişki Kervan'ı yeniden güncel yaptı ve "değişiklik" olarak Atlas'ı kapattı. Kod yolu Faz 9'dan önce de vardı; bu turda modelin yanıtı onu tetikledi.
  - **Düzeltme** (`87f3c97`): Bir işyeri, şehir ya da meslek değerinden hemen sonra olumsuz bir sözcük geliyorsa ("çalışmıyorum", "yaşamıyorum", "değilim"), o değer bugünün değeri olamaz. "Artık" varsa geçmiş, yoksa hiç yazılmıyor; işyeri ya da yer ilişkisi olumsuz okunuyor. İki kişi arasındaki ilişkilere uygulanmıyor ("Kardeşim Elif sigara içmiyor" kardeşliği bitirmez). "Kervan'da değil, Atlas'ta çalışıyorum" cümlesinde Atlas olumsuzlanmıyor.
  - Gemma'nın bu yanıtı senaryolu bir testte dört biçimiyle yeniden üretildi; ikisi eski kodda başarısız, yenide geçiyor. 10 birim testi ekledim.
  - Faz 7 oturumları son kodla yeniden koştu: **54/54**; Kervan bitti, Atlas güncel.
- Faz 9'un Gemma değerlendirmesinde "çalışmıyorum" ile biten bir işyeri cümlesi yok; bu hatayı yalnızca Faz 7 regresyonu yakaladı. Bu bir kapsam eksiği; değerlendirmeye eklenmesini öneriyorum (§19).

**Son koşu (`87f3c97`):**

- **c07**, "Kervan'da çalışıyorum." → "Pusula'da çalışıyorum.": Hafıza doğru davrandı. Değişiklik sözcüğü olmadığı için Kervan değişmedi, gelen kutusuna bir çelişki sorusu düştü. Ama **yanıt "Bilgiyi güncelledim efendim." dedi** ve bu kullanıcıya ulaştı. Hiçbir şey güncellenmemişti.
  - Bu bir **erken / dayanaksız kayıt iddiası**: Faz 7.1 güvencesinin ihlali. Önceki üç turda aynı konuşmada model bunu söylememişti.
  - **Neden:** Faz 7.1 koruyucusu "güncelledim / sildim / düzelttim" fiillerini ancak yanlarında bir hafıza sözcüğü ("hafızamda", "kayıtlarımda") varsa ya da açık bir hafıza isteğinde iddia sayıyordu. "Bilgiyi" bu listede yoktu. Edilgen "Kayıt güncellendi" de geçiyordu.
  - **Düzeltme** (`f0e682c`): Nesnesi bilgi olan bu fiiller ("bilgiyi / bilgilerinizi / iş yeri bilginizi güncelledim", "bu bilgiyi sildim") ve "güncellendi" edilgeni artık iddia; akış o kelimeden itibaren tutuluyor. "Bilgisayarınızı güncelledim", "Paragraf güncellendi" gibi cümlelere dokunulmuyor. 16 yeni test; 12'si eski kodda başarısız.
  - **Kayıtlı yanıtlar üzerinde deterministik kontrol:** Faz 9 boyunca saklanan 354 ham Gemma yanıtı yeni koruyucudan geçirildi: hiçbiri yanlışlıkla değişmedi (eski kodla da aynı tek fark çıkıyor; o fark betiğin hatırlama varsayımından). Gemma değerlendirmesinin dört koşusundaki 384 gösterilen yanıt içinde yeni koruyucunun yakaladığı tek iddia c07'ninki.
  - Bu kodla yeniden koşanlar:
    - g1 çelişki konuşmaları: **10/10** güvenli.
    - Faz 7.1 iddia değerlendirmesi: kullanıcıya ulaşan dayanaksız iddia **0**. Ham yanıtlardaki 6 iddianın 6'sı yeniden yazıldı; altısını da elle okudum, cümleler doğru ("not ettim" → "anladım", "Notu aldım" → "Bilgiyi henüz kaydetmedim").
    - Faz 7.2 kimlik: **48/48**, iç etiket 0 (l06 bu koşuda geçti).
  - **Kalan sınır durumu:** c07'nin yeniden koşusunda model "Pusula'da çalıştığınızı anladım. **Kervan bilgisini düzelterek bunu esas alıyorum.**" dedi. Kervan düzeltilmedi; LAZIS gelen kutusunda soruyor.
    - "-erek" zarf-fiili bitmiş bir eylem değil; değerlendirme de koruyucu da bunu iddia saymıyor. Ama kullanıcıyı yanıltabilir.
    - Koruyucuya eklemek kolay değil: "düzelterek" yerine "anlayarak" yazmak, cümlenin geri kalanı ("esas alıyorum") hâlâ bir güncelleme ima ettiği için yetmiyor. Faz 9'da düzeltmedim (§17, §19).

### 13.4 Modelden kaynaklanan, kalan durumlar

| Konuşma | Ne oluyor | Değerlendirme |
|---|---|---|
| r01 "sabah çalışmak" üç söyleyiş | 2–3 kayıt | Kalite önerisinde "tekrar"; birleştirme sizin kararınız |
| i02 "İki Ahmet tanıyorum…" → "Ahmet'in doğum günü 5 Mayıs." | Model hiçbir şey çıkarmıyor, bu yüzden "hangisi?" sorusu da oluşmuyor | Güvenli: kimseye yazılmıyor; doğum günü kayıp |
| s05 "Mehmet, Ali'nin avukat olduğunu söyledi." | Ali'nin mesleği önerilmiyor | Eksik, yanlış değil (Mehmet'e de yazılmıyor) |
| t12, c08 | Model, Elif'in / Ece'nin şehrini `location` yerine `family` yüklemiyle öneriyor | Bilgi ve geçmişi doğru, yüklem yanlış: "Elif nerede yaşıyor?" sorusunda yine bulunuyor ama denetim eksik sayıyor |

---

## 14. Otomatik testler

| Grup | Dosya | Test | Kapsam |
|---|---|---|---|
| A — Çoklu bilgi | `unit/test_lists.py`, `integration/test_learning_lists.py` | 139 + 45 = **184** | İki ve daha çok kardeş, projeler, şehirler, tercihler, ilişkiler, adaşlar, eksik sayısal listeler; ek okuma yalnızca eksik üyeler; liste başka bir şeyin nesnesiyken ilişki uydurulmuyor; JSON kurtarma |
| B — Zaman | `unit/test_temporal.py`, `integration/test_learning_time.py` | 105 + 57 = **162** | Geçmiş / güncel meslek, taşınma, iş değişikliği, tercih değişikliği, tarihsel olaylar, ayrılınan yer, bırakılan alışkanlık, tarihli niyet, boşanma, bir kişi hakkındaki geçmiş, "çalışmıyorum" ile söylenen işyeri, zaman ifadesi, geçici durumlar |
| C — Tekrar ve kanıt | `integration/test_learning_evidence.py` | **52** | Anlamsal tekrar, farklı kaynaklar, aynı mesajın yeniden okunması, düzeltme, güven sınırı |
| D — Kimlik | `integration/test_learning_identity.py` (+ `unit/test_bootstrap_extract.py` 2) | **60** + 2 | **Yanlış kişiye kayıt 0, yanlış ilişki 0** |
| E — Çelişki ve düzeltme | `integration/test_learning_corrections.py` (+ `integration/test_graph_store.py` 2) | **78** + 2 | Açık düzeltmeler (kişi, değer, işyeri; ek uyumu), zamanlı değişiklikler, belirsiz çelişkiler, mevcut hafızanın korunması, biten ilişki |
| F — Kayıt işlem güvenliği | `integration/test_learning_saves.py` (+ `unit/test_memory_claims.py` 16) | **45** + 16 | İptal, ret, başarısız kayıt, yeniden deneme, arka plan öğrenmesi, akıştaki iddialar ("bilgiyi güncelledim", "kayıt güncellendi" dahil), reddedilen yeniden öğrenilmiyor |
| Kalite, önem, kurtarma | `integration/test_memory_quality.py` | **34** | Öneri türleri, sıra, gizleme, hiçbir şeyin değişmemesi, önem dereceleri |
| Arayüz | `ui/tests/unit/memory.spec.ts` | **3** | Öneriler ve gizleme; rozetler; "son 7 gün" süzgeci |

Her grubun test sayısı talimattaki en düşük sayının üstünde (A ≥ 100, B ≥ 60, C ≥ 50, D ≥ 60, E ≥ 50, F ≥ 40).

**Testlerin bulduğu hatalar** (`7cb916d`):

- Düzeltme iki mesaj geriye bakıyordu ve eski bilgileri de taşıyordu.
- "Kervan değil Pusula" bir işyeri için kişi yolunu izliyordu.
- Hâlâ "hangisi?" bekleyen bir isme yapılan düzeltme kayıtlı adaşı seçiyordu.
- "Hayır, vazgeç" bekleyen soruyu iptal etmiyordu.
- Ekle değişen neredeyse aynı değerler tekrar önerisi olarak çıkmıyordu.

`make check` (son kod): **rc = 0**. Çekirdek **2304**, arayüz **128**, arayüz–arka uç **8** test geçti; kabuk (Rust) testleri de geçti. Faz 8 sonunda çekirdekte 1669, arayüzde 125 test vardı: Faz 9 **638 yeni test** ekledi (635 çekirdek, 3 arayüz).

---

## 15. Önceki faz regresyonları

Hepsi gerçek Gemma ile koştu. 1. ve 2. tur raporları karşılaştırma için `_p9a` / `_p9b` etiketleriyle saklanıyor; 3. tur `_p9`.

| Değerlendirme | Faz 8 | 1. tur | 2. tur | 3. tur | Son kod (`87f3c97`) |
|---|---|---|---|---|---|
| Faz 5 kişilik | 110/111 | 109/111 | — | — | — |
| Faz 5 kimlik | 10/12 | 11/12 | — | — | — |
| Faz 6 çıkarım (kritik) | 40/41 (0) | 37/41 (0) | 40/41 (0) | 39/41 (0) | — |
| Faz 6 oturumları | 54–55/56 | 52/56 | 52/56 | **55/56** | — |
| Faz 7 ilişki (kritik) | 47/50 (0) | 46/50 (0) | 44/50 (0) | 45/50 (0) | **46/50 (0)** |
| Faz 7 oturumları | 54/54 | 51/54 | 54/54 | **52/54** | **54/54** |
| Faz 7.1: kullanıcıya ulaşan dayanaksız iddia | 0 | 0 | 0 | 0 (ham 9, yeniden yazılan 9) | **0** (ham 6, yeniden yazılan 6; `f0e682c`) |
| Faz 7.2 kimlik | 47/48 | 48/48 | 48/48 | 47/48 (l06: iç etiket) | **48/48** (`f0e682c`) |
| Faz 8 bağlam (koşul E) | 8/8 | 8/8 | 8/8 | 8/8 | — |
| Faz 8 bootstrap güvenli | 56/56 | 55/56 (n04) | 56/56 | 56/56 | — |
| `make check` | rc 0 | rc 0 | rc 0 | rc 0 | rc 0 (2304 + 128 + 8) |

Faz 5 değerlendirmeleri öğrenme yolunu kullanmıyor; 1. turdan sonra yeniden koşulmadı. "Kritik", altın setin kendi tanımı (yanlış kişi, yanlış ilişki, hassas bilginin onaysız yazılması vb.).

**Elle okuduklarım:**

- **Faz 6 çıkarım:** 3. turda düşen iki vaka R3 ve E4. E4'te Burak'ın mesleği "restoran işletmecisi" `family` yüklemiyle yazıldı (yanlış yüklem, kişi doğru); R3'te bilgi önerilmedi. Kritik 0.
- **Faz 6 oturumları:** Kalan tek adım "Hakkımda ne biliyorsun?" özeti. Model bu koşuda mesleği hiç önermediği için yanıt yalnızca şehri ve tercihi saydı. Eksik, yanlış değil. 2. turdaki E3 adımında yanıt doğruydu ("henüz paylaşmadınız"); düşmesi denetimin ifade eşleştirmesinden.
- **Faz 7 ilişki:** Son kodla düşenler F2, F3, O2 ve M2; dördü de eksik kayıt (yanlış kayıt 0). F3, O2 ve M2 Faz 8'den beri bilinen vakalar. 3. turda düşenler F2 (bilinen yön hatası, §17), O2, O3, T3 ve M4. O3, T3 ve M4 eksik kayıt: model Atlas Yazılım'ı kişi olarak verdi ve ilişki tür uyuşmazlığından yazılmadı (O3); "Gelecek ay Selin ile evleniyoruz" ilişki sözcüğü söylenmediği için reddedildi (T3); zincirin ikinci halkası önerilmedi (M4). Hiçbirinde yanlış kayıt yok. 2. turdan farklı vakaların düşmesi model değişkenliği; 3. tur `3fea95d` öncesi kodla koştu.
- **Faz 7 oturumları:** 3. turdaki **yanlış güncel işyeri** (§13.3) gerçek bir hataydı; `87f3c97` ile düzeltildi ve son kodla yeniden koştu.
- **Faz 7.2:** l06 (§10).

---

## 16. Bellek ve model performansı

| | 20 bilgi | 100 bilgi | 500 bilgi |
|---|---|---|---|
| Arka uç süreci (Python, şifreli veritabanı dahil) en yüksek RSS | 66 MB | 66 MB | 66 MB |
| Model çalıştırıcısının (Ollama) en yüksek bellek ayak izi | 10,6 GB | 13,3 GB | 13,6 GB |

- **Arka uç** her boyutta 66 MB'ta kaldı. Hafıza büyüdükçe arka ucun belleği artmıyor.
- **Model çalıştırıcısı:** 7,15 GB'lık model ağırlıklarına bağlamın KV önbelleği ekleniyor. Uzun sohbette büyüyor, ama 100'den 500 bilgiye neredeyse değişmiyor: sıkıştırma bağlamı sınırlı tutuyor.
  - Faz 8'in içe aktarma ölçümünde 5–6 GB görünüyordu. O ölçüm kısa bölümler üzerindeydi; buradaki uzun sohbet bağlamıyla karşılaştırılamaz.
- **İkinci model yok:** Ölçüm boyunca tek bir model çalıştırıcısı vardı; sıkıştırma, öğrenme ve sohbet aynı modeli kullanıyor.
- **Makinenin durumu:** Ölçüm başlarken makinede 8,2 GB swap kullanılıyordu ve boş bellek 0,33 GB'tı (başka uygulamalar açıktı; `manifest` raporda). 500 bilgilik gecikmelerin bir kısmı bundan da etkilenmiş olabilir; ayırt edemiyorum.

---

## 17. Bilinen sınırlamalar

1. **Aynı tercihin başka sözlerle tekrarı:** Bazen 2–3 kayıt oluşuyor (r01). Kalite önerisi bunları "tekrar" olarak gösteriyor; LAZIS kendiliğinden birleştirmiyor (§6).
2. **Model bazı bilgileri hiç önermiyor:** Kayıtlı iki Ahmet varken "Ahmet'in doğum günü" (i02); "Mehmet, Ali'nin avukat olduğunu söyledi" cümlesinde Ali'nin mesleği (s05).
   - Bunlar eksik, yanlış değil. İsterseniz açıkça "not al" diyebilir ya da Hafıza ekranından ekleyebilirsiniz.
3. **Zaman sözcüklerden okunuyor, dilbilgisinden değil:** Alışılmadık söyleyişler kaçabilir. Örneğin "önceden X'tim" cümlesinde model bazen geçmiş değeri hiç önermiyor.
4. **Öğrenilmemiş bir mesajı bekleyen düzeltme:** Bellekte tutuluyor; uygulama o arada yeniden başlarsa kayboluyor.
5. **Uzun sohbette öğrenme sıkıştırmayı bekliyor:** Kuyruk gecikmesine sıkıştırma da giriyor (§12).
6. **Model yön hatası** (Faz 7 ilişki F2): Model bir cümlede ilişkinin yönünü ters önerdi ("Gülsüm, … çocuğu"). Faz 8'den beri bilinen F3, O2, M2 de aynı türden.
7. **Faz 6 oturum adımları:** "Eski / yeni meslek" adımı (brief/3) ve "hakkımda ne biliyorsun" özeti (G) Faz 8'de de düşüyordu. Faz 9 ile gelmedi.
8. **Denetimin katılığı:** "Uydurma" denetimi kök eşleştirmesine dayanıyor; "koşarım" → "koşu yapmak" gibi doğru açıklamaları uydurma sayabiliyor (r05). Ham sonuç değiştirilmeden verildi.
9. **Yüklem seçimi:** Model bir kişinin şehrini bazen `location` yerine `family` yüklemiyle öneriyor (t12, c08). Bilgi doğru kişide ve doğru zamanda, ancak yapılandırılmış yüklemi yanlış.
10. **Zarf-fiille söylenen işlem:** "Kervan bilgisini düzelterek bunu esas alıyorum" gibi bir cümle, hiçbir şey düzeltilmemişken kullanıcıya ulaşabiliyor (c07 yeniden koşusu). Koruyucu yalnızca bitmiş, sürmekte olan ya da söz verilen eylemleri ("düzelttim", "düzeltiyorum", "düzelteceğim") yakalıyor.
11. **İç katmana gönderme:** Model nadiren "sistem notlarında belirttiğim gibi" gibi bir ifadeyle iç talimat katmanından söz ediyor (Faz 7.2 l06, 5 koşunun birinde). Bunu yakalayan deterministik bir filtre yok.
12. **Yoğun yükte sohbet gecikmesi:** 500 bilgilik (100 mesaj, her 9 saniyede bir) yükte sohbetin ilk tokenı medyan 8 sn, en kötüsü 195 sn (ilk koşu) ve 62 sn (yeniden koşu) (§12). Yeniden koşunun dökümüne göre neden öğrenme değil, arka plan sıkıştırmasının yarıda kesilmesi ve ardından uzun önekin yeniden işlenmesi. Gerçek kullanımda mesajlar arasında daha uzun süre olur; ama çok uzun bir sohbette ilk token birkaç saniyeyi aşabilir.
13. **Değerlendirme kapsamı:** Faz 9 Gemma değerlendirmesi "Artık X'te çalışmıyorum, Y'ye geçtim" türü olumsuz cümleleri içermiyordu; o hatayı Faz 7 regresyonu yakaladı (§13.3).

### Kabul kriterleri (talimat §17)

✅ karşılandı · ⚠️ kısmen / değerlendirme sırasında ihlal görüldü · ❌ karşılanmadı

| Kriter | Durum | Kanıt |
|---|---|---|
| Çoklu bilgi çıkarımı iyileştirildi | ✅ | Liste konuşmaları 14/14 (4 koşuda); grup A 184 test (§3) |
| İki kardeş gibi çoklu ilişkiler güvenle çıkarılıyor | ✅ | İlişkiler 21/21, yanlış ilişki 0 (§13.2) |
| Kaynakta olmayan ilişki uydurulmuyor | ✅ | Yanlış ilişki 0; "arkadaşımın kardeşi" bırakılıyor (§3); kaynak konuşmaları 8/8 |
| Geçmiş ve güncel bilgiler doğru ayrılıyor | ⚠️ | Son kodla zaman hatası ve yanlış güncel değer 0. Değerlendirme sırasında iki hata bulundu ve düzeltildi: kardeşliğin "bitti" yazılması (t12, `3fea95d`), "çalışmıyorum" ile söylenen işyerinin yeniden güncel olması (Faz 7 oturumları, `87f3c97`) |
| Anlamsal tekrarlar gereksiz hafıza oluşturmuyor | ⚠️ | Aynı mesaj ve aynı söz tek kayıt; farklı sözlerle aynı tercih 2–3 kayıt (r01). Kalite önerisi gösteriyor, birleştirme yok (§6) |
| Bağımsız kanıtlar korunuyor | ✅ | Kaynak başına kanıt, aynı mesaj ikinci kanıt değil, güven ≤ 0,95; grup C 52 test |
| Kullanıcı düzeltmeleri doğru işleniyor | ✅ | Çelişki konuşmaları 10/10 (son kod); c08 ek uyumu düzeldi; grup E 80 test |
| Yanlış kişiye kayıt sıfır | ✅ | 4 Gemma koşusu, Faz 7.2, Faz 8 bootstrap: 0; grup D 0 |
| Yanlış ilişki sıfır | ⚠️ | Son kodla 0. İlk üç turda t12'de bir yanlış ilişki **durumu** (kardeşlik "bitti"), denetim kaçırdı, elle buldum; düzeltildi |
| Belirsiz kişi bilgileri yanlış bağlamda kullanılmıyor | ✅ | Faz 8 bağlam 8/8; kimlik konuşmaları 10/10 (son kod); Faz 7.2 adaş 18/18 |
| Mevcut hafıza sessizce değiştirilmiyor | ⚠️ | Çelişki hatası 0 (4 koşu). Ama Faz 7 oturumlarının 3. turunda güncel işyeri yanlış değişti (yukarıda, düzeltildi) |
| İptal ve ret işlemleri sonradan yazılmıyor | ✅ | Grup F 45 test; onaysız kayıt 0 |
| Erken kayıt iddiaları kullanıcıya ulaşmıyor | ⚠️ | Son kodla Faz 7.1 ve Gemma değerlendirmesinde 0. Son koşuda bir iddia ulaştı (c07, "Bilgiyi güncelledim"), düzeltildi (`f0e682c`). Zarf-fiilli sınır durumu kaldı (§17-10) |
| İç sistem etiketleri sızmıyor | ⚠️ | Ham etiket hiç görünmedi. "Sistem notlarında belirttiğim gibi" 5 Faz 7.2 koşusunun birinde göründü; deterministik filtre yok (§10) |
| Arka plan öğrenmesi sohbeti kilitlemiyor | ✅ | Öğrenme sürerken gönderilen tur 500 bilgide de en kötü 3,4 sn'de başladı (20 / 100 bilgide medyan 2,1 / 2,5 sn). Yoğun yükte sohbeti yavaşlatan şey arka plan sıkıştırması: en kötü 62 sn (§12, §17-12) |
| Faz 8 bootstrap güvenliği korunuyor | ✅ | 56/56 güvenli, güvenlik denetimlerinin hiçbiri düşmedi |
| SQLCipher ve yerel çalışma korunuyor | ✅ | Depolama ve ağ testleri `make check` içinde; yeni migration yalnızca ekleme; bulut, telemetri, ikinci model yok |
| Gerçek Gemma testleri tamamlandı | ✅ | 68 konuşma × 4 koşu + yeniden koşular; veritabanı durumu okundu |
| Performans ölçüldü | ✅ | 20 / 100 / 500 bilgi (§12, §16) |
| Regresyonlar çalıştırıldı | ✅ | Faz 5–8, üç tur + son kod (§15); Faz 5 yalnızca 1. turda |
| make check başarılı | ✅ | rc 0: çekirdek 2304, arayüz 128, arayüz–arka uç 8, Rust |
| Gerçek kullanıcı verileri değiştirilmedi | ✅ | `default` profilinin veritabanı en son 20 Ekim'de, logları 21 Ekim'de değişmiş; Faz 9 çalışması 28 Ekim'de başladı. `dev` profiline ve Anahtar Zinciri'ne dokunulmadı |
| Kodlar yerel commit edildi | ✅ | Raporun başındaki commit tablosu; push yok |
| Faz 10'a başlanmadı | ✅ | |

---

## 18. Kullanıcı kabul testleri

Önerim: Hepsini `dev` profilinde ve sentetik isimlerle yapın.

1. `make dev` ile uygulamayı açın.
2. Sohbette yazın: **"Ahmet'in iki kardeşi var: Mehmet ve Ali."** Birkaç saniye bekleyin.
   - **Beklenen:** Hafıza → Kayıtlar'da Mehmet ve Ali, Ahmet'in kardeşi olarak görünür.
3. **"Annemin üç kardeşi var: Ayşe, Fatma ve Zeynep."**
   - **Beklenen:** Üçü sizin kardeşiniz olarak değil, annenizin kardeşi olarak kaydedilir.
4. **"Geçen yıl Kervan'da çalışıyordum, artık Pusula'dayım."**
   - **Beklenen:** Pusula güncel; Kervan "geçmişte" rozetiyle.
5. **"Gelecek yıl İzmir'e taşınacağım."**
   - **Beklenen:** Güncel şehriniz değişmez; bir plan olarak "Gelecek yıl" ifadesiyle görünür.
6. **"Kız kardeşim Ece Bursa'da yaşıyor."** ardından **"Hayır, Bursa değil Eskişehir."**
   - **Beklenen:** LAZIS düzelttiğini söyler; kayıt "Eskişehir'de".
7. **"Ahmet'in doğum günü 3 Mart."** ardından **"Hayır, Ahmet değil Mehmet demek istedim."**
   - **Beklenen:** Doğum günü Mehmet'te, Ahmet'te değil.
8. **"Komşum Can Ankara'da yaşıyor."**, sonra yeni bir mesajda **"Can İstanbul'da yaşıyor."**
   - **Beklenen:** Ankara sessizce değişmez; gelen kutusunda bir çelişki sorusu çıkar.
   - **"Can artık İstanbul'da yaşıyor."** derseniz güncellenir ve Ankara geçmişte kalır.
9. **"Bugün çok yorgunum."**
   - **Beklenen:** Hafızaya kaydedilmez.
10. **"Sabah çalışmayı seviyorum."**, **"En verimli olduğum saatler sabah."**
    - **Beklenen:** Bir ya da iki kayıt. İkiyse Hafıza → Öneriler'de "tekrar" önerisi çıkar. "Bu öneriyi gizle" deyin: öneri bir daha görünmez, kayıtlar değişmez.
11. Hafıza → Kayıtlar'da **"Son 7 günde öğrenilenler"** süzgecini seçin.
    - **Beklenen:** Yalnızca bu testte öğrenilenler; önemli olanlarda "önemli / çok önemli" rozeti.
12. Bir bilgiyi reddedin ya da unutun, aynı cümleyi tekrar yazın.
    - **Beklenen:** Reddettiğiniz bilgi o mesajdan yeniden öğrenilmez.
13. Uzun bir mesaj yazdıktan hemen sonra kısa bir soru sorun.
    - **Beklenen:** Yanıt gecikmeden başlar; öğrenme arkadan devam eder.

---

## 19. Faz 10 için öneriler

Bunlar öneri; Faz 10'a başlanmadı.

1. **Anlamsal tekrar:** Aynı tercihin farklı söyleyişleri için kullanıcıya "bunlar aynı mı?" diye soran bir birleştirme akışı. Kalite önerisinden tek tıklamayla birleştirme olabilir.
2. **Bekleyen düzeltmelerin kalıcı olması:** Öğrenilmemiş mesajı bekleyen düzeltme veritabanına yazılabilir.
3. **Yüklem denetimi:** Bir kişinin şehrinin `family` yüklemiyle gelmesi (t12, c08) gibi durumlar için Faz 8'in içe aktarmadaki yüklem denetimi sohbet öğrenmesine de uygulanabilir; altın setlerle ölçülerek karar verilmeli.
4. **Sıkıştırma ile öğrenmenin sırası:** Uzun sohbette öğrenmenin sıkıştırmadan önce çalışması kuyruk gecikmesini kısaltabilir; önbellek etkisi ölçülmeli.
5. **İç etiket göndermeleri için deterministik filtre:** Faz 7.1'in yanıt koruyucusu ("ClaimGuard") gibi, "sistem notu", "kişisel hafıza bloğu" gibi iç katmana göndermeleri yanıt kullanıcıya ulaşmadan yakalayan bir kural (§10, l06).
6. **Zarf-fiil iddiaları:** Koruyucunun "düzelterek / kaydederek / not alarak" gibi zarf-fiillerle kurulan cümleleri, cümlenin ana fiiliyle birlikte ele alması (§17-10).
7. **Değerlendirme kapsamı:** Faz 9 Gemma değerlendirmesine "Artık X'te çalışmıyorum, Y'ye geçtim" türü olumsuz cümleler eklenmeli (§13.3).
8. **Değerlendirme denetimi:** "Uydurma" denetimi, "yapmak / etmek / olmak" gibi yardımcı fiilleri yok sayacak biçimde iyileştirilebilir (r05).
9. **Yoğun yükte sıkıştırma:** Sohbet bir sıkıştırmayı kestiğinde öneki yeniden işleme maliyeti (§12, en kötü 62 sn). Sıkıştırmanın daha seyrek ama daha büyük adımlarla yapılması ya da kesilen sıkıştırmadan sonra sohbet önekinin önce ısıtılması ölçülerek değerlendirilebilir.
