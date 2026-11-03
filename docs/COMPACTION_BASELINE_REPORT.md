# Bağlam sıkıştırma: dokuz koşuluk taban çizgisi ve günlük kullanım hedefleri

**Tarih:** 2026-11-03. **Makine:** MacBook Pro M4 Pro, 24 GB. **Önbellek:** 2048 MiB, geçici süreçte. **Durum:** ölçüm raporu. Sahibi 2026-11-03'te §8 senaryolarını, §9 hedeflerini ve C → B → A sırasını kabul etti; hedefler kabul kriteridir, doğrulanmış performans değildir. Optimizasyon yapılmadı.

Üç commit (`298ad54`, `75bec72`, `1d98f8a`) arasında ürün kodu ve koşu aracı aynı. Ham veri: `evals/reports/phase10/perf/`.

## 1. Koşullar

| Etiket | Koşular | Sistem |
|---|---|---|
| Dolu | 6 s ×3, 30 s ×2, 60 s ×2 | 25 gündür açık Mac, uygulamalar açık, başlangıç swap'ı 8,1–10,3 GB |
| Boş (30 s) | 1 | Yeniden başlatma sonrası, başlangıçta 6,1 GB ve swap 0. **Uygulamalar koşu sırasında yeniden açıldı:** 20:03'ten sonra 10 GB üstü, en çok 11,9 GB |
| Boş (60 s) | 1 | Uygulamalar kapalı, koşu boyunca 6,0–7,3 GB, başlangıç swap'ı 0,3 GB |

30 s'lik üçüncü koşunun ilk denemesi kritik bellek baskısında 17. turdan sonra durduruldu; sayılmıyor.

## 2. Gecikme ve bütünlük

| Aralık | Koşu | Medyan | En kötü | Herhangi 8 mesajda 15 s üstü | Sıkıştırma (s) |
|---|---|---|---|---|---|
| 6 s (hedef ≤6, ≤90) | Dolu 1 | 1,07 | 196,1 | 5 | 181 + 61 |
| | Dolu 2 | 5,94 | 194,1 | 5 | 179 + 63 |
| | Dolu 3 | 1,00 | 196,8 | 4 | 183 |
| 30 s (hedef ≤6, ≤45) | Dolu 1 | 14,6 | 180,2 | 8 | 166 + 64 |
| | Dolu 2 | 1,50 | 174,6 | 8 | 160 |
| | Boş | 3,78 | 179,2 | 8 | 165 + 63 |
| 60 s (hedef ≤2, ≤20) | Dolu 1 | 3,61 | 51,4 | 8 | 181 |
| | Dolu 2 | 1,41 | 192,7 | 8 | 51 + 178 |
| | Boş | 1,24 | 180,3 | 8 | 166 + 59 |

**Hiçbir aralıkta en kötü bekleme ve 15 s hedefi tutmadı; hedef "8 mesajda en çok 1".** Medyan hedefi koşuya göre değişiyor, çünkü sıkıştırma döneminin nereye düştüğüne bağlı.

**Dokuz koşunun hepsinde:** mesaj kaybı, sıra bozulması, kırpma, kapsanmayan geçmiş ve başarısız sıkıştırma yok; kaydedilen ve gösterilen metin aynı. Seslendirilecek metin bu araçla ölçülmedi.

## 3. Bellek

| | Dolu (7 koşu) | Boş (2 koşu) |
|---|---|---|
| Swap en yüksek | 15,0–19,3 GB | 7,2 ve 4,0 GB |
| Sıkıştırılmış bellek en yüksek | 7,0–7,7 GB | 8,1 ve 8,2 GB |
| Model süreci en yüksek (RSS) | 10,6–12,5 GB | 12,4 ve 14,5 GB |
| En yüksek baskı | 1 koşuda kritik, diğerlerinde uyarı | Uyarı |
| Uyarı süresi | Bu koşularda süre kaydı yok | 555 s ve 926 + 201 s |
| Yanıt verebilirlik | Bu koşularda kayıt yok | Program başlatma en çok 8,8 ms, dosya yazma en çok 1,9 ms |

- Durdurulan koşuyla birlikte dolu sistemde kritik baskı 8 denemenin 2'sinde görüldü. Tetikleyici süreç kaydı o koşularda yoktu, neden bilinmiyor.
- Model yüklüyken sisteme kilitli bellek 2 GB'tan 10–12 GB'a çıkıyor. Geriye macOS dahil her şey için yaklaşık 12 GB kalıyor.
- Boş sistemde bile sıkıştırılmış bellek 8 GB'a çıkıyor ve uyarı görülüyor. Nedeni açıklanmadı.
- Model süreci belleğinin boş sistemde daha yüksek görünmesi, belleğinin daha az sıkıştırılmasından kaynaklanıyor olabilir. Bu bir çıkarım, sızıntı olup olmadığı ayrıca sınanmadı.

