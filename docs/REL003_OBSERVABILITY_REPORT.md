# LAZIS — REL-003: Gözlemlenebilirlik ve 20 İddialık Değerlendirme Seti

- **Tarih:** 2026-11-04
- **Kapsam:** Sahibinin onayladığı düzeltme 1 ve 2. Özetin içeriği, istemi, şeması ve çıktı sınırı değişmedi; migration yok.
- **Araçlar:** `core/src/lazis/conversation/compaction.py` (`parse_kind`, `audit_rewrite`), `engine.py` (`summary.output`, `summary.rewrite`, `summary_audit`), `evals/runners/p10p_claim_score.py`, `evals/datasets/tr_compaction_claims_sample_v1.json`.
- **Sonuçlar:** `evals/reports/phase10/perf/claims/claim_sample_v1.json`.

## 1. Düzeltme 1: Gözlemlenebilirlik

| Soru | Nereden görülür | İçerik |
|---|---|---|
| Çıktı sınıra ulaştı mı, gerçek token, durma nedeni? | `summary.output` günlük olayı | `output_tokens`, `max_tokens`, `done_reason`, `at_limit` |
| Çıktı tam mı, kesilip kurtarıldı mı? | `summary.output` | `parse`: `complete`, `salvaged`, `failed` |
| Bu yazım neyi kaybetmiş olabilir? | `summary.rewrite` günlük olayı | Kullanıcı ve LAZIS maddesi sayısı, artık atıf almayan mesaj numaraları, `became_certain` |
| Özet başına toplam | `compaction.completed` | `output_limit_hits`, `possibly_lost_user_items`, `became_certain` |
| Bir konuşmanın bütün sürümleri | `engine.summary_audit(conversation_id)` | Sürüm başına aday listesi: bölüm, kaynak, atıflar, kaybolan kelime sayısı |

**Gizlilik:** Günlüğe yalnızca sayı ve mesaj numarası yazılır, madde metni yazılmaz. Bunu bir test sınar. `audit_rewrite` sonucu da metin taşımaz. Metin zaten şifreli veritabanındaki özetlerde.

**`dropped_items`:** Kod ve API yorumları artık bunun kanıt denetiminin reddettiği madde sayısı olduğunu, kayıp ölçüsü olmadığını söylüyor. Alan adı değişmedi (API uyumu); `summary_audit` aynı değeri `rejected_items` diye veriyor.

**Sınırlar:**

- Token ve durma nedeni günlükte kalıyor, veritabanına yazılmıyor; bu migration gerektirir.
- `summary_audit` henüz bir API'ye veya arayüze bağlı değil. Yalnızca motor ve değerlendirme araçlarından çağrılıyor.
- Aday listesi kesin hüküm değildir (bölüm 3).

**Davranış değişmedi, kanıt:** `engine.py`'de silinen satır yok, yalnızca ekleme var. Gerçek Gemma ile kısa denetimde (D1, tohum 7, 2 sürüm, geçici süreç) özet isteklerinin özeti (hash), ham çıktılar ve özet metni, değişiklikten önceki hâliyle **bayt bayt aynı**. Denetimdeki bir hata özetlemeyi etkilemez: hata yakalanır, `summary.audit_failed` yazılır.

## 2. Düzeltme 2: 20 iddialık set

**Bu set bilinen kayıpları içerecek şekilde seçildi. Konuşmaların genelindeki hata oranını temsil etmez.**

**Kapsam:** D1 ve D5'ten 20 iddia (15 kesin, 3 belirsiz, 2 değişmiş); kişi, değer, kaynak mesaj, ilişki ve kesinlik durumu. 24 saklı özet, 208 denetim. Model çağrısı yok. Bir iddia ancak parçaları aynı özet maddesinde ve durumu doğruysa geçer. 37 farklı durumun hepsini elle okudum.

| Sonuç | Denetim |
|---|---|
| Korundu | 134 |
| Belirsiz olarak korundu | 17 |
| Değişmiş değer özette yok (doğru) | 20 |
| **Kayıp** | **32** |
| **Anlamı bozuk** | **5** |
| Belirsizliği kaybolmuş | 0 |
| Eski değer güncel gibi | 0 |

**Kayıpların ayrıntısı:**

| İddia | Kayıp | Nerede | Tür |
|---|---|---|---|
| Ayşe, kız kardeş | 6 | D1, iki tohum, sürüm 3–5 | Yeniden yazımda; kesilme |
| Selin, vejetaryen (aynı maddede) | 3 | D5 tohum 7, sürüm 3–5 | Yeniden yazımda; yer varken |
| Kaş, Mavi Koy, otobüs, 35 bin | 1'er | D5 tohum 11, sürüm 5 | Yeniden yazımda; yer varken |
| Mehmet'in seyahati ve iş arkadaşlığı | 2'şer | REL-002 koşuları, sürüm 2 | Yeniden yazımda |
| Yarın kahvaltı planı (D1) | 10 | Bütün sürümler | Özete hiç girmedi; düşük önem |
| Yarın kahvaltı planı (D5) | 5 | Tohum 7, bütün sürümler | Özete hiç girmedi; düşük önem |

