# LAZIS — REL-003 Düzeltme 3: Uygulama ve Kısa Deneme

- **Tarih:** 2026-11-04
- **Kod:** `3f6f260`. Gerçek profil, Ollama servis ayarları, model, migration, öğrenme ve kanıt denetimi değişmedi.
- **Deneme:** Geçici Ollama süreci, sınır 8, öğrenme kapalı, 9,2 dakika. Ham veri: `evals/reports/phase10/perf/fix3-short/`.
- **Durum:** Durdu, sahibinin kararı bekleniyor. Tam çoklu test başlatılmadı, Düzeltme 4'e geçilmedi.

## 1. Sonuç

**Sıra doğru uygulanıyor ve kesilme bu denemede kalktı. Ama yeni bir anlam sorunu ortaya çıktı: model gerçek bilgileri "Kullanıcının talimatları" başlığına yazıyor.** Kelime sayımı ve iddia seti bunu görmüyor. Bu çözülmeden tam testi önermiyorum.

## 2. Ne değişti

| Dosya | Değişiklik |
|---|---|
| `conversation/prompts.py` | `SUMMARY_OUTPUT_ORDER` eklendi; `SUMMARY_SCHEMA` bu sırayla kuruluyor; `SUMMARY_PROMPT_VERSION` `s3-v3` → `s3-v4` |
| `tests/unit/test_compaction.py`, `tests/integration/test_conversation_engine.py` | 6 yeni test |
| `evals/runners/p10p_compaction_cycles.py` | Yeni `short` deneme seti; `all` değişmedi |
| `evals/runners/p10p_cycles_compare.py` | Yeni karşılaştırma aracı |

**Yeni yazma sırası:** kararlar → talimatlar → kısıtlamalar → kişiler → hedefler → konular → sorular → LAZIS notları.

**Değişmeyen:** `SECTIONS` ve yanıt isteminde görünen özet düzeni, kanıt denetimi, ayrıştırıcı, özet talimatı metni, 1.200 token sınırı, veritabanı. `prompt_version` yalnızca kayda yazılıyor; eski özetler okunmaya devam ediyor.

**Sınır:** Şema bölüm düzeyinde. "Önemli değerler" (bütçe, tarih) için ayrı bölüm yok; model onları kararlara ya da konulara yazıyor. Sıranız bu yüzden yaklaşık uygulanabiliyor.

## 3. Kısa deneme

Eski testte üçüncü sürüme kadar kayıp görülen konuşmalar seçildi: D1 iki tohum, D3 tohum 11, D5 tohum 7; 3 sürüm, 12 özet, 13 soru.

| | Eski sıra | Yeni sıra |
|---|---|---|
| 1 200'de kesilen çıktı | **4 / 12** | **0 / 12** |
| Çıktı tokeni | 673–1 200 | 581–829 |
| Sıkıştırma süresi, ortalama | 51 s | 42 s |
| Sorular | 12 / 13 | 13 / 13 |
| Kelime denetiminde eksik (81 denetim) | 2 | 0 |
| Yeniden yazımda aday kayıp (kullanıcı) | 4 | 1 |
| "Talimatlar" bölümündeki madde | 0 | 2–4 (her özette) |
| Mehmet belirsizliği | Korundu | Korundu; ilişki satırındaki yanlış işaret de gitti |
| Yeni sıranın izlenmesi | | 12 / 12 |

**Geri gelenler:** `kız kardeş` (iki tohum, 3. sürüm), `8 bin`, `vejetaryen` (aynı maddede). Restoran sorusu artık vejetaryenliği söylüyor. D1 ve D5'in kahvaltı planı da ilk özete girdi.

**Yine kaybolan:** D5 kahvaltı planı 2. sürümde düştü. Mekanizma A sürüyor.

**Sistem:** Kritik yok, kısa uyarılar (48 s, en uzunu 30 s), swap artışı yok; program belleği 14 GB civarındaydı.

## 4. Elle okumada görülen sorunlar

**Sorun 1, önemli: "Talimatlar" başlığı yanlış kullanılıyor.** 12 özetin hepsinde bu başlık altında talimat olmayan bilgiler var:

