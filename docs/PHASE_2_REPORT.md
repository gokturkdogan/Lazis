# LAZIS — Faz 2 Raporu: Yerel Zekâ Entegrasyonu, Model Kıyaslama ve Seçim

> Tarih: 2026-10-17 · Durum: **Faz 2 tamamlandı. Model kararı (ADR-0001) Kabul Edildi; G2 kapısı sonuçlar görüldükten sonra sahibin koşullu onayıyla revize edildi (Bölüm O).** Faz 3'e başlanmadı; ayrı onay bekleniyor.
> Ayrıntılı ölçümler: [PHASE_2_MODEL_BENCHMARKS.md](PHASE_2_MODEL_BENCHMARKS.md) · Karar kaydı: [ADR-0001](adr/0001-primary-model.md) · Güvenlik: [SECURITY_MODEL.md §5.13](SECURITY_MODEL.md), [ADR-0009 Ek 1](adr/0009-backend-network-sandbox.md)

---

## A. Yönetici Özeti

LAZIS artık bu Mac'te çalışan gerçek bir yerel dil modeliyle Türkçe konuşabiliyor:

- Masaüstü uygulamasında model seçilip mesaj gönderilebiliyor.
- Yanıt akış halinde geliyor ve durdurulabiliyor.
- Hatalar Türkçe gösteriliyor.
- Sohbet bilinçli olarak **geçici**: hiçbir yere kaydedilmiyor ve günlüğe yazılmıyor.

**Neler yapıldı:**

1. **Çalışma zamanından bağımsız çıkarım katmanı** (`LLMProvider` portu) ve Ollama uygulaması. Uygulama şunları sağlıyor:
   - akış, iptal ve üç zaman aşımı (ilk token, boşta kalma, toplam);
   - kararlı Türkçe hata kodları;
   - yükleme/boşaltma ve ölçümler (metrikler).
2. **Güvenlik:**
   - Arka ucun sandbox'ı daraltıldı; artık yalnızca Ollama portuna (`127.0.0.1:11434`) çıkabiliyor.
   - Ollama bulut özellikleri kapalı başlatılıyor.
   - Adaptör yalnızca izin verilen beş uç noktayı çağırıyor ve yalnızca yerelde yüklü modelleri kullanıyor.
   - Model indirme yalnızca açık, onay listeli bir komutla yapılıyor.
3. **Ölçüm altyapısı ve sonuçları:**
   - Tekrarlanabilir performans ve Türkçe kalite ölçüm araçları, sentetik Türkçe veri kümeleri ve kör değerlendirme sayfası.
   - 4 aday model ve 1 MLX varyantı, toplam **35,36 GB** indirildi (onaylı bütçe 35,5 GB) ve gerçekten ölçüldü.
4. **Karar (ADR-0001, Kabul Edildi):**
   - Birincil model: **Gemma 4 12B** (`gemma4:12b-it-qat`). Türkçe kalitesi, talimat uyma, düşünme modunda akıl yürütme ve hafıza hazırlığında en iyisi.
   - Yedek model: **Qwen3.5-9B** (`qwen3.5:9b-q4_K_M`). Daha hızlı ve daha küçük.
   - Çalışma zamanı: **Ollama (llama.cpp)**. MLX ölçüldü ve benimsenmedi.
5. **Testler:** `make check` ile 282 test çalıştı ve geçti; isteğe bağlı gerçek model testleri ayrıca 9 test olarak çalıştı ve geçti. Mevcut bütün Faz 1 ve 1.1 testleri geçiyor.

**Sahibin kararları (2026-10-17):**

- **Kör değerlendirme:** Gemma 4 12B, 14 karşılaştırmanın 13'ünü kazandı (kazanma oranı 0,929).
- **G2 revizyonu koşullu olarak onaylandı. Kalite önceliklendirildi.**
  - Gemma ilk G2'yi (300–600 token'lık turlar) **geçemedi**: 1,71 sn. Bu sonuç raporlarda korunuyor.
  - Revize kapsamda (kullanıcı mesajı ≤ 100 token, toplam giriş bağlamı 2,2K–11,9K token arasında ölçülerek) **geçti**: 0,46–0,58 sn.
- **Faz 3'ün en büyük gecikme riski önbellek ıskası:** bütün geçmiş yeniden işleniyor, 8K bağlamda 34 sn sürüyor (Bölüm J, P).

---

## B. Ortam Doğrulaması

| Kontrol | Sonuç |
|---|---|
| Donanım | MacBook Pro, Apple M4 Pro, 24 GB, macOS 27.0.1 |
| Disk | Başlangıçta 121 GiB boş; şu an 106 GB boş |
| Güç / ısı | Bütün ölçümler AC güçte yapıldı; termal uyarı kaydedilmedi |
| Bellek | Diğer uygulamalar açıktı (tarayıcı, Slack, Microsoft, VS Code, Cursor, Claude). Başlangıçta 2,1 GB takas vardı; ölçümler sırasında takas büyüdü |
| Ollama | 0.40.4 (Homebrew). Başlangıçta `OLLAMA_NO_CLOUD` **tanımlı değildi** (sunucu ortamı çekirdekten okundu), yani bulut özellikleri açıktı. Onayınızla LaunchAgent olarak `OLLAMA_NO_CLOUD=1` ve `OLLAMA_HOST=127.0.0.1:11434` ayarlarıyla yeniden başlatıldı |
| Başlangıç model envanteri | Boş |

---

## C. Model Envanteri

