# Faz 10C ilk sürüm: Konuya dönme

**Tarih:** 2026-11-05. **Dal:** `phase10c/continuity`, `main`'den (`fc1716d`, `s3-v3`) açıldı. **Durum:** Geliştirildi, `make check` geçti. Sahip kabulü bekliyor. **`main`'e alınmadı, varsayılan olarak kapalı.**

## 1. Davranış

Hepsi sağlanırsa, yanıtın sonuna tek bir sabit cümle eklenir:

1. Kullanıcının son mesajından en az 6 saat geçmiş.
2. Yeni mesaj yalnızca selam ("Merhaba", "Günaydın", "Selam LAZIS", "Merhaba, nasılsın?").
3. Güvenilir bir konu var.

```
Merhaba efendim, size nasıl yardımcı olabilirim?

«Python öğrenmek» konusuna devam etmek ister misiniz?
```

Güvenilir konu yoksa normal selamlama kalır. Kullanıcı "evet" derse model soruyu geçmişte görür ve devam eder; "hayır" derse normal sohbet sürer.

Soruyu model yazmaz, bu yüzden uyduramaz, söz veremez, kesinleştiremez. Selamlama yanıtının kendisini ise model yazmaya devam eder.

## 2. Konu olabilecekler

**Yalnızca** kullanıcının kendi `goal` ve `interest` kayıtları, şu koşulların hepsiyle:

| Koşul | Dışarıda kalan |
|---|---|
| Konu kullanıcının kendisi hakkında | Üçüncü kişilerin kayıtları; akraba veya kayıtlı kişi adı geçen konular |
| Tür hedef veya ilgi | Plan, sağlık, para, doğum günü, karar ve diğerleri |
| Metinde sayı, ay, gün, para yok; en çok 5 kelime, 40 karakter | "20 bin TL biriktirmek", "Mayısta sınava girmek" |
| Kaynak cümle kayıtlı; belirsiz, geçmiş veya gelecek değil | "Galiba…", "Eskiden…", "Seneye…", kaynağı olmayan |
| Güven ≥ 0,8; kullanıcı söyledi, istedi, düzeltti veya onayladı | Çıkarım, içe aktarma, düşük güven |
| Hassasiyet `normal` | `personal`, `sensitive` |
| Son 30 gün içinde güncellendi; tarihli değil | Eski konular |
| `proactive.py` kapısı kabul ediyor | Unutulan, reddedilen, çakışan, etkin olmayan |
| Daha önce sunulmadı | Aynı konu hiçbir zaman ikinci kez sunulmaz |

Birden çok aday varsa önem, sonra yenilik; **yalnızca biri**.

## 3. Bilerek yapılmayanlar

Hatırlatma, bildirim, arka plan işi, model çağrısı, araştırma, kullanıcı adına işlem, özetten okuma, `open_loops`, `episodes`, ilişki özeti, migration. Yol haritasındaki Faz 10C'nin tamamı bu değildir.

## 4. Değişen dosyalar

| Dosya | Değişiklik |
|---|---|
| `core/src/lazis/conversation/continuity.py` | **Yeni.** Selam, zaman aralığı, konu seçimi, sabit cümle |
| `core/src/lazis/conversation/engine.py` | Turun sonunda okuma ve ekleme, günlükte yalnızca olay |
| `core/src/lazis/config/model.py` | `continuity_followups`, varsayılan `False` |
| `core/tests/integration/test_continuity.py` | **Yeni.** |

Açmak için: `LAZIS_CONVERSATION__CONTINUITY_FOLLOWUPS=true`. **Gerçek profilde açılmadı.**

Durum, mevcut `app_meta` tablosunda yalnızca kayıt kimlikleri olarak tutulur; metin yok, migration yok.

## 5. Testler

İstenen her durum gerçek veritabanı, gerçek motor ve betikli modelle sınandı:

