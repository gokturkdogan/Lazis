# Faz 10D ilk sürüm: Kapsam ve kabul kriterleri

**Tarih:** 2026-11-05. **Dal:** `phase10d/first-version`, `main`'den (`12217c3`) açıldı. **Durum:** Sahibin kararıyla test edilmeden `main`'e alındı (2026-11-05). Kapsam kapatılmadı.

**Test durumu:** Sahibin talimatıyla **hiçbir test, lint, tip denetimi veya derleme çalıştırılmadı**, uygulama açılmadı. Aşağıdaki kriterler kodu okuyarak değerlendirildi.

## 1. Yol haritasındaki kapsam

Interview (atla, duraklat, devam et), Ayarlar'da "LAZIS'in seninle konuşma tarzı", tekrarları azaltma, günlük özetler, en az 40 kör eşleştirme (PER-02).

## 2. Başlangıç düzeltmeleri

| Düzeltme | Kabul kriteri |
|---|---|
| Eski ayar dosyası veya ortam değişkeni `auto_extract=true` dese bile otomatik öğrenme açılmaz | `load_settings` kullanıcı dosyasından ve ortamdan gelen değeri yok sayar |
| Manuel komut tespiti daralır | "Dosyayı kaydet", "Kaydet butonuna bastım" gibi cümleler kayıt başlatmaz; "Bunu kaydet", "Hafızana kaydet: …", "Şunu öğren: …" başlatır |

## 3. En küçük sürüm

| Özellik | Bu sürümde | Kabul kriteri |
|---|---|---|
| **İlk kurulum** | Sohbet ekranında isteğe bağlı 4 soru: hitap adı, siz/sen, yanıt uzunluğu, bir hedef veya ilgi alanı. Atla, sonra devam et, bir daha gösterme | Model çağrısı yok. Yalnızca kullanıcının yazdığı veya seçtiği kaydedilir, mevcut uçlarla. Duraklatınca aynı adımdan devam eder |
| **Konuşma tarzı ekranı** | Ayarlar'da 6 boyut: değer, kaynak (söylediniz, öğrenildi, varsayılan), değiştir, kaldır | Mevcut `/style` uçları. Yeni uç yok |
| **Günlük özet** | "Bugünün özetini çıkar" isteğinde veya düğmesiyle, o günkü kendi mesajlarından yanıt | Ek model çağrısı yok: o turun yanıtı yazar. Arka plan işi yok, hafızaya kayıt yok, zamanlama yok |
| **Dürüst bilgilendirme** | Ayarlar'da öğrenmenin yalnızca açık komutla olduğu, hatırlatma ve bildirim olmadığı | Sabit metin |

## 4. Bu sürüme girmeyenler

| Konu | Neden |
|---|---|
| Tekrarları azaltma ayarı | Modelle ölçüm gerektirir; test yasak |
| 40 kör eşleştirme (PER-02) | Model çıktısı üretir, oylamayı sahip yapar |
| Otomatik günlük özet, `episodes` | Arka plan modeli veya migration gerektirir |
| Model yönlendirmeli sohbet mülakatı | Sabit form daha ucuz ve güvenli |

**Bu yüzden Faz 10D'nin yol haritası kapsamının tamamı bitmiş sayılmaz.**

## 5. Uygulama durumu

Kod, bu dalda yazıldı. **Hiçbiri çalıştırılmadı.** Yeni testler yazıldı ama koşulmadı; kriterlerin karşılandığı iddia edilmiyor. Python ve Vue dosyalarının sözdizimi bile denetlenmedi. Mevcut kayıt cümleleri `told_to_remember` üzerinden yalnızca kodu okuyarak izlendi.

