# LAZIS — Faz 3 Raporu: Sohbet Motoru, Kalıcı Sohbet ve Bağlam Yönetimi

> Tarih: 2026-10-17 · Durum: **Faz 3 tamamlandı, onayınızı bekliyor.** Faz 4'e başlanmadı.
> Karar kaydı: [ADR-0010](adr/0010-conversation-persistence-and-context.md) · Güvenlik: [SECURITY_MODEL.md §5.14](SECURITY_MODEL.md) · Mimari: [ARCHITECTURE.md §6.1, §8.1](ARCHITECTURE.md)
> Ölçüm dosyaları: `evals/reports/phase3/` · Model: `gemma4:12b-it-qat` (ADR-0001), Ollama 0.40.4, MacBook Pro M4 Pro 24 GB, AC güç

---

## Özet

LAZIS artık tek mesajlık bir önizleme değil. Masaüstü uygulamasında kalıcı, çok turlu Türkçe sohbetler var:

- birden fazla sohbet açılabiliyor, yeniden adlandırılabiliyor ve onayla siliniyor;
- sohbetler uygulama kapanıp açılınca geri geliyor;
- yanıt akış halinde geliyor ve durdurulabiliyor.

**Saklama:** Sohbetler mevcut SQLCipher veritabanında, Keychain'deki anahtarla şifreli saklanıyor. Yeni ağ izni yok; buluta hiçbir şey gitmiyor; günlüklerde mesaj metni yok.

**Uzun sohbetler:**

- Bağlam, modelin kendi token sayımına dayanan bir bütçeyle yönetiliyor.
- Eski mesajlar kaynak gösteren ve kodla doğrulanan bir özete dönüştürülüyor.
- Orijinal mesajlar hiçbir zaman silinmiyor.

