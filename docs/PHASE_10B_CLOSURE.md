# Faz 10B kapanış değerlendirmesi

**Tarih:** 2026-11-05. **Sonuç:** Sahip Faz 10B'yi temel teslimatlarıyla kapattı. REL-001, REL-002, REL-003 ve REL-004 **açık** kalıyor; çözülmüş sayılmaz.

## 1. Tamamlananlar

| Teslimat | Durum | Kanıt |
|---|---|---|
| Açık üslup tercihleri hemen geçerli, oturumlar arası kalıcı (PER-06) | Sahip kabul etti (2026-11-02) | Yeni oturum 30/30 (`a440a3d`) |
| Beş katman, ayrı ayrı açılıp kapanıyor (PER-07) | Sahip kabul etti | Anlık görüntü testleri |
| Karşıt istekler güvenliği ve çekirdeği değiştiremiyor (PER-12) | Sahip kabul etti | 42/42 (`c449a0d`) |
| Örtük öğrenme: ≥ 3 sinyal, ≥ 2 oturum, ±0,1 | Sahip kabul etti | Gerçek Gemma, `PHASE_10_REPORT` Bölüm B |
| DOI koruması | Sahip kabul etti | 48/48 ve 24 saldırı turu, elle okundu (`6531811`) |
| Stabilizasyon | Sahip kabul etti (2026-11-03) | `c366fbf`, `PHASE_10B_STABILIZATION_REPORT` |
| Gerçek serviste checkpoint 8 | Sahip onayıyla uygulandı (2026-11-04) | `CHECKPOINT_LIMIT_REPORT`, `56442c6` |

**Kabul edilmiş davranış korunuyor:**

- `main` üzerinde özet istemi `c366fbf` ile aynı (`s3-v3`).
- O tarihten beri çekirdek kodda değişen tek şey sayı kaydeden gözlemlenebilirlik (`2c2a6f4`).
- `s3-v5` ve `carry` yalnızca kendi deney dallarında.

## 2. Bu değerlendirmede kontrol edilenler

Yeni test koşulmadı. Faz 10B'nin gerçek Gemma sonuçları `a440a3d`, `c449a0d` ve `6531811` kodlarına aittir. Bugünkü `make check` geçişi `rel004/action-claims` dalındadır (3.953 çekirdek, 128 arayüz, 39 Rust testi).

## 3. Hataların sınıflandırması

**Ertelemek, çözmek değildir.** Kayıtlar `RELIABILITY_ISSUES.md` içinde açık kalıyor.

| Konu | Faz 10C'yi engelliyor mu? | Karar | Gerekçe |
|---|---|---|---|
| **REL-004** hatırlatma vaadi | İlk sürümü engellemiyor | **Açık, kabul testini geçmedi** | İlk sürümün cümlesi sabit. Model metni kullanan her genişlemeden önce ele alınmalı |
| **REL-001** belirsiz bilgi kesin kaydediliyor | **Yalnızca dolaylı** | Ertelendi; 10C ilk sürümünde sınırla aşıldı | Üçüncü kişiler ve planlar ilk sürümde kullanılmıyor (`PHASE_10C_FIRST_VERSION` §2). **Gerçek profile geçmeden önce çözülmesi kararı aynen geçerli** |
| **REL-002** kayıtlı bilgi geri çağrılamıyor | Hayır | Ertelendi | Sonucu yanlış söz değil, sessizlik |
| **REL-003** özet yeniden yazımında bilgi kaybı | Hayır | Ertelendi; "kabul edilmiş kalite" değil | İlk sürüm özet okumuyor. Üç okuma testi ve kaynak getirme başarısız; aynı yöntemler tekrar denenmeyecek |
| Sıkıştırma gecikmesi (en kötü 175 s) | Hayır, ama kullanıcıyı etkiliyor | Ayrı öncelik | İlk sürüm model çağrısı eklemiyor |
| Öğrenme çağrılarının maliyeti | Hayır | Ayrı öncelik | Aynı gerekçe |
| Yanıltıcı onay (a38), adı anmayan kesin yanıt (n1#2) | Hayır | Teknik borç | İlk sürümün metni modelden gelmiyor |
| DOI sınırları, hitap sınırları, `=== Menü ===` | Hayır | Teknik borç | Üründe bilinen küçük sınırlar |
| Dolu sistemde ve ekran uyanışında bellek riski | Hayır | Açık risk | Checkpoint 8 ile günlük kullanım testi hâlâ yok |
| `0008_adaptation` gerçek profilde değil | Hayır | Ayrı onay | Geçiş sırasında yedekle uygulanacak |

## 4. REL-004

Kabul testi 2026-11-05'te koştu ve **geçmedi**: 72 turda gösterilen 2 doğrulanmamış iddia ([REL004_ACCEPTANCE_REPORT.md](REL004_ACCEPTANCE_REPORT.md)). **Düzeltme `rel004/action-claims` dalında kalıyor, `main`'e alınmadı.** Sahibin kararıyla yeni kelime eklenmedi ve test yeniden koşulmadı. Faz 10C'nin ilk sürümü model metni kullanmadığı için bu hata onu engellemez; ama **hata açıktır**.

## 5. Sahip kararı

Sahip 2026-11-05'te Faz 10B'yi kapattı ve 10C ilk sürümünü onayladı. Bu, sıkıştırma gecikmesinin 10C'den önce çözülmesi yönündeki 2026-11-03 sırasını, ilk sürüm için değiştirir: "Faz 10C için sıkıştırma optimizasyonu geliştirme."

## 6. Faz 10C için zorunlu güvenlik sınırları

1. Gerçekleşmemiş işlem için söz yok (REL-004 kabul edilmiş olmalı).
2. Belirsiz bilgi kesin gerçek gibi anlatılmaz.
3. Unutulan, reddedilen, hassas ve çakışan bilgi kendiliğinden açılmaz (`memory/proactive.py`).
4. Ek model çağrısı veya kendiliğinden başlayan arka plan işi yok.
5. Migration yok, gerçek profil yok.
6. Oturum başına en çok bir takip; kapatılan konu bir daha açılmaz (PER-08).