## 4. Ana bulgu: 3 dakikalık bekleme bellekten değil, sıkıştırmadan geliyor

| | Dolu | Boş |
|---|---|---|
| Üç parçalı sıkıştırma | 160–183 s | 165–166 s |
| Tek parçalı sıkıştırma | 51–64 s | 59–63 s |
| En kötü ilk token (60 s dolu 1 hariç) | 175–197 s | 179–180 s |

Swap dörtte birine indi, ama bekleme değişmedi. Koşu başına tek ölçüm olduğundan bu bir kanıt değil, güçlü bir işarettir.

Her koşuda aynı akış görülüyor:
1. **1–19. turlar:** yaklaşık 1 s.
2. **Eşik:** bağlam 6144 tokene ulaşınca sıkıştırma başlıyor. Bir parça, yazma aralığından uzun sürdüğü için bitemiyor ve her yeni mesajda kesiliyor. Konuşma önbellekten çıktığı için ilk token 27 s'den 53 s'ye tırmanıyor.
3. **Kesin sınır (yaklaşık 13,5–14,8 bin token):** üç parça aynı turda özetleniyor, 175–197 s bekleniyor.
4. **Sonrası:** tek parça daha, ardından bazı koşularda yine yaklaşık 26 s'lik bekleme.

## 5. Dayanıklılık testi ile günlük kullanımın ayrımı

| Gözlem | Gerçek kullanımda da olur mu? | Kanıt |
|---|---|---|
| 3 dakikalık bekleme | **Evet**, dakikada bir yazılan uzun sohbetlerde | 60 s'lik gerçekçi aralıkta bile görüldü |
| 27–53 s'lik beklemeler | **Evet**, aynı koşullarda | Boş sistemde de aynı |
| Sıkıştırma dışında 1 s'lik ilk token | Evet, iyi haber | 9 koşunun hepsi |
| Art arda 40 uzun yanıt | Testin yükü, seyrek görülür | Senaryo gereği |
| 6 s aralıkta birikmiş hafıza işleri | Testin yükü, hızlı yazımda kısmen | 300 s'de bitmeyen iki koşu |
| Swap 15–19 GB, kritik baskı | **Belirsiz:** 25 gündür açık Mac ve 24,8 GB program belleği | Günlük koşulda ölçülmedi |
| Uzun aralıklar (3 dakika ve üstü) | Asıl günlük durum | **Ölçülmedi.** Sıkıştırmanın boşta bitmesi bekleniyor, bu turda kanıtlanmadı |
| Soğuk model yüklemesi | Evet, `keep_alive` 10 dakika | Bu koşularda ölçülmedi |

## 6. Gemma 12B bu Mac'te ne kadar sürdürülebilir

Ölçülenler:
- **Kilitli bellek yanında diğer programlar 6–7 GB:** kritik yok, swap en çok 4 GB.
- **11–12 GB (Codex, Teams, Slack açık):** o bölümde baskı normal, swap yaklaşık 1,5 GB, tek koşu.
- **24,8 GB (25 günlük sistem, uygulamalar açık):** swap 15–19 GB, kritik baskı 8 denemenin 2'sinde.

**Ölçülmeyen ara bölge, 12–25 GB, tam olarak hedeflediğiniz kullanım.** Şimdilik "uygulamalar açıkken çalışır" diyemem, "çalışamaz" da diyemem.

**Ses için uyarı:** P2 raporu STT için 1,5–2 GB, TTS için 2–4 GB tahmin ediyor. Bu bellek bütçesi bugünden düşünülmeli.

**Mevcut veriye göre alternatifler (model değiştirilmiyor):**
| Model | Bellek | Kalite verisi | Değerlendirme |
|---|---|---|---|
| Gemma 4 12B | 7,4 GB (16K bağlam, sade) | Kişilik 108/111, hafıza 40/41 | Mevcut |
| Qwen3.5-9B | 6,3 GB, yaklaşık 1,2 GB az | Kişilik 14/37, hafıza 31/41 (eski değerlendirmeler) | Kalite koşulunuzu karşılamıyor |

Yeni küçük modeller için dış araştırma yapmadım. Bu ancak hedefler kod iyileştirmesiyle tutmazsa gündeme gelmeli ve aynı altın setlerden geçmeli. Yaklaşık 1 GB'lık kazanç da 3 dakikalık beklemeyi çözmez, çünkü ana neden bellek değil.

## 7. Kalite bulguları

Bunlar taban çizgisi hatalarıdır, A/B/C'ye atfedilmez; ayrıntı [RELIABILITY_ISSUES.md](RELIABILITY_ISSUES.md).

