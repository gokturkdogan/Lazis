# Faz 11 ilk sürüm: Seçilen belgeyi okuma, özetleme ve soru-cevap

**Tarih:** 2026-11-06. **Dal:** `phase11/documents`, `main`'den (`8ef5b83`) açıldı. **Durum:** Sahibin onayı bekleniyor; `main`'e alınmadı.

## 1. Kapsam

Kullanıcının seçtiği tek bir TXT, PDF veya DOCX belgesi:

1. Bu bilgisayarda okunur ve metni çıkarılır.
2. "Özetle" ile Türkçe özetlenir.
3. Belge açıkken sorulan sorular yalnızca belgeden yanıtlanır, kaynak parça gösterilir (`[s. 3]`, `[parça 2]`).

## 2. Kabul kriterleri

| Kriter | Nasıl sağlandı | Durum |
|---|---|---|
| Belge yerel okunur | Arayüz dosyayı okur, baytlarını yerel arka uca gönderir; arka uç dosya yolu açmaz; ağ yok | Test edildi |
| TXT, PDF, DOCX | TXT: UTF-8, UTF-16 (BOM), Türkçe Windows (cp1254). PDF: metin katmanı, sayfa sayfa (pypdf). DOCX: paragraflar | Test edildi |
| Okunamayan belge açık nedenle reddedilir | Desteklenmeyen tür, 10 MB üstü, boş, ikili, kodlama, bozuk, parolalı, metin katmanı olmayan PDF; Türkçe mesaj | Test edildi |
| Özet ve soru-cevap ek model çağrısı yapmaz | O turun normal yanıtı; belge parçaları yalnızca o turun notuna girer | Test edildi (betikli model) |
| Belge talimat sayılmaz | Not, metnin bilgi olduğunu söyler; belge metni notu kapatamaz | Test edildi |
| Belge kişisel bilgiyle karışmaz | Belge turunda hafıza kayıtları nota eklenmez; belgeden hafıza kaydı oluşmaz | Test edildi |
| Uydurma yerine dürüstlük | Yanıt metinde yoksa söylemesi; uzun belgede tamamını görmediğini söylemesi; sığmazsa okuyamadığını söylemesi istenir | Not metni test edildi; **modelin uyması denenmedi** |
| Belge kalıcı saklanmaz | Yalnızca bu oturumda bellekte; kapatınca veya uygulama kapanınca silinir | Test edildi |
| Kullanıcının mesajı yalnızca yazdığıdır | Saklanan mesaj soru; belge metni saklanmaz | Test edildi |

## 3. Yol haritasından bilerek ayrılanlar

Yol haritasındaki P11 klasör tabanlı ve öğrenen bir sistem. Bu ilk sürüm seçilen tek belgeyle sınırlı:

| Yol haritası | Bu sürüm | Neden |
|---|---|---|
| Kaynak klasörleri, keşif, PathGuard, eşitleme, geri alma | Yok; tek dosya, kullanıcı seçer | İstenen kapsam |
| `documents.db`, `0009_sources` | Yok; bellekte | Migration ve kalıcı özel kopya olmadan |
| Belgeden öğrenme, belge iddiaları, güven sınırları | Yok; belgeden hiçbir şey öğrenilmez | En güvenli varsayılan (R25) |
| Ayrı, sınırlı ayrıştırıcı süreci | **Yok**: ayrıştırma arka uç sürecinde, sınırlarla | Arka ucun güvenlik kancası P13'e kadar alt süreci yasaklıyor; değiştirmek sahibin kararı |
| Markdown, HTML | Yok | İstenen biçimler TXT, PDF, DOCX |
| OCR | Yok | Yol haritasında da kapsam dışı |

**Ayrıştırma sınırları:** 10 MB, 500 sayfa, 1.000.000 karakter, PDF sayfaları arasında 20 saniye süre denetimi, DOCX'te en çok 30 MB açılmış XML, DTD içeren XML reddedilir. pypdf saf Python'dur; bozuk bir dosya bellek güvenliğini değil, yalnızca zamanı tehdit eder.

## 4. Seçim yöntemi

- Belge bağlama sığıyorsa tamamı (en çok yaklaşık 11.000 karakter, bağlamın yaklaşık üçte biri).
- Özet isteğinde uzun belgenin her yerinden eşit aralıklı parçalar.
- Soruda, soruyla en çok ortak kelime kökü taşıyan parçalar (BM25, Türkçe ekler için 5 harflik kök).