| Durum | Test |
|---|---|
| 6 saat dolmamış / dolmuş | 5,9 saatte yok, 7 saatte var |
| Normal mesajla / selamla giriş | "Selam, bütçem ne kadardı?" araya girmez |
| Güvenilir konu var / yok | Var: tek soru. Yok: normal selam |
| Belirsiz, eski, tarihli, özel | 21 ayrı durum |
| Unutulmuş bilgi | Gerçek `forget_memories` ile; sunulduktan sonra unutulan da |
| Reddetme | Normal yanıt, konu geri gelmez |
| Aynı konunun tekrarı | Gelmez |
| Uygulamanın kapanıp açılması | Her tur yeni motor, aynı veritabanı; durum kalıcı |
| Akış, ekran, kayıt | 1, 3 ve 64 parçada aynı metin |
| Ek model çağrısı | İstek sayısı değişmez, sistem istemi değişmez |

`make check` bu dalda geçti (çıkış kodu 0): 3.355 çekirdek, 128 arayüz, 8 arayüz-arka uç, 39 Rust testi; ruff, pyright ve içe aktarma kuralları temiz.

## 6. Maliyet

| Ölçüt | Etki |
|---|---|
| Ek model çağrısı | **0** (testle doğrulandı) |
| Sistem istemi | Değişmez; önbelleği bozmaz (testle doğrulandı) |
| Sonraki turlarda istem | Geçmişe bir kısa cümle eklenir, yaklaşık 20–30 token (tahmin) |
| Normal mesajda gecikme | Yalnızca selam kontrolü, yaklaşık 4 mikrosaniye (ölçüldü) |
| Selamda gecikme | Yaklaşık 5 ms, 2.000 kayıtlı geçici veritabanında (ölçüldü); gerçek profilde ölçülmedi. İlk tokeni etkilemez, yanıt yazıldıktan sonra çalışır |
| Bellek | Ek yapı yok; en çok 500 kimlik |

## 7. Yanlış veya eski konu riski

Risk azaltıldı, **sıfır değil**:

- **Hedef vazgeçilmiş veya tamamlanmış olabilir.** "Python öğrendim" ayrı kayıt olarak yazılırsa eski hedef 30 gün içinde hâlâ sunulabilir. Soru biçimi yanlış bilgi vermez, en kötü sonuç gereksiz bir sorudur.
- **Hafıza kaydı hatalı olabilir.** REL-001 belirsizliği kaybediyor; kaynak cümleyi de kontrol ediyoruz, ama denetim belirli kelimelere dayanıyor ve başka bir söyleyiş geçebilir.
- **Hassas bir hedef `normal` kaydedilmişse** ("kilo vermek" gibi), tür ve kelime kontrolleri bunu yakalayamayabilir.
- **Seçim ve selam kuralları kelimeye dayanıyor.** "Selam, nasılsın" geçer; yazım hataları geçmez, sonuç yalnızca sorunun sorulmamasıdır.
- **Gemma'nın selamlama yanıtı REL-004'ten korunmuyor.** Bu dal, başarısız düzeltmeyi içermiyor. Eklenen cümle söz vermez, ama model özette hatırlatma cümlesi varken kendi yanıtında söz verebilir.

## 8. İlk sürüm kabul kriterleri

| Kriter | Durum |
|---|---|
| Davranışın 5 maddesi ve Karar 3'ün sınırları | Karşılandı (test) |
| Ek model çağrısı yok | Karşılandı (test) |
| İstenen 10 test durumu | Karşılandı |
| `make check` | Bu dalda geçti |
| Gerçek profil, servis, checkpoint, model, migration, push | Dokunulmadı |
| **Gerçek uygulamada ve gerçek Gemma ile kullanım** | **Yapılmadı.** Bu aşamada istenmedi |
| Sahibin kabulü | Bekliyor |

Yani kabul edilen test kapsamında kriterler karşılandı; ama ürün **gerçek kullanımda sınanmadı**.