- "Ayşe, kullanıcının kız kardeşi, 3 Kasım'da Ankara'ya taşınıyor."
- "Taşınma için bütçe en fazla 20 bin TL."
- "Mehmet (iş arkadaşı) 10 Kasım'da İzmir'e gidebilir (kesin değil)."
- "Kullanıcı yarın için … kahvaltı planlıyor."
- "22 Ekim saat 10:30'da diyetisyen randevusu var."

Gerçekten talimata benzeyen yalnızca "restoran seçiminde buna dikkat edilecek". Bu satırlar yanıt isteminde **"Kullanıcının talimatları:"** başlığıyla görünür. Bu, kullanıcının söylemediği bir talimat izlenimi verebilir; özellikle belirsiz Mehmet bilgisi için. Kısa sorularda zararı görülmedi, ama ölçülmedi. Nedeni muhtemelen modelin ikinci sıradaki bölümü genel bilgi kabı gibi kullanması; bu bir tahmin.

**Sorun 2: Konular belirsizleşti.** "Tatil Planı", "Sağlık ve Spor" gibi başlıklar içerik taşımıyor. Asıl bilgi diğer bölümlerde olduğu için bu denemede kayıp yok.

**Sorun 3: Sorular bölümü boşaldı.** Tekrarlı dolgu soruları artık yazılmıyor; çıktının küçülmesinin ana nedeni bu. İyi görünüyor, ama gerçek ve açık bir kullanıcı sorusu da düşebilir. Ölçülmedi.

**Sorun 4: Özet donmuş gibi görünüyor.** Sonraki sürümlerde metin neredeyse aynı kalıyor. Bu testte sonraki mesajlar yalnızca dolgu olduğu için bu doğru davranış olabilir, ama **sonradan gelen gerçek bir bilginin ve değişen bir kararın özete girip girmediğini bu test sınamıyor.** Çoklu test ve 40 mesajlık koşu da bilgileri ilk özetten önce veriyor.

## 5. Bu sonucun sınırları

- **Seçim etkisi:** Konuşmalar eski kayıplar olduğu için seçildi. İyileşmenin bir kısmı buna bağlı olabilir.
- **Az kapsam:** 12 özet, 2 tohum, 3 sürüm. En büyük kayıp (D5 tohum 11, 5. sürüm) kapsam dışında.
- **Kaybın ana nedeni değişmedi:** Mekanizma A hâlâ var; bu denemede daha az göründü, nedeni kanıtlanmadı.
- **Sınanmadı:** Gerçek konuşma metni, öğrenme açık kullanım, sonradan gelen bilgi, eski değer yönetimi.
- **Sıkıştırma süresi:** Düşüş çıktının kısalmasından geliyor. Bu C sayılmaz; 175 s'lik bekleme ölçülmedi.
- **Kanıt denetimi:** Değişmedi. Mekanizma C (`Kuzey`, `15 Aralık`) ayrı kayıt olarak açık.

## 6. Tam test için önerilen plan (başlatılmadı)

**Ön koşul:** Sorun 1'in çözümü. Önerilen en küçük yol: özet talimatına tek satır ("`instructions`: yalnızca kullanıcının LAZIS'ten açıkça istedikleri; bilgi ve planlar buraya yazılmaz"), ardından aynı 9 dakikalık kısa deneme. Bu, talimat metnini değiştirdiği için ayrıca onayınızı ister. Alternatif olarak `instructions` hedeflerin arkasına alınır; ama bu sizin önceliğinizle çelişir.

Ardından sırayla:

1. **Yeni kısa senaryo (yaklaşık 10 dakika):** İlk özetten sonra gelen gerçek bilgi, değişen karar ("bütçe 25 bin oldu") ve belirsizleşen bilgi. Sonraki özette yerini alıyor mu, eski değer güncel görünüyor mu?
2. **Tam çoklu test (46 dakika):** 10 konuşma, 2 tohum, 5 sürüm, sınır 8.
3. **40 mesajlık konuşma, 60 s (1 saat), en az 2 koşu.** Girdi yanıtlara bağlı; bilgi kaybı burada doğal değişken.

**Kabul ölçütleri:**