Kelimeye dayalı seçim, soruyla aynı kelimeleri kullanmayan bölümleri kaçırabilir. Bu yüzden model, belgenin tamamını görmediğini söylemeye yönlendirilir.

## 5. Değişen dosyalar

| Dosya | Değişiklik |
|---|---|
| `core/src/lazis/documents/` | **Yeni.** `extract.py` (metin çıkarma), `library.py` (oturum belgeleri, parçalar, seçim, not) |
| `core/src/lazis/api/documents.py` | **Yeni.** `GET/POST /documents`, `DELETE /documents/{id}` |
| `core/src/lazis/conversation/engine.py` | Turda belge kimliği; belge notu; belge turunda hafıza kaydı eklenmez |
| `core/src/lazis/api/{app_factory,conversations,schemas}.py` | Yönlendirici, 13,4 MB yükleme sınırı yalnızca bu uçta, `document_id` |
| `core/src/lazis/errors.py`, `i18n.py` | `document_*` hata kodları ve Türkçe iletileri |
| `core/pyproject.toml`, `uv.lock` | `pypdf` (BSD-3; teknoloji kararlarında seçilmişti). `lazis.documents` katmanı; pypdf'i yalnızca bu katman kullanabilir |
| `apps/desktop/ui/src/components/DocumentPanel.vue` | **Yeni.** Belge ekle, özetle, kapat |
| `apps/desktop/ui/src/{api/client.ts,stores/assistant.ts,views/AssistantView.vue,i18n/tr.ts}` | İstemci, açık belge, metinler |
| `apps/desktop/ui/src/api/{openapi.json,schema.d.ts}` | Yeniden üretildi |
| Testler | `test_documents_extract.py`, `test_documents_library.py`, `integration/test_documents.py`, `document_support.py`, `documents.spec.ts` |

## 6. Doğrulama

Yalnızca modelsiz testler çalıştırıldı (sahibin izniyle). `make check` bu dalda geçti (çıkış kodu 0): 3.423 çekirdek, 133 arayüz, 8 arayüz–arka uç, 39 Rust testi; ruff, biçim, pyright, vue-tsc, clippy ve 4 içe aktarma kuralı temiz. Yeni testler: 29 çekirdek (çıkarma, seçme, not, API, sohbet), 5 arayüz.

**Gerçek Gemma ile denenmedi.** Özetin ve yanıtların kalitesi, modelin "metinde yok" deme oranı ölçülmedi. Masaüstü penceresi açılıp panel görsel olarak denenmedi.

## 7. Açık riskler

- **Model uyumu bilinmiyor.** Gemma yine de ekleme yapabilir veya belge dışından bilgi katabilir. Kaynak gösterme ve "bilmiyorum" deme talimattır, denetlenmez.
- **Belge içine gömülü talimatlar.** Not, belgeyi talimat saymamasını söyler ve not sınırları korunur; ama model yine de uyabilir. Belge turunda araç veya işlem yoktur, en kötü sonuç yanlış bir yanıttır.
- **Uzun belgeler.** Özet belgenin bir kısmına dayanır; soru-cevap kelime örtüşmesine dayanır, eş anlamlıları bulmaz.
- **Arka uç süreci içinde ayrıştırma.** Kötü niyetli bir PDF, süre denetimi sayfa arasında olduğu için tek bir sayfada uzun süre işlemci harcayabilir; yanıt vermeye devam eden arka ucu kilitlemez, ama bir iş parçacığını meşgul eder.
- **Taranmış PDF, tablo düzeni, dipnot, üst ve alt bilgi** okunmaz veya düz metne dönüşür.
- **Belge geçmişte kalır:** Özet ve yanıtlar normal yanıt olarak sohbet geçmişinde saklanır ve sonraki turlarda veya sıkıştırma özetinde görünebilir. Belgenin kendisi saklanmaz.
- **Tek belge:** Arayüz aynı anda bir belgeyle konuşur; arka uç beşe kadar tutar.
- **Uygulama yeniden başlarsa** belge kaybolur; arayüz bunu `document_not_found` ile bildirir ve belgeyi bırakır.