| Model | Etiket | Kaynak | Lisans | Durum |
|---|---|---|---|---|
| Gemma 4 12B | `gemma4:12b-it-qat` | ollama.com kütüphanesi (Google) | Apache 2.0 (+ Gemma 4 lisans sayfası) | **Kurulu, birincil öneri** |
| Qwen3.5-9B | `qwen3.5:9b-q4_K_M` | ollama.com kütüphanesi (Qwen) | Apache 2.0 | **Kurulu, yedek öneri** |
| Qwen3-8B | `qwen3:8b-q4_K_M` | ollama.com kütüphanesi | Apache 2.0 | Ölçüldü, silindi |
| Qwen3-14B | `qwen3:14b-q4_K_M` | ollama.com kütüphanesi | Apache 2.0 | Ölçüldü, silindi |
| Qwen3.5-9B MLX | `qwen3.5:9b-nvfp4` | ollama.com kütüphanesi | Apache 2.0 | Ölçüldü, silindi |

Model adları, özetleri, nicemleme biçimleri ve lisanslar indirmeden önce ollama.com ve Hugging Face API'sinden doğrulandı. Hiçbir model adı uydurulmadı.

Bulut etiketleri (`gemma4:cloud`, `gemma4:31b-cloud`) da kütüphanede var; bunlar hiçbir zaman kullanılmıyor.

---

## D. İndirme ve Kurulum Kaydı

**Onay:** Ana 4 model ve koşullu MLX varyantı onaylandı. Bulut özelliklerinin kalıcı olarak kapatılması ve elenen modellerin silinmesi de onaylandı.

**Araçlar:**

- `scripts/ollama-agent.sh install|status|uninstall`: LaunchAgent `~/Library/LaunchAgents/com.lazis.ollama.plist` dosyasını oluşturur. Çalışan eski `ollama serve` süreci durduruldu. **Geri almak için:** `scripts/ollama-agent.sh uninstall`.
- `scripts/model-pull.sh` (`make model-pull`): yalnızca `scripts/approved-models.txt` listesindeki etiketleri indirir; bulut ve kayıt sunuculu adları reddeder; 20 GB boş alan payını denetler.

**İndirmeler:** Sırayla, her biri ölçüldükten sonra bir sonraki indirildi. Her indirmede Ollama SHA-256 özetini doğruladı.

| # | Etiket | Boyut | Özet |
|---|---|---|---|
| 1 | qwen3.5:9b-q4_K_M | 6,55 GB | 56671c2a… |
| 2 | gemma4:12b-it-qat | 7,15 GB | 38044be4… |
| 3 | qwen3:8b-q4_K_M | 5,23 GB | 500a1f06… |
| 4 | qwen3:14b-q4_K_M | 9,28 GB | bdbd181c… |
| 5 | qwen3.5:9b-nvfp4 | 7,15 GB | 8218177a… |

5 numaralı MLX varyantının gerekçesi: GGUF'ta istem işleme hızı düşük ölçüldü (yaklaşık 420 token/sn).

**Toplam ve silme:**

- İndirilen toplam 35,36 GB.
- Elenen üç model raporla birlikte silindi (`ollama rm`). Diskte kalan model toplamı 13 GB.
- Fazladan nicemleme indirilmedi.

---

## E. Çıkarım Mimarisi

- **`core/src/lazis/providers/llm/ports.py`:** Çalışma zamanından bağımsız tipler ve `LLMProvider` protokolü. Metotlar:
  - `health`, `list_models`, `loaded_models`;
  - `stream`: içerik veya düşünme parçaları ve sonunda ölçümler;
  - `generate`, `cancel(request_id)`, `load`, `unload`, `aclose`.

  Seçenekler: `num_ctx`, en fazla token sayısı, örnekleme, `seed`, `think`, `keep_alive`, `response_format` (JSON veya JSON Şeması). Sohbet katmanı (P3) bu tiplere bağlanacak; Ollama'nın veri biçimine bağlanmayacak.
- **`core/src/lazis/providers/llm/ollama.py`:** Ollama uygulaması (Bölüm F).
- **`core/src/lazis/api/chat.py`:** Model durumu ve geçici sohbet uç noktaları.
- **Katman kuralları:**
  - `lazis.providers` katmanı `storage` ile aynı seviyede.
  - Yeni bir import-linter kuralı var: HTTP istemcisini (`httpx`, `http`, `requests`, `aiohttp`) **yalnızca** `lazis.providers` içe aktarabilir. Üç sözleşmenin üçü de korunuyor.
- **Değerlendirme araçları:** `evals/` altında. Paketle birlikte dağıtılmıyor, ama üretimdeki adaptörü kullanıyor; böylece ölçümler gerçek kodu da sınıyor.
- **Bilinçli olarak eklenmeyenler:** Eklenti çatısı, ayrı bir MLX adaptörü ve ileride kullanılmayacak soyutlamalar eklenmedi.

---

## F. Ollama Entegrasyonu