- Korunan bilgi sürüm başına en az 62, 61, 59, 59, 56; yeni kayıp dengelenmez.
- 20 iddialık sette yeni kayıp ve anlam bozulması yok.
- **Yeni:** Bölüm doğruluğu elle okunur; talimat olmayan bilgi "talimatlar" altında kalmaz.
- Kesilen çıktı sayısı 16/50'nin belirgin altında; kesilirse kritik bölümler tamam.
- Belirsizlik korunur, eski değer güncel görünmez, sorular 28/32'nin altına düşmez.
- Durma kuralları aynı.

## 7. Düzeltme 4 için güvenli sınırlar (uygulanmadı)

Düzeltme 3 kabul edilmeden başlanmamalı; taban çizgisi yeniden ölçülmüş olmalı.

- **Yalnızca kullanıcı kaynaklı maddeler** taşınır. LAZIS notları, öneriler ve çıkarımlar asla.
- **Metin aynen taşınır:** yeniden yazma, birleştirme, `certain` değiştirme yok. Belirsiz, belirsiz kalır.
- **Yeni kullanıcı gerçeği üretilmez:** Kaynak mesajı, atfı ve alıntısı geçerli olmayan madde taşınmaz; kanıt denetiminden geçer.
- **Değişen bilgi geri gelmez:** Yeni mesajlar değiştirdiyse taşınmaz. Bu kural emin değilse madde taşınmaz ama **görünür aday** olarak raporlanır; sessizce eski değer canlandırılmaz.
- **Reddedilen madde taşınmaz:** Mekanizma C bu işe dâhil değil.
- **Üst sınır ve görünürlük:** Taşınan maddeler bölüm ve token sınırına tabi; düşürülen madde sayılır.
- **Kalıcı kayıtlar değişmez:** Mesajlar ve eski özet sürümleri aynı kalır; migration yok.
- **Önce modelsiz:** Saklı 50 ham çıktıda geri gelen, yinelenen, büyüyen ölçülür. Kötüyse model koşusuna geçilmez.
- **Ayrı onay ve geri alma:** Tek commit, `git revert`; C ve REL-001, REL-002 ile karıştırılmaz.

## 8. İkinci deneme: talimat tanımı eklendi (2026-11-04, `df4da97`, `s3-v5`)

**Değişen:** Özet talimatına sahibinin verdiği metinle 11. kural. Bölüm sırası, kanıt denetimi, ayrıştırıcı, veritabanı, öğrenme ve 1.200 sınırı aynı. `make check` geçti (3 305 test).

**Sonuç: Talimat hatası düzeldi, ama önemli bir bilgi kayboldu. Düzeltme 3 bu hâliyle kabul edilemez.**

Aynı kısa deneme (12 özet, geçici süreç, sınır 8). Ham veri: `evals/reports/phase10/perf/fix3b-short/`.

| | Eski sıra | Yalnız yeni sıra | Yeni sıra + kural |
|---|---|---|---|
| Kesilen çıktı | 4 / 12 | 0 / 12 | **0 / 12** |
| Çıktı tokeni | 673–1 200 | 581–829 | 512–947 |
| Ortalama sıkıştırma | 51 s | 42 s | 43 s |
| "Talimatlar" bölümünde madde | 0 | 2–4 | **0** |
| Kelime denetiminde eksik (81) | 2 | 0 | **4** |
| İddia setinde kayıp (87) | 12 | 2 | **13** |
| Sorular, elle | 12 / 13 | 13 / 13 | 12 / 13 |

