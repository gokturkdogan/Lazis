# LAZIS — Faz 0 Nihai Mimari İncelemesi ve Uygulamaya Hazırlık Raporu (Faz 0.1)

> Tarih: 17 Ekim 2026 · Faz: 0.1 (mimari revizyon) · Durum: **tamamlandı, onay bekliyor**
> Bu fazda **uygulama kodu yazılmadı, bağımlılık kurulmadı, model indirilmedi, benchmark çalıştırılmadı.** Tüm performans rakamları *(tahmin)* olarak işaretlidir ve ölçülene kadar doğrulanmış sayılmaz.
> Dil notu: teknik dokümanlar kod tabanıyla tutarlı olsun diye İngilizce kaldı. Bu rapor ve kullanıcıya dönük metinler Türkçedir.

---

## A. Yönetici Özeti

Faz 0'da kurulan mimarinin temeli sağlam bulundu ve korundu:
- modüler monolit (Python `lazis-core`), Tauri + Vue arayüz, Ollama üzerinden yerel model;
- tek SQLite veritabanı (FTS5 + sqlite-vec);
- kanıta dayalı hafıza, "yalnızca isimle kimlik eşleştirme yok" kuralı, tek çıkış kapısı (egress gateway).

Revizyon, LAZIS'i tanımlayan yeteneği (kullanıcıyı giderek daha iyi anlamak) **uygulanabilir ayrıntıya** indirdi ve Faz 0'daki tutarsızlıkları giderdi. En önemli beş değişiklik:

1. **Risk tabanlı otonom öğrenme (A/B/C):** sıradan bilgi onaysız öğrenilir. Belirsiz bilgi "geçici" (provisional) saklanır. Hassas, belirsiz kimlikli, çelişkili veya yıkıcı değişiklikler onaya gider. Yüksek güven tek başına yüksek riskli bir değişikliği asla yetkilendirmez. Faz 0'daki "her şeyi elle onayla" varsayılanı kaldırıldı.
2. **Kimlik ve ilişki hafızası güçlendirildi:** ifade düzeyinde (mention-level) kaynak bağlantısı sayesinde düzeltmeler yalnızca ilgili bilgiyi taşır. "Çocukluk arkadaşımın kardeşinin adı neydi?" gibi sorular graftan deterministik olarak yanıtlanır. Varlık bölme (split) eklendi.
3. **Yerel kaynaklardan öğrenme birinci sınıf yetenek oldu:** ayrı bir mimari doküman ve ayrı bir faz (P11). Bir dokümanda geçen kişi, kullanıcının arkadaşı sayılmaz. Belge bilgisi kişisel bilgiden ayrı tutulur.
4. **Araştırma izin modeli:** kapalı (varsayılan), oturum başına sor, kamuya açık bilgiyi otomatik ara ve özel kurallar. Sorgular gönderilmeden önce kamuya açık / özel / hassas olarak sınıflandırılır. Kamuya açık isimler korunur, özel bağlam çıkarılır.
5. **Yol haritası 15 küçük, bağımsız doğrulanabilir faza bölündü.** Erken işlevsel masaüstü arayüzü P4'te gelir. Sinematik arayüz P14'te, yani konuşma, durum ve ses sistemleri oturduktan sonra gelir. Şifreleme P1'den itibaren varsayılandır.

**Hazırlık kararı:** mimari, Faz 1'e başlamak için **hazırdır**. Bunun koşulu, revize planın onaylanması ve §N'deki kararların yanıtlanmasıdır (önerilen varsayılanlar kabul edilebilir). Kalan belirsizlikler (Türkçe model kalitesi, önbellek davranışı, TTS doğallığı, şifreli vektör arama performansı) ölçüm gerektirir. Bunlar adlandırılmış spike'lara ve geçti/kaldı kapılarına bağlandı.

## B. Yapılan Değişiklikler

### B.1 Tespit edilen sorunlar ve çözümleri