**Önbellek ıskası** (Faz 2'de 12K bağlamda 50 sn) ön ısıtmayla kapatılıyor:

- Ön ısıtılmış bir sohbette ilk yanıt 0,4 sn'de başlıyor.
- Son kullanılan sohbetlere geri dönüş 1–1,4 sn sürüyor.

**Bulunup düzeltilen sorunlar:**

- **Bellek sorunu:** Ollama'nın içindeki llama.cpp, gizli bir RAM önbelleğiyle bellek kullanımını 13,2 GB'a çıkarıyordu; 2 GB ile sınırlandı (§7.4).
- **Hata ayıklama ve ölçüm bulguları:** Bozuk veritabanında yanlış hata kodu, özetin ayrıntı kaybetmesi ve önbellek durumunun yanlış raporlanması.

**Testler:** `make check` geçti: Python 302, arayüz 37 + 5 (3 canlı test atlandı), Rust 19 + 7. Gerçek modelle canlı testler: 8/8 arayüz bütünleşik, 3/3 Python.

### Kabul kriterleri

| Kriter | Durum | Kanıt |
|---|---|---|
| Gerçek masaüstü uygulamasında sohbet oluşturulabiliyor | **Kısmen doğrulandı.** Sürüm derlemesi açıldı ve sohbet ekranı göründü. Ancak macOS benim arayüzde tıklamama izin vermediği için ilk mesajı arayüzden göndermedim. Aynı istemci koduyla gerçek arka uca ve gerçek modele sohbet oluşturuldu | Canlı bütünleşik test; bileşen testleri; §9.3. Sizin elle denemeniz gerekiyor (§12) |
| Mesajlar SQLCipher ile kalıcı saklanıyor | Karşılandı | Depolama testleri: veritabanı, WAL ve yedeklerde düz metin yok |
| Uygulama yeniden açıldığında sohbetler geri geliyor | Karşılandı (arka uç düzeyinde) | Gerçek arka uç süreci durdurulup aynı anahtarla yeniden başlatıldı; sohbet, başlık ve mesajlar geri geldi, model önceki bilgiyi hatırladı. Motor testi: yeniden açıp devam ettirme |
| Birden fazla sohbet bağımsız çalışıyor | Karşılandı | İzolasyon testleri (motor, API, arayüz) |
| Eski sohbet açılıp devam ettirilebiliyor | Karşılandı | Motor, API ve canlı testler |
| Başlık değiştirilebiliyor | Karşılandı | API, arayüz ve canlı test |
| Sohbet silinebiliyor | Karşılandı | Zincirleme silme, denetim kaydı, WAL temizliği, model önbelleğinin boşaltılması |
| Yanıt akışı çalışıyor | Karşılandı | NDJSON; canlı testler |
| Yanıt iptali güvenli | Karşılandı | Kısmi yanıt `cancelled` olarak saklanıyor; sonraki bağlama işaretle giriyor |
| Yarım kalan üretimler doğru yönetiliyor | Karşılandı | Çökme sonrası `interrupted`; kapanışta `interrupted`; arayüzde etiketli |
| Bağlam bütçesi uygulanıyor | Karşılandı | 300 turluk dayanıklılık testinde sınır hiç aşılmadı; tahmin hatası canlı ölçümde ±%5 |
| Uzun konuşmalar kontrollü sıkıştırılıyor | Karşılandı | Boşta ve sınırda özetleme; parça parça kayıt; duyurulu kırpma |
| Özetler orijinal mesajların yerine geçmiyor | Karşılandı | Orijinaller korunuyor; özetler geçersiz kılınabiliyor |
| Önceki bağlam doğru kullanılıyor | Karşılandı (küçük örneklemle) | Bağlam değerlendirmesi 16/16 (§7.5); sınırlamalar §10 |
| İçerik loglara sızmıyor | Karşılandı | API güvenlik testleri; canlı testte gerçek günlük dosyası taranıyor |
| Veritabanı şifresiz moda düşmüyor | Karşılandı | Faz 1 garantileri ve Faz 3 testleri |
| Cold/warm performans ölçüldü | Karşılandı | §7 |
| 24 GB sınırı dikkate alındı | Karşılandı | RAM önbelleği sınırı, keep_alive değerlendirmesi, §7.4 |
| Faz 2 özellikleri bozulmadı | Karşılandı | Bütün Faz 1/2 testleri geçiyor. Faz 2 geçici sohbet uç noktası çalışıyor, ama arayüz paneli kalıcı sohbetle değiştirildi (§2) |
| `make check` başarılı | Karşılandı | §9 |
| Faz 3 raporu hazır | Bu belge | — |

**Tam karşılanmayan tek kriter:** ilk mesajın gerçek uygulama penceresinden gönderilmesi. Bu adımı ben yapamadım; sizin elle denemeniz gerekiyor (§12).

---

## 1. Tamamlanan özellikler

**Kalıcı sohbetler:**

- Yeni sohbet yalnızca taslak olarak açılıyor; ilk mesajla birlikte kaydediliyor ve başlığı ilk mesajdan otomatik oluşuyor.
- Sohbet listesi son güncellemeye göre sıralanıyor; aktif sohbet vurgulanıyor.
- Yeniden adlandırma satır içinde yapılıyor; silme, geri alınamayacağını ve yedekleri açıkça söyleyen bir onay penceresiyle yapılıyor.

**Tur yaşam döngüsü:**

- **Kayıt:** Kullanıcı mesajı ve boş bir yanıt satırı tek işlemde (transaction) kaydediliyor.
- **Tekrar gönderim:** Aynı mesaj iki kez gönderilirse istemci kimliği sayesinde reddediliyor.
- **Kısmi yanıt:** Akış sırasında en geç saniyede bir veya 400 karakterde bir diske yazılıyor.
- **Kapanış:** Yanıt satırı tam bir kez kapanıyor: `complete`, `cancelled`, `interrupted` ya da `failed`.
- **Çökme sonrası:** Açılışta yarım kalan satırlar `interrupted` olarak işaretleniyor.

**Gerçek aşamalar:** Arayüz sahte yüzde göstermiyor; arka ucun bildirdiği gerçek aşamaları gösteriyor:

- Sırada
- Model hazırlanıyor
- Konuşma bağlamı hazırlanıyor (≈N token)
- Yanıt hazırlanıyor
- Uzun konuşma özetleniyor
- Yanıt oluşturuluyor
- Durduruluyor
- Arka planda hazırlanıyor / özetleniyor

**Hata durumları:**

- Türkçe hata iletileri: Ollama çalışmıyor, model yok, model yüklenemedi, veritabanı meşgul, mesaj kaydedilemedi, bağlam hazırlanamadı, yanıt üretilemedi, bağlantı hatası.
- Anahtar erişim hatası Faz 1'deki başlatma ekranında gösteriliyor.
- Reddedilen bir mesaj kutudan silinmiyor.

**Bağlam yönetimi:**

- S0 güvenlik kuralları ve S1 kişilik v0, sabit önekte.
- Her mesaja bir zaman notu ekleniyor; not saklandığı için önek değişmiyor.
- Token bütçesi modelin kendi sayımına dayanıyor; özetleme kodla doğrulanıyor.
- Hiçbir yöntem işe yaramazsa en eski mesajlar, bu açıkça duyurularak bağlamdan çıkarılıyor.

**Performans:**

- Tek model yuvası için bir zamanlayıcı var: kullanıcının turu arka plan işini durduruyor.
- Ön ısıtma şu anlarda yapılıyor: sohbet açılınca, pencere öne gelince, yazmaya başlayınca ve özetlemeden sonra.
- llama.cpp RAM önbelleği 2 GB ile sınırlı.

**Güvenlik:**

- Silinen sohbet için WAL temizleniyor; model önbelleği o sohbeti tutuyorsa model boşaltılıyor.
- FileVault kapalıysa sohbet ekranında kalıcı bir uyarı var.
- Bozuk veritabanında `internal_error` yerine `database_corrupt` dönüyor (bu düzeltme Faz 1 kodunda).

**Sayfalama:**

- Mesajlar 50'lik sayfalarla yükleniyor ("Daha eski mesajları göster").
- Sohbet listesi de sayfalı.

## 2. Değiştirilen dosyalar

`7ba9d8a` (Faz 2) ile Faz 3 commit'leri arası.

**Yeni:**

- **Arka uç:**
  - `core/src/lazis/conversation/`: `models.py`, `repository.py`, `prompts.py`, `context.py`, `compaction.py`, `scheduler.py`, `engine.py`
  - `core/src/lazis/api/conversations.py`
  - `core/src/lazis/storage/migrations/lazis/0002_conversations.sql`
- **Arayüz:**
  - `ui/src/stores/conversations.ts`
  - `ui/src/components/ConversationSidebar.vue`, `ConversationThread.vue`
  - `ui/src/views/ConversationView.vue`
- **Testler:**
  - `core/tests/conversation_support.py`
  - `core/tests/unit/test_conversation_context.py`, `test_compaction.py`
  - `core/tests/integration/test_conversation_engine.py`, `test_conversation_storage.py`
  - `core/tests/security/test_conversation_api.py`
  - `ui/tests/unit/conversations.spec.ts`
- **Ölçüm:**
  - `evals/runners/p3_conversation.py`, `p3_context_eval.py`
  - `evals/datasets/tr_compaction_v1.json`
  - `evals/reports/phase3/*`
- **Belge:** `docs/adr/0010-conversation-persistence-and-context.md`, bu rapor

**Değişen:**

- **Arka uç:**
  - `core/src/lazis/api/app_factory.py`, `api/chat.py` (Faz 2 sohbeti aynı yuvayı kullanıyor), `api/schemas.py`
  - `config/model.py` (`[conversation]` bölümü)
  - `errors.py`, `i18n.py`
  - `storage/__init__.py` (bozuk sayfa → `database_corrupt`)
  - `__init__.py` (P3)
  - `core/pyproject.toml` (katman kuralına `lazis.conversation` eklendi)
- **Arayüz:**
  - `ui/src/App.vue` (Sohbet sekmesi varsayılan)
  - `api/client.ts`, OpenAPI anlık görüntüsü ve TS tipleri
  - `i18n/tr.ts`, `format.ts`, `views/OverviewView.vue`
- **Testler ve betik:**
  - Faz 1/2 testlerinde sürüm ve faz güncellemeleri
  - `scripts/ollama-agent.sh` (RAM önbelleği sınırı, başlatma yarışı düzeltmesi)
- **Belgeler:** ARCHITECTURE, DEVELOPMENT_ROADMAP, SECURITY_MODEL, TESTING_STRATEGY, DEVELOPER_GUIDE, RISK_ASSESSMENT, README

**Silinen:** Faz 2'nin geçici sohbet paneli (`ChatPanel.vue`, `stores/chat.ts`, `chat.spec.ts`). Yerini kalıcı sohbet aldı. Faz 2'nin `/chat/stream` uç noktası ve testleri duruyor.

## 3. Veritabanı şeması (`0002_conversations`)

| Tablo | Önemli sütunlar | Kurallar |
|---|---|---|
| `conversations` | `id` (ULID), `title`, `title_source` (auto/user), `model`, `status`, `message_count`, `last_seq`, `created_at`, `updated_at` | `updated_at` sırasına göre indeks |
| `messages` | `id`, `conversation_id` → conversations (**CASCADE**), `seq`, `role`, `content`, `context_note` (zaman notu), `status` (complete/streaming/cancelled/interrupted/failed), `client_id` (**UNIQUE**), `reply_to`, `model`, `token_count` + `token_source` (runtime/estimate), `prompt_tokens`, `output_tokens`, `ttft_ms`, `total_ms`, `error_code`, `created_at`, `completed_at` | `UNIQUE(conversation_id, seq)`; `seq` işlem içinde atanıyor |
| `context_summaries` | `id`, `conversation_id` (**CASCADE**), `version`, `from_seq`, `to_seq`, `previous_id`, `status` (active/superseded/invalidated), `content_json` (her maddede `refs`/`quote`/`source`/`certain`), `rendered`, `token_count`, `model`, `prompt_version`, `kept_items`, `dropped_items` | Özet bir mesaj aralığını kapsıyor; maddeler mesaj numaralarına atıf yapıyor |
| `conversation_context` | `conversation_id` (**CASCADE**), `context_version`, `prompt_version`, `strategy` (full/summary_window/window_only), `window_start_seq`, `summary_id`, `budget_tokens`, `anchor_seq`, `anchor_tokens`, `prefix_hash`, `last_prompt_tokens` | Çapa (anchor) yalnızca aynı `context_version` ve aynı önek hash'i için geçerli |

**Silme:**

- Tek işlemde zincirleme siliniyor (`ON DELETE CASCADE`).
- Denetim kaydına yalnızca kimlik ve sayılar yazılıyor; ardından `wal_checkpoint(TRUNCATE)`.
- `secure_delete=ON` Faz 1'den beri açık.

**Neler kapsam dışında:**

- **Değişiklik kümeleri:** Sohbet satırları değişiklik kümesi/`history` sistemine bilerek alınmadı. Alınsaydı silinen sohbetin bir kopyası `history` tablosunda kalırdı (ADR-0010 §1).
- **`segments` tablosu:** Öğrenme hattıyla birlikte P9'da gelecek.

**Yükseltme:** Mevcut v1 veritabanı otomatik ve güvenli yükseltiliyor.

- Önce şifreli bir yedek alınıyor; migration tek işlemde uygulanıyor.
- Sonraki bir migration başarısız olursa veriler değişmiyor (test edildi).

## 4. API değişiklikleri

Hepsi mevcut korumanın arkasında: token, Host, Origin, hız ve boyut sınırları.

| Uç nokta | Açıklama |
|---|---|
| `GET /conversations?limit&cursor` | Liste (son güncellenen önce) |
| `GET /conversations/{id}` | Sohbet ve bağlam durumu: strateji, pencere, özet, tahmini token, önbellek sıcak/soğuk |
| `GET /conversations/{id}/messages?before_seq&limit` | Sayfalı mesajlar |
| `PATCH /conversations/{id}` | Yeniden adlandırma |
| `DELETE /conversations/{id}` | Silme |
| `POST /conversations/{id}/context/reset` | Özetleri geçersiz kılma |
| `POST /turns` | Tur gönderme. NDJSON akışı: `start` → `status{stage}` → `delta` → `done` / `cancelled` / `error` |
| `POST /turns/cancel` | İptal |
| `POST /chat/prepare` | Ön ısıtma |
| `GET /chat/activity` | Tur ve arka plan işi durumu |

- **Akıştan önce reddedilenler:** Meşgul, tekrar, bilinmeyen sohbet, yüklü olmayan model, çalışma ortamı kapalı ve aşırı uzun mesaj durumları **akış başlamadan** HTTP hatası olarak dönüyor; bu durumlarda hiçbir şey kaydedilmiyor.
- **Yeni hata kodları:** `conversation_not_found`, `turn_duplicate`, `database_busy`, `message_save_failed`, `context_failed`, `message_too_long`.
- **WebSocket eklenmedi:** Arka uç WebSocket'i hâlâ reddediyor; akış NDJSON/HTTP ile.

## 5. Bağlam yönetimi stratejisi

**İstem düzeni** (ARCHITECTURE §6):

- **Sistem mesajı:** S0 güvenlik kuralları, S1 kişilik v0, konuşma özeti ve gerekirse bağlama sığmayan aralığın notu.
- **Ardından:** sözlü pencere (her kullanıcı mesajı saklanmış zaman notuyla) ve yeni mesaj.
- **Önek kararlılığı:** Bir bağlam sürümü içinde geçmiş yalnızca sonuna ekleme yapılarak büyüyor. Önek hash'i istem sürümünü, modeli, `num_ctx`'i ve sistem metnini kapsıyor. Bu, testlerle doğrulandı: n. istek, (n+1). isteğin baş kısmıyla bayt bayt aynı.

**Kısmi yanıt kuralı:**

- Durdurulan yanıt `[Bu yanıt kullanıcı tarafından yarıda kesildi.]` notuyla bağlama giriyor.
- Yarım kalan yanıt `[… uygulama kapandığı için yarım kaldı.]` notuyla giriyor.
- Başarısız ve boş yanıtlar bağlama hiç girmiyor.

**Token bütçesi:**

- Ollama 0.40.4'te tokenize uç noktası yok; bu doğrulandı.
- **Hesap:** Her turdan sonra modelin bildirdiği `prompt_eval_count` "çapa" olarak saklanıyor. Sonraki tahmin yalnızca yeni eklenen kısmı ekliyor: yanıtın `eval_count`'u, şablon payı ve yeni mesaj. Model tarafından sayılmamış metin 2,2 karakter/token ile güvenli tarafta tahmin ediliyor; ölçülen Türkçe değer 2,5–3,8.
- **Canlı ölçüm:** 56 turda tahmin hatası ortanca 0, en kötü −%5 / +%3.
- **Sınırlar** (16.384 token'lık bağlam):

| Eşik | Değer |
|---|---|
| Sert sınır | 13.721 (yanıt için 1.024 ve %10 güvenlik payı ayrılınca) |
| Boşta özetleme | 6.144'ün üzerinde |

**Bütçe aşılırsa adım adım:**

1. Kullanıcı boştayken (turdan 5 sn sonra) arka planda özetleme yapılıyor.
2. Sert sınır aşılacaksa, tur gönderilmeden önce görünür "özetleniyor" aşamasıyla özetleme yapılıyor.
3. Özetleme mümkün değilse en eski sözlü mesajlar bağlamdan çıkarılıyor. Model ve arayüz hangi aralığın eksik olduğunu biliyor; model hatırlamadığını söylüyor. **Hiçbir şey sessizce kesilmiyor.**

## 6. Özetleme stratejisi

**Biçim:** JSON şemasıyla kısıtlanmış yapılandırılmış özet. Bölümler: hedefler, devam eden konular, kararlar (`current` ile), çözülmemiş sorular, kısıtlamalar, kişiler, talimatlar, LAZIS'in önerileri.

- Her madde şunları taşıyor: `source` (kullanıcı ya da LAZIS), `refs` (mesaj numaraları), kelimesi kelimesine `quote` ve `certain`.

**Kodla doğrulama:** Her madde orijinal mesajlarla karşılaştırılıyor.

- Atıf yapılan mesaj özetlenen aralıkta olmalı.
- Kullanıcıya atfedilen maddenin alıntısı, atıf yapılan kullanıcı mesajında geçmeli (normalize edilmiş, ≥ 0,85 bulanık eşleşme).
- LAZIS'e atfedilen madde bir asistan mesajına atıf yapmalı.
- **Geçemeyen madde atılıyor ve sayılıyor.**

**Sonuçları:**

- LAZIS'in önerisi kullanıcının kararı gibi yazılamıyor.
- Mesajda olmayan bir bilgi alıntıyla desteklenemiyor.
- Değişmiş kararlar "artık geçerli değil" olarak gösteriliyor.
- Kesin olmayan bilgiler "(belirsiz)" olarak işaretleniyor.

**Sağlamlık:**

- **Parça parça kayıt:** Büyük birikimler yaklaşık 6.000 token'lık parçalar halinde özetleniyor ve **her parça bitince kaydediliyor**. Kullanıcı araya girerse en fazla o anki parça kayboluyor.
- **Token sınırında kesilen JSON:** İçindeki tamamlanmış maddeler kurtarılıyor.
- **Daha kısa çıktı:** Tek satır JSON ve tekrarsız madde talimatı çıktıyı yarıya indirdi (1.070 → 520 token).

**Orijinaller ve iz sürme:**

- Orijinal mesajlar asla değişmiyor.
- `context/reset` bütün özetleri geçersiz kılıyor; sonraki özetleme yeniden üretiyor.
- Özet maddelerinin mesaj numaraları, ileride hafıza sisteminin (Faz 6) kaynak gösterebileceği temiz bir iz bırakıyor.

**Bu fazda yapılmayanlar:** Kişi profili, otomatik bilgi çıkarma ve kalıcı hafıza yok.

## 7. Cold-cache ve warm-cache performans sonuçları

**Yöntem** (`evals/runners/p3_conversation.py`):

- Üretimdeki motor kullanıldı; ölçüm geçici bir şifreli veritabanında yapıldı ve sonra silindi.
- İlk yanıt süresi (TTFT), kullanıcının gördüğü şekilde ölçüldü: gönderimden ilk karaktere kadar.
- Her satırda modele giden toplam bağlam kaydedildi.
- Sentetik geçmişler, motorun kendi oluşturduğu mesajlardaki gibi modelin gerçek token sayımlarıyla dolduruldu.
- 2 tekrar yapıldı (sıcak turlarda 4).
- "Önbellek ıskası" için her tekrarda **yeni** bir sohbet kullanıldı; böylece model o metni daha önce hiç görmemiş oluyor.

**Not:**

- Ölçümler, §7.5'teki istem düzeltmesinden (p3-v2) önce yapıldı. Sistem istemi birkaç düzine token uzadı; bu süreleri ölçülebilir biçimde değiştirmez.
- İlk ölçüm turunu geçersiz saydım. Ölçerken modelin gizli RAM önbelleğini keşfettim (§7.4); o turdaki "soğuk" değerler aslında önbellekten geliyordu. O tur bu rapora alınmadı.

### 7.1 Bağlam boyutuna göre ilk yanıt süresi (RAM önbelleği 2 GB, son ayar)

| Toplam bağlam | Hiç görülmemiş (önbellek ıskası) | Son kullanılanlardan geri dönüş | Ön ısıtma bitince | Sohbet açıldıktan 2 sn sonra gönderim | 10 sn sonra gönderim | Sıcak (art arda tur) |
|---|---|---|---|---|---|---|
| ~2,7K | 9,5–9,9 sn | 1,0–1,1 sn | 0,34–0,36 sn | 7,7 sn | 0,39 sn | 0,45–0,68 sn |
| ~4,6K | 16,1–16,2 sn | 1,1 sn | 0,36 sn | 14,3–14,4 sn | 6,2–6,7 sn | 0,47–0,60 sn |
| ~8,6K | 31,5–32,1 sn | 1,1–1,2 sn | 0,40–0,41 sn | 30,3–30,4 sn | 22,2–22,4 sn | 0,52–0,68 sn |
| ~12,7K | 48,6–48,7 sn | 1,3–1,4 sn | 0,44–0,45 sn | 47,7–47,8 sn | 39,0–39,8 sn | 0,57–0,72 sn |

### 7.2 Senaryolar (8K bağlam)

| Senaryo | Ön ısıtma yok | Ön ısıtma ile |
|---|---|---|
| Yeni boş sohbet | Model ilk kez: 1,6 sn; sonrası: 0,10 sn | — |
| Uygulama yeniden açıldı, Ollama çalışmaya devam ediyor | 0,54 sn | — |
| Uygulama yeniden açıldı, Ollama/model yeniden başladı | 34,8 sn | 0,39 sn (ön ısıtma 35 sn sürdü; kullanıcı açınca bekler) |
| Model yeniden yüklendi (keep_alive doldu) | 36,4 sn | Odakta ön ısıtma + 10 sn sonra gönderim: 27,6 sn |
| İki 8K sohbet arasında geçiş, başka işlerden sonra | 32,6 sn (2 GB) / 1,9 sn (8 GB önbellek) | 0,40 sn |
| 12K sohbet arka planda özetlendikten sonraki ilk mesaj | 11,6 sn (özet sonrası 3,5K bağlam) | 0,38 sn |
| İçe aktarılmış gibi, token sayısı olmayan 12K sohbet | 160 sn (tahmin sert sınırı aştı → önce özetleme) | — |

**Özetleme maliyeti:**

- 12,7K → 3,5K token'lık bir arka plan özetlemesi (3 parça) 178–181 sn sürdü.
- Normal kullanımda özetleme 6K civarında başlıyor ve yaklaşık 4K'lık birikimi tek parçada 20–25 sn'de bitiriyor (§7.5'teki değerlendirme çalıştırmalarında 17–25 sn).

### 7.3 Yorum

- **İyileşen durumlar.** Ön ısıtma, bekleme süresini kullanıcının o sohbete bakıp yazdığı süre kadar gizliyor.
  - Ön ısıtma bittiyse, 12K'da bile ilk yanıt 0,45 sn.
  - Uygulama yeniden açılınca son sohbet otomatik ön ısıtılıyor.
  - Özetlemeden sonra ön ısıtma: 11,6 sn yerine 0,38 sn.
  - Son kullanılan sohbetlere geri dönüş 1–1,4 sn (RAM önbelleği).
- **İyileşmeyen durumlar** (açıkça):
  - Uzun bir sohbet açılıp **hemen** yazılırsa ilk yanıt hâlâ yavaş: 8K'da 2 sn sonra gönderimde 30 sn. Ön ısıtma yalnızca geçen süre kadar kazandırıyor.
  - Model 10 dakika boşta kalınca bellekten çıkıyor; geri yüklemek ve bağlamı yeniden işlemek 8K'da yaklaşık 36 sn.
  - Hiç görülmemiş uzun bağlamın işlenme hızı değişmedi: yaklaşık 3,5–4,5 sn / 1K token.
- **Asıl çözüm bağlamı küçük tutmak.** 6K'da başlayan özetleme, bir sohbetin aktif bağlamını normalde 2–6K'da tutuyor (soğuk 9–20 sn).
- **keep_alive değerlendirmesi:** 10 dakikada bırakıldı. Modeli (7,4–8 GB) sürekli bellekte tutmak, 24 GB'lık makinede açık uygulamalarla takası büyütüyor; Faz 2'de ölçüldü. Bunun yerine pencere öne gelince ve sohbet açılınca ön ısıtma yapılıyor.
- **Bekleyen G2-r1 değerlendirmesi:** Sıcak turlar gerçek istem birleştiriciyle 0,45–0,8 sn, 4,6K bağlamda tek bir istisnada 1,34 sn. Faz 2'deki G2-r1 eşiği 1,2 sn. Resmî yeniden ölçüm (CNV-01, 100 tur) Faz 4'e devrediliyor.

### 7.4 Bellek ve llama.cpp'nin RAM önbelleği (önemli bulgu)

**Bulgu:** Ollama 0.40.4'ün içindeki llama.cpp sunucusu önceki istemlerin durumunu **ana bellekte** saklayıp geri yüklüyor (`--cache-ram`). Ollama bu ayarı vermiyor, bu yüzden varsayılan 8 GB geçerliydi.

- Ölçüm sırasında önbellek **8.159 MiB / 31 istem** ile doldu.
- Çalıştırıcı sürecin bellek kullanımı (`phys_footprint`) **13,2 GB'a** çıktı; buna modelin kendisi dahil değil.

**Önlem:** `scripts/ollama-agent.sh` artık `LLAMA_ARG_CACHE_RAM=2048` ayarlıyor. Değiştirmek için `LAZIS_PROMPT_CACHE_MIB=<MiB> scripts/ollama-agent.sh install`.

**Sizin Mac'inizde uygulanan değişiklik:** LaunchAgent bu değerle yeniden kuruldu. Çalışıyor ve doğrulandı: sunucu ortamında `LLAMA_ARG_CACHE_RAM=2048`, çalıştırıcı günlüğünde "limits: 2048 MiB".

**Sonuç:**

| | 8 GB (varsayılan) | 2 GB (yeni) |
|---|---|---|
| Çalıştırıcı tepe bellek kullanımı | 13,2 GB | **6,4 GB** |
| Önbellek ıskası, sıcak ve ön ısıtma süreleri | aynı | aynı |
| Hemen geri dönüş | ~1 sn | ~1 sn |
| Başka işlerden sonra 8K sohbete dönüş (ön ısıtmasız) | 1,9 sn | 32,6 sn |

Bu son satırdaki değer kötümser: ölçüm aracının kendi sayım istekleri de önbelleği doldurdu. Ön ısıtmayla iki ayarda da 0,4 sn. **Bellek tasarrufu öncelikli tutuldu.**

**Model belleği:** `/api/ps` başta ve sonda 7,98 GB gösterdi. İkinci bir model hiç yüklenmedi.

### 7.5 Bağlam doğruluğu (özetlemeden sonra)

**Yöntem** (`p3_context_eval.py`, `tr_compaction_v1.json` v1.2):

- 5 sentetik diyalog. Tuzaklar: reddedilen LAZIS önerisi, değişen karar, belirsiz bilgi, aynı adlı iki kişi, düzeltilen saat.
- Sohbetler gerçek özetleyiciyle özetlendi. Sözlü kuyrukta yalnızca sohbet dışı kısa konuşmalar kaldı; yani bütün bilgiler özetten gelmek zorundaydı.
- 16 soru, bütün geçmiş verilerek de soruldu (karşılaştırma için).

| | Doğru yanıt | Özette korunan bilgi | Atılan madde |
|---|---|---|---|
| Bütün geçmiş | 16/16 | — | — |
| **Özetlenmiş** (son istemler, s3-v3/p3-v2) | **16/16** | **32/32** | 0 |
| Önceki istem sürümü (s3-v2, D1–D4) | 10/12 | 21/25 | 1 |

**Önceki sürümde ne oldu:** D1'in özeti ayrıntıları genelleştirdi ("taşınma planı"; Ankara, 3 Kasım, perşembe yok). Model de "bu bilgiyi paylaşmadınız" diye **yanlış** yanıt verdi.

**İki düzeltme yapıldı:**

1. Özet talimatı: tarih, gün, saat, yer, isim ve sayıları maddeye mutlaka yaz.
2. S0 kuralı: bir ayrıntı bağlamda yoksa, kullanıcının onu hiç söylemediğini iddia etme; hatırlamadığını söyle.

**Kontrol:** Düzeltmeden sonra eklenen, yani ayara katılmamış **D5 diyaloğu** da 4/4 geçti.

**Örneklem küçük:** 5 diyalog ve 16 soru. Sonuç bir yön gösterir, güvence vermez.

## 8. Güvenlik değerlendirmesi

Ayrıntılı tablo: SECURITY_MODEL §5.14. Özetle:

- **Değişmeyenler:** Yeni ağ izni ya da yeni dış servis yok. Sandbox yalnızca Ollama portuna izin veriyor. WebSocket hâlâ reddediliyor. API koruması yeni uç noktaları da kapsıyor. Bulut çıkarımı kapalı.
- **Şifreleme:** Sohbetler yalnızca SQLCipher'da. Testte bir işaret metni veritabanında, WAL'de, SHM'de ve yedeklerde düz metin olarak bulunamadı; arayüz tarayıcı depolamasına yazmıyor.
- **Günlükler ve hata iletileri:** Mesaj metni günlüklerde, denetim kaydında ve hata yanıtlarında yok. Bu hem sahte LLM'li testlerle hem de gerçek arka ucun günlük dosyasında doğrulandı.
- **Güvenli başlatma:** Faz 1'den beri anahtar Keychain'den alınıyor, migration güvenli uygulanıyor ve şifresiz moda hiç düşülmüyor. Bozuk sayfa artık doğru kodla (`database_corrupt`) raporlanıyor ve dosyaya dokunulmuyor.
- **FileVault:** Sizin Mac'inizde **kapalı**. Sohbet ekranında kalıcı uyarı var; belgelerde zorunluluk değil uyarı öngörüldüğü için sohbet engellenmiyor. Kişisel sohbetlere başlamadan önce açmanızı öneririm.

**Kalan riskler:**

- Silmeden önce alınmış şifreli yedekler, dönene kadar sohbeti içeriyor.
- SSD'de fiziksel silme garanti edilemiyor.
- Model belleğe yüklüyken Ollama süreci o anki sohbetin istemini bellekte tutuyor. Silinen sohbet önbellekteyse model boşaltılıyor.
- FileVault kapalıyken günlükler ve takas alanı şifresiz.
- Özetleyici model bir ayrıntıyı atlayabilir; orijinaller her zaman saklı.

## 9. Test sonuçları

### 9.1 `make check` (çıkış kodu 0)

| Takım | Sonuç |
|---|---|
| Python (birim, bütünleşik, güvenlik) | **302 geçti**, 3 canlı test seçilmedi (Faz 2'de 219) |
| Arayüz birim | **37 geçti** |
| Arayüz bütünleşik (gerçek arka uç) | **5 geçti**, 3 atlandı (canlı model gerektiriyor) |
| Rust birim | 19 geçti (1 Anahtar Zinciri testi isteğe bağlı) |
| Rust yaşam döngüsü (gerçek, sandbox'lı arka uç) | 7 geçti |

Statik denetimler de temiz: ruff, format, pyright strict (0 hata), import-linter (3/3), vue-tsc, rustfmt, clippy.

### 9.2 Gerçek modelle (isteğe bağlı)

| Komut | Sonuç | Kapsam |
|---|---|---|
| `LAZIS_TEST_MODEL=gemma4:12b-it-qat make test-ui-integration` | **8/8** | Kalıcı çok turlu sohbet ve önceki mesajı hatırlama; durdurma ve kısmi yanıt; yeniden adlandırma; silme; **arka uç süreci yeniden başlatılınca sohbetin geri gelmesi**; günlükte sohbet metni olmaması |
| `make test-ollama` | **3/3** | Faz 2 akışı, sandbox'lı arka uç |

### 9.3 Gerçek uygulama

- Sürüm derlemesi `LAZIS.app` (7,7 MiB) tek kullanımlık `p3verify` profiliyle açıldı.
- Arka uç sandbox içinde başladı; ilk kurulum penceresi ve arkasında sohbet ekranı göründü.
- macOS bu oturumda otomasyon (Erişilebilirlik) izni vermediği için arayüzde tıklayıp mesaj gönderemedim; izinleri de değiştirmedim. **Sizin elle denemeniz gerekiyor** (§12).
- Ekran görüntüsü, başka uygulamaların penceresini de içerdiği için kaydedilmedi ve silindi.
- Tek kullanımlık profil ve Anahtar Zinciri kaydı silindi; gerçek `default` profilinize dokunulmadı.

### 9.4 Bu fazda testlerin bulduğu ve düzeltilen sorunlar

1. Veritabanında derindeki bir sayfa bozuksa `internal_error` dönüyordu → `database_corrupt` (Faz 1 kodu).
2. Bir arka plan özetlemesi önbelleği değiştirdiği halde motor sohbeti "sıcak" sanıyordu; bir sonraki tur sıcak raporlandı ama 3 sn sürdü → her istek önbellek kaydını sıfırlıyor.
3. Token sınırında kesilen özet JSON'u bütün özetlemeyi başarısız yapıyordu → tamamlanmış maddeler kurtarılıyor.
4. Bağlam satırı olmayan sohbetlerde ön ısıtma ölçümü kaydedilmiyor ve özetleme başarısız oluyordu → satır oluşturuluyor.
5. Arka plan özetlemesi uzun sürünce kullanıcının her yeni mesajıyla iptal edilip baştan başlıyordu → parça parça kayıt, 5 sn bekleme.
6. Özetin ayrıntı kaybetmesi ve modelin "söylemediniz" demesi → istem düzeltmesi (§7.5).
7. LaunchAgent yeniden kurulurken eski görev kapanmadan yeni görev başlatılınca yükleme bazen başarısız oluyordu (yarış durumu) → bekleme ve yeniden deneme.

## 10. Bilinen eksikler

1. **Arayüzden ilk mesaj gönderimi** benim tarafımdan doğrulanamadı (§9.3).
2. **Yol haritasında P3 kapsamında olup yapılmayanlar:**
   - WebSocket hub (güvenlik gereği reddediliyor);
   - kalıcı iş kuyruğu, olay veri yolu ve DI konteyneri (gerek olmadı);
   - `lazis chat` CLI;
   - kayıt dışı mod (CNV-08);
   - araç çerçevesi (SEC-08);
   - dil kayması koruması;
   - sohbet arama (CNV-04);
   - gerçek modelle 300 turluk dayanıklılık testi (sahte modelle yapıldı);
   - G2-r1/G4'ün 100 turluk resmî yeniden ölçümü (CNV-01, AIE-08);
   - göreli tarih değerlendirmesi (CNV-06).
3. **Uzun sohbetlerde ilk mesaj gecikmesi:** Uzun bir sohbet açılıp hemen yazılırsa ilk yanıt hâlâ uzun sürüyor (8K'da yaklaşık 30 sn), model yeniden yüklendiyse de yaklaşık 36 sn. Ön ısıtma yalnızca geçen süre kadar kazandırıyor.
4. **İçe aktarılmış sohbetler:** Token sayımı olmayan sohbetlerin tahmini temkinli (+%64'e kadar). 12K'lık böyle bir sohbet önce özetleniyor (160 sn). Faz 3'te içe aktarma yok; Faz 8'de önemli olacak.
5. **Uzun özetleme süresi:** 12K'lık büyük bir birikimin arka planda özetlenmesi yaklaşık 3 dakika sürüyor ve bu sırada tek model yuvası meşgul. Kullanıcının turu özetlemeyi durdurup öne geçiyor.
6. **Bağlam değerlendirmesinin örneklemi küçük:** 5 diyalog, 16 soru. İstemler bu diyaloglara bakılarak iyileştirildi; ayara katılmayan tek diyalog D5.
7. **Başlık:** Sohbetin başlığı ilk mesajdan otomatik oluşuyor (ek model çağrısı yok). Yeniden adlandırma sohbeti listenin en üstüne taşıyor.
8. **Faz 2 geçici sohbet uç noktası** (`/chat/stream`) hâlâ var ama arayüzde kullanılmıyor; kayıt dışı mod için ileride değerlendirilebilir.
9. **`evals/` betikleri** `make check` kapsamında değil; Faz 2'den kalan stil uyarıları duruyor.

## 11. Faz 4'e devredilen riskler

| Risk | Neden | Öneri |
|---|---|---|
| Model yeniden yüklenince ya da uzun sohbet ilk açılınca uzun bekleme | Hiç görülmemiş bağlamın işlenmesi 1K token başına 3,5–4,5 sn; keep_alive 10 dk | Arayüzde "hazırlanıyor" ve bekleme süresini (gerçek token sayısına göre) göstermek; boşta özetleme eşiğini (6K) gerçek kullanımla ayarlamak; isterseniz keep_alive'ı artırmak (bellek bedeliyle) |
| Bellek baskısı (R6) | Model yaklaşık 8 GB + çalıştırıcı en fazla 6,4 GB (2 GB önbellekle); tipik uygulamalar açık | Faz 4 tanılama panelinde bellek göstergesi; ses modelleri gelmeden (P13) birlikte ölçüm |
| Özetin ayrıntı kaybetmesi | Model özeti; örneklem küçük | Değerlendirme setini büyütmek; "özeti göster/yeniden üret" arayüzü; P6'da kaynak gösteren hafıza |
| Tek model yuvası | Özetleme, ön ısıtma ve sohbet aynı yuvayı paylaşıyor | Faz 9'daki öğrenme işleriyle birlikte yeniden değerlendirmek (`OLLAMA_NUM_PARALLEL`, bellek bedeli) |
| FileVault kapalı | Sohbetler artık kalıcı | Açmanız önerilir |
| Gerçek kullanımda doğrulanmamış arayüz akışı | Otomasyon izni yok | Faz 4'teki Playwright E2E testleri ve sizin kullanıcı kabul oturumunuz |
| Yol haritasındaki ertelenen maddeler | §10.2 | Faz 4 planında kapsamın yeniden kararlaştırılması |

## 12. Uygulamayı nasıl açarsınız

1. **Ollama:** Ollama'nın çalıştığını kontrol edin. `scripts/ollama-agent.sh status` komutu `LLAMA_ARG_CACHE_RAM=2048` ve `OLLAMA_NO_CLOUD=1` göstermeli.
2. **Uygulama:** Geliştirme sürümü için `make dev` (izole `dev` profili). Sürüm derlemesi için `make build`, sonra `apps/desktop/src-tauri/target/release/bundle/macos/LAZIS.app`. Sürüm derlemesi gerçek `default` profilinizi kullanır.
3. **İlk açılış:** Kurtarma kodunu kaydedin. Ardından **Sohbet** sekmesinde "Yeni sohbet" ile bir mesaj yazıp `⌘↵` ile gönderin.
4. **Elle doğrulama listesi:**
   - iki sohbet oluşturun ve aralarında geçin;
   - birini yeniden adlandırın;
   - uzun bir yanıtı "Durdur" ile kesin;
   - uygulamayı kapatıp açın: sohbetler ve son sohbet geri gelmeli;
   - bir sohbeti onaylayarak silin.
5. **İsterseniz canlı test:** `LAZIS_TEST_MODEL=gemma4:12b-it-qat make test-ui-integration`.

**Geri alma:**

- Önbellek ayarı: `LAZIS_PROMPT_CACHE_MIB=8192 scripts/ollama-agent.sh install` (eski davranış) ya da `scripts/ollama-agent.sh uninstall`.
- Faz 3'ün kendisi: `git revert` ile geri alınabilir. Ancak v2 şemasına yükseltilmiş bir veritabanı eski sürümle açılmaz; v2'den önce alınan şifreli yedek `backups/` altında duruyor.