(İddia sayımı yalnızca kurala göre; bu denemedeki sonuçları ayrıca elle okudum. Kayıpların 9'u düşük önemli kahvaltı planı.)

**Düzelen:**

- Kısa setin 12 özetinde "talimatlar" boş; gerçek talimat olmadığı için doğru.
- `kız kardeş` ve `8 bin` korundu. Mehmet belirsizliği korundu.

**Kötüleşen, D5 tohum 7:**

- **`vejetaryen` ilk özetten itibaren yok.** Model bunu "Beslenme Tercihleri [#8]" gibi içeriksiz bir başlığa indirdi. Restoran yanıtı yine vejetaryenliği atladı. Sahibinin özellikle korunmasını istediği bilgi türü bu.
- **`Mavi Koy` 3. sürümde kayboldu.**

**Yeni sınıflandırma sorunları:**

- **Bilgi kabı yer değiştirdi:** D1'de "Ayşe 3 Kasım'da Ankara'ya taşınıyor" ve belirsiz Mehmet seyahati "Önemli kısıtlamalar" altında. Talimat kadar yanıltıcı değil, ama doğru bölüm değil.
- **Dolgu soruları hedefe dönüştü:** D1 tohum 7'de "Kompost yapmak" kullanıcı hedefi olarak yazıldı, "Ayşe'ye yardım" hedefi düştü. Kullanıcı yalnızca soru sormuştu.

**Sentetik talimat denemesi (`fix3b-instructions`, 1 diyalog, 2 tohum, 3 sürüm, 5,9 dakika):**

| Beklenen | Sonuç |
|---|---|
| Yanıtlar en fazla üç cümle | Talimatlarda, 6/6 |
| Tarihler gün.ay.yıl | Talimatlarda, 6/6 |
| Emoji: eskisi "kullanma", yenisi "kullanabilirsin" | Yalnız yenisi talimatlarda, 6/6; eskisi güncel görünmüyor |
| Avukat bulmayı hatırlat | **Talimat olarak kayboldu:** "Hedefler: Kira sözleşmesi için avukat bul." Hatırlatma isteği gitti |
| Bütçe, randevu | "Devam eden konular" altında, doğru |
| Fıstık alerjisi | "Önemli kısıtlamalar" altında, doğru |
| Fatma'nın belirsiz planı | Talimatlara girmedi, belirsiz kaldı |

**Sentetikte görülen ayrı sorunlar:**

- **Uydurma yıl:** "5 Nisan" ve "12 Mart", "05.04.2024" ve "12.03.2024" oldu; kullanıcı yıl söylemedi ve yıl yanlış. Yanıtlar da bunu tekrarladı. Tarih biçimi talimatı tetiklemiş olabilir. Kanıt denetimi metni alıntıyla karşılaştırmadığı için geçti. Bu, kuralın kapsamı dışında ama gerçek bir anlam hatası.
- **Yineleme:** Talimatlar "Kararlar" altında da yazıldı.
- **Yanlış işaret:** "Fatma: Kullanıcının annesi (belirsiz)". İlişki kesin, belirsiz olan plan.

Çıktılar 986–1 057 token, kesilme yok. Sorular otomatik 3/4 ve 4/4; "gidebileceği bilgisi" belirsizliği koruduğu için elle 4/4 ve 4/4. Yanıtların talimata uyup uymadığı ayrıca ölçülmedi.

### Bu deneme neyi kanıtlamıyor

Küçük girdi değişikliği büyük sonuç doğuruyor: tek cümle D5 tohum 7'yi baştan değiştirdi. **Kuralın "tercihler" sözcüğü mü vejetaryenliği düşürdü, yoksa bu doğal değişkenlik mi, 12 özetten söylenemez.** Bu yüzden metni bu tek olaya göre yeniden ayarlamayı önermiyorum; aşırı uyum riski taşır. Daha geniş ölçüm gerekir.

### Sonraki adım önerisi (başlatılmadı)

1. **Sonradan gelen bilgi ve değişen karar senaryosu (yaklaşık 10 dakika):** Ayrı bir soruyu yanıtlıyor, bu sonuçtan bağımsız. Kabul değil, ölçüm.
2. **Tam çoklu test (46 dakika) `s3-v5` ile:** 10 konuşma, 5 sürüm; 62→56/64 ile karşılaştırılır. Vejetaryen kaybının yaygın mı tek seferlik mi olduğunu ve `D5 tohum 11` sonucunu gösterir. Düzeltme 3'ün kabulü buna bağlı.
3. **Sonuç kötüyse:** Kural metninde bir düzeltme (örneğin "beslenme ve sağlık bilgisi somut değeriyle yazılır") veya yeni sıranın geri alınması. Geri alma `git revert`.

Uydurma yıl ve hatırlatma isteğinin kaybı REL-003 kaydına işlendi; bu düzeltmenin parçası değildir.