| Kategori | Sorun (Faz 0) | Çözüm (Faz 0.1) |
|---|---|---|
| Mimari tutarsızlık | `works_at` ve `lives_in` hem hafıza yüklemi hem graf ilişkisiydi; aynı bilginin iki evi vardı | **Bilgi yerleşim kuralı:** varlık↔varlık bilgisi ilişkidir (graf), varlık→değer bilgisi hafızadır. İkisi aynı yaşam döngüsünü paylaşır |
| Mimari tutarsızlık | Üç ayrı geri alma mekanizması vardı (`memory_history`, `graph_history`, `import_batch_id`) | Tek mekanizma: **değişiklik setleri (change sets) + ortak `history` tablosu** |
| Eksik gereksinim | İlişkilerin kaynak (provenance) kaydı yoktu | Ortak `evidence` tablosu (hafıza, ilişki, takma ad, varlık) |
| Eksik gereksinim | "Geçici bilgi" kavramı yoktu; sorgulanma sayısı önemi artırıyordu | `provisional` durumu eklendi. **Getirme (retrieval) bilgiyi asla terfi ettirmez**; terfi yalnızca yeni kanıtla olur |
| Eksik gereksinim | Varlık bölme, ilişki yolu soruları ve düzeltme yayılımı tanımsızdı | KG §6.5, §6.6, §7.3, §7.5 ve Hafıza §11 |
| Belirsiz sorumluluk | `memory_entity_links` ve mention tablolarının sahibi belirsizdi (döngü riski) | Sahibi `graph`. Birleştirme (merge) ve bölme tek modülde kalır; modül DAG'ı yazıldı |
| Belirsiz sorumluluk | Öğrenme politikasının hangi yollarda çalışacağı belirsizdi | Kural: **her bilgi yazımı `learning.policy`'den geçer** (doğrudan kullanıcı düzenlemesi hariç) |
| Gerçekçi olmayan varsayım | Varsayılan `qwen3.5:9b` etiketinin MLX ile çalıştığı ima ediliyordu | Bu etiket GGUF `q4_K_M`. MLX, `nvfp4`/`mlx` etiketlerinde devreye girer. P2'de iki yol da ölçülecek |
| Gerçekçi olmayan varsayım | Konuşma geçmişini korumanın KV önbellek yeniden kullanımını garanti ettiği varsayılıyordu | 7 soruluk önbellek analizi (Teknoloji §2.1). Hibrit model kısıtları, şablonun geçmişi yeniden yazması, tokenizasyon kayması ve **arka plan işinin önbelleği silmesi** belirlendi. Ölçüm: B3, kapı G4 |
| Gerçekçi olmayan varsayım | Metin 16K / ses 8K bağlam ayrımı vardı | Bağlam boyutu değişince Ollama modeli yeniden yükleyebilir. **Tek sabit `num_ctx`** kullanılır; ses ile metin yalnızca hafıza bütçesinde ayrılır |
| Doğrulanmamış performans | Hibrit Qwen3.5 için prefill tahmini güvenilir sanılıyordu | "Düşük güvenli tahmin" olarak işaretlendi; Gated DeltaNet çekirdeklerinin Metal'deki olgunluğu bilinmiyor. Gemma 4 12B hazır rakip |
| Doğrulanmamış performans | Uçtan uca ses gecikmesi tek bir rakamdı | Beş aşamaya ayrıldı (uç nokta tespiti, STT, LLM TTFT, TTS ilk ses, oynatma başlangıcı). Her aşama ayrı ölçülecek ve ölçülmeden doğrulanmış sayılmayacak |
| Eksik faz bağımlılığı | Ses modellerinin bellek ayak izi LLM seçimini etkiliyordu ama sesten önce değerlendirilmiyordu | P2'de **ses fizibilite duman testi** (SPK-07): yalnızca bellek ve RTF ölçülür |
| Eksik faz bağımlılığı | Açık hafıza komutları politika motoruna ihtiyaç duyuyordu ama politika öğrenme fazındaydı | `learning.policy` v1, P6'ya alındı |
| Eksik faz bağımlılığı | Araştırma gizliliği varlık görünürlüğüne bağlıydı | P12'nin ön koşulu P7 yapıldı |
| Güvenlik zayıflığı | Şifreleme "opsiyonel"di; fazı belgeler arasında çelişiyordu (P3 / P10) | **SQLCipher varsayılan, P1'den itibaren.** Gerçek kişisel veri asla şifresiz saklanmaz. Anahtar yönetimi, kurtarma kodu ve kayıp senaryoları yazıldı |
| Güvenlik zayıflığı | Araştırma günlüğü silinebilir önbellekteydi | Denetim kaydı (`audit_log`) artık ana veritabanında; tüm güvenlikle ilgili olaylar orada, içerik olmadan |
| Güvenlik zayıflığı | Belgeler ve üçüncü taraf metinlerinin güven düzeyi tanımsızdı | **Güven sınıfları T0–T5** ve araç izin matrisi (temiz / yarı güvenilir / kirli tur) |
| Güvenlik zayıflığı | Çıkış kuralı yerel adreslere giden SearXNG trafiğini kapsamıyordu; SearXNG sorguları internete taşır | Kural netleşti: geri döngü bağlantısı yalnızca yerel çıkarım için serbest. **Tüm araştırma trafiği, yerel SearXNG dahil, egress gateway'den geçer** |
| Ölçeklenebilirlik / bakım | Kodlama ve bağımlılık kuralları yoktu | Yeni [ENGINEERING_STANDARDS.md](ENGINEERING_STANDARDS.md) |
| Ölçeklenebilirlik / bakım | Belge indeksi kişisel veritabanını şişirebilirdi | Ayrı, yeniden üretilebilir `documents.db`; kararlı (içerikten türetilen) parça kimlikleri |
| Eksik kabul kriteri | Geçici bilgi, ilişki soruları, bölme, düzeltme yayılımı, belge alımı, araştırma modları, denetim, şifreleme göçü, anahtar kurtarma ve erken arayüz için kriter yoktu | Hepsi [ACCEPTANCE_CRITERIA.md](ACCEPTANCE_CRITERIA.md)'ye eklendi; tüm gereksinim kimlikleri çapraz kontrol edildi |
| Yetersiz uygulama kararı | Benchmark ve model seçim kuralları dağınıktı | Yeni [BENCHMARK_PLAN.md](BENCHMARK_PLAN.md): B1–B10, kapılar G1–G8, ağırlıklı puan, önceden ilan edilmiş karar kuralları |

### B.2 Güncellenen ve yeni dokümanlar

