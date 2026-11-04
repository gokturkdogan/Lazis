# LAZIS — Bağlam Sıkıştırma Gecikmesi: Teknik Öneri

- **Durum:** Öneri; sahibinin uygulama onayını bekliyor. Kod değiştirilmedi. Faz 10C'ye başlanmadı.
- **Tarih:** 2026-11-03
- **Kod:** `c366fbf` (stabilizasyonun son kodu)
- **Ölçümler:** Geçici betikler, doğrudan yerel model istekleri, sentetik veri. Profil ya da veritabanı kullanılmadı. Önbellek denemeleri 11499 portunda geçici bir Ollama sürecinde yapıldı; gerçek servisin ayarları değişmedi, yalnızca yüklü model bir kez boşaltıldı. Ham veriler: `evals/reports/phase10/compaction_probe_{1,2,3}.json`.

## 1. Mevcut mimari ve çakışmanın nedeni

Yerel çalışma zamanında tek bir yuva ve bu yuvaya ait tek bir etkin önek vardır. Bütün model istekleri `conversation/scheduler.py` üzerinden sıraya girer; kullanıcı turu arka plan işini keser.

Sıkıştırma şöyle ilerler:

1. Bağlam 6 144 tokeni geçince yanıttan 5 s sonra arka plan işi başlar (`engine._run_due`).
2. Yaklaşık 6 000 tahmini tokenlik her parça için **konuşmadan bağımsız ayrı bir istem** gönderilir (`compaction.build_messages`). Bir parça 34–65 s sürer: önce dolum, sonra çıktı.
3. Her parça doğrulanıp ayrı kaydedilir; kesilen parça kaybolur, kaydedilenler kalır.
4. Bağlam kesin sınıra (13 721 token) ulaşırsa bütün birikim tur içinde özetlenir: 3 parça, 148–167 s (`engine._fit_for_turn`).

**Sorunu üç şey birlikte yaratıyor:**

- **Önbellek kaybı.** Ayrı istem konuşmayı yuvadan çıkarıyor. Bu artık doğrudan gözlendi (rapordaki çıkarımın yerine geçer): kesilen sıkıştırmadan sonraki tur 6 200 tokende **22,6–23,5 s**, 12 050 tokende **46,5–52,3 s** bekliyor.
- **Bitemeyen iş.** Parça 34–65 s sürerken 30 s aralıkla yazan kullanıcının bıraktığı süre yaklaşık 25 s. İş hep kesiliyor, hiç ilerlemiyor, bağlam büyüyor.
- **Birikmiş faturanın tek turda ödenmesi.** Kesin sınırda 3 parça aynı anda yapılıyor.

Kod okumasından çıkan yan etki: sıkıştırma beklerken yeniden ısıtma ve öğrenme de çalışmıyor (`_run_due`). Öğrenme gecikmesi henüz ölçülmedi.

## 2. Seçeneklerin karşılaştırılması

İlk dördü stabilizasyon raporundaki öneriler; son üçü bu çalışmada eklendi.

| # | Yaklaşım | Veri güvenilirliği | Bağlam ve hafıza | Token maliyeti | İlk token | Yerel donanım | Karar |
|---|---|---|---|---|---|---|---|
| 1 | Etkin konuşmada başlatmamak | Değişmez | Değişmez | Değişmez | Ara turlar hızlı, ama sınırda 148 s durur | Değişmez | Tek başına **yetmez**; sorunu erteler |
| 2 | Önce en eski mesajları düşürmek | Mesaj silinmez | **Bilgi kaybı:** bu aralık hiçbir zaman özetlenmez | Az | En iyi | Değişmez | **Ret:** sınırınızı ihlal eder |
| 3 | Kesilen işin ilerlemesini korumak | Değişmez | Fazla kuşak özeti bozabilir (ölçülmedi) | Parça başına özet yeniden yazılır | Küçük etki | Değişmez | **Zaten var;** yalnızca parça küçültme kalıyor, gerekirse ayar |
| 4 | Sıkıştırmadan önce yeniden ısıtmak | Değişmez | Değişmez | Yanıt kadar (yaklaşık 500) | Yaklaşık 2 s kazanç (tahmin) | Değişmez | **Kabul** (küçük tamamlayıcı) |
| 5 | Özeti konuşma önekine eklemek (öğrenme gibi) | Değişmez | **Kalite düştü** (aşağıda) | Dolum azalır | Sonraki tur 2,2–2,6 s | Değişmez | **Ret** (şimdilik) |
| 6 | RAM istem önbelleğini büyütmek | Değişmez | **Değişmez:** özet istemi aynı kalır | Yok | Kesintiden sonra 0,8–6,3 s | Ek RAM; dolunca en çok 6 GB | **Kabul** |
| 7 | Eşik aşılınca tek parçayı bitirmek | Değişmez; süre sınırlı | Değişmez | Değişmez | Seyrek, sınırlı bekleme | Değişmez | **Kabul** |