| Konu | Uygulama ve ölçüm |
|---|---|
| Model keşfi | `/api/tags`. Bulut veya uzak kayıtlar, kayıt sunuculu adlar ve hatalı adlar filtrelenir |
| Seçim ve yükleme | Yalnızca yerelde yüklü modeller kullanılabilir. Eksik model indirilmez, `llm_model_not_found` döner |
| Akış | `/api/chat` NDJSON akışı; içerik ve düşünme parçaları ayrı tutulur |
| İptal | Bağlantıyı kapatarak yapılır; Ollama üretimi hemen durdurur. Ölçülen durma süresi 1 ms. Sahte sunucu testi, iptalden sonra sunucunun üretimi bıraktığını kanıtladı |
| Zaman aşımları | İlk token 180 sn (soğuk yükleme dahil), boşta kalma 60 sn, toplam 600 sn, durum çağrıları 60 sn. Düzeltilen hata: Akışta da 60 sn'lik HTTP okuma zaman aşımı devredeydi ve uzun istemleri kesiyordu |
| Bağlam | `num_ctx` değişince llama.cpp çalıştırıcısı modeli **yeniden yüklüyor**: 0,9–2,8 sn. Bu yüzden adlandırılmış sabit profiller kullanılıyor |
| Yükleme ve boşaltma | `keep_alive` ile; soğuk yükleme 0,9–3,0 sn |
| Eşzamanlılık | Tek kullanıcı, tek model; aynı anda tek üretim. İkinci istek `llm_busy` hatası alır |
| Hata eşlemesi | `llm_unavailable`, `llm_model_not_found`, `llm_model_not_allowed`, `llm_out_of_memory`, `llm_load_failed`, `llm_timeout`, `llm_invalid_response`, `llm_cancelled`, `llm_busy`. Hepsinin Türkçe iletisi var |

**Önbellek:** Ollama 0.40, önbellekten gelen token'ları da `prompt_eval_count` alanında sayıyor. Ekleme yapılan sohbetlerde ilk token yalnızca yeni token'lara göre büyüyor; yani önek önbelleği çalışıyor.

---

## G. MLX Değerlendirmesi

**Yöntem:** Aynı model (Qwen3.5-9B), Ollama'nın MLX çalıştırıcısında (NVFP4) ve llama.cpp'de (Q4_K_M) ölçüldü. Ayrı bir `mlx_lm` kurulumu gerekmedi; Ollama 0.40 MLX etiketlerini kendisi çalıştırıyor.

| Ölçüt | MLX | llama.cpp |
|---|---|---|
| İstem işleme (token/sn) | 459 | 430 |
| Üretim (token/sn) | 42,8 | 39,0 |
| Bellek (16K bağlam) | 6,75 GB | 6,27 GB |
| `num_ctx` değişikliğinde yeniden yükleme | yok | var |
| Yapılandırılmış çıktı | **kullanılamıyor** ("structured output is unavailable") | var |
| Düşünme modunda akıl yürütme | 8/15 | 11/15 |
| Kişi çıkarımı | 0,64 | 1,0 |

**Karar:** MLX hızda yaklaşık %7–10 kazandırıyor, ama hafıza hattı için gerekli olan yapılandırılmış çıktıyı sağlamıyor. Kalite farkının bir kısmı nicemlemeden kaynaklanıyor olabilir. Bu yüzden MLX **benimsenmedi**. Ollama'nın MLX etiketleri aynı adaptörle kullanılabildiği için MLX deneysel olarak erişilebilir kalıyor.

**Kurulum karmaşıklığı:** Ollama üzerinden sıfır. Ayrı bir `mlx_lm` kurulumu yeni bir Python ortamı ve sunucu gerektirirdi; ölçümler bunu haklı çıkarmadı.