| Doküman | Durum | Önemli değişiklikler |
|---|---|---|
| MEMORY_ARCHITECTURE.md | Büyük revizyon | Bilgi yerleşim kuralı; A/B/C politika; güven ve risk hesabı; karar matrisi; yaşam döngüsü; onay akışı; çelişki akışı; düzeltme yayılımı; inceleme modu; geri alma; değişiklik setleri; uydurmama sözleşmesi |
| KNOWLEDGE_GRAPH_DESIGN.md | Büyük revizyon | Nitelikli rol sözlüğü; kimlik kanıtı birikimi; düşük sürtünmeli onay; ilişki yolu soruları; Ahmet/Mehmet örneği; bölme; alanlar ve görünürlük; ilişki kanıtı |
| LOCAL_INGESTION_ARCHITECTURE.md | **Yeni** | 14 adımlı yerel kaynak hattı; kaynak sınıfları; güven tavanları; senkronizasyon; iptal |
| RESEARCH_ARCHITECTURE.md | Büyük revizyon | İzin modları; sorgu sınıflandırma; kamuya açık/özel ayrımı; kaynak güvenilirliği; tazelik; denetim |
| TECHNOLOGY_DECISIONS.md | Revizyon | Varsayım incelemesi (A1–A13); önbellek analizi; Ollama işletim parametreleri; spike kimlikleri `SPK-xx`; TTS adayları ölçüme bağlandı |
| BENCHMARK_PLAN.md | **Yeni** | Tekrarlanabilir ölçüm protokolü ve kapılar; Türkçe ses değerlendirme takımları |
| VOICE_ARCHITECTURE.md | Revizyon | Hedef ses profili; devam / kesme / iptal / kurtarma durumlarıyla FSM; aşamalı gecikme bütçesi |
| PERSONALITY_ENGINE.md | Revizyon | Beş katman ve öncelik sırası; güvenlik/gizlilik katmanı; hafıza dürüstlüğü ve hafıza iddiası koruması |
| UI_ARCHITECTURE.md | Revizyon | Erken işlevsel arayüz ile nihai sinir arayüzünün ayrımı; `StateVisual` arayüzü; yeni görünümler |
| SECURITY_MODEL.md | Revizyon | Varsayılan şifreleme ayrıntıları; güven sınıfları; araç izin matrisi; denetim kaydı |
| ARCHITECTURE.md | Revizyon | `ingestion` modülü; modül DAG'ı; yazım kuralları; önbellek kuralları; yeni API uçları; veri konumları |
| REQUIREMENTS.md | Yeniden düzenlendi | Faz numaraları P1–P15; yeni aileler ING, MEM-13…19, KG-08…13, RES-08…13, VOC-10…13, UI-08/09, SEC-12…15, PER-10…12 |
| DEVELOPMENT_ROADMAP.md | Yeniden yazıldı | 15 faz; her biri için 13 başlıklı tanım |
| ACCEPTANCE_CRITERIA.md | Revizyon | Yeni ölçülebilir kriterler; kapı referansları |
| ENGINEERING_STANDARDS.md | **Yeni** | Fazlar arası mühendislik standartları |
| TESTING_STRATEGY.md · RISK_ASSESSMENT.md | Revizyon | Yeni test takımları; 8 yeni risk (R23–R30) |
| PROJECT_VISION.md | Revizyon | Tanımlayıcı yetenek yeniden teyit edildi; yeni ilkeler |
| PHASE_0_REPORT.md | Tarihî kayıt | Hangi bölümlerin geçersiz olduğunu belirten başlık eklendi |

## C. Güncellenmiş Mimari

- **Süreçler:**
  - LAZIS Desktop (Tauri 2 kabuğu + Vue 3 arayüz);
  - `lazis-core` (Python 3.13 modüler monolit);
  - Ollama (yerel LLM ve gömme modeli; bulut kapalı);
  - `lazis-audio` (Swift; macOS yankı engelleme, P13);
  - belge ayrıştırıcı alt süreci (kaynak sınırlı, P11);
  - isteğe bağlı SearXNG (Docker, P12).
- **Veri:** üç SQLCipher veritabanı.
  - `lazis.db`: kişisel bilgi, geçmiş, değişiklik setleri, denetim;
  - `documents.db`: yeniden üretilebilir belge indeksi;
  - `cache.db`: silinebilir araştırma ve metrik önbelleği.
- **Modüller:** `conversation`, `voice`, `state` (orkestrasyon); `personality`, `memory`, `graph`, `learning` (politika ve inceleme dahil), `ingestion`, `bootstrap`, `research` (izinler dahil) (alan); `providers`, `storage`, `security`, `jobs`, `text`, `config`, `observability` (platform). Bağımlılıklar katmanlı ve döngüsüzdür; `import-linter` ile zorlanır.
- **Temel kurallar:**
  1. Her bilgi yazımı `learning.policy`'den geçer.
  2. Her yazım tek bir değişiklik setindedir.
  3. Dışarı bağlantıyı yalnızca egress gateway açar.
  4. Varlık ve ilişki tablolarına yalnızca `graph` yazar.
  5. Prompt yalnızca sona eklenerek büyür; sabit önek, tek `num_ctx`, önbellek telemetrisi.

## D. Hafıza ve Öğrenme (otonom öğrenme nasıl çalışır?)

1. **Kaynaktan aday bilgiye:** konuşma bir bölüm (segment) olarak kapandığında arka planda, boşta ve kesilebilir şekilde işlenir. Model aday bilgileri çıkarır. Her aday, **kullanıcının kendi mesajından birebir alıntıyla** doğrulanır; LAZIS'in kendi sözleri asla kanıt sayılmaz.
2. **Güven (confidence)** deterministik olarak hesaplanır:
   - kanıt türü (açık komut 0,95 · kendisi hakkında birinci tekil ifade 0,90 · başkası hakkında ifade 0,80 · aktarılan söz 0,65 · …);
   - × çekince ("sanırım" ×0,75);
   - × netlik;
   - → kimlik eşleştirmenin en zayıf halkası;
   - \+ yalnızca **bağımsız** teyitler.
3. **Risk** ayrı hesaplanır: hassasiyet, etki (aile yapısı, kimlik), çelişki, belirsiz kişi, işlem türü (birleştirme, bölme, silme), kaynak güveni.
4. **Karar matrisi:**
   - düşük/orta risk + yüksek güven → **A (otomatik)**;
   - orta güven → **B (geçici)**;
   - yüksek risk → her zaman **C (onay)**.
   Açık "bunu hatırla" isteği onay sayılır.