**Değişen ve çelişen bilgiler:** `salı` ve `Antalya` eski değerleri bu özetlerde güncel gibi hiç görünmedi (20/20). Karar değişikliğinin kendisi ise iyi taşınmıyor: D5 tohum 7'de "Araba kiralama: False (Eski: assistant önerisi, Yeni: user reddetti)" satırı beş sürümde de duruyor ve aynı özette LAZIS notlarında "True" olanı da var.

**Sorular (14 saklı yanıt, sınır 8):** Otomatik 10, elle 11. Gerçek hatalar: iki restoran yanıtında vejetaryenliğin atlanması ve "Antalya'ya mı gidiyoruz?" sorusunda "bilgiye sahip değilim".

## 3. Yanlış alarmlar

| Yöntem | Yanlış alarm veya kaçırma | Örnek |
|---|---|---|
| **İddia kuralı** | 5 yanlış "korundu" | "Araba kiralama: False (…)": kelime var, anlam yok. Elle düzeltildi, gerekçesi veri dosyasında |
| **Kelime denetimi** | 7 yeniden yazım kaybını görmedi | `kız kardeş` (6 denetim): `Ayşe` kelimesi duruyor. `otobüs` (1): listede yok |
| **Kelime denetimi** | Yanlış alarm | Geçmiş olarak yazılmış `React`, `9:00` eski değer sayıldı (bu setin dışında) |
| **Soru denetleyicisi** | Doğru yanıtı kaldı | "planlamadığınızı hatırlatmak isterim"; uzun konuşmada "gitme ihtimali var" |
| **`audit_rewrite`** | Kaçırdığı bilinen yeniden yazım kaybı yok; çok aday | Aşağıda |

**`audit_rewrite` adayları (50 özet, 40 yeniden yazım, saklı ham çıktılarda; 22 kullanıcı maddesi, elle sınıflandırıldı):**

| Sınıf | Aday | Not |
|---|---|---|
| Gerçek kayıp | 8 | `kız kardeşi` (2), `vejetaryen`, `cuma`, `8 bin`, Kaş ve Mavi Koy, otobüs, `35 bin` |
| Düşük önemli gerçek kayıp | 2 | Kahvaltı planı |
| Tekrarlı dolgu sorusu | 9 | Testin yapay etkisi |
| Yanlış alarm (yeniden ifade) | 3 | "arka uçtan" → "arka uç"; "hareket" düştü; "Kullanıcının" düştü |

Yani adayların %36'sı gerçek kayıp. Bu bir hüküm değil, **okunacak listedir.** Tek kelime kaybını ayıklamak yanlış alarmları azaltır, ama gerçek kayıpları kaçırma riski taşır; şimdilik değiştirmedim. Bu yeniden oynatma, kanıt denetiminden geçmemiş ham çıktıyı kullanır. Ürün kodu denetlenmiş özeti karşılaştırır; bu yüzden denetimin reddettiği `Kuzey` maddesi 23. aday olarak çıktı ve sayıma almadım.

## 4. Yeni bulgu ve düzeltme: üçüncü mekanizma

**Düzeltmem:** "`Kuzey` ve `15 Aralık` ilk özette hiç yoktu" demiştim. Ham çıktı bunun yanlış olduğunu gösteriyor. Model D2 tohum 11'de "Kuzey projesinin teslim tarihi 15 Aralık." maddesini yazmış, ama kullanıcıya atfedip alıntıyı LAZIS'in yanıtından almış. Kanıt denetimi kurala uygun olarak reddetmiş (`dropped: 1`). Bilgi doğruydu.

Yani REL-003'te üç mekanizma var:

| | Mekanizma | Görüldüğü |
|---|---|---|
| A | Model yer varken bilgiyi atlıyor | `vejetaryen`, `cuma`, Kaş, Mavi Koy, `35 bin` |
| B | Çıktı 1 200'de kesiliyor, sessizce kurtarılıyor | `kız kardeşi` |
| C | Kanıt denetimi doğru bir bilgiyi, alıntısı yanlış mesajdan olduğu için reddediyor | `Kuzey`, `15 Aralık` |

C için önerim yok; denetim LAZIS'in sözlerini kullanıcı kanıtı saymamak için böyle. Plana ayrı not olarak girdi.

## 5. REL durumu

- **REL-001:** Bu aşamada değişmedi. Özet tarafında set 17/17 belirsizliği korudu, ama hafıza kaydındaki hata ayrı ve açık.
- **REL-002:** Set, Mehmet satırının sürüm 2'de kayboluşunu iki koşuda da yakaladı. Hatırlama tarafı açık.
- **REL-003:** Açık. Artık görünür ve ölçülebilir; düzeltilmedi.
