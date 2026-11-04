# LAZIS — Kısa Bellek Teşhisi: Model Süreci Neden Büyüyor?

- **Tarih:** 2026-11-04, 10:44–11:24
- **Durum:** Kısa aşama tamam. Düzeltme uygulanmadı; sahibinin onayı bekleniyor.
- **Kod:** Ürün kodu değişmedi. Eklenen: `evals/runners/p10p_memdiag_learning.py`; `p10p_supervise.py`'ye isteğe bağlı durma kuralları (varsayılan davranış aynı). Gerçek profil, gerçek servis ayarları, model ve migration'a dokunulmadı. Öğrenme yalnızca B'nin geçici profilinde kapatıldı.
- **Ham veri:** `evals/reports/phase10/perf/memdiag-learning/`

## Kapanış (2026-11-04, sahibinin kararı)

**Checkpoint bellek teşhisi kapandı.** Bu, LAZIS'in bütün günlük kullanım testlerini geçtiği anlamına gelmez.

| Konu | Sonuç | Rapor |
|---|---|---|
| Neden | llama.cpp context checkpoint'leri: yaklaşık 320 MiB, sınır 32, en çok 10,2 GB; önbellek sınırının dışında | Bu rapor |
| Öğrenmenin payı | Hızlandırıcı, kök neden değil (tur başına 3'e karşı 2 checkpoint, bir kez 1,7 GB önbellek) | Bu rapor |
| Sınır 8 ve 4 | 8 seçildi: 5,5 GB'ta sabit; 4 her öğrenmeden sonra konuşmayı yeniden işliyor | [CHECKPOINT_LIMIT_REPORT.md](CHECKPOINT_LIMIT_REPORT.md) |
| Uzun konuşma | 59 dakika: uyarı yok, swap artışı yok, 5,3 GB; gecikme değişmedi | [LONG_CONVERSATION_LIMIT8_REPORT.md](LONG_CONVERSATION_LIMIT8_REPORT.md) |
| Özetlere etkisi | Yok: 50/50 bayt bayt aynı, aynı 4 soru geçemedi | [MULTI_CYCLE_LIMIT8_REPORT.md](MULTI_CYCLE_LIMIT8_REPORT.md) |

**Gerçek servis:** `LLAMA_ARG_CTX_CHECKPOINTS=8` 2026-11-04'te uygulandı (`scripts/ollama-agent.sh`).

- **Doğrulama:** Plist farkı tek satır; süreç ve llama-server ortamında 8; Ollama kaydında "of 8"; sentetik sağlık kontrolü hatasız; model boşaltıldı. Gerçek profil kullanılmadı.
- **Önceki yapılandırma:** `evals/reports/phase10/service/com.lazis.ollama.plist.before-checkpoint8`.
- **Geri alma:** `LAZIS_CTX_CHECKPOINTS=32 scripts/ollama-agent.sh install`. Ayarı tamamen kaldırmak için önceki plist'i geri kopyalayın:
  `launchctl bootout gui/$(id -u)/com.lazis.ollama; cp evals/reports/phase10/service/com.lazis.ollama.plist.before-checkpoint8 ~/Library/LaunchAgents/com.lazis.ollama.plist; launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.lazis.ollama.plist`

**Açık riskler (ölçülmedi veya çözülmedi):**

- **Çok dolu sistem:** Program belleği 16 GB'a yaklaşınca kısa uyarılar görüldü (en uzunu 48 s); 25 GB'lık ortam sınanmadı.
- **Uzun ekran uykusundan uyanma:** Hafif testteki kritik baskı 13 dakikalık kapanmadan sonra geldi. Sınır 8 ile yalnızca 17 saniyelik bir kapanma görüldü.
- **Yoğun kesinti:** 6 s ve 30 s aralıklar sınır 8 ile sınanmadı.
- **Sınır 8 ile hafif, orta ve yoğun günlük testler ile gerçek uygulama kullanımı:** Yapılmadı.
- **Sıkıştırma gecikmesi:** Değişmedi (en kötü 175 s); C'nin konusu.

## 1. Sonuç

**Büyümenin kaynağı Ollama'nın içindeki llama.cpp sunucusunun "context checkpoint" kopyalarıdır.** Her biri yaklaşık 320 MiB, varsayılan sınır 32, yani en çok yaklaşık 10,2 GB. 2048 MiB'lık önbellek sınırı bunları kapsamaz.

**Öğrenme kök neden değil, hızlandırıcıdır.** Öğrenme kapalıyken de bellek büyüdü, uyarı oluştu. Öğrenme tur başına bir checkpoint ve bir kez 1,7 GB önbellek ekliyor.

**Sızıntı işareti yok.** Artış sayılı ve üst sınırlı; her adım çalışma zamanının kendi kaydıyla eşleşiyor. Ancak model yüklü kaldığı sürece bellek geri verilmiyor.

## 2. Karşılaştırma

Aynı 10 mesaj, aynı sıra, aynı model ayarları, 45 s aralık, geçici Ollama süreci, aynı günlük uygulamalar.

| | A: Öğrenme açık | B: Öğrenme kapalı |
|---|---|---|
| Sonuç | 7. mesajda durdu: swap 4 GB artış sınırı | 10 mesaj ve 5 dakika boşta tamamlandı |
| Kritik baskı | Yok | Yok |
| Başlangıç swap / diğer programlar | 1,7 GB / 13,3 GB | 2,8 GB / 13,0 GB |
| **7. mesaj sonunda checkpoint** | **23** | **16** |
| **7. mesaj sonunda ayak izi** | **10,6 GB** | **6,5 GB** |
| Tur başına yeni checkpoint | 3 (yanıt, yeniden ısıtma, öğrenme) | 2 (yanıt, yeniden ısıtma) |
| Önbellek | 1,7 GB (bir kez) | 0 |
| İlk uyarı | 116 s | 296 s |
| Swap artışı | +4,1 GB, 5,5 dakikada | +1,3 GB, 12,5 dakikada |
| Swap hızı, tepe | 2,2 GB/dk | 0,8 GB/dk |
| Soğuk ilk token | 6,5 s | 6,6 s |
| Sıcak ilk token, medyan (aralık) | 0,95 s (0,5–1,9) | 0,74 s (0,6–1,0) |
| Yanıt modeli süresi | 25,3 s (7 yanıt) | 24,0 s (10 yanıt) |
| Öğrenme modeli süresi | 74,6 s (7 çağrı) | Yok |
| Yeniden ısıtma süresi | 13,2 s (15 çağrı) | 8,8 s (11 çağrı) |

A ile B'nin 7. mesajdaki 4,1 GB farkı hesapla açıklanıyor: 7 checkpoint (2,2 GB) + önbellek (1,7 GB).

## 3. Bellek kalemleri

B'nin sonundaki ölçüm (`vmmap`, `/api/ps`, çalışma zamanı kaydı):

| Kalem | Boyut | Not |
|---|---|---|
| Model | 8,0 GB (`size_vram`) | Sistem kablolu belleğinin çoğu. Sabit |
| Context checkpoint | 7,0 GB (22 × 320 MiB) | `vmmap`: Malloc Large 7,1 GB |
| Önbellek | B'de 0, A'da 1,7 GB | Sınırın altında, büyümüyor |
| Diğer çalışma belleği | yaklaşık 1,3 GB | Ayak izi eksi checkpoint |

**Çağrı bitince:** Ayak izi düşmedi. B'de 5 dakika boşta 8 318 MB'ta sabit kaldı. Yalnızca yeri değişti: checkpoint'ler sıkıştırıcıya ve swap'a taşındı (RAM'deki süreç belleği 9,1 → 6,7 GB). Model kapanınca geri verildiği bu testte görülmedi; süreç kapatılarak bitti.

**Boşta kablolu bellek:** Son çağrıdan yaklaşık 3 dakika 50 saniye sonra sistem kablolu belleği 10,1 → 2,7 GB düştü, baskı normale döndü. Hafif testte de görülmüştü. Düşüş, modelin kablolu payıyla (yaklaşık 8 GB) uyumlu; kaynağı incelenmedi.

**Eski ölçümlerle uyum:** 32 × 320 MiB + 1,7 GB + 1,3 GB ≈ 13,3 GB; boşaltılmış sistem koşusunun tepesi tam olarak 13,3 GB. Hafif testteki 11,3 GB ve 8 mesajda kritik baskı da aynı yönde. Çoklu sıkıştırmada (5,3 GB) tur sayısı azdı ve özet istemleri checkpoint'leri siliyordu. Bu eski koşuların çalışma zamanı kaydı alınmadığı için bu bir çıkarımdır.

**Uyarı eşiği:** Üç koşuda ilk uyarı, diğer programlar 11,7–13,3 GB iken ayak izi 5–6 GB civarındayken geldi. Az örnek.

## 4. Eski checkpoint'ler kullanılıyor mu?

Bu iki senaryodaki her istemde yeniden kullanılan konum, önceki istemlerin son yaklaşık 150 tokeni içindeydi. Yani görülen kullanım hep en yeni checkpoint'lerden. Bu, sınırın düşürülebileceğine işaret eder ama kanıtlamaz: konuşmalar kısaydı, sıkıştırma yoktu, kesilen istek yoktu.

## 5. Önerilen en düşük riskli düzeltme (onay bekliyor, uygulanmadı)

**`LLAMA_ARG_CTX_CHECKPOINTS` ile checkpoint sınırını düşürmek.** Ayar bu Ollama sürümünün sunucusunda var (`llama-server --help`, varsayılan 32) ve önbellek sınırıyla aynı yolla verilir.

| Sınır | En çok checkpoint belleği | Tepe tahmini (önbellek ve çalışma belleği dahil) |
|---|---|---|
| 32 (bugün) | 10,2 GB | 13,3 GB (ölçüldü) |
| 8 | 2,6 GB | yaklaşık 5,6 GB (hesap) |
| 4 | 1,3 GB | yaklaşık 4,3 GB (hesap) |

- **Neden en düşük risk:** Ürün kodu, hafıza, özet, model ve veri değişmez. Geri alması tek ayar.
- **Olası bedel:** Geri dönülecek checkpoint bulunamazsa konuşma yeniden işlenir, ilk token uzar. Ölçülmedi. Sıkıştırma ve kesintiden sonrası özellikle riskli.
- **Doğrulama sırası:**
  1. Geçici Ollama sürecinde, aynı 10 mesaj, öğrenme açık, önce sınır 8, sonra 4. Koşu başına yaklaşık 13 dakika, aynı durma kuralları.
  2. Sonuç iyiyse sıkıştırma ve kesinti içeren uzun konuşma, ayrı onayla.
  3. Gerçek servise (`scripts/ollama-agent.sh`) ancak ayrı onayla.

Değiştirilmemiş senaryoyu uzatmayı önermiyorum: A 5,5 dakikada güvenlik sınırına ulaştı, uzatmak aynı sonucu verir.

**Sonraki ölçüm:** sınır 8 ve 4 denendi, sonuç [CHECKPOINT_LIMIT_REPORT.md](CHECKPOINT_LIMIT_REPORT.md).

## 6. Seçici öğrenme değerlendirmesi (kod yok)

| | Hafif test | A |
|---|---|---|
| Öğrenme çağrısı | 8 | 7 |
| Hiçbir şey kaydetmeyen | 5 | 5 |
| Bunların süresi | 41 s (öğrenmenin %46'sı) | 41 s (%55) |

- **Model zamanı:** Mükemmel bir ön denetimle en çok bu kadar kazanılır. Bu, üst sınırdır.
- **Bellek:** Tur başına bir checkpoint azalır, ama asıl sınır çözülürse bu fark büyük ölçüde kaybolur. Bir kez alınan 1,7 GB önbellek, tek bir öğrenme çağrısı olsa bile oluşur. **Seçici öğrenme bellek düzeltmesi değil, zaman düzeltmesidir.**
- **Koşul:** Bilgi içeren sorular atlanmayacak, yanlış hafıza oluşmayacak, belirsizlik kesinleşmeyecek (sahibinin kararı). Kaçırma oranı henüz ölçülmedi. Öneri ayrıca sunulacak.

## 7. Sınırlar

- Senaryo başına tek koşu; A önce çalıştı.
- A 7. mesajda durduğu için 5 dakika boşta ölçümü ve son iki soru yalnızca B'de var.
- B, A'dan 1,1 GB fazla swap ile başladı. Kendi koyduğum 2,6 GB başlangıç koşulu tutmayınca 3,0 GB'a çıkardım (swap 15 dakikada 2,85 GB'a inmişti). Karşılaştırma bu yüzden swap artışına ve checkpoint sayısına dayanıyor.
- 45 s aralık hafif testin 2–5 dakikasından kısa; checkpoint artışı çağrı başına olduğundan etkisi az görünüyor, ama zaman etkisi sınanmadı.
- Codex da açıktı; önceki hafif testten daha dolu bir ortam.
- Checkpoint'lerin neden bu boyutta olduğu kod okunarak doğrulanmadı. Kayıtta `n_swa = 1024` var.
