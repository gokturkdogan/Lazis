# Faz 10D ilk sürüm: Kapsam ve kabul kriterleri

**Tarih:** 2026-11-05. **Dal:** `phase10d/first-version`, `main`'den (`12217c3`) açıldı. **Durum:** Sahibin kararıyla test edilmeden `main`'e alındı (2026-11-05). **Kapsam 2026-11-06'da sahibin kararıyla kapatıldı** (bölüm 7); hatalar ve teknik borçlar açık.

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
| Tekrarları azaltmanın ölçümü | Modelle ölçüm gerektirir; test yasak. En küçük sürüm bölüm 7'de |
| 40 kör eşleştirme (PER-02) | **Teknik borç** (bölüm 7) |
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

## 7. Kapanış (2026-11-06)

Sahibin talimatı: kalan küçük işleri tamamla, kapsamı kapat, Faz 11'e sahibin talimatıyla geç. **Hiçbir test, `make check`, Gemma veya performans ölçümü çalıştırılmadı.** Aşağıdakiler kod okunarak değerlendirildi; hiçbiri test edilmiş sayılmaz.

### 7.1 Kapanışta eklenenler

| Konu | Değişiklik |
|---|---|
| Otomatik öğrenme | `load_settings` değeri başlatma seçenekleri dahil her katmandan sonra siler. Testler ve değerlendirmeler `MemorySection(auto_extract=True)` ile doğrudan kurar |
| İlk kurulum | Kayıt düğmeleri "Hafızaya kaydet" adını taşır; giriş metni yalnızca basılan yanıtın kaydedildiğini söyler |
| Konuşma tarzı | Açıklama, değişikliğin sonraki yanıtlardan itibaren geçerli olduğunu ve tarzın kendiliğinden öğrenilmediğini söyler |
| Günlük özet | Hatırlanan eski hafıza kayıtları özet turuna eklenmez. Mesajlar okunamazsa veya bağlama sığmazsa model özetin çıkarılamadığını söyler, uydurmaz |
| Tekrarları azaltma | `repetition.py`: kullanıcı yalnızca selam verirse önceki yanıtın açılış cümlesi, önceki yanıt soru ile bittiyse o soru, tekrarlanmaması için o turun notunda anılır. Model çağrısı yok, kayıt yok, sistem istemi değişmez |

### 7.2 Kod düzeyinde denetim (okuma)

| Gereksinim | Nerede |
|---|---|
| Otomatik öğrenme kapalı | `MemorySection.auto_extract = False`; `load_settings` her kaynaktan siler; `_learn_now` ve `learning.py` kapalıyken çıkar |
| Otomatik üslup öğrenme kapalı | `adaptation.observe(implicit=auto_extract)`: sinyal sayılmaz. Önceden öğrenilmiş değerler "önceden öğrenildi" olarak görünür, kaldırılabilir |
| Tarz değişikliği sonraki sohbetlerde | `set_style` veritabanına yazar ve tercihleri yeniler; her tur tercih hatırlatması ondan kurulur. Model çağrısı yok |
| İlk kurulumda kayıt yalnızca onayla | Hafıza kaydı yalnızca "Hafızaya kaydet" düğmeleriyle; atlamak hiçbir şeyi değiştirmez |
| Özet istekle, arka plan yok | Yalnızca `daily.asks` eşleşirse, o turun içinde |
| Aynı proaktif konu, reddedilen konu | `continuity`: bir konu en çok bir kez sunulur, reddedilince geri gelmez; özellik varsayılan olarak kapalı |

### 7.3 Teknik borçlar

- **PER-02 kapsamlı değerlendirmesi (en az 40 kör eşleştirme):** yapılmadı, teknik borç.
- **Otomatik `episodes` ve günlük özet üretimi:** bilerek geliştirilmedi.
- **Tekrar azaltmanın etkisi ölçülmedi.** Not yalnızca bir önceki yanıta bakar; daha eski tekrarları ve farklı söylenmiş aynı kalıpları görmez.
- **Bellek katmanı kapalı değerlendirme ayarında**, tekrar notu olan turlarda hatırlama okuması yine çalışır (atıf notunda olduğu gibi); üründe bellek katmanı açıktır.
- **Açık hatalar:** REL-001, REL-002, REL-003, REL-004 ve uzun sohbet sıkıştırma gecikmeleri.
- **Doğrulama:** Faz 10C, 10D ve kapanış kodu hiç çalıştırılmadı; `main` test edilmedi.

**Sonuç:** Faz 10D kapsam bakımından kapalı. Faz 11'e sahibin bir sonraki talimatıyla geçilecek.