5. **Geçici bilgi** çekinceyle kullanılır ("yanılmıyorsam…"), asla kesin bilgi gibi söylenmez. Yalnızca yeni kanıtla (onay, inceleme onayı, bağımsız teyit) A'ya yükselir. **Tekrar tekrar hatırlanması onu doğrulamaz.**
6. **Onay akışı:** yanıt başına en fazla bir doğal soru sorulur; seste ve duygusal anlarda ertelenir. Onay Kutusu (Inbox) üzerinden yürür. Bekleyen öğe asla kendiliğinden uygulanmaz.
7. **Çelişki:** değişim sinyali varsa ("taşındım") eski bilgi tarihli olarak geçmişe alınır. Yoksa ve mevcut bilgi yerleşikse kullanıcıya sorulur ("Daha önce İzmir demiştin, değişti mi?").
8. **Düzeltme:** yalnızca ilgili ifadeye bağlı bilgi taşınır ya da güncellenir; ilgisiz bilgi bozulmaz. Reddedilen bilgi yeniden öğrenilmez (bastırma parmak izi).
9. **İnceleme modu ("Öğrendiklerim"):** ilk 21 gün `calibration`, sonra `digest`; `off` ve `strict` seçenekleri de var. Eylemler: onayla, düzelt, reddet, sil, belirsiz işaretle, kaynağı gör, ilgili varlıkları gör. İnceleme **engelleyici değildir**.
10. **Geri alma:** tek öğe, tek öğrenme turu, tek içe aktarma, birleştirme veya bölme geri alınabilir. Sonraki değişikliklerle çakışmalar kullanıcıya gösterilir; yeni düzenlemeler sessizce ezilmez.
11. **Uydurmama:** LAZIS yalnızca getirilen bilgiyle desteklenen şeyleri "hatırladığını" söyler. Hafıza iddiası koruması (memory-claim guard) desteklenmeyen iddiaları yeniden üretir.

## E. Bilgi Grafiği (kimlik eşleştirme ve ilişki yönetimi)

- **Varlıklar:** kişi, kurum, yer, proje, olay ve diğerleri. Her biri durum, güven, alan (kişisel / proje / referans), köken ve görünürlük (özel / kamuya açık) taşır.
- **İlişkiler:** tipli ve zamanlı (geçerlilik aralığı); kanıtlı, güvenli ve geçmişli. Proje–kişi (rol), kurum–kişi (unvan), olay–kişi (katılım) dahil.
- **Kimlik eşleştirme:**
  - sinyaller: takma ad / isim benzerliği, akrabalık veya rol yolu, öznitelik uyumu, birlikte geçen kişiler, yakınlık;
  - cezalar: ayrım kısıtları, öznitelik çelişkisi, "yeni kişi" ipuçları;
  - **yalnızca isim eşleşmesi bir kişiyi asla kesinleştirmez:** en fazla *geçici bağlantı* olur. Kimlik, kullanıcıdan gelen isim dışı kanıtla "bağlı", açık onayla "onaylı" olur.
- **Ahmet/Mehmet örneği** (KG §6.6):
  1. "Ahmet benim çocukluk arkadaşım" → A seviyesinde kayıt.
  2. "Bugün Ahmet'le görüştüm…" → tek aday, yalnızca isim → plan bilgisi B seviyesinde; LAZIS isterse hafifçe teyit eder.
  3. "Ahmet'in kardeşi Mehmet…" → kardeşlik ilişkisi kaydedilir.
  4. "Çocukluk arkadaşımın kardeşinin adı neydi?" → graf yolu `ben → arkadaş{çocukluk} → kardeş` → "Mehmet". Yoldaki bir kenar geçiciyse yanıt çekinceyle verilir.
  İki Ahmet olsaydı ikinci konuşmada "Hangi Ahmet?" diye sorulurdu.
- **Birleştirme, ayırma ve bölme:** hepsi geri alınabilir; "farklı kişiler" kısıtı hatırlanır.
- **Düzeltme yayılımı:** ifade düzeyinde kaynak bağlantısıyla yalnızca ilgili bilgi taşınır.

## F. Harici Bilgi Alımı (yetkilendirilmiş yerel dosyalar)

- **Yalnızca açıkça yetkilendirilmiş klasör ve dosyalar okunur.** Bilgisayar asla taranmaz.
- **Kaynak sınıfı zorunludur:**
  - `personal_authored` (günlük, kişisel notlar; T2);
  - `project_docs` (T1);
  - `reference` (T1; hiç hafıza üretmez);
  - `third_party` (T1; iddialar yazarına atfedilir).