**Ses uyumu:** Ölçülmedi (ses Faz 13'te).

---

## H. Güvenlik ve Sandbox Uyumu

**Sorun:** Faz 1.1 profili, arka ucun `localhost` üzerindeki her porta çıkmasına izin veriyordu. Yerel bir proxy varsa bu, internete çıkış yolu demekti. Ayrıca Ollama'nın kendisi bir vekil (proxy) gibi kötüye kullanılabilir: `/api/pull` herhangi bir kayıt sunucusundan model indirebilir. Bulut özellikleri de açıktı.

**En küçük gerekli düzeltme:**

1. **Sandbox profili:** Çıkış yalnızca `(remote ip "localhost:11434")` adresine açık. macOS 27'de doğrulandı: Ollama'ya erişiliyor, başka bir yerel port EPERM alıyor, arka ucun kendi dinleyicisi etkilenmiyor. Yapılandırma da `models.endpoint` adresinin 11434 portunu kullanmasını zorunlu kılıyor.
2. **Adaptör izin listesi:** Yalnızca `version`, `tags`, `ps`, `show` ve `chat` uç noktaları çağrılabiliyor. `pull`, `push`, `create`, `copy`, `delete` ve `blobs` kod yolunda yok. HTTP istemcisi ortamdaki proxy ayarlarını kullanmıyor (`trust_env=False`) ve yönlendirme izlemiyor.
3. **Bulut:** Sunucu düzeyinde `OLLAMA_NO_CLOUD=1`; adaptör düzeyinde de bulut adları ve uzak kayıtlar reddediliyor.
4. **İndirme:** Yalnızca onay listeli, açık bir komutla. Uygulama hiçbir zaman model indirmiyor.
5. **Gizlilik:**
   - İstemler ve yanıtlar günlüğe yazılmıyor; günlüklerde yalnızca model adı, sayılar ve süreler var. Bir test, günlüklerde bilerek yerleştirilmiş gizli bir istemi arıyor.
   - İstemci sistem istemi gönderemiyor.
   - Sohbet SQLCipher'a da tarayıcı depolamasına da yazılmıyor.

**Kanıt:**

- Gerçek uygulamanın günlüğünde `os_network_sandbox: enforced` kaydı var.
- Rust yaşam döngüsü testinde sandbox altındaki arka uç Ollama'ya ulaşabiliyor.
- `test_os_sandbox.py`: başka bir yerel port EPERM alıyor.
- `test_ollama_provider.py`: bulut ve kayıt sunuculu adlar ağ isteği yapılmadan reddediliyor.

**Kalan riskler:**

1. Ollama'nın API'sinde kimlik doğrulama yok; aynı kullanıcının başka bir süreci de onu kullanabilir. Bu, Ollama'nın kendi tasarımı.
2. Arka uca sızmış kötü niyetli bir kod, adaptörü atlayıp `/api/pull` çağırabilir. Sandbox HTTP yollarını süzemiyor.
3. Ollama'nın kendi günlüğünde (`~/.ollama/logs/server.log`) istek yolları ve süreler var, istemler yok. `OLLAMA_DEBUG=1` gerçek sohbetlerde kullanılmamalı.
4. Ollama'nın güncelleme ve indirme trafiği, LAZIS'in değil Ollama'nın kendi trafiğidir.

**Değişmeyenler:** SQLCipher, Anahtar Zinciri, kurtarma kodu, API kimlik doğrulaması, WebSocket reddi ve FileVault göstergesi aynen çalışıyor; bütün Faz 1/1.1 testleri geçiyor.

---

## I. Türkçe Kıyaslama Sonuçları

Ayrıntılar PHASE_2_MODEL_BENCHMARKS.md §9–§13'te. Özet:

| | Gemma 4 12B | Qwen3.5-9B | Qwen3-14B | Qwen3-8B |
|---|---|---|---|---|
| Otomatik denetimler /48 | **43** | 37 | 40 | 32 |
| Talimat uyma /12 | **12** | 11 | 11 | 8 |
| Akıl yürütme, düşünmeden /10 | 7 | 4 | **8** | 5 |
| Akıl yürütme, düşünerek /15 | **15** | 11 | 12 | 12 |
| Türkçe uç durumlar /10 | **9** | 7 | 6 | 5 |
| Hafıza senaryoları /10 | 9 | 9 | 9 | 9 |
| Çıkarım (kişi / düzeltme / uydurma) | **1,0 / 1,0 / 0** | 1,0 / 1,0 / 0 | 0,86 / 0,0 / 3 | 0,71 / 1,0 / 3 |
| Bir yanıtta birden fazla "efendim" (/60) | **2** | 7 | 18 | 15 |
| Dil kayması | 0 | 0 | 0 | 0 |

**Öznel değerlendirme (yapay zekâ değerlendiricisi):** Gemma en doğal Türkçeyi üretiyor; Qwen3.5'te anlatım bozuklukları var. Qwen3 modelleri "efendim"i mekanik olarak ekliyor.

**Sahibin kör değerlendirmesi (tamamlandı):** 14 karşılaştırmada Gemma 4 12B 13 kez, Qwen3.5-9B 1 kez kazandı (kazanma oranı 0,929 / 0,071; kıyaslama raporu §9.4).

Gemma kazandığı yanıtlarda bile şu zayıflıklar not edildi:

- yanlış yer bilgisi (İstanbul planında);
- e-posta taslağında dil hataları;
- sıradan bir şiire yeterince eleştirel olmama.

Bunlar Faz 3'te olgu doğrulama ve Faz 5'te kişilik (itiraz, kısalık) için girdi. Bilinen sınırlamalar listesinde de yer alıyorlar (Bölüm N, madde 2).

**Kör değerlendirme eşleştirmeleri** (`evals/reports/phase2/blind/key.json` ve `ratings_owner.json`):

- A/B sırası rastgeleydi; değerlendirme bitene kadar gizli tutuldu.
- Hiç "Eşit" seçilmedi.
- A01–A10 doğallık, E02–E08 asistan davranışı maddeleri.

| Karşılaştırma | Madde | Yanıt A | Yanıt B | Seçim | Kazanan | Sahibin notu |
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

---

## J. Performans Sonuçları

| | Gemma 4 12B | Qwen3.5-9B | Qwen3-14B | Qwen3-8B | Qwen3.5 MLX |
|---|---|---|---|---|---|
| Üretim (token/sn, 2K istem) | 29,2 | 39,0 | 25,3 | 42,8 | 42,8 |
| İstem işleme (token/sn) | 286 | 430 | 233 | 433 | 459 |
| İlk token, 512 / 2K / 8K istem | 1,8 / 6,5 / 28,0 sn | 1,4 / 4,7 / 18,6 sn | 2,5 / 9,1 / 40,1 sn | 1,4 / 4,9 / 22,5 sn | 1,2 / 4,4 / 17,4 sn |
| Çok turlu, ağır turlar (ilk G2 senaryosu), p50 | 1,71 sn (**ilk G2'yi karşılamıyor**) | 1,14 sn | 2,22 sn | 1,47 sn | 1,18 sn |
| Çok turlu, gerçekçi kısa turlar, p50 | **0,79 sn** | **0,51 sn** | — | — | — |
| Soğuk yükleme | 1,46 sn | 1,14 sn | 2,98 sn | 0,90 sn | 1,26 sn |
| `num_ctx` değişikliği | 1,36 sn yeniden yükleme | 1,06 sn | 2,83 sn | 0,86 sn | yok |

**Ölçüm yöntemi:** Her senaryoda 1 ısınma ve 10 ölçüm yapıldı; ortanca ve p95 raporlandı. Önek önbelleğini atlatmak için her isteme rastgele bir başlangıç eklendi.

**G2-r1: kısa mesaj ve toplam giriş bağlamı** (`evals/runners/g2_context.py`; kıyaslama raporu §7.1):

- Kullanıcı mesajları kısa: turda 18–34 yeni token.
- Modele giden toplam bağlam 2K'dan 12K'ya büyütüldü.
- Her boyutta 10 sıcak tur ölçüldü. Soğuk değerler 2 ölçümün ortancası; yeni bir geçmişin ilk turu, yani önbellek ıskası.
- Yanıtlar 64 token ile sınırlandı.

| Toplam giriş bağlamı (token) | Gemma sıcak p50 / p95 | Gemma soğuk | Qwen3.5 sıcak p50 / p95 | Qwen3.5 soğuk |
|---|---|---|---|---|
| 2.183–2.626 | 0,46 / 0,47 sn | 8,1 sn | 0,29 / 0,36 sn | 5,6 sn |
| 4.032–4.437 | 0,49 / 0,54 sn | 15,2 sn | 0,30 / 0,37 sn | 10,4 sn |
| 7.636–8.099 | 0,53 / 0,55 sn | 33,9 sn | 0,33 / 0,39 sn | 20,2 sn |
| 11.426–11.857 | 0,58 / 0,61 sn | 50,3 sn | 0,35 / 0,41 sn | 30,6 sn |

**Bulgular:**

- Önbellek sıcakken gecikme geçmiş uzadıkça yavaşça artıyor. **Önbellek ıskasında ise bütün geçmiş yeniden işleniyor;** Gemma'da 1K token başına yaklaşık 3,5–4,5 sn.
- Önceki yanıtın uzunluğu da etkili:
  - 256 token'lık yanıtlarla Gemma 0,85 / 1,15 sn (yaklaşık 2K) ve 0,84 / 1,32 sn (yaklaşık 8K) verdi.
  - 150 token'lık yanıtlarla 0,79 / 0,81 sn verdi.
  - Olası neden, önceki yanıtın sonraki turda kısmen yeniden işlenmesi. Bu doğrulanmadı; Faz 3'te ölçülecek.
- Bütün bu değerler G2-r1 eşiklerinin içinde: p50 ≤ 1,2 sn, p95 ≤ 2,5 sn.

**Kapsam dışı kalanlar:** 300 turluk dayanıklılık testi ve araç çağırma ölçülmedi (P3).

---

## K. Bellek ve Kaynak Analizi

**Ollama'nın raporladığı toplam bellek** (`/api/ps`; ağırlıklar, KV önbelleği ve hesaplama):

| Bağlam | Gemma 4 12B | Qwen3.5-9B | Qwen3-8B | Qwen3-14B |
|---|---|---|---|---|
| 16K | 7,43 GB | 6,27 GB | 7,25 GB | 10,88 GB |
| 32K | 7,48 GB | 6,84 GB | 9,25 GB | 13,45 GB |

- Gemma'nın kayan pencereli dikkat (sliding-window attention) yapısı ve Qwen3.5'in hibrit yapısı nedeniyle bu iki modelin bağlam maliyeti çok düşük.
- Çalıştırıcı sürecin CPU tarafı ayrıca ölçüldü: boştayken 1,6–2,8 GB, 8K istem sırasında tepe 2,4–4,1 GB.

**Sistem baskısı:**

- Tipik uygulamalar açıkken her ölçüm sırasında takas büyüdü: Gemma 2,4 GB, Qwen3.5 2,6 GB, Qwen3-14B 7,0 GB.
- Bir ölçüm sırasında sistemin boş bellek oranı %15'e kadar düştü.
- **Sonuç:** 24 GB'ın tamamı modele ayrılamaz. 14B modeli ses modelleriyle birlikte barındırmak gerçekçi değil.

**Ses için bellek payı:**

- Gemma (7,4 GB), STT (tahmini 1,5–2 GB) ve TTS (tahmini 2–4 GB) birlikte yaklaşık 11–13,5 GB eder.
- Kapı G1, LAZIS'in toplamı için 14 GB sınırı koyuyor; bu sınır sağlanabilir, ama tipik uygulamalarla takas riski var.
- Gerekirse ses oturumlarında Qwen3.5'e geçilebilir (yaklaşık 1,2 GB tasarruf).
- Bu birlikte barındırma senaryosu (B10) Faz 13'te ölçülmeli.

**Bağlam varsayılanları** (ölçüme dayalı):

- Kısa ve normal profiller aynı **16K** bağlamı kullanıyor. Böylece model yeniden yüklenmiyor; 4K'ya göre bellek farkı Gemma'da yalnızca 0,3 GB.
- Uzun profil **32K**, açık uzun görevler için.
- Düşünme modu yalnızca uzun akıl yürütmede açılıyor.

---

## L. Masaüstü Sohbet Entegrasyonu

**Arayüz:**

- Genel bakış ekranında artık "Sohbet (Geçici)" paneli var.
- Panelde:
  - yüklü yerel modellerin listesi; yapılandırılmış birincil model kuruluysa önceden seçili geliyor;
  - mesaj kutusu (`⌘↵` ile gönderme);
  - akışla gelen yanıt;
  - "Durdur" düğmesi;
  - "Model hazırlanıyor…" yükleniyor durumu;
  - ilk token süresi, token/sn ve token sayısı ölçümleri;
  - "Temizle" düğmesi;
  - Türkçe hata iletileri;
  - Ollama kapalıyken ve hiç model yokken açıklayıcı ekranlar.
- "Yapay Zekâ" kartında çalışma ortamı, yüklü model sayısı, bellekteki model ve "Bulut çıkarımı: Kapalı" bilgisi gösteriliyor.
- Panelde açık bir geçicilik uyarısı var: "mesajlar yalnızca bu pencerenin belleğinde tutulur; diske, veritabanına veya günlüklere yazılmaz…"

**Teknik ayrıntılar:**

- İstemci NDJSON akışını `fetch` ve `ReadableStream` ile okuyor.
- İptal iki aşamalı: önce sunucudaki iptal uç noktası çağrılıyor; sunucu 2 sn içinde durmazsa `AbortController` bağlantıyı kesiyor.
- Belirteç önceki gibi reaktif durumda tutulmuyor.

**Doğrulama:**

- Sürüm derlemesi `LAZIS.app` tek kullanımlık bir profille açıldı ve ekran görüntüsünde panel, model listesi, durum kartları doğru görüldü.
- Ben arayüzde tıklayamadığım için sohbetin kendisi, masaüstü API istemcisi üzerinden gerçek arka uç ve gerçek modelle sınandı (bütünleşik test): Türkçe yanıt, akış ve iptal çalıştı.
- Tek kullanımlık profil ve Anahtar Zinciri kaydı silindi. Gerçek `default` profilinize dokunulmadı.

**Kapsam dışı (Faz 3+):** Kalıcı geçmiş, çoklu sohbet, sohbet motoru ve sistem isteminin kişilikle yönetilmesi.

---

## M. Otomatik Testler

**Çalıştırılan komut:** `make check` (çıkış kodu 0).

| Takım | Sayı | Not |
|---|---|---|
| Python (birim, bütünleşik, güvenlik) | **219 geçti** | 3 canlı test bu komutta seçilmiyor |
| Arayüz birim | **33 geçti** | |
| Arayüz bütünleşik (gerçek arka uç) | **4 geçti**, 1 atlandı | Atlanan, model gerektiren canlı test |
| Rust birim | **19 geçti** | Anahtar Zinciri testi ayrıca çalıştırıldı |
| Rust yaşam döngüsü | **7 geçti** | |

Statik denetimler de temiz: ruff, ruff format, pyright strict (0 hata), import-linter (3/3), vue-tsc, rustfmt, clippy `-D warnings`.

**İsteğe bağlı testler** (ayrıca çalıştırıldı, hepsi geçti):

| Komut | Sonuç |
|---|---|
| `make test-ollama` (gemma4 ve qwen3.5 ile) | 3/3: sandbox altındaki gerçek arka uç Türkçe akış üretiyor ve günlükte sohbetten iz yok; istemci bağlantıyı kesince üretim duruyor; üretim sürerken temiz kapanış |
| Arayüz canlı testi (gemma4 ve qwen3.5 ile) | 5/5: TS istemcisi, gerçek arka uç ve gerçek modelle akış ve iptal |
| `make test-keychain` | 1/1 |

**Yeni testlerin kapsamı:**

- **Adaptör** (26 test):
  - başlatma, keşif ve bulut/uzak filtreleme;
  - akış ve ölçümler;
  - hata eşleme: 404, bellek yetersizliği, yükleme hatası, akış içi hata;
  - geçersiz akış;
  - iptal: akış sırasında ve model yüklenirken;
  - ilk token ve boşta kalma zaman aşımları;
  - model adı reddi ve uç nokta izin listesi.
- **Gerçek HTTP** (5 test): iptal edilince sunucu üretimi durduruyor; çalışma ortamı yanıtın ortasında çöküyor; kapalı port hızlı hata veriyor; API'den akış; yavaş ilk token regresyonu.
- **API güvenliği** (26 test):
  - kimlik doğrulama, yabancı kaynak (Origin) ve doğrulama hataları;
  - boyut sınırı;
  - bulut veya yüklü olmayan model;
  - çalışma ortamı kapalı;
  - akış içi hata;
  - günlükte istem olmaması.
- **Sandbox:** Yalnızca Ollama portuna izin verildiği test ediliyor.
- **Arayüz** (12 yeni test): model seçimi, akış, geçmiş, yükleniyor/durdurma, zorla kesme, Türkçe hatalar, boş envanter, çalışma ortamı kapalı, `localStorage`'a yazılmaması.

**Dahil edilmeyen:** Gerçek bir modelin performansına veya içeriğine bağlı testler `make check`'e dahil değil. Varsayılan test takımı deterministik ve çevrimdışı kalıyor.

---

## N. Bilinen Sınırlamalar

1. **G2 sonuçlar görüldükten sonra revize edildi.** Gemma ilk G2'yi (300–600 yeni token'lık turlar, p50 ≤ 1,2 sn) 1,71 sn ile **geçemedi**. Sahip, kaliteyi önceliklendirerek revizyonu koşullu olarak onayladı: kullanıcı mesajı ≤ 100 token, toplam bağlam ölçülerek ve raporlanarak. Gemma bu revize kapsamı (G2-r1) geçiyor. Kayıt: ADR-0001 "G2 revision record" ve BENCHMARK_PLAN §5.1 Ek 1. Uzun kullanıcı mesajlarında (300–600 token) Gemma'nın ilk token süresi 1,2 sn'yi aşıyor.
2. **Gemma'nın kör değerlendirmede görülen zayıflıkları:**
   - **Coğrafi ve olgusal doğruluk:** Örneğin Kuzguncuk'u "Beşiktaş'ın hemen yanında" diye anlatıyor; Kuzguncuk Üsküdar'dadır. Yer ve olgu iddiaları doğrulanmamış kabul edilmeli; internet araştırması Faz 12'ye kadar yok.
   - **Dil hataları:** e-posta taslağında "XM oluşması", "onaylanmasını hususunu".
   - **Gereksiz övgü (dalkavukluk):** sıradan bir dizeye eleştirmeden övgü.

   Faz 3'te bu zayıflıklara karşı sistem istemi kuralları ve değerlendirme maddeleri eklenmeli. Kişilik ve itiraz davranışı Faz 5'te.
3. **Uzun sohbet geçmişinde gecikme ve bağlam yönetimi riski:**
   - Önbellek ıskasında bütün geçmiş yeniden işleniyor: Gemma'da 2K bağlamda 8 sn, 8K'da 34 sn, 12K'da 50 sn. Iskaya yol açan durumlar:
     - 10 dakika boşta kalınca model boşaltılıyor;
     - bağlam profili değişiyor;
     - geçmiş sıkıştırılıyor ya da önek değişiyor;
     - arka plan işi çalışıyor;
     - uygulama veya Ollama yeniden başlatılıyor.
   - Sıcak gecikme de geçmiş ve önceki yanıt uzadıkça artıyor.
   - Faz 3 bunun için şunları yapmalı:
     - geçmiş bütçesini sıkıştırmayla küçük tutmak;
     - modeli önceden ısıtmak;
     - istem önekini sabit tutmak;
     - beklemeyi "hazırlanıyor" durumuyla göstermek;
     - G2-r1'i gerçek istem birleştiriciyle yeniden ölçmek.
4. **Ölçülmeyen kapılar ve kriterler:**
   - G6 (araç çağırma) ve B7 → Faz 3.
   - B8 (300 turluk dayanıklılık) → Faz 3.
   - B10 (ses modelleriyle birlikte bellek) → Faz 13.
   - B9 (embedding) → Faz 6.
5. **G4 (önbellek yeniden kullanımı) kesin ölçülemedi.** Ollama 0.40, önbellekten gelen token'ları ayırmıyor; oran süreden tahmin edildi (0,85).
6. **Örneklem küçük.** Veri kümeleri (60 kalite maddesi, 8 çıkarım diyaloğu, 12 turluk sohbet) yön gösterici; BENCHMARK_PLAN'ın hedeflediği büyüklükte değil. Örneğin çıkarım için plan 100 diyalog öngörüyor.
7. **Ölçüm ortamı:** Ölçümler tipik uygulamalar açıkken yapıldı; bellek baskısı sonuçları etkilemiş olabilir. Ağır uygulamalar kapatılmadı.
8. **"Efendim" ve "sen/siz" tutarlılığı:** Bütün modellerde sorunlu. Ele alınacağı yer Faz 5 kişilik motoru.
9. **Akrabalık soruları** bütün modeller için zor; Faz 7'deki bilgi grafiği kuralları gerekli.
10. **MLX yapılandırılmış çıktısı:** Ollama 0.40.4'ün MLX çalıştırıcısı desteklemiyor.
11. **Ollama'nın API'sinde kimlik doğrulama yok** ve `/api/pull` ile vekil olarak kötüye kullanma riski sürüyor; yalnızca LAZIS'in kodunda engelleniyor.
12. **Sohbet sınırları:**
    - Geçici sohbetin geçmişi istek başına en fazla 40 tur ve 48.000 karakter.
    - Gövde sınırı 64 KB.
    - Daha uzun sohbetler `validation_error` veya `request_too_large` hatası alır. Gerçek sohbet motoru (P3) bağlamı sıkıştırarak yönetecek.
13. **Uzun soğuk istemler yavaş:** Gemma'da 8K token'lık soğuk bir istem ilk token için 28 sn bekliyor. Uzun belge özetleme gibi görevler arka planda ve düşük öncelikle yapılmalı.
14. **FileVault hâlâ kapalı.** Faz 3'te konuşmalar kaydedilmeye başlamadan önce açılması öneriliyor.
15. **Yol haritasındaki P2 kapsamından farklar.** Faz 2 talimatı, DEVELOPMENT_ROADMAP'teki P2 kapsamından farklıydı. Talimatta masaüstü sohbet vardı, yol haritasında yoktu. Yol haritasındaki şu maddeler bu fazda **yapılmadı**:
    - `OpenAICompatLLMProvider`. Tek çalışma zamanı Ollama; port, ikinci bir adaptöre hazır.
    - `EmbeddingProvider` ve embedding karşılaştırması (SPK-06, ADR-0002) → Faz 6'dan önce.
    - Modelleri özetle sabitleme ve açılışta özet doğrulaması. Şu an özetler yalnızca raporlarda ve ADR-0001'de kayıtlı → Faz 3.
    - Token sayma servisi → Faz 3 (istem birleştirici).
    - Ses fizibilite ölçümü (SPK-07, B10) → Faz 13'ten önce.
    - Ayrı bir ADR-0004 yazılmadı; Ollama çalışma parametreleri ADR-0001'de.
    - Komut satırından `lazis bench` / `lazis eval` komutları yok. Aynı işi `make bench` ve `make eval` (`evals/runners/`) yapıyor.
    - SPK-02 kısmen yapıldı: şemayla kısıtlanmış çıktı llama.cpp'de 8/8 geçerli; MLX'te kullanılamıyor. Şemayı ihlale zorlayan bir stres testi yapılmadı.

---

## O. Model Seçim Kararı

Karar kaydı **ADR-0001**, durumu **Kabul Edildi** (2026-10-17):

| Rol | Model | Çalışma zamanı | Gerekçe |
|---|---|---|---|
| Birincil | `gemma4:12b-it-qat` | Ollama / llama.cpp, Q4_0 QAT | En yüksek otomatik puan (43/48). Talimat uymada 12/12, düşünme modunda 15/15 (10,7 sn). Hatasız çıkarım. En az "efendim" taşkınlığı. En doğal Türkçe (öznel). 7,4 GB bellek |
| Yedek | `qwen3.5:9b-q4_K_M` | Ollama / llama.cpp, Q4_K_M | 1,2 GB daha az bellek, daha hızlı. Çıkarımı iyi, ama akıl yürütmesi ve doğallığı zayıf |
| Yüksek kalite | — | — | 14B'nin bellek, hız ve çıkarım maliyeti tek üstünlüğünü (düşünmeden akıl yürütme) karşılamıyor |
| Çalışma zamanı | Ollama (llama.cpp) | — | MLX daha hızlı ama yapılandırılmış çıktı yok |

**Kapıların durumu (birincil model):**

| Kapı | Sonuç |
|---|---|
| G1 bellek | Geçti (yalnızca LLM) |
| G2 ilk token, ilk tanım (300–600 token'lık turlar) | **Geçemedi:** p50 1,71 sn, p95 2,43 sn (kapı 1,2 / 2,5 sn). Sonuç korunuyor |
| G2-r1 (revize: mesaj ≤ 100 token, sıcak önbellek, toplam bağlam raporlanarak) | **Geçti:** 2,2K–11,9K bağlamda p50 0,46–0,58 sn; 256 token'lık yanıtlarla en kötü p95 1,32 sn |
| G3 üretim hızı | Geçti |
| G4 önbellek | Kesin ölçülemedi |
| G5 JSON | Geçti |
| G6 araç çağırma | Ölçülmedi |
| G7 dil kayması | Geçti |
| G8 kararlılık | Kısmen (çöküş yok, dayanıklılık testi yapılmadı) |

BENCHMARK_PLAN'a göre bir kapıyı değiştirmek sahibin onayladığı bir ADR'yi gerektirir. İki kabul koşulu da karşılandı:

1. **Kör değerlendirme:** Gemma 13/14 kazandı.
2. **G2 revizyonu:** Sahip 2026-10-17'de koşullu olarak onayladı.
   - Eşikler değişmedi (p50 ≤ 1,2 sn, p95 ≤ 2,5 sn).
   - Kısa etkileşim yalnızca mesaj uzunluğuyla tanımlanmıyor; toplam giriş bağlamı da ölçülüp raporlanıyor.
   - Ağır tur sonucu (1,71 sn) ilk G2'yi karşılamadığı açıkça belirtilerek korunuyor.
   - Revizyonun sonuçlar görüldükten sonra yapıldığı ADR-0001 ve BENCHMARK_PLAN §5.1 Ek 1'de yazılı. İlk kriter silinmedi.

**Gerekçe (sahibin kararı):** Kalite önceliklendirildi. Gemma kör değerlendirmede 13/14 kazandı ve teknik değerlendirmelerin çoğunda önde: talimat uyma, akıl yürütme (düşünme modunda), çıkarım, Türkçe uç durumlar.

**Yapılandırma:** Varsayılanlar karara göre (`models.primary_model = gemma4:12b-it-qat`, bağlam 16K / 16K / 32K).

---

## P. Faz 3 Hazırlığı

**Karar: SINIRLAMALARLA HAZIR**

**Neden hazır:**

- Gerçek bir yerel model Türkçe yanıt üretiyor ve masaüstü uygulamasıyla akış ve iptal çalışıyor.
- Adaptör modüler; P3'ün sohbet motoru `LLMProvider` portuna bağlanabilir.
- Kıyaslamalar çalıştırıldı ve model kararı kanıta dayanarak kabul edildi (ADR-0001).
- Güvenlik kontrolleri korunuyor ve Ollama için daraltıldı.
- Bütün regresyon testleri geçiyor.
- Belgeler gerçek durumu yansıtıyor.

**Faz 2 kabul kriterleri:** 14 kriterin hepsi karşılandı. Kriter 8 (kanıta dayalı model seçimi) ADR-0001'in kabulüyle kapandı. G2 kapısının revize edildiği ve ilk G2'nin karşılanmadığı Bölüm N'de açıkça yazılı.

**Faz 3'ten önce kararınız gereken konular:**

1. Faz 3'e başlama onayı.
2. FileVault'u açma kararı. Faz 3'te sohbetler şifreli veritabanına kaydedilmeye başlayacak.

Faz 2 değişiklikleri sahibin isteğiyle yerel olarak commit edildi; GitHub'a gönderilmedi.

**Faz 3'te ele alınacak Faz 2 bulguları:**

- **Uzun sohbet geçmişi ve bağlam yönetimi (en büyük risk):**
  - Önbellek ıskası bütün geçmişi yeniden işletiyor (Gemma'da 8K bağlamda 34 sn).
  - Sıkıştırma, önceden ısıtma, sabit önek ve "hazırlanıyor" durumu tasarımın parçası olmalı.
  - Gerçek istem birleştiriciyle G2-r1 (toplam bağlam raporlanarak) ve G4 yeniden ölçülmeli.
  - Önceki yanıtın yeniden işlenip işlenmediği (SPK-03b) doğrulanmalı.
- Gemma'nın olgu ve coğrafya hataları, dil hataları ve gereksiz övgüsü için değerlendirme maddeleri eklenmeli.
- 300 turluk dayanıklılık testi (B8) ve araç çağırma ölçümü (B7) yapılmalı.
- Geçici sistem isteminin yerini kişilik v0 almalı. "Efendim" ve "sen/siz" tutarlılığı ilk sınanacak davranış.

**Faz 3'e başlamadım; açık onayınızı bekliyorum.**