| Değişen dosya | Değişiklik |
|---|---|
| `core/src/lazis/config/loader.py` | Kullanıcı dosyası ve ortam `auto_extract` değeri yok sayılır |
| `core/src/lazis/memory/commands.py` | `told_to_remember`: açık talimat yoksa kayıt başlamaz, silme de başlamaz |
| `core/src/lazis/conversation/daily.py` | **Yeni.** İsteğin tespiti, bugünkü mesajlar, tek turluk not |
| `core/src/lazis/conversation/engine.py` | Günlük özet notu `_with_memory` içinde eklenir |
| `apps/desktop/ui/src/components/IntakePanel.vue` | **Yeni.** İlk kurulum formu |
| `apps/desktop/ui/src/components/StylePanel.vue` | **Yeni.** Konuşma tarzı ekranı |
| `apps/desktop/ui/src/components/AssistantThread.vue` | "Bugünün özeti" düğmesi |
| `apps/desktop/ui/src/views/AssistantView.vue`, `SettingsView.vue` | Panellerin yerleşimi, Ayarlar notları |
| `apps/desktop/ui/src/api/client.ts`, `i18n/tr.ts` | `/style` istemcisi, metinler |
| `apps/desktop/ui/tests/unit/fixtures.ts` | Sahte istemciye `/style` yöntemleri |
| `core/tests/unit/test_daily_summary.py`, `test_config.py`, `test_memory_requests.py` | Yeni testler, **çalıştırılmadı** |

Migration, yeni API ucu, yeni model çağrısı, arka plan işi yok. Gerçek profil, Ollama, checkpoint 8 ve modele dokunulmadı.

## 6. Açık riskler

**Doğrulama**
- Hiçbir kod çalışmadı; sözdizimi, tip veya çalışma hatası olabilir. `main`'in kendisi de hâlâ test edilmedi.

**Komut tespiti**
- Virgülsüz "Mehmet'in doğum günü 5 Mayıs unutma" artık kayıt başlatmaz. Otomatik öğrenme kapalı olduğu için bilgi kaydedilmez ve REL-004 açık olduğu için model yine de "kaydettim" diyebilir.
- Kural hâlâ kelimeye dayanır. "Ekranımı kaydet" gibi kişi eki taşıyan bir cümle kayıt isteği sayılabilir; ikinci aşamadaki model kararı yine çalışır.

**Günlük özet**
- Yalnızca kullanıcının bugünkü mesajlarına dayanır, LAZIS'in yanıtlarına değil. Bütün sohbetleri kapsar. En yeni mesajlar seçilir: en çok 3.000 karakter, satır başına 160.
- Özeti model yazar, gerçek Gemma ile denenmedi. Ekleme yapabilir veya belirsizi kesinleştirebilir (REL-001, REL-002, REL-003 açık). Yanıt korumaları özetten cümle çıkarabilir.
- İstem bağlam sınırını aşarsa not eklenmez, model mesajları görmeden yanıt verir ve uydurabilir.
- Özet hafızaya yazılmaz, ama her yanıt gibi sohbet geçmişinde kalır ve sonraki turlarda görünebilir.
- Unutma süzgeci, hafıza kaydına hiç dönüşmemiş cümleleri kapsamaz (bilinen sınır).
- İstem bu turda yaklaşık 1.000 token büyür (tahmin, ölçülmedi); sistem istemi değişmez.

**İlk kurulum ve ayarlar**
- Form durumu pencerenin yerel depolamasındadır, profilden bağımsızdır. Var olan kullanıcıya da bir kez görünür; depolama silinirse yeniden görünür.
- Bir kaydın politika nedeniyle reddedilmesi veya yalnızca onay kutusuna düşmesi "yapılamadı" olarak görünür.
- Daha önce öğrenilmiş tarz tercihleri "önceden öğrenildi" olarak görünür ve kaldırılabilir.

**Kapsam**
- Tekrarları azaltma, `episodes` ve otomatik özet, PER-02 kör eşleştirmeleri yapılmadı. REL-001, REL-002, REL-003, REL-004 ve uzun sohbet sıkıştırma gecikmeleri açıktır.