**Düzeltme:** Raporda 3. öneriyi yeni bir iş gibi yazmıştım. Parça başına kayıt zaten var; asıl sorun çoğu konuşmada işin tek parça olması ve o parçanın süresi.

### Seçenek 5 neden elendi

Hız kazancı gerçek, ama kalite kapısını geçemedi. Veri seti: `tr_compaction_v1`; aynı 5 diyalog, 32 bilgi.

| Biçim | Koşu | Kaybolan bilgi | Tutulan madde | Elle okuma |
|---|---|---|---|---|
| Mevcut ayrı istem | 4 × 32 bilgi | 2/128 | 243 | D2'de bir koşuda "Kuzey" ve "15 Aralık" kayıp |
| Önek + döküm | 4 × 32 bilgi | 3/128 | 189 | "Ali cumartesi dönüyor" 4 koşunun 3'ünde kayıp (mevcut biçimde 0/4); güncel bir karar "eski kararlar"a yazıldı |
| Önek + yalnızca numara listesi | 1 × 32 bilgi | 4/32 | 38 (mevcut: 54) | D4'te 3 bilgi kayıp |

Tekrarlı uzun konuşmada önek + döküm **boş özet** üretti (2/2 denemede 0 madde; mevcut biçim 11 madde). Kayıp sayısı küçük örnekte yakın görünse de bu boş özet ve yanlış karar, hız için kalite riskini kabul edilemez kılıyor. Bu biçim gerçek kesintiyle de sınanmadı, çünkü özetler süre dolmadan bitti.

### Seçenek 6: Ölçüm

Bugünkü özet istemi değişmeden gönderildi, 20. saniyede gerçekten kesildi, ardından eski konuşmaya bir tur gönderildi.

| `LLAMA_ARG_CACHE_RAM` | 6 200 token (2 koşu) | 12 050 token (2 koşu) |
|---|---|---|
| 2 048 MiB (bugünkü) | 22,6 / 22,9 s | 52,0 / 52,3 s |
| 4 096 MiB | 5,7 / 1,2 s | 5,5 / **49,1 s** (kaçırdı) |
| 8 192 MiB | 4,6 / 0,8 s | 6,3 / 1,8 s |

Kesilen özet yeniden denenince dolumu da çoğu zaman 1–4 s'ye iniyor (16–18 s yerine).

**Sınırlar:** Koşu başına 4 ölçüm var, gerçek motordan geçmedi ve konuşma öneki tam ısıtılmıştı. Kısa denemede önbellek dolmadı, bu yüzden çalıştırıcının RSS tepesi (10,5–11,0 GB) RAM maliyetini göstermiyor. ADR-0010'daki dolu önbellek ölçümü 13,2 GB, 2 048 MiB ile 6,4 GB'tı. Uzun testte yeniden ölçülmeli.

## 3. Arka plan sıkıştırması sürerken mesaj gelirse

1. Mesaj **her durumda önce kaydedilir** (bugünkü gibi).
2. **Bağlam acil eşiğin altındaysa** (öneri 9 000–10 000 token, kesin değer testle): iş en geç 2 s içinde kesilir, yanıt hemen başlar, konuşma RAM'den geri yüklenir. Kesilen parça hiç yazılmaz.
3. **Bağlam acil eşiğin üstündeyse ve iş sürüyorsa:** o parça bitirilir, görünür "sıkıştırılıyor" durumu gösterilir. Bekleme en çok 60 s'dir; aşılırsa iş kesilir ve kesin sınırın altındaysa yanıt verilir.
4. **Bağlam acil eşiğin üstündeyse ve iş yoksa:** yanıttan önce **yalnızca bir parça** özetlenir.
5. **Kesin sınır** son çare olarak kalır. Duyurulu kırpma yalnızca sıkıştırma başarısız olursa çalışır; hız için asla.
6. Yarım özet yazılmaz. Parça yalnızca bütün olarak ve kanıt denetiminden geçerek kaydedilir.
7. Yanıt sürerken gelen ikinci mesajın reddedilmesi ve kapanış davranışı değişmez.

## 4. Önerilen çözüm: En az müdahale

