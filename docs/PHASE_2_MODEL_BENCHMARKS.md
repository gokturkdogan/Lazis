# LAZIS — Faz 2 Model Kıyaslama Raporu

> Tarih: 2026-10-17 · Makine: MacBook Pro M4 Pro (14 CPU / 20 GPU), 24 GB, macOS 27.0.1 · Ollama 0.40.4 (`OLLAMA_NO_CLOUD=1`, `127.0.0.1:11434`)
> **Ham veriler:** `evals/reports/phase2/<model>/perf.json` ve `quality.json` (ham model çıktıları dahil). Karşılaştırma tablosu `evals/reports/phase2/comparison.json` dosyasında. Bu rapordaki sayılar o dosyalardan alındı; hiçbiri elle tahmin edilmedi.
> **Yeniden üretmek için:** `make bench MODEL=…`, `make eval MODEL=…`, `uv run --project core python evals/runners/compare.py`
> **Model kararı:** ADR-0001 **Kabul Edildi** (2026-10-17). Birincil `gemma4:12b-it-qat`, yedek `qwen3.5:9b-q4_K_M`. G2 kapısı sonuçlar görüldükten sonra, sahibin onayıyla revize edildi (§7.1).
> **Ayrım:** §1–§15 nesnel ölçümler ve otomatik denetimlerdir. §9'daki "öznel değerlendirme" yapay zekâ değerlendiricisinin (bu raporun yazarının) görüşüdür; Türkçe doğallık için asıl karar sahibin kör değerlendirmesidir (§9.3).

## 1. Test edilen modeller

| Model | Rol | Durum |
|---|---|---|
| Qwen3.5-9B | Birincil aday (Faz 0 planı) | Ölçüldü; **yedek model olarak öneriliyor** |
| Gemma 4 12B | Rakip | Ölçüldü; **birincil model olarak öneriliyor** (geçici, §17) |
| Qwen3-8B | Hafif yedek adayı | Ölçüldü, elendi, silindi |
| Qwen3-14B | Yüksek kalite seçeneği | Ölçüldü, elendi, silindi |
| Qwen3.5-9B (MLX, nvfp4) | Çalışma zamanı karşılaştırması | Ölçüldü, elendi, silindi |

Dört aday da ollama.com resmî kütüphanesinde var ve Hugging Face model kartlarına göre **Apache 2.0** lisanslı. Gemma 4 kartı ayrıca Google'ın Gemma 4 lisans sayfasına bağlanıyor. Hiçbir aday yerine başka bir model konmadı.

## 2. Model tanımlayıcıları

| Ollama etiketi | Özet (digest) | Mimari | Parametre |
|---|---|---|---|
| `qwen3.5:9b-q4_K_M` | `56671c2ab938…` | qwen35 (hibrit dikkat), görüntü girişi var | 8,95 B (dil) + 0,46 B (görüntü) |
| `gemma4:12b-it-qat` | `38044be4f923…` | gemma4, görüntü girişi var | 11,96 B |
| `qwen3:8b-q4_K_M` | `500a1f067a9f…` | qwen3 | 8,19 B |
| `qwen3:14b-q4_K_M` | `bdbd181c33f2…` | qwen3 | 14,77 B |
| `qwen3.5:9b-nvfp4` | `8218177ac78e…` | qwen35 (MLX) | 8,95 B |

Tam özetler `perf.json` → `manifest.model.digest` alanında.

## 3. Nicemleme (quantization) ayrıntıları