- **Hat:** yetkilendirme → keşif (PathGuard) → izole ayrıştırma → normalleştirme → sınıflandırma → parçalama ve indeksleme → varlık tanıma → aday çıkarımı → tekrar tespiti → alan duyarlı kimlik eşleştirme → kaynak kaydı → risk tabanlı inceleme → kalıcılaştırma → artımlı güncelleme → silme ve senkronizasyon.
- **Kritik ayrım:** bir proje dokümanında geçen "Ahmet", kullanıcının arkadaşı sayılmaz. Belge kişileri ayrı bir alanda tutulur. Kişisel ilişkiler yalnızca kullanıcının ifadesi veya onayıyla kurulur. Doğrulanmamış belge iddiaları `document_claims`'te kalır.
- **Kaynak kaldırma:** yalnızca o kaynağa dayanan bilgi geri çekilir; kullanıcının onayladığı bilgi korunur. Etki özeti gösterilir. Kaynak geçmişi, dosya başına geri alma ve hata kurtarma vardır.
- **Faz:** ayrı faz P11 (P9'daki politika ve hat hazır olduktan sonra).

## G. İnternet Araştırması (izin modları ve gizlilik sınırları)

- **Modlar:** `offline` (varsayılan) · `ask_per_session` · `auto_public` · `custom`. Araştırma etkinleştirildikten sonra sıradan **kamuya açık** aramalar (maç sonuçları, teknoloji haberleri, ürün özellikleri, güncel yazılım dokümanları) tekrar tekrar onay istemez.
- **Sınıflandırma** (gönderimden önce): kamuya açık · karışık (özel bağlam çıkarılabilir) · özel · hassas konu · belirsiz isim · kısıtlı veri.
  - Kamuya açık isimler (ünlüler, şirketler, ürünler) sorguda kalabilir.
  - Aile üyeleri, özel tanıdıklar, kişisel bağlam ve gizli proje adları çıkarılır.
  - Hassas konular varsayılan olarak sorar.
  - Kısıtlı veri her modda engellenir.
- **Örnek:** "Ahmet'in kurmak istediği şirket için sermaye ne kadar gerekir?" → gönderilen sorgu: "Türkiye limited şirket kuruluş sermayesi 2026". Bu sorgu kullanıcıya gösterilir.
- **Güvenlik:** web içeriği araçsız, karantinadaki bir okuyucuda işlenir; alıntılar doğrulanır; enjeksiyon taranır; kirli turlarda yazma araçları kapalıdır. Araştırma içeriği ayarları değiştiremez, komut veremez.
- **Diğer:** kaynak güvenilirliği sıralama ve ifade için kullanılır; TTL ile tazelik yönetilir. **Her karar ve gönderilen sorgunun birebir metni denetim kaydına yazılır.** Araştırma sonuçları kişisel hafızadan ayrı tutulur.

## H. Yerel Yapay Zekâ Modelleri (adaylar ve benchmark gereksinimleri)

- **Seçim korundu:**
  - birincil aday: **Qwen3.5-9B**;
  - rakip: **Gemma 4 12B**;
  - karşılaştırma tabanı: **Qwen3-14B** ve **Qwen3-8B**.
  Değiştirmek için teknik bir gerekçe bulunmadı.
- **İncelenen varsayımlar:**
  - **M4 Pro + Ollama 0.40.4:** kurulu, ancak hiçbir model çalıştırılmadı.
  - **MLX:** yalnızca MLX formatlı etiketlerde geçerli; varsayılan etiket GGUF.
  - **24 GB bütçesi:** tahmin; sabit `num_ctx` ile ölçülecek.
  - **KV önbellek:** ~32 KiB/token; hesaplandı, ölçülmedi.
  - **Prefill:** düşük güvenli tahmin.
  - **Yapılandırılmış çıktının zorlanması:** MLX yolunda belgelenmemiş.
  - **Türkçe kalite:** ölçülmedi.
  - **Nicemleme:** Q4 ile Q8 karşılaştırılacak.
  - **Model değiştirme:** çalışma sırasında yok; tek model bellekte.
- **Önbellek (KV cache):**
  - Geçmişi korumak tek başına önbellek yeniden kullanımını garanti etmez.
  - Riskler: hibrit modellerde durum yalnızca *uzatılabilir*; şablon geçmişi yeniden yazabilir; tokenizasyon gidiş-dönüşü kayabilir; tek slotlu motorda **arka plan işi önbelleği silebilir**; özetleme sonrası ilk tur soğuktur.
  - Önlemler: sabit önek, sona ekleme düzeni, boşta özetleme + ön ısıtma, `prompt_eval_count` ile kaçırma tespiti, gerekirse ikinci slot veya yeniden ısıtma.
- **P2 benchmark planı** (tekrarlanabilir, AC güçte, ortam manifestiyle):
  - B1 soğuk yükleme · B2 sıcak gecikme · B3 çok turlu önbellek (6 varyant) · B4 bellek;
  - B5 Türkçe kalite (kullanıcının kör ikili puanlaması) · B6 JSON çıkarımı · B7 araç çağırma;
  - B8 uzun konuşma · B9 gömme · B10 ses fizibilitesi.
- **Geçti/kaldı kapıları:** G1 bellek · G2 sıcak TTFT p50 ≤ 1,2 sn · G3 ≥ 20 token/sn · G4 önbellek yeniden kullanımı ≥ 0,9 · G5 JSON ≥ %99 · G6 araç ≥ %95 · G7 dil kayması ≤ %1 · G8 kararlılık.
  - Kapıları geçenler arasında ağırlıklı puan uygulanır (Türkçe doğallık %40).
  - Karar kuralları önceden ilan edildi. Kapı gevşetmek, kullanıcı onaylı bir ADR gerektirir.

## I. Türkçe Ses Sistemi (değerlendirme stratejisi ve açık seçimler)

- **Hedef ses:** erkek, hafif tok, sıcak, doğal, ifadeli, uzun dinlemede yormayan, net Türkçe telaffuzlu.
- **TTS adayları:** Chatterbox Multilingual V3 (önde, ama kesin değil), XTTS-v2, VoxCPM2, Trendyol-TTS; yedekler: Piper, Supertonic 3, MMS. **Seçim yalnızca dil desteğine göre yapılmayacak.**
- **TTS değerlendirme takımı:** 11 kategoride 64 cümle ve 3 dakikalık bir metin. Kategoriler: günlük konuşma, uzun cümleler, sorular, duygusal ifadeler, özel isimler, sayılar, tarih ve saat, kısaltmalar, Türkçe içinde yabancı isimler, Türkçeye özgü sesler, doğal duraklamalar.
  - Ölçütler: ses yüksekliği eşitlenmiş kör dinleme puanları (doğallık, telaffuz, erkek ses uygunluğu, ifade, uzun dinleme konforu), ASR gidiş-dönüş karakter hata oranı, kararlılık, gecikme, kaynak tüketimi, akış desteği, lisans.
- **STT:** Whisper large-v3-turbo (iki çalışma zamanı), large-v3, Türkçe ince ayarlı turbo, Qwen3-ASR.
  - Test kategorileri: hızlı, alçak sesli, gürültülü, gündelik Türkçe, özel isimler, kesintili ya da kendini düzelten konuşma, uzun ifadeler, sayılar, kod değiştirme, sessizlikte halüsinasyon.
  - Kullanıcının kayıtları depoda değil, şifreli veri dizininde tutulur.
- **Sıra alma:**
  - Silero VAD + Smart Turn v3.2 (Türkçe destekli) + macOS yerleşik yankı engelleme (VPIO).
  - Durumlar: dinleme → kullanıcı konuşuyor → uç nokta tespiti → işleme → asistan konuşuyor → kesme → iptal → kurtarma.
  - Kenar durumları: kullanıcı ilk ses çıkmadan konuşmaya devam ederse istek iptal edilir, transkriptler birleştirilip yeniden gönderilir.
- **Gecikme:** beş aşamalı bütçe (toplam ≈ 1,5–3,5 sn *tahmin*). Uçtan uca rakam ölçülmeden doğrulanmış sunulmayacak.
- **Açık seçimler:** TTS motoru, ses kimliği, STT modeli ve çalışma zamanı, yankı engelleme kalitesi. Bunlar P13 testleri sonucunda seçilecek ve ADR'ye bağlanacak.

## J. Masaüstü Uygulaması (erken arayüz ve nihai sinir arayüzü)

- **Erken işlevsel arayüz (P4):** sohbet, 2B durum göstergesi (beş renk), tanılama paneli (tur bazında süreler, önbellek yeniden kullanımı, model ve runner durumu, bellek, hata konsolu, geliştirici modunda prompt denetçisi), temel ayarlar ve sistem görünümü.
  - Her yetenek kendi fazında görünüm ekler: Hafıza (P6), Kişiler ve Onay Kutusu (P7), İçe Aktarma (P8), Öğrendiklerim (P9), Kaynaklar (P11), Araştırma günlüğü (P12), ses kontrolleri (P13).
- **Nihai sinir arayüzü (P14):** Three.js enerji çekirdeği, holografik halkalar, parçacıklar, sese duyarlı animasyon, OKLab renk geçişleri, kare bütçesi.
  - Aynı store'ları ve olayları kullanır. 2B gösterge düşük güç ve azaltılmış hareket modunda yedek olarak kalır (`StateVisual` arayüzü), yani erken yapılan iş atılmaz.

## K. Güvenlik (şifreleme, izinler, güven sınırları)

- **Şifreleme varsayılan:** SQLite tek başına şifrelemez; **SQLCipher** kullanılır.
  - Her veritabanı ve yedek P1'den itibaren şifreli oluşturulur. Gerçek kişisel veri P3'te başlar, dolayısıyla hiçbir zaman şifresiz saklanmaz.
  - Ön koşul: SPK-05 (sqlite-vec + FTS5 + SQLCipher uyumu ve performansı). Başarısız olursa karar kullanıcıya aittir (§N.7). Yalnızca bu durum için şifresizden şifreliye göç yolu (`sqlcipher_export`) tanımlandı.
- **Anahtar yönetimi:**
  - 256 bit veri anahtarı macOS Anahtar Zinciri'nde tutulur (yalnızca bu cihaz, kilit açıkken), çekirdeğe yalnızca stdin üzerinden verilir.
  - Kurulumda tek seferlik **kurtarma kodu** gösterilir. Anahtarlar sürümlüdür ve döndürülebilir (`PRAGMA rekey`).
  - **Anahtar ve kurtarma kodu birlikte kaybolursa veri geri getirilemez** (arka kapı yok).
  - Yeni Mac'e geri yükleme kurtarma koduyla yapılır.
- **Arama ve şifreleme:** FTS5 ve vektör tabloları da şifrelenir, arama değişmeden çalışır. Ancak kaba kuvvet vektör aramada sayfa çözme maliyeti doğar; sayfa önbelleği boyutu ve int8 vektörlerle hafifletilir ve **ölçülecek**.
- **Güven sınıfları** (yalnızca kullanıcının kendi ifadeleri yüksek güven taşır):
  - T5: kullanıcı düzenlemesi veya onayı;
  - T4: açık komut veya içe aktarma;
  - T3: konuşmadaki ifadeler;
  - T2: kullanıcının yazdığı belgeler;
  - T1: diğer belgeler, üçüncü taraflar, çıkarımlar;
  - T0: web.
- **Araç izin matrisi:** kabuk veya kod çalıştırma aracı yok. Belge veya web içeriği taşıyan turlarda yazma araçları kısıtlıdır. Ayarlar hiçbir zaman araçla değişmez.
- **Denetim kaydı:** silme, birleştirme/bölme, içe aktarma, kaynak yetkilendirme, araştırma kararları, politika reddi, anahtar işlemleri ve izin değişiklikleri kaydedilir; kişisel içerik yazılmaz.
- **Loglar** içeriksizdir. Yerel API yalnızca geri döngüde (loopback), oturum belirteci ve Origin denetimiyle çalışır. Tek çıkış kapısı P1'de "her şeyi reddet" modunda kurulur.

## L. Revize Geliştirme Yol Haritası

| Faz | Ad | Test edilebilir sonuç | Boyut |
|---|---|---|---|
| P1 | Proje temeli | `just ci` yeşil; şifreli veritabanı oluşturuluyor, göç ediyor, yedekleniyor ve geri yükleniyor | M |
| P2 | Yerel yapay zekâ entegrasyonu ve benchmark | Tekrarlanabilir benchmark/eval raporları; ADR-0001/0002/0004 ile model kararı | M |
| P3 | Konuşma motoru | Terminalde akışlı, iptal edilebilir Türkçe sohbet ve tur bazında metrikler | M |
| P4 | Asgari işlevsel masaüstü arayüzü | Masaüstü penceresinde sohbet, durum, tanılama ve hata görünümü | M |
| P5 | Kişilik motoru (çekirdek) | Daha doğal ve dürüst LAZIS; koruma metrikleri tanılamada | M |
| P6 | Kalıcı hafıza | "Bunu hatırla" yeni oturumda doğru hatırlanıyor; "unut" her yerden siliyor; bilinmeyen şey uydurulmuyor | L |
| P7 | Varlık ve ilişki grafiği | "Çocukluk arkadaşımın kardeşinin adı neydi?" graftan doğru kesinlikle yanıtlanıyor | L |
| P8 | Kişisel bilgi başlangıç aktarımı | Kullanıcının gerçek dosyası önizleniyor, uygulanıyor, geri alınabiliyor | M |
| P9 | Otomatik öğrenme (risk tabanlı) + inceleme | Normal sohbetten sonra doğru seviyelendirilmiş yeni bilgiler; tek tıkla geri alma | L |
| P10 | Uyarlanabilir kişilik ve proaktif takip | Bir kez söylenen tercih kalıcı; tarihli plan doğal biçimde bir kez takip ediliyor | M |
| P11 | Yetkilendirilmiş yerel belge alımı | Not klasörü kaynaklı yanıtlar veriyor; kaldırılınca katkısı da kalkıyor | L |
| P12 | İnternet araştırması | `auto_public` ile kaynaklı yanıt; aile üyesi içeren soru önce soruyor; her şey günlükte | M |
| P13 | Türkçe sesli iletişim | Eller serbest Türkçe konuşma; kullanıcı LAZIS'in sözünü doğal biçimde kesebiliyor | L |
| P14 | Nihai sinir arayüzü | Çekirdek beş durumu ve sesi kare bütçesi içinde yansıtıyor, gizlenince duruyor | M |
| P15 | Entegrasyon, güvenlik sertleştirme ve optimizasyon | Temiz kullanıcı hesabında baştan sona kurulum ve kurtarma koduyla geri yükleme çalışıyor | M |

Her fazın hedefi, ön koşulları, kapsamı, kapsam dışı işleri, etkilenen modülleri, beklenen dosyaları, veritabanı değişiklikleri, gerekli testleri, kabul kriterleri, çıktıları, riskleri ve çıkış koşulları [DEVELOPMENT_ROADMAP.md](DEVELOPMENT_ROADMAP.md) içinde tanımlıdır. **Hiçbir faz yalnızca kod yazıldığı için tamamlanmış sayılmaz.** Testlerin gerçekten çalıştırılıp raporlanması ve kullanıcı onayı şarttır.

## M. Kalan Riskler

| Risk | Puan | Durum / önlem |
|---|---|---|
| Prefill gecikmesi ve önbelleğin pratikte işe yaramaması (R2, R24) | 16 / 12 | P2'de B3'ün altı varyantı; alternatif motorlar; gerekirse ikinci slot veya yeniden ısıtma |
| 9–12B modellerin Türkçe doğallığı (R1) | 15 | Kullanıcının kör puanlaması belirleyici; Q4/Q8 karşılaştırması; model yükseltme yolu açık |
| Hafıza kirliliği (R4) ve politika kalibrasyonu (R28) | 15 / 12 | Kanıt doğrulama, geçici seviye, güvenilirlik diyagramı, inceleme modu, geri alma |
| Onay yorgunluğu ya da riskli öğelerin kaçması (R27) | 9 | Oran sınırları; günlük soru metriği; özet modu |
| Türkçe TTS doğallığı ve gecikmesi (R3) | 12 | Çok adaylı kör test; sentetik ses tasarımı; P2 fizibilite testi |
| Kimlik hataları (R5), belge güven kirlenmesi (R25), araştırmada kamuya açık/özel karışıklığı (R26) | 12 | Her biri için sıfır tolerans kapısı |
| SQLCipher ile sqlite-vec uyumsuzluğu veya yavaşlığı (R23) | 8 | P1'de SPK-05; yedek karar kullanıcıda |
| Anahtar kaybı ve kalıcı veri kaybı (R29) | 10 | Kurtarma kodu; geri yükleme tatbikatları |
| 24 GB birleşik bellek baskısı (R6) | 12 | Bütçe ölçümü (G1, B10); ses modellerini boşaltma politikası |

**Ölçülmeden çözülemeyecek belirsizlikler:**
- Türkçe yanıt kalitesi;
- gerçek TTFT ve önbellek yeniden kullanımı;
- hangi Ollama runner'ının hangi etiketi çalıştırdığı;
- MLX yolunda JSON zorlaması;
- şifreli vektör arama süresi;
- TTS ve STT kalitesi ile gecikmesi;
- yerleşik hoparlörde yankı engelleme kalitesi.

Bunların her biri adlandırılmış bir spike'a ve kapıya bağlıdır.

## N. Kullanıcı Onayı Gerektiren Kararlar

Önerilen varsayılanlar **kalın** yazılmıştır. Varsayılanları kabul ederseniz bunlarla ilerlenir.

1. **Revize planın onayı:** 15 fazlı yol haritası, risk tabanlı öğrenme politikası, yerel kaynak mimarisi ve araştırma izin modeli.
2. **P2 model indirmeleri:** bake-off seti (Qwen3.5-9B'nin GGUF ve MLX varyantları ile Q8, Gemma 4 12B, Qwen3-14B, Qwen3-8B, gömme modelleri; ≈ 30–40 GB). Ölçümler **adaptör takılıyken** yapılır. Onaylıyor musunuz?
3. **Model önceliği:** gecikme kapıları içinde **Türkçe doğallık, hızdan önce gelsin mi?**
4. **İnceleme modu:** **ilk 21 gün `calibration`, sonra `digest`.** Alternatifler: `off` ya da `strict`.
5. **Hassas kategoriler:** sağlık, finans, inanç, siyasi görüş, cinsel yaşam, hukuki konular, etnik köken, üyelikler, biyometri, mahrem ilişki ayrıntıları. Varsayılan: **onayla saklanır (C).** "Hiç saklanmasın" demek istediğiniz bir kategori var mı?
6. **Üçüncü kişilerin sağlık bilgisi:** **her zaman onay (C).** Uygun mu?
7. **Şifreleme:** **SQLCipher varsayılan + kurtarma kodunu parola yöneticinizde saklamak.** SPK-05 başarısız olursa önerimiz **P3'ü durdurup çözüm aramak**. Alternatif, geçici olarak yalnızca FileVault ile devam etmek.
8. **Araştırma:** başlangıçta **kapalı**. Etkinleştirildiğinde önerilen mod **`auto_public`**, hassas konular **sorar**. SearXNG'nin **Docker'da çalıştırılması** kabul mü?
9. **Hitap ve ton:** **`sen`** mi `siz` mi? Size nasıl hitap edilsin? Mizah düzeyi: **hafif** mi, az mı, daha esprili mi?
10. **Ses:** çoğunlukla **yerleşik hoparlör** mü, kulaklık mı? Varsayılan etkileşim **bas-konuş + eller serbest oturum seçeneği** olsun mu? Ses kimliği **sentetik tasarım** mı, rıza veren birinin kaydı mı?
11. **Yerel kaynaklar (P11):** öncelik hangisi? Markdown/Obsidian notları, PDF'ler, proje dokümanları, başka bir şey?
12. **Başlangıç aktarımı:** **YAML dosyasını siz mi yazacaksınız** (P8'de Türkçe şablon verilir), yoksa P10'daki rehberli görüşmeyi mi beklemek istersiniz?
13. **Çalışma zamanı:** backend için **Python (uv ile, günlük kullanımda görünmez)** kabul mü?
14. **Kullanım kapsamı:** **yalnızca kişisel, ticari olmayan** kullanım mı? Bu, ticari olmayan lisanslı ses modellerini aday olarak tutmamızı sağlar.
15. **Kaynak kontrolü:** **yalnızca yerel git** mi, özel bir GitHub deposu mu?
16. **Yerel ayarlar:** **Europe/Istanbul** saat dilimi ve **Türkçe arayüz** onaylı mı?
17. **Doküman dili:** teknik dokümanlar **İngilizce** kalsın, raporlar Türkçe olsun mu? Önerim bu.

## O. Faz 1 Hazırlığı

**Karar: mimari, uygulamaya geçmek için hazırdır.** Koşulu, §N'deki kararların yanıtlanması ya da varsayılanların kabul edilmesi ve revize planın açıkça onaylanmasıdır.

| Alan | Güven | Gerekçe |
|---|---|---|
| Mimari, depolama, güvenlik modeli | Yüksek | Basit ve iyi bilinen bileşenler; tutarsızlıklar giderildi; kurallar yazılı ve test edilebilir |
| Hafıza ve öğrenme politikası | Orta-yüksek | Tasarım ayrıntılı ve deterministik; sayısal eşikler P9'da kalibre edilecek |
| Bilgi grafiği | Orta-yüksek | Sıfır tolerans kapılarıyla korunuyor; kalite P7'deki test takımına bağlı |
| Model seçimi ve gecikme | Orta | Adaylar güçlü; Türkçe kalite ve önbellek davranışı ölçülmedi (P2) |
| Yerel belge alımı | Orta-yüksek | Güven tavanları net; ayrıştırma kalitesi ve verim P11'de ölçülecek |
| Araştırma gizliliği | Orta-yüksek | Sınıflandırma ve temizleme kuralları tanımlı; sınıflandırma doğruluğu P12'de kapıya bağlı |
| Ses (TTS doğallığı, yerleşik hoparlörde yankı engelleme) | Orta-düşük | Türkçe destekli adaylar model kartlarında doğrulandı; M4 üzerinde ölçüm yok (P2 fizibilite, P13 bake-off) |
| Arayüz | Yüksek | Erken ve nihai arayüz ayrımı riski azaltıyor |

**Faz 1 başlamadan önce gerekenler:**
1. Bu revizyonun ve §N kararlarının onayı.
2. `uv` kurulumu (Homebrew); Python 3.13'ü uv yönetecek. Sistemdeki Python 3.9.6 uygun değil.
3. Depo için `git init`.
4. P1'in ilk işi SPK-04 ve SPK-05 olacak (sürücü ve şifreleme doğrulaması). Model indirme P2'de, onayınızla.

**Faz 1'in teslim edeceği test edilebilir sonuç:** `just ci` temiz bir checkout'ta yeşil çalışır. Şifreli bir veritabanı oluşturulur, göç ettirilir, yedeklenir ve testlerle geri yüklenir. Yapay zekâ kodu ve kişisel veri içermez.

**Faz 1, açık onayınız olmadan başlamayacaktır.**