Üç küçük parça. **`compaction.py`, `prompts.py`, veritabanı şeması ve özet biçimi değişmiyor;** özet istemi birebir aynı kalıyor. Hafıza riskinin en düşük olduğu yol bu.

- **A. RAM önbelleği:** Değer ölçümle belirlenecek; aday 8 192 MiB, ara değer olarak 6 144 MiB de denenecek. Mac'inizdeki LaunchAgent'a yalnızca **ayrı onayınızla** uygulanır.
- **B. Sıkıştırmadan önce yeniden ısıtma:** Geri yüklenen durum son yanıtı da içerir.
- **C. Acil eşik ve tek parça sınırı:** Bölüm 3'teki davranış.

Parça küçültme (`compaction_chunk_tokens`, 6 000 → 3 000) yalnızca hedef tutmazsa ve kalite testi geçerse ayar olarak denenir.

**Beklenen sonuç (ölçülen parçalardan hesap; henüz ölçülmedi):** 30 s aralıkta çoğu tur birkaç saniye, yaklaşık 8 mesajda bir 15–40 s; 6 s aralık ya da hemen yazan kullanıcıda seyrek 45–80 s. Bu, sıkıştırma süresini ortadan kaldırmaz: özet kalitesini korumak için bir parçanın 34–65 s'lik işi bazen kullanıcının önüne düşebilir. Ama 2–3 dakikalık bekleme kalkar.

**Maliyet:** En çok 6 GB'a kadar ek RAM (dolu önbellekte). 24 GB'lık Mac'te bu sınır uzun testte denetlenecek; sorun çıkarsa daha düşük değer seçilecek.

## 5. Başarı kriterleri

Üretim ayarları, her aralık için 3 koşu, boş konuşmadan başlayan 40 mesaj (birkaç sıkıştırma döngüsü).

| Yazma aralığı | Bugün (medyan / en kötü) | Hedef medyan | Hedef en kötü |
|---|---|---|---|
| 6 s | 7,0–7,6 s / 181 s | ≤ 6 s | ≤ 90 s |
| 30 s | 35,8 s / 162 s | ≤ 6 s | ≤ 45 s |
| 60 s | 0,4 s / 29,8 s | ≤ 2 s | ≤ 20 s |

Bütün aralıklarda ayrıca:

- 15 s'yi aşan bekleme 8 mesajda en çok 1 kez olacak ve görünür durum gösterecek.
- Kırpma (`window_only`) ve bağlam dışı aralık: **0**.
- Mesaj kaybı ve sıralama bozulması: **0**.
- Hedef tutmazsa kriteri gevşetmeden size raporlarım.

**Sahibinin kararı (2026-11-04), C için zorunlu:**

