# Faz 15C: Performans ve güvenilirlik (küçük, kanıtlanabilir düzeltmeler)

**Tarih:** 2026-11-07. **Dal:** `phase15/reliability`, `main`'den (`f1f437c`). **Durum:** Sahibin onayı bekleniyor; `main`'e alınmadı, push yapılmadı. Gemma, mikrofon ve uzun test kullanılmadı.

## 1. REL-004: Yapılmayan işlem için söz

**Yöntem:** Betikli modelle (gerçek model yok) dört yol denendi: model yanlış iddiayı söylüyor, ekranda ne kaldığına bakıldı.

| Yol | Modelin cümlesi | Ekranda | Sonuç |
|---|---|---|---|
| Sesli "Bunu hatırla: …" | "Kaydettim efendim" | "Anladım efendim" | Denetim çalışıyor |
| Sesli "Derya'yı unut." | "Derya'yı unuttum" | **Değişmeden gösterildi** | **Hata (Faz 13 sesli yolu)** |
| Yazılı bilgi cümlesi, öğrenme kapalı | "hafızama kaydettim" | "anladım" | Denetim çalışıyor |
| "Yarın toplantım var" | "size hatırlatacağım" | Değişmeden | Açık (REL-004'ün asıl kısmı) |

**Uygulanan düzeltme:** Sesli bir hafıza isteğinde gerçek sonuç ("hiçbir şey değişmedi") artık iddia denetimine bildiriliyor. Model "unuttum" ya da "kaydettim" dese de gösterilmiyor ve saklanmıyor. Karar modelin cümlesine değil, gerçek işlem sonucuna dayanıyor.

**Açık kalan:** Hatırlatma sözü. Hatırlatma özelliği olmadığı için kodun bakabileceği bir işlem sonucu yok. Bu durumda tek yol kelime kuralı, o da kabul testini geçemedi (2 gözden kaçan söz, 1 yanlış değişiklik). İstem kuralı da yetmiyor: kural her denemede vardı, bağlamda bir istek olduğunda 18 denemenin 12'sinde söz verildi.

## 2. REL-002: Kayıtlı bilginin hatırlanmaması

- **Deneme:** Başarısız iki çalışmanın son hafıza durumu (9 ve 6 etkin kayıt) test veritabanında yeniden kuruldu. Aynı soru, ürünün varsayılan hafıza bütçesiyle (440 karakter) hafıza getirme işlevine verildi.
- **Sonuç:** Mehmet'in seyahati iki durumda da modele giden blokta. Üç farklı söyleniş de bulundu. **Getirme işlevinde hata bulunamadı; kod değişmedi.**
- **Kalan açıklamalar (modelsiz ayırt edilemez):** Kayıt o turda henüz yoktu (eski arka plan öğrenmesi), ya da model bloğu kullanmadı veya özete güvendi (REL-003).
- **Not:** Otomatik öğrenme kapalı olduğundan böyle bir cümle artık hafıza kaydına dönüşmüyor; yalnızca sohbette ve özetinde kalıyor.

## 3. Uzun sohbet gecikmesi

**Darboğaz** (`COMPACTION_LATENCY_PROPOSAL.md`, ölçümlü): Sıkıştırma modelin önbelleğindeki konuşmayı kendi istemiyle değiştiriyor. Mesaj gelince sıkıştırma kesiliyor, ama konuşma öneki baştan işleniyor: 6.200 tokende 22,6–23,5 sn, 12.050 tokende 46,5–52,3 sn.

| Seçenek | Kazanç | Bu aşamada |
|---|---|---|
| A: Ollama RAM istem önbelleği 2 → 8 GB | Kesintiden sonra 0,8–6,3 sn (ölçüldü) | **Uygulanamaz:** Ollama servis ayarı; ayrı onayınız gerekir |
| C: Acil eşikte tek parça sınırı | Seyrek, sınırlı bekleme | Kod adayı; kabulü gerçek Gemma ile çok döngülü bilgi koruma testine bağlı |
| B: Sıkıştırmadan önce yeniden ısıtma | Tahminen ~2 sn | Kod adayı, küçük; aynı kabul koşulu |
| Eski mesajları düşürme, özeti öneke ekleme | Hızlı | **Reddedilmişti** (bilgi kaybı, kalite düşüşü) |

**Sonuç:** Model testi olmadan güvenle kabul edilebilecek bir kod değişikliği yok; bu yüzden değişiklik yapılmadı. Önerilen sıra: önce C, sonra B, kendi kabul testleriyle (M7 benzeri, sizin başlatacağınız). A için ayrı karar.

## 4. M2 ve M5

Faz 15B'deki hazırlık geçerli (`scripts/measure-resources.py`, `LAZIS_METRICS=1`, adımlar `PHASE_15B_SAFETY_METRICS.md` bölüm 4). Sınırlar aynı: boş bellek %20, swap +512 MB. Başlatılmadı.

## 5. Mikrofon kayıt doğrulaması

**Açık.** Faz 15B'deki testin kaydı yok; macOS izleyicisinin WebKit kullanımını gördüğü kanıtlanmadı.

Yeni deneme için:
1. Onayınızla geçici ön ısıtma ayarını ve izleyiciyi ben kurarım.
2. Siz `LAZIS_METRICS=1 make dev` ile açıp oturumu başlatırsınız ve pencereyi kapatırsınız.
3. Ben `metrics.mic` satırlarını ve izleyicinin zaman çizelgesini karşılaştırırım.

## 6. Testler

`make check` geçti (çıkış kodu 0): 3.497 çekirdek (1 yeni), 169 arayüz, 8 arayüz–arka uç, 49 Rust testi.

## 7. Açık teknik borçlar

- REL-001, REL-002, REL-003.
- REL-004'ün hatırlatma sözü kısmı.
- Sıkıştırma gecikmesi (A, B, C bekliyor).
- M2, M5, M7.
- Mikrofon kapanışının kayıtla doğrulanması; ekran kilidi algısı.
- Paketleme (15A P1-2).
