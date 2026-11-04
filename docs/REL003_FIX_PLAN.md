# LAZIS — REL-003: Düzeltme 3 ve 4 Uygulama Planı

- **Durum:** Düzeltme 3 uygulandı (`3f6f260`), kısa denemede yeni bir anlam sorunu görüldü: [REL003_FIX3_REPORT.md](REL003_FIX3_REPORT.md). İkinci denemede talimat hatası düzeldi ama `vejetaryen` kayboldu (aynı rapor, §8); kabul edilmedi. Sonraki değerlendirme ve öneri: [LATE_FACTS_AND_ARCHITECTURE_REVIEW.md](LATE_FACTS_AND_ARCHITECTURE_REVIEW.md). Tam test ve Düzeltme 4 başlamadı. **Her adım ayrı onay ister.** Özet davranışını değiştireceği için C'den önce yapılması önerilir (C'nin kabul taban çizgisi aksi hâlde sonradan geçersiz olur).
- **Sahibin kararı (2026-11-04):** Düzeltme 3 için C seçildi. `s3-v5` **deneysel**, Düzeltme 3 **tamamlanmadı**. Kodu `experiment/rel003-s3-v5` dalında; `main` `s3-v3` davranışına döndü: [S3_V5_ISOLATION_PLAN.md](S3_V5_ISOLATION_PLAN.md). Koruma tasarımı ve modelsiz değerlendirme: [SAFE_CARRY_DESIGN.md](SAFE_CARRY_DESIGN.md). Düzeltme 4 ürün koduna uygulanmadı.
- **Sıra:** Önce 3, ölçüm, sonra 4. Aynı anda uygulanmaz; yoksa etkileri ayrılamaz.

## Düzeltme 3: Bölüm sırası (mekanizma B)

**Sorun:** Model şema sırasını izliyor; sorular kişilerden, kısıtlamalardan ve talimatlardan önce yazılıyor. 1 200'de kesilen 16 çıktının 12'si talimatlara, 9'u kişilere, 8'i kısıtlamalara ulaşamadı.

**Değişiklik:**

- `SUMMARY_SCHEMA` özellik sırası: `goals, decisions, constraints, people, instructions, topics, open_questions, assistant_notes`.
- Modele giden düzenli metnin (`render`) sırası değişmez, bu yüzden yanıt istemi aynı kalır.
- `SUMMARY_PROMPT_VERSION` yükselir. Özet talimatı metni, çıktı sınırı, migration ve veritabanı değişmez.

**Beklenen etki:** Kesilme bu kez soruları ve notları keser. **Çözmediği:** A ve C. Çıktı sınırı yine dolabilir.

**Risk:** Düşük. Özet metni ve dolayısıyla bilgi koruma değişebilir, daha kötü de olabilir; bu yüzden ölçülmeden kabul edilmez.

**Doğrulama:**

1. Birim: şema sırası ve eski özetlerin okunması; özet isteği için altın test.
2. Gerçek Gemma, geçici süreç, sınır 8: çoklu sıkıştırma testi (yaklaşık 46 dakika).
3. Karşılaştırma: `summary.output`, `summary_audit`, 20 iddialık set, elle okuma.

**Kabul:**

- Korunan bilgi sürüm başına en az 62, 61, 59, 59, 56; yeni kayıp başka bilgiyle dengelenmez.
- Kesilen çıktılarda kişilere, kısıtlamalara ve talimatlara ulaşmada bugünkü değerlere göre belirgin artış.
- İddia setinde yeni kayıp yok; `kız kardeş` kaybı kalkmalı.
- Belirsizlik korunur; soru sonuçları 28/32'nin altına düşmez.

**Geri alma:** `git revert`. Eski özetler aynı biçimde okunur.

## Düzeltme 4: Kullanıcı maddelerini kodla taşımak (mekanizma A, ana neden)