| Model | Biçim | Nicemleme | Not |
|---|---|---|---|
| qwen3.5:9b | GGUF | Q4_K_M; görüntü projektörü BF16 (922 MB) | llama.cpp çalıştırıcısı |
| gemma4:12b | GGUF | Q4_0 (Google'ın nicemleme-farkındalıklı eğitimi, QAT) | llama.cpp çalıştırıcısı |
| qwen3:8b / 14b | GGUF | Q4_K_M | llama.cpp çalıştırıcısı |
| qwen3.5:9b-nvfp4 | safetensors (MLX) | NVFP4 (4 bit) | Ollama'nın MLX çalıştırıcısı |

Nicemleme ile çalışma zamanı ayrı ayrı ele alındı. Çalışma zamanı karşılaştırması aynı model üzerinde yapıldı (Qwen3.5-9B: Q4_K_M ile NVFP4). Ancak iki nicemleme birebir aynı değil; bu nedenle kalite farkları çalışma zamanından değil nicemlemeden kaynaklanıyor olabilir.

## 4. Çalışma zamanı sürümleri

- **Ollama:** 0.40.4 (Homebrew), kendi LaunchAgent'ıyla çalışıyor.
- **GGUF modelleri:** `libexec/lib/ollama/llama-server` alt sürecinde (llama.cpp) çalıştı.
- **MLX modeli:** Ollama'nın MLX çalıştırıcısında çalıştı; bu çalıştırıcı sunucunun ayrı bir alt süreci olarak görünmedi.
- **Ortam:** Ölçümler AC güçte yapıldı ve termal uyarı kaydedilmedi (`pmset -g therm`). Diğer uygulamalar açıktı: tarayıcı, Slack, Microsoft uygulamaları, VS Code, Cursor, Claude. Bu, BENCHMARK_PLAN'daki "tipik uygulamalar açık" senaryosudur.

## 5. İndirme boyutları

| Model | İndirilen | Sonuç |
|---|---|---|
| qwen3.5:9b-q4_K_M | 6,55 GB | duruyor |
| gemma4:12b-it-qat | 7,15 GB | duruyor |
| qwen3:8b-q4_K_M | 5,23 GB | silindi |
| qwen3:14b-q4_K_M | 9,28 GB | silindi |
| qwen3.5:9b-nvfp4 | 7,15 GB | silindi |
| **Toplam** | **35,36 GB** (onaylı bütçe 35,5 GB) | Diskte kalan: 13 GB |

## 6. Bellek tüketimi

Ollama'nın `/api/ps` değeri ağırlıkları, KV önbelleğini ve hesaplama tamponlarını içerir. Çalıştırıcının fiziksel ayak izi ise yalnızca CPU tarafını gösterir; GPU'ya bağlı (wired) bellek buna dahil değildir.

| Model | 4K | 8K | 16K | 32K | Çalıştırıcı boşta / 8K istem sırasında tepe |
|---|---|---|---|---|---|
| Gemma 4 12B | 7,13 | 7,42 | **7,43** | 7,48 GB | 1,57 / 3,43 GB |
| Qwen3.5-9B | 5,76 | 6,01 | **6,27** | 6,84 GB | 1,75 / 2,38 GB |
| Qwen3.5-9B MLX | — | 6,75 | 6,75 | 6,75 GB | ölçülemedi (ayrı süreç yok) |
| Qwen3-8B | — | 6,20 | 7,25 | 9,25 GB | 2,47 / 3,78 GB |
| Qwen3-14B | — | 9,62 | 10,88 | 13,45 GB | 2,75 / 4,14 GB |

**Sistem baskısı:** Tipik uygulamalar açıkken her modelin ölçümü sırasında takas büyüdü. Büyüme Gemma'da 2,4 GB, Qwen3.5'te 2,6 GB, Qwen3-14B'de 7,0 GB, Qwen3-8B'de 6,6 GB oldu. Bir ölçüm sırasında sistemin boş bellek oranı %15'e kadar düştü. Bu makinede 24 GB'ın tamamı modele ayrılamaz.

## 7. İlk token gecikmesi (TTFT)

Ortanca (p50) değerler, 16K bağlamda, her senaryoda 1 ısınma ve 10 ölçüm:

| Model | 512 token istem | 2K | 8K | Çok turlu, ağır turlar (B3) p50 / p95 | Gerçekçi kısa turlar p50 / p95 | Soğuk yükleme |
|---|---|---|---|---|---|---|
| Gemma 4 12B | 1,81 sn | 6,53 sn | 28,0 sn | 1,71 / 2,43 sn | **0,79 / 0,81 sn** | 1,46 sn |
| Qwen3.5-9B | 1,36 sn | 4,65 sn | 18,6 sn | 1,14 / 1,60 sn | **0,51 / 0,52 sn** | 1,14 sn |
| Qwen3.5-9B MLX | 1,21 sn | 4,36 sn | 17,4 sn | 1,18 / 1,88 sn | — | 1,26 sn |
| Qwen3-8B | 1,36 sn | 4,91 sn | 22,5 sn | 1,47 / 2,07 sn | — | 0,90 sn |
| Qwen3-14B | 2,51 sn | 9,13 sn | 40,1 sn | 2,22 / 3,30 sn | — | 2,98 sn |

**`num_ctx` ve yeniden yükleme:**

- llama.cpp çalıştırıcısında bağlam boyutunu değiştirmek modeli **yeniden yüklüyor**: 0,86 sn (Qwen3-8B) ile 2,83 sn (Qwen3-14B) arası.
- Aynı bağlam boyutuyla gelen bir istekte yükleme süresi 0,4 ms.
- MLX çalıştırıcısı bağlam değişikliğinde yeniden yüklemiyor (7,5 ms).
- **Sonuç:** Uygulama sabit bağlam profilleri kullanıyor (§17).

**Önbellek:**

- Ekleme yapılan (append-only) sohbetlerde ilk token yalnızca yeni token'larla orantılı; yani önbellek çalışıyor.
- Ollama 0.40, önbellekten gelen token'ları da `prompt_eval_count` alanında saydığı için yeniden kullanım oranı işleme süresinden tahmin edildi: ortanca 0,84–0,86.

### 7.1 G2 kapısı: ilk tanım, sonuç ve revizyon

**Bu revizyon, ölçüm sonuçları görüldükten sonra yapıldı.** İlk kriter de başarısız sonuç da burada korunuyor.

**İlk G2 (BENCHMARK_PLAN §5.1, Faz 0.1):**

- Senaryo: ekleme yapılan turlar, yaklaşık 8K geçmiş, tur başına 300–600 yeni token.
- Eşikler: p50 ≤ 1,2 sn, p95 ≤ 2,5 sn.
- Sonuç: **Gemma 4 12B bu kapıyı geçemedi** (p50 1,71 sn, p95 2,43 sn). Qwen3.5-9B geçti (1,14 / 1,60 sn). Bu sonuç geçerliliğini koruyor.

**Revizyon (G2-r1):** Sahip 2026-10-17'de koşullu olarak onayladı.

- Eşikler değişmedi.
- Kapsam: kullanıcı mesajı ≤ 100 token, önbellek sıcak, `think=false`, `num_ctx` 16384.
- Kısa etkileşim yalnızca mesaj uzunluğuyla tanımlanmıyor: modele gönderilen **toplam giriş bağlamı** da ölçülüp raporlanıyor. Kısa bir mesaj bile uzun bir sohbet geçmişinin ardından geliyorsa gecikme artabilir.
- Ağır tur senaryosu ve önbellek ıskası (cache miss) her zaman bilgi amaçlı raporlanıyor.
- Kayıt: ADR-0001 "G2 revision record" ve BENCHMARK_PLAN §5.1 Ek 1.

**G2-r1 ölçümü** (`evals/runners/g2_context.py`, AC güç):

- Rastgele içerikli, çok turlu sentetik geçmişler kullanıldı.
- Her boyut için 2 yeni geçmiş kuruldu. Her geçmişte ilk tur soğuk (önbellek ıskası), ardından 5 kısa tur sıcak; boyut başına toplam 10 sıcak tur.
- Sıcak turlarda yeni token sayısı 18–34 (kullanıcı mesajı ve sohbet şablonu birlikte; yani ≤ 100 koşulu sağlanıyor).
- Yanıtlar 64 token ile sınırlandı.

| Toplam giriş bağlamı (token) | Gemma sıcak p50 / p95 | Gemma soğuk | Qwen3.5 sıcak p50 / p95 | Qwen3.5 soğuk |
|---|---|---|---|---|
| 2.183–2.626 | 0,46 / 0,47 sn | 8,1 sn | 0,29 / 0,36 sn | 5,6 sn |
| 4.032–4.437 | 0,49 / 0,54 sn | 15,2 sn | 0,30 / 0,37 sn | 10,4 sn |
| 7.636–8.099 | 0,53 / 0,55 sn | 33,9 sn | 0,33 / 0,39 sn | 20,2 sn |
| 11.426–11.857 | 0,58 / 0,61 sn | 50,3 sn | 0,35 / 0,41 sn | 30,6 sn |

**Önceki yanıtın uzunluğu da gecikmeyi etkiliyor:**

- 256 token'lık yanıtlarla (`g2_context_out256`) Gemma yaklaşık 2K bağlamda 0,85 / 1,15 sn, yaklaşık 8K bağlamda 0,84 / 1,32 sn verdi.
- Qwen3.5 aynı koşullarda 0,40 / 0,51 ve 0,52 / 0,81 sn verdi.
- 150 token'lık yanıtlarla (§7 tablosundaki "gerçekçi kısa turlar", 1,9K–3,3K bağlam) Gemma 0,79 / 0,81 sn verdi.
- Olası neden: bir önceki yanıtın bir kısmı sonraki turda yeniden işleniyor (token'a çevirme sırasındaki sapma, SPK-03b). Bu **doğrulanmadı**; Faz 3'te gerçek istem birleştiriciyle ölçülmeli.

**Sonuç:**

- Gemma 4 12B, ölçülen bütün bağlam uzunluklarında (2,2K–11,9K) G2-r1'i **geçiyor**.
- İlk G2'yi **geçmiyor**.
- Önbellek ıskasında bütün geçmiş yeniden işleniyor. Bu Gemma'da 1K token başına yaklaşık 3,5–4,5 sn (12K'da 50 sn) demek ve Faz 3'ün en büyük gecikme riski (§17).

## 8. Üretim hızı (token/sn, ortanca)

| Model | 2K istemde üretim | 8K istemde üretim | İstem işleme (2K) |
|---|---|---|---|
| Qwen3.5-9B MLX | 42,8 | 41,2 | 459 |
| Qwen3-8B | 42,8 | 37,0 | 433 |
| Qwen3.5-9B | 39,0 | 37,5 | 430 |
| Gemma 4 12B | 29,2 | 28,2 | 286 |
| Qwen3-14B | 25,3 | 22,7 | 233 |

Karşılaştırma için: Türkçe konuşma sentezi yaklaşık 4–7 token/sn hızında tüketir. Bütün adaylar ses için yeterince hızlı üretiyor.

## 9. Türkçe dil değerlendirmesi

**Veri kümesi:** `evals/datasets/tr_quality_v1.json`, 60 özgün sentetik madde.

- 48 madde otomatik denetimli, 12 madde yalnızca öznel.
- Ayarlar: Faz 2 sistem istemi, `think=false`, `seed=42`, modelin kendi varsayılan örneklemesi, 8K bağlam.
- Denetleyici düzeltmeleri bütün modellere aynı uygulandı ve veri kümesinin `changes` alanına kaydedildi.

### 9.1 Otomatik sonuçlar

| Model | Uç durumlar /10 | Dil kayması | Emoji | "efendim" geçen yanıt | Bir yanıtta birden fazla "efendim" |
|---|---|---|---|---|---|
| Gemma 4 12B | **9** | 0/60 | 0 | %50 | **2** |
| Qwen3.5-9B | 7 | 0/60 | 0 | %40 | 7 |
| Qwen3.5-9B MLX | 7 | 0/60 | 0 | %35 | 2 |
| Qwen3-14B | 6 | 0/60 | 1 | %53 | 18 |
| Qwen3-8B | 5 | 0/60 | 1 | %83 | 15 |

Uç durumlar şunlardır: akrabalık, yazım hatası, ağız/yöre ifadesi, kod karıştırma, olumsuzluk, belirsiz iyelik.

Ortak zayıflık: Akrabalık soruları bütün modeller için zor. Örneğin "Babamın annesi benim neyim olur?" sorusuna doğru yanıtı ("babaanne") yalnızca bazı modeller verdi.

### 9.2 Öznel değerlendirme (yapay zekâ değerlendiricisi)

12 öznel maddenin çıktılarını yan yana okudum. Bunlar benim izlenimlerim, ölçüm değil:

- **Gemma 4 12B:**
  - En doğal, akıcı ve deyimsel Türkçe; yanıtlar iyi yapılandırılmış ve sıcak.
  - Kusurları: Bir yanıtta "sen" hitabıyla "efendim"i birlikte kullandı (üslup tutarsızlığı). Bir şiir değerlendirmesinde hafif övgüye kaydı.
- **Qwen3.5-9B:** Anlatım bozuklukları var: "toplantıların ardının arkasının bittiği", "kendinize şefkati ve nazlı bir şekilde", "mutlu ettirsin". "Sen" ile "siz"i karıştırıyor; bir yanıtta emoji kullandı.
- **Qwen3-8B ve Qwen3-14B:** "Efendim"i cümlelere mekanik olarak ekliyorlar ("TAMAM efendim.", "33% efendim."); bu, kesin çıktı isteyen görevleri bozuyor.

### 9.3 Kör değerlendirme (sahip için)

Türkçe doğallık, ağırlığı en yüksek ölçüt (BENCHMARK_PLAN §5.2'de 40 puan) ve bunu otomatik puanlama tam olarak doğrulayamaz. Önerilen yöntem:

1. `evals/reports/phase2/blind/rate.html` dosyasını tarayıcıda açın (internet gerekmez, hiçbir yere veri göndermez). Sayfada iki finalistin 14 öznel maddesi var: 10 doğallık ve 4 asistan davranışı maddesi, toplam 14 karşılaştırma. Yanıtlar rastgele sırayla gösteriliyor ve model adları gizli.
2. Her soruda A, B veya "Eşit" seçin. Ölçütler: doğallık, Türkçe kalitesi, sıcaklık, dürüstlük ve "efendim"in yerinde kullanımı.
3. "Sonuçları indir" düğmesine basın, sonra şu komutu çalıştırın: `uv run --project core python evals/runners/blind.py score ~/Downloads/lazis-blind-ratings.json`
4. Değerlendirmeyi bitirmeden `key.json` dosyasını açmayın.

Bütün modellerin karşılaştırılması isteniyorsa sayfa `make blind MODELS="…"` ile yeniden üretilebilir. Elenen modellerin çıktıları rapor dosyalarında saklı.

### 9.4 Kör değerlendirme sonucu (sahip, 2026-10-17)

Sahip 14 karşılaştırmanın hepsini puanladı; hiç "Eşit" seçilmedi. Puanlar `evals/reports/phase2/blind/ratings_owner.json`, skor `scores.json` dosyasında.

| Model | Kazanma oranı | Kazanılan karşılaştırma |
|---|---|---|
| **gemma4:12b-it-qat** | **0,929** | 13 / 14 |
| qwen3.5:9b-q4_K_M | 0,071 | 1 / 14 |

Eşleştirmeler (`key.json`; A/B sırası sayfada rastgeleydi, değerlendirme bitene kadar gizli tutuldu):

| Karşılaştırma | Madde | Yanıt A | Yanıt B | Sahibin seçimi | Kazanan | Sahibin notu |
|---|---|---|---|---|---|---|
| T001 | A01 | Gemma | Qwen3.5 | A | **Gemma** | A daha doğal ve uygulanabilir. |
| T002 | A02 | Gemma | Qwen3.5 | A | **Gemma** | A daha içten ve düzgün Türkçe. |
| T003 | A03 | Qwen3.5 | Gemma | B | **Gemma** | B daha empatik ve tutarlı. |
| T004 | A04 | Gemma | Qwen3.5 | B | **Qwen3.5** | B daha kısa ve gerçekçi. |
| T005 | A05 | Qwen3.5 | Gemma | B | **Gemma** | B deyimi doğru açıklıyor. |
| T006 | A06 | Qwen3.5 | Gemma | B | **Gemma** | B daha anlaşılır; coğrafi hatalar mevcut. |
| T007 | A07 | Qwen3.5 | Gemma | B | **Gemma** | B daha somut ve kullanışlı. |
| T008 | A08 | Qwen3.5 | Gemma | B | **Gemma** | B daha anlaşılır bir mizah sunuyor. |
| T009 | A09 | Qwen3.5 | Gemma | B | **Gemma** | B daha kullanılabilir; ancak dil hataları var. |
| T010 | A10 | Gemma | Qwen3.5 | A | **Gemma** | A daha doğal ve dengeli. |
| T011 | E02 | Gemma | Qwen3.5 | A | **Gemma** | A riskleri daha doğru değerlendiriyor. |
| T012 | E05 | Qwen3.5 | Gemma | B | **Gemma** | B daha akıcı ancak yeterince eleştirel değil. |
| T013 | E07 | Qwen3.5 | Gemma | B | **Gemma** | B daha doğal ve ölçülü. |
| T014 | E08 | Qwen3.5 | Gemma | B | **Gemma** | B daha sıcak ve kısa. |

- Qwen3.5'in tek kazandığı karşılaştırma A04 (kitap okuma alışkanlığı); sahibin notu: "daha kısa ve gerçekçi".
- Sahibin Gemma kazansa bile not ettiği zayıflıklar (Faz 3 / 5 için girdi):
  - **A06, yanlış yer bilgisi:** "coğrafi hatalar mevcut". Örneğin Kuzguncuk "Beşiktaş'ın hemen yanında" diye anlatılıyor; Kuzguncuk Üsküdar'dadır. Yer ve olgu iddiaları doğrulanmadan söylenmemeli.
  - **A09, dil hataları:** "ancak dil hataları var" ("Acil bir durum XM oluşması", "onaylanmasını hususunu").
  - **E05, dalkavukluk:** "yeterince eleştirel değil". Sıradan bir dize için itiraz etmek yerine övgüye kaçıyor.
- Sonuç, yapay zekâ değerlendiricisinin öznel izlenimiyle (§9.2) aynı yönde. Örneklem 14 karşılaştırma ve tek değerlendirici; güçlü bir eğilim olarak okunmalı, istatistiksel bir kesinlik olarak değil.

## 10. Talimat uyma

12 otomatik madde: tam çıktı, madde sayısı, JSON, kelime sınırı, düzeltmeye uyma, büyük harf, dil, birebir tekrar, "siz" hitabı, yasaklı kelime.

| Gemma 4 12B | Qwen3.5-9B | Qwen3.5 MLX | Qwen3-14B | Qwen3-8B |
|---|---|---|---|---|
| **12/12** | 11/12 | 10/12 | 11/12 | 8/12 |

## 11. Akıl yürütme

| Model | Düşünmeden (`think=false`), /10 | Düşünerek (`think=true`), /15 | Düşünerek ortanca süre |
|---|---|---|---|
| Gemma 4 12B | 7 | **15** | 10,7 sn |
| Qwen3-14B | **8** | 12 | 11,6 sn |
| Qwen3-8B | 5 | 12 | 6,5 sn |
| Qwen3.5-9B | 4 | 11 | 65,6 sn |
| Qwen3.5-9B MLX | 4 | 8 | 50,3 sn |

- Düşünme modundaki set, akıl yürütme maddelerine akrabalık ve hafıza maddeleri eklenerek oluşturuldu.
- Düşünmeden yapılan hataların çoğu aritmetik ve takvim sorularında.
- Qwen3.5 düşünme modunda çok uzun akıl yürütme izleri üretiyor; bu yüzden 50–65 sn sürüyor.

## 12. Yapılandırılmış bilgi çıkarımı (hafıza hazırlığı)

**Veri kümesi:** `tr_extraction_v1.json`, 8 sentetik diyalog. Kapsadığı durumlar:

- aynı adı taşıyan iki kişi;
- açık bir düzeltme;
- belirsiz tarih;
- akrabalık zinciri;
- hiç kişi geçmeyen bir metin.

**Hafıza senaryoları** (`memory` kategorisi, 10 soru): Gemma, Qwen3.5 ve Qwen3-14B 9/10, Qwen3-8B 9/10, MLX 9/10 doğru yaptı.

| Model | Geçerli JSON (yalnızca istem / şema kısıtlı) | Kişi + ilişki | Tarih | Tercih | Hedef/proje | Düzeltme | Uydurulan, yanlış atanan veya düzeltilmiş ad |
|---|---|---|---|---|---|---|---|
| Gemma 4 12B | 100% / 100% | **1,00** | 1,00 | **1,00** | 1,00 | **1,00** | **0** |
| Qwen3.5-9B | 100% / 100% | 1,00 | 1,00 | 0,67 | 1,00 | 1,00 | 0 |
| Qwen3.5-9B MLX | 100% / **kullanılamıyor** | 0,64 | 1,00 | 0,67 | 1,00 | 1,00 | 0 |
| Qwen3-14B | 100% / 100% | 0,86 | 1,00 | 0,67 | 1,00 | **0,00** | 3 |
| Qwen3-8B | 100% / 100% | 0,71 | 1,00 | 0,67 | 1,00 | 1,00 | 3 |

- Ollama 0.40.4'ün MLX çalıştırıcısı şema kısıtlı JSON isteğini "structured output is unavailable" hatasıyla reddediyor.
- Örneklem 8 diyalog; bu sonuçlar yön göstericidir, kesin değildir.

## 13. Uzun bağlam

**Bilgi bulma:** 16K bağlam, yaklaşık 11,4K token'lık metin, 3 bilgi metnin %10, %50 ve %90 konumlarında.

| Model | Doğru | Soğuk istemde ilk token |
|---|---|---|
| Gemma 4 12B | 3/3 | 41,1 sn |
| Qwen3.5-9B | 3/3 | 27,8 sn |
| Qwen3.5 MLX | 3/3 | 26,9 sn |
| Qwen3-8B | 3/3 | 35,6 sn |
| Qwen3-14B | 2/3 | 63,3 sn |

**12 turluk uzun sohbet:** Sohbette bir düzeltme ("Trabzon değil Rize") ve araya giren konular var. Bütün modeller sondaki 3 hatırlama sorusunun 3'ünü de doğru yanıtladı.

## 14. Kararlılık

- Beş modelde yaklaşık 850 üretim yapıldı; hiçbir çöküş, takılma veya geçersiz yanıt olmadı.
- Bir ölçüm aracı hatası ortaya çıktı (§ PHASE_2_REPORT M): Uzun istemlerde HTTP okuma zaman aşımı devreye giriyordu. Düzeltildi ve regresyon testi eklendi.
- 300 turluk dayanıklılık testi (B8) bu fazda çalıştırılmadı.

## 15. Gelecekteki ses kullanımına uygunluk

- **Üretim hızı:** Bütün adaylar konuşma sentezinin tüketim hızından hızlı üretiyor (Gemma 28 token/sn).
- **İlk token:** Gerçekçi kısa turlarda Gemma 0,79 sn, Qwen3.5 0,51 sn.
- **Bellek:** Asıl kısıt bu.
  - Gemma 16K bağlamda 7,4 GB tutuyor.
  - Bunun üstüne STT (Whisper turbo, tahmini 1,5–2 GB) ve TTS modeli (tahmini 2–4 GB) eklenecek.
  - Tipik uygulamalar açıkken ölçümlerde takas zaten büyüdü.
  - Ses ve LLM'in birlikte bellekte durması (B10) ölçülmedi, çünkü ses modelleri Faz 2 kapsamında değildi. Faz 13'te ölçülmeli.
  - Gerekirse ses oturumlarında Qwen3.5-9B'ye geçmek (yaklaşık 1,2 GB tasarruf) bir yedek yol.

## 16. Model sıralaması

Otomatik puanlara, performans ölçümlerine, benim öznel izlenimime ve **sahibin kör değerlendirmesine** (§9.4: Gemma 13/14) dayanıyor. Sıralama ADR-0001 ile kabul edildi.

1. **Gemma 4 12B:** En iyi Türkçe ve en iyi hafıza hazırlığı. Daha yavaş ama bütçe içinde.
2. **Qwen3.5-9B:** Hızlı ve küçük; akıl yürütmesi ve doğallığı daha zayıf.
3. **Qwen3-14B:** İyi akıl yürütme, ama bellek, hız ve çıkarım sorunlu.
4. **Qwen3-8B:** Hızlı, ama talimat uyma ve çıkarım zayıf.
5. **Qwen3.5 MLX:** Model sıralamasının değil, çalışma zamanı karşılaştırmasının parçası; §19'a bakın.

## 17. Önerilen birincil model (kabul edildi)

**`gemma4:12b-it-qat`** (ADR-0001, durumu **Kabul Edildi**, 2026-10-17).

**Ayarlar:**

- Kısa ve normal istekler için `num_ctx=16384`. İkisi aynı boyutta tutuluyor ki model yeniden yüklenmesin; bellek farkı ≤ 0,3 GB.
- Açık uzun görevler için 32768.
- Varsayılan olarak `think=false`; `think=true` yalnızca uzun akıl yürütme için.
- `keep_alive=10m`.

**Kabul koşulları (ikisi de karşılandı):**

1. Sahibin kör değerlendirmesi: Gemma 13/14 kazandı (§9.4).
2. G2 revizyonunun onayı: sahip 2026-10-17'de koşullu olarak onayladı. İlk G2'de Gemma başarısız oldu (1,71 sn); G2-r1'i bütün ölçülen bağlam uzunluklarında geçiyor (§7.1).

**Faz 3 için gecikme ve bağlam riskleri:**

- **Önbellek ıskası pahalı.** Iska olduğunda bütün sohbet geçmişi yeniden işleniyor; Gemma'da 2K bağlamda 8 sn, 8K'da 34 sn, 12K'da 50 sn. Iskaya yol açan durumlar:
  - 10 dakika boşta kalınca model bellekten boşaltılıyor (`keep_alive`);
  - bağlam profili değişince model yeniden yükleniyor;
  - geçmiş sıkıştırılınca ya da istem öneki değişince önek bozuluyor;
  - arka plan işleri tek çalışma yuvasını kullanıyor;
  - uygulama veya Ollama yeniden başlatılıyor.
- **Sıcak gecikme de büyüyor.** Geçmiş uzadıkça (2K'dan 12K'ya 0,46 sn'den 0,58 sn'ye) ve önceki yanıt uzadıkça (256 token'da yaklaşık 0,85 sn) artıyor.
- **Faz 3'te yapılması gerekenler:**
  - sıkıştırmayla geçmiş bütçesini küçük tutmak;
  - boşta kalma ve sıkıştırma sonrasında modeli önceden ısıtmak;
  - istem önekini sabit tutmak;
  - beklemeyi "hazırlanıyor" durumuyla göstermek;
  - G2-r1'i gerçek istem birleştiriciyle ve gerçek yanıt uzunluklarıyla yeniden ölçmek (CNV-01).

## 18. Önerilen yedek model (kabul edildi)

**`qwen3.5:9b-q4_K_M`:**

- Yaklaşık 1,2 GB daha az bellek, daha hızlı ilk token ve üretim.
- Çıkarımda kişi, tarih ve düzeltmeleri doğru yakalıyor.
- Ses modelleriyle bellek sıkıştığında ya da hız öncelikli olduğunda kullanılabilir.

Ayrıca bir "yüksek kalite" modeli **önerilmiyor**: 14B'nin üstünlüğü yalnızca düşünmeden akıl yürütmede ve bu, bellek ve hız maliyetini karşılamıyor.

## 19. Elenen adaylar ve gerekçeleri

- **Qwen3-14B (`qwen3:14b-q4_K_M`):**
  - 32K bağlamda 13,45 GB; ölçümde 7 GB takas büyümesine yol açtı.
  - En yavaş aday: 22,7–25,3 token/sn; 8K istemde ilk token 40 sn.
  - Hafıza hazırlığında en zayıfı: düzeltmeleri yakalayamadı, düzeltilmiş eski adı kişi olarak çıkardı.
  - "Efendim"i 18 yanıtta aşırı kullandı.
  - Uzun bağlamda 2/3.
- **Qwen3-8B (`qwen3:8b-q4_K_M`):**
  - Talimat uymada 8/12, uç durumlarda 5/10.
  - Yanıtların %83'ünde "efendim" var; kesin çıktıları bozuyor.
  - Çıkarımda kişi uydurdu ve ilişkileri yanlış atadı.
- **MLX çalışma zamanı (`qwen3.5:9b-nvfp4`):**
  - Aynı modelde llama.cpp'ye göre yalnızca %7–10 hız kazancı.
  - Ollama 0.40.4'ün MLX çalıştırıcısı yapılandırılmış çıktıyı desteklemiyor; hafıza çıkarımı için bu şart.
  - Bu nicemlemeyle akıl yürütme (8/15) ve kişi çıkarımı (0,64) daha düşük.
  - **Karar:** MLX "deneysel" kalıyor. Uygulamada ayrı bir MLX adaptörü yazılmadı; Ollama'nın MLX etiketleri aynı adaptörle zaten kullanılabiliyor.
  - Gemma için ayrı bir MLX ölçümü (`gemma4:12b-nvfp4`, 7,7 GB) yeni onay gerektirir. Ancak yapılandırılmış çıktı eksikliği sürdükçe karar değişmez.