- **Bilgi koruma hız kadar zorunludur.** C, çoklu sıkıştırma sonrası bilgi korumada mevcut kayıptan kötü sonuç verirse kabul edilmez. Sınırlar ve ölçüm: [COMPACTION_MULTI_CYCLE_QUALITY_TEST.md](COMPACTION_MULTI_CYCLE_QUALITY_TEST.md#acceptance-for-c-owners-decision-2026-11-04).
- **Kayıtlar silinmez.** Kalıcı konuşma ve özet kayıtları hiçbir koşulda hız uğruna silinmez.
- **Yeni kayıp dengelenmez.** Yeni bir bilgi kaybı, başka bir bilginin geri gelmesiyle telafi edilmiş sayılmaz.
- **Ölçüm C'nin çalıştığı senaryolarda yapılır.** C'nin kodunu hiç çalıştırmayan bir testin geçmesi kanıt değildir.
- **Bütün konuşmaya bakılır.** Özet sürümü başına rakamlar yanında konuşma sonundaki toplam bilgi kaybı ve yeniden yazım sayısı da karşılaştırılır.
- **62/64 → 56/64 yalnızca regresyon taban çizgisidir,** LAZIS'in hafıza kalite hedefi değildir. Uzun vadeli hedef: önemli bilgiler tekrarlanan sıkıştırmalarda kaybolmaz, belirsiz ifadeler kesinleştirilmez. [REL-003](RELIABILITY_ISSUES.md#rel-003-facts-disappear-silently-when-a-summary-is-rewritten) açık kalır.
- Kelime veya embedding eşleşmesi tek başına doğruluk kanıtı sayılmaz. Model tabanlı otomatik hakem şimdilik eklenmez.

## 6. Mesaj kaybı, sıralama ve bilgi kaybı testleri

**Birim ve entegrasyon (sahte model):**

- Özet isteği bugünküyle birebir aynı (altın test).
- Acil eşiğin altında ve üstünde kesme ve bekleme davranışı; 60 s sınırı.
- Bekleme sırasında iptal, kapanış ve başarısız sıkıştırma.
- Kesilen parçanın yazılmaması; özgün mesajların değişmemesi.

**Gerçek Gemma, uzun görüşme:**

- **Mesaj bütünlüğü** (veritabanından): her mesaj bir kez ve sırasında, her soruya tamamlanmış yanıt, yarım kalan yok; yeniden açılışta aynı sonuç.
- **Bağlam bilgisi:** Bilinen bilgiler konuşmanın başına yerleştirilir, birkaç sıkıştırma döngüsünden sonra sorulur. `p3_context_eval` taban çizgisi korunur (soru doğruluğu 16/16, bu çalışmada mevcut biçim 126/128 bilgi).
- **Yanlış hafıza:** Bütün özetler ve yanıtlar elle okunur. LAZIS önerisi kullanıcı kararı gibi yazılmamalı, güncel karar eski görünmemeli. Hafıza kayıtları veritabanından denetlenir.
- **Öğrenme:** Kuyruktaki işlerin bitmesi ve gecikmesi ölçülür.
- **Donanım:** Çalıştırıcının RAM tepesi, takas ve bellek baskısı.

**Regresyonlar:** çıktı korumaları, kimlik, hafıza iddiaları, öğrenme, hafıza işlemleri, Faz 6–7, PER-06, PER-12, DOI, kişilik, `make check`. Hangi testin hangi commit'te koştuğu ayrı raporlanır.

## 7. Uygulama sırası

Her adım ayrı commit'tir; yeni adıma ölçümle geçilir.

1. Değerlendirme aracını genişlet (40 mesaj, boş başlangıç, geçici Ollama portu); bugünkü taban çizgisini ölç.
2. A: Gerçek motorla önbellek değerini seç (kod değişmez). Sonucu raporla.
3. B: Yeniden ısıtma; ölç.
4. C: Acil eşik ve tek parça; ölç.
5. Regresyonlar ve ayrı rapor; onayınızı bekle.

## 8. Geri alma planı ve etkilenecek dosyalar

**Geri alma:**

- **A:** `LAZIS_PROMPT_CACHE_MIB=2048 scripts/ollama-agent.sh install`
- **B ve C:** İlgili commit'lerin `git revert` ile geri alınması. C ayrıca kesin sınıra eşit ayarla kapatılabilir.
- **Veri:** Migration ve biçim değişikliği olmadığı için veri geri dönüşümü gerekmez.

**Değişecek dosyalar:**

| Dosya | Değişiklik |
|---|---|
| `scripts/ollama-agent.sh` | Önbellek varsayılanı (A) |
| `core/src/lazis/config/model.py` | Acil eşik ayarı |
| `core/src/lazis/conversation/scheduler.py` | Turun sıkıştırma parçasını süreli beklemesi |
| `core/src/lazis/conversation/engine.py` | `_run_due`, `_fit_for_turn`, `_compact` (parça sınırı) |
| `core/tests/integration/test_conversation_engine.py` ve zamanlayıcı testleri | Yeni testler |
| `evals/runners/p10s_compaction_turn.py` | Uzun senaryolar |
| `docs/adr/0023-…`, `docs/adr/0010-…` §7a, `docs/DEVELOPER_GUIDE.md`, `docs/DEVELOPMENT_ROADMAP.md` | Karar ve belgeler |

**Değişmeyecekler:** `compaction.py`, `prompts.py`, migration'lar, hafıza kodu. Arayüz "sıkıştırılıyor" durumunu zaten gösteriyor; değişiklik beklemiyorum, gerçek uygulamada doğrulanacak.

**Dokunulmayacaklar:** Gerçek profil, `0008_adaptation`, push, Faz 10C.

## 9. C planına ek: küçük iddia seti (kapsam ve maliyet)

**Durum:** Set 2026-11-04'te kuruldu, sonuçlar [REL003_OBSERVABILITY_REPORT.md](REL003_OBSERVABILITY_REPORT.md). Kapsamlı bir sistem kurulmadı. Aşağıdaki süreler tahmindi.

**Amaç:** C'nin bilgi korumasını kelime sayımından daha doğru ölçmek ve aynı yöntemle bugünkü taban çizgisini de puanlamak. Kapsamlı değerlendirme sisteminin yerine geçmez.

**Kapsam: 20 iddia, D1 ve D5 diyaloglarından.** Her iddia: konu, değer, kaynak mesaj, kesinlik durumu.

| Durum | Sayı | İddialar |
|---|---|---|
| Kesin | 15 | Ayşe kız kardeş; Ayşe 3 Kasım Ankara; nakliye tutulmayacak; bütçe 20 bin; toplantı perşembe; Mehmet iş arkadaşı; uçuş 14 Haziran 07:45; Sabiha Gökçen; Kaş; Mavi Koy; araba kiralanmayacak; otobüs; bütçe 35 bin; Selin eş; Selin vejetaryen |
| Belirsiz | 3 | Mehmet 10 Kasım İzmir; yarın kahvaltı planı (D1, D5) |
| Değişti | 2 | Toplantı salı; Antalya |

**Tekrar üretilebilirlik:** Yeni model çağrısı yok. Girdi, saklı `rendered` alanıdır.

| Girdi | Özet | Denetim |
|---|---|---|
| Çoklu test, D1 ve D5, 2 tohum, 5 sürüm | 20 | 200 |
| REL-002 koşuları (6 s, koşu 2 ve 3), sürüm 1 ve 2, yalnızca Mehmet'in 2 iddiası; bu koşularda tekrarlı dolgu yok | 4 | 8 |
| **Toplam** | **24, yaklaşık 35 bin karakter** | **208** |

Ayrıca bu iki diyaloğun saklı 14 yanıtı elle okunur.

**Neden bu ikisi:** yeniden yazımda kaybolan 6 bilginin 4'ü (`vejetaryen`, `Kaş`, `Mavi Koy`, `35 bin`), kelime denetiminin kaçırdığı iki kayıp (`otobüs`, `kız kardeşi`), REL-002'nin Mehmet olayı ve geçemeyen 4 yanıtın tamamı burada.

**Maliyet:**

| Kalem | Tahmin |
|---|---|
| Model süresi, RAM, ürün kodu | Yok |
| Değişecek ürün dosyası | Yok; yalnızca bir veri dosyası ve yaklaşık 100–150 satırlık bir puanlama betiği (`evals/`) |
| Elle puanlama, taban çizgisi | 208 denetim, benim için tek oturum |
| Sizin doğrulamanız | 20 iddiayı ve tartışmalı denetimleri gözden geçirmek: yaklaşık 15–30 dakika |
| Her C sürümü | Zaten gereken 46 dakikalık çoklu test ve günlük testlerin çıktısı üzerinde aynı elle puanlama. Ek model süresi yok |

**C'nin çalıştığı senaryolarda kullanım:** Günlük senaryolar ve 40 mesajlık koşular aynı veri setinin bilgi mesajlarından seçiyor (`fact_messages`), bu yüzden iddialar yeniden yazılmadan kullanılabilir. Kapsam senaryoya göre değişir:

| Senaryo | Geçerli iddia (20'den) | Belirsiz olan |
|---|---|---|
| Hafif | 6 (Ayşe 2, Mehmet 2, Selin 2) | Mehmet |
| Orta | 10 (hafiftekiler, toplantı 2, uçuş 2) | Mehmet |
| Yoğun ve 40 mesajlık koşular | 18 (kahvaltı dışında hepsi) | Mehmet |

Orta ve yoğun senaryolardaki diğer belirsiz ifadeler (`Kadir`, `Gülay`) bu 20 iddianın dışındadır; gerekirse birer iddia olarak eklenebilir. Hafif test 10 kısa mesajdan oluştuğu için sıkıştırmaya hiç ulaşmayabilir; o zaman C için kanıt vermez. Bu, hafif testin sonucunda görülecek.

**Sınırlar:**

- Set bilinen kayıpları içerecek şekilde seçildi. Bu nedenle kayıp **oranı** vermez; 64 bilgilik regresyon taban çizgisinin yerine geçmez, onunla birlikte raporlanır.
- D2, D3, D4 dışarıda: `cuma` ve `8 bin` kayıpları bu setle görünmez.
- Belirsizlik için hâlâ 3 iddia var ve hepsinde açık kelime geçiyor ("galiba", "belki"). Örtük belirsizlik ölçülemez; bunun için yeni diyalog ve yeni koşu gerekir, bu ek kapsam dışındadır.
- Dolgu uyarısı aynen geçerlidir: çoklu test özetleri tekrarlı dolgu içerir.
- Elle puanlama bir kişinin yargısıdır. Bu yüzden iddialar ve tartışmalı kararlar size gösterilir.