- **REL-001:** belirsiz Mehmet bilgisi 9 koşunun 5'inde kesin yazıldı.
- **REL-002:** bilgi 9 koşunun 2'sinde ikinci özet yazımında kayboldu.
- **Özet sürümleri boyunca (kelime denetimi, 19 bilgi):** 7 koşuda her sürümde 19/19; 2 koşuda son sürümde 17/19. Kayıpların ikisi de 6 s aralıkta. Elle okuma yerine geçmez.
- **Sorular:** 90 sorunun 85'i geçti. Kalan 5: Mehmet 2 gerçek hata ve 1 olası denetleyici hatası, restoran sorusunda vejetaryenliğin atlanması 2.

## 8. Önerilen günlük kullanım senaryoları

Üçü de sabit mesaj ve zaman çizelgesiyle, aynı denetleyici altında, **uygulamalar açıkken** çalışır. Uygulamaları siz açarsınız; araç bellek toplamını kaydeder, kapatmaz. Kritik baskıda durur.

| | Hafif | Orta | Yoğun |
|---|---|---|---|
| Süre | 30 dakika | 1 saat | 2 saat |
| Mesaj | 10, çoğu kısa | 25, karışık uzunluk | 50, çoğu uzun |
| Aralık | 2–5 dakika | 30 s–5 dakika, 1–2 tane 15 dakika | 15–60 s dalgalar, araya 5–15 dakika |
| Açık uygulamalar | VS Code, Chrome | + Cursor, Slack, Teams | + Codex, çok sekmeli Chrome |
| Beklenen program belleği | yaklaşık 10–12 GB | yaklaşık 15–18 GB | 20 GB ve üstü |

Ek olarak ölçülür: soğuk model yüklemesi (15 dakikalık aralıktan sonra), LAZIS boştayken tutulan bellek, diğer uygulamaların yanıt verebilirliği.

## 9. Önerilen günlük kullanım hedefleri

Bunlar öneridir; ulaşılabilir olup olmadıkları henüz ölçülmedi. **Önceki dayanıklılık hedefleri aynen kalır, gevşetilmez.**

| | Hafif | Orta | Yoğun |
|---|---|---|---|
| Medyan ilk token | ≤1,5 s | ≤2 s | ≤3 s |
| %95 ilk token | ≤3 s | ≤6 s | ≤15 s |
| En kötü ilk token | ≤5 s | ≤15 s | ≤45 s |
| Soğuk yükleme sonrası ilk token | ≤10 s | ≤10 s | ≤10 s |
| Kritik bellek baskısı | 0 | 0 | 0 |
| Swap artışı | ≤2 GB | ≤4 GB | ≤6 GB |
| En uzun kesintisiz uyarı | ≤1 dakika | ≤5 dakika | ≤10 dakika |
| Tur içinde sıkıştırma beklemesi | Hiç | Hiç | ≤45 s, seyrek |

Her senaryoda değişmez koşullar: mesaj kaybı ve yanlış hafızada A/B/C kaynaklı yeni hata sıfır, kaydedilen, gösterilen ve seslendirilecek metin aynı, kişilik ve güvenlik testlerinde gerileme yok.

## 10. Önerilen sonraki adım planı

Her adım ayrı onay ister.

1. **Önce mevcut kodda ölçüm:** üç günlük senaryo ve çoklu sıkıştırma kalite testi. Toplam yaklaşık 4,5 saat, makine çoğunlukla kullanımda kalabilir ama bu süre yük bindirir.
2. **Önce C, sonra B, en son A.** Sırayı değiştirmeyi öneriyorum, çünkü C (acil eşik, tek parça sınırı) ek RAM istemez ve 3 dakikalık beklemeyi doğrudan hedefler. B de RAM istemez. A ise günlük kullanım hedefinizle çelişen tek seçenek.
3. **A yalnızca gerekirse:** C ve B'den sonra 27–53 s'lik önbellek kaybı beklemeleri hedefi tutmuyorsa, ayrı onayla, önce yalnızca 4096 MiB. 6144 ve 8192 MiB bu Mac için plan dışı kalır.
4. **Birleşik doğrulama:** dayanıklılık, günlük senaryolar, çoklu sıkıştırma ve PER-06/PER-12, DOI, kimlik, hafıza, çıktı koruma testleri.
5. **Model alternatifleri:** ancak 4. adımda bellek hedefleri tutmazsa araştırılır.
6. **REL-001 ve REL-002:** gerçek profile geçmeden önce ayrı çalışma.

**Dürüst sınır:** C ve B'nin birleşik etkisi tahmindir. Özellikle yoğun senaryoda 15 s hedefinin önbellek büyütmeden tutup tutmayacağını bilmiyorum.