**Sorun:** Önceki özet her seferinde modele yeniden yazdırılıyor. Madde 9 "koru" diye rica ediyor, kod denetlemiyor. Kelime kayıplarının 6'da 5'i çıktıda yer varken oldu.

**Değişiklik önerisi:** Doğrulamadan sonra, modeli yeniden çağırmadan:

1. `audit_rewrite` ile önceki sürümde olup yeni sürümde görünmeyen **kullanıcı kaynaklı** maddeleri bul.
2. Aşağıdakiler hariç, onları özgün metin, atıf, alıntı ve `certain` değeriyle aynen geri ekle.
   - Aynı alıntılı bir madde yeni sürümde varsa eklemez.
   - Yeni mesajlar onu değiştirdiyse (karar `current: false`, ya da aynı konu yeni değerle) eklemez. **Bu kuralın tasarımı işin en zor parçası.**
3. Üst sınır: Taşınan maddeler bölüm ve toplam token sınırına tabi. Sınır aşılırsa düşürülen madde sayılır ve görünür yapılır; sessiz düşürme yok.
4. Yeni ayar yok, migration yok, özet talimatı aynı.

**Çözdüğü:** A. **Çözmediği:** Hiç özete girmemiş bilgi; yanıtın özetteki bilgiyi kullanmaması (restoran); REL-001.

**Riskler:**

| Risk | Karşı önlem |
|---|---|
| Eski bilgi canlı kalır, değişen karar güncel görünür | Değiştirme kuralı, eski değer denetimi, elle okuma |
| Yeniden ifade edilen madde iki kez görünür (adayların bir kısmı yanlış alarm) | Alıntı eşleşmesi, yinelenen madde ölçümü |
| Özet büyür, sıkıştırma sıklaşır, bağlam dolar | Üst sınır, özet token ölçümü, yeniden yazım sayısı |
| Kod, modelin kasıtlı düzeltmesini geri alır | Kullanıcı düzeltme senaryoları |

**Doğrulama sırası:**

1. **Modelsiz deneme:** Saklı 50 ham çıktı üzerinde hangi maddelerin geri geleceğini, kaç yinelenme ve ne kadar büyüme olacağını hesapla. Sonuç kötüyse model koşusuna geçme.
2. Birim ve entegrasyon: değiştirme, belirsizlik, yinelenme, üst sınır, kalıcı kayıtlar.
3. Gerçek Gemma, geçici süreç, sınır 8: çoklu sıkıştırma testi.
4. Gerçek Gemma: 40 mesajlık, 60 s aralıklı konuşma; özet girdisi yanıtlara bağlı olduğundan tek koşudan hüküm çıkarılmaz, en az 2 koşu.

**Kabul:**

- Korunan bilgi taban çizgisinin üstünde, 5. sürümde belirgin artış. Sayısal hedefi modelsiz deneme belirler.
- Sıfır: yeni yanlış bilgi, eski değerin güncel görünmesi, belirsizliğin kesinleşmesi.
- Özet token artışı ve sıkıştırma sıklığı raporlanır ve onaylanır.
- Kalıcı mesaj ve özet kayıtları silinmez.

**Geri alma:** `git revert`; sonraki özet yine modelden üretilir, veri dönüşümü gerekmez.

## Bu planın dışında kalanlar

- **Mekanizma C:** Yanlış alıntı nedeniyle reddedilen doğru bilgi. Denetimi gevşetmek LAZIS'in sözlerini kullanıcıya mal etme riskini açar; önermiyorum. Önce sıklığı ölçülmeli (bu testte 1 madde).
- **Genel bilgi yanıtlarının yer kaplaması (düzeltme 5) ve özet talimatı:** 3 ve 4'ün sonucundan sonra değerlendirilir.
- **Çıktı sınırını yükseltmek:** A'yı çözmez, sıkıştırmayı uzatır.
- **REL-001, REL-002 hatırlama tarafı:** Ayrı işler.
