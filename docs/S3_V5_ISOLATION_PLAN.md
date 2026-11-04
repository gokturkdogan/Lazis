# LAZIS — `s3-v5` Deneysel Davranışını İzole Etme Planı

- **Durum:** Yalnızca plan. Dal oluşturulmadı, varsayılan davranış değişmedi. Prova, repoya dokunmadan geçici bir dosya kopyasında yapıldı.
- **Karar gereken:** Bu planı onaylıyor musunuz?

## Özet

`main` üzerinde tek bir ileri commit ile özet davranışı, son kabul edilen `s3-v3` sürümüne döner. Deneysel kod ve testleri ayrı dalda kalır. Geçmiş yeniden yazılmaz. Gözlemlenebilirlik, 20 iddialık set, checkpoint ayarı ve tüm test sonuçları `main`'de kalır.

## Bugünkü durum

| Konu | Durum |
|---|---|
| `main` | `d431691` |
| GitHub `main` | **Aynı: `d431691`.** Deneysel davranış GitHub'da da var. Geçmiş yeniden yazılmamalı |
| `c33cf36` sonrası değişen ürün dosyaları | Yalnızca `prompts.py` ve iki test dosyası |
| Bu değişikliği yapan commit'ler | `3f6f260` (bölüm sırası), `df4da97` (`instructions` kuralı) |

**Düzeltme:** Önceki raporlarımda "push yok" yazdım. Bu yanlış çıktı. Uzak dal kaydına göre `main` bugün birkaç kez GitHub'a gönderilmiş; son gönderim 23:06'da `d431691`. Bu oturumun komut geçmişinde `git push` yok, göndermeyi kimin yaptığını kayıttan söyleyemem. "Push yok" derken bunu doğrulamamıştım.

## Seçenekler

| | Ayrı dal (önerim) | Varsayılan kapalı seçenek |
|---|---|---|
| `main`'e eklenen ürün kodu | Yok | `prompts.py`, motor ve ayar kodu |
| Yanlışlıkla açılma riski | Yok | Var |
| Test yükü | Azalır | İki yol da test edilmeli |
| Deneye dönüş | Dala geçilir | Ayar açılır |

Tercihiniz olan ayrı dal aynı zamanda daha güvenli olan. Seçenek, kabul edilmemiş bir davranışı ürünün içinde tutar.

**`git revert` kullanılmamalı.** `3f6f260` ve `df4da97` değerlendirme araçlarını ve veri setini de içeriyor. Geri almak `short` ve `instructions` test setlerini de siler. Bunun yerine yalnızca üç dosya hedeflenir.

## Uygulama adımları (onaydan sonra)

1. Bu rapordaki yeni dosyalar için commit atılır, çünkü dal bunları da taşımalı. Onayınız gerekir.
2. Deneysel dal bugünkü noktadan açılır. Hiçbir commit taşınmaz:
   `git branch experiment/rel003-s3-v5`
3. `main`'de üç dosya kabul edilen sürüme döner:
   `git checkout c33cf36 -- core/src/lazis/conversation/prompts.py core/tests/unit/test_compaction.py core/tests/integration/test_conversation_engine.py`
4. `evals/runners/p10p_cycles_compare.py` içindeki `SUMMARY_OUTPUT_ORDER` içe aktarımı, aynı değerde yerel sabitle değiştirilir. Yoksa bu araç `main`'de açılmaz.
5. `REL003_FIX_PLAN.md` ve `RELIABILITY_ISSUES.md` güncellenir: Düzeltme 3 deneysel, tamamlanmadı, kodu şu dalda.
6. `make check` çalışır; geçerse tek commit atılır.

`reset`, `rebase` veya zorla gönderme yok. Ben push yapmam. **GitHub'daki `main`, bu commit siz gönderene kadar `s3-v5` üzerinde kalır.** Yeni dal da siz gönderene kadar yalnızca bu makinede durur.

## Sonuçta ne nerede kalır

| Öğe | `main` | Deneysel dal |
|---|---|---|
| Özet davranışı | `s3-v3` | `s3-v5` |
| `SUMMARY_OUTPUT_ORDER`, `instructions` kuralı ve 7 testi | Yok | Var |
| Gözlemlenebilirlik (`2c2a6f4`: `summary.output`, `summary.rewrite`, `summary_audit`) | Var | Var |
| Checkpoint sınırı 8 (`56442c6`) | Var | Var |
| 20 iddialık set, kısa test setleri, tüm eval araçları | Var | Var |
| Geçmiş test sonuçları ve raporlar | Var | Var |

## `main` hangi sürüme döner

`prompts.py`, `c33cf36` sürümüne döner. Bu dosya kabul edilen `c366fbf` ile birebir aynı. Yani özet istemi, şema sırası ve sürüm etiketi (`s3-v3`) kabul edilen haline geri gelir.

## Prova sonucu

Geçici kopyada 3 dosya döndürüldü ve araç düzeltildi. Repoda hiçbir şey değişmedi.

| Kontrol | Sonuç |
|---|---|
| `prompts.py` özeti | `c33cf36` ile aynı (`fd77cc5a…`) |
| Sürüm ve şema | `s3-v3`, `goals` önce, `SUMMARY_OUTPUT_ORDER` yok |
| Python testleri | **3 298 geçti** (bugün 3 305; fark, dalda kalan 7 test) |
| `ruff`, `ruff format`, `pyright`, `lint-imports` | Temiz; 0 hata; 3 sözleşme korundu |
| `make check` bütünü | **Koşulmadı.** Arayüz ve Rust testleri uygulama adımında çalışacak |

Provanın ilk koşusunda 4 test başarısız oldu. Neden, kopyada `apps/` klasörünün olmamasıydı; tam kopyada hepsi geçti.

## Veri uyumu

- `prompt_version` yalnızca etiket olarak yazılıyor; kod bu değere göre karar vermiyor. `s3-v4` veya `s3-v5` satırları varsa `s3-v3` onları okuyabilir, çünkü alanlar aynı.
- Bu nedenle migration ve veri düzeltmesi gerekmiyor.
- Gerçek profili incelemedim. Uygulama 17:12'den sonra bu koddan çalıştıysa orada `s3-v4` veya `s3-v5` etiketli özetler olabilir. Zararsızlar, silinmeleri gerekmiyor.

## Geri dönüş

Yeni commit `git revert` ile geri alınır veya deneysel dala geçilir. Veri kaybı olmaz.

## Yan kazanç

Sonradan gelen bilgi testinin eski sıra karşılaştırması yoktu. İzolasyondan sonra `main` bu karşılaştırmayı yapabilir. Şimdi çalıştırılmıyor; ayrı onay ister.
