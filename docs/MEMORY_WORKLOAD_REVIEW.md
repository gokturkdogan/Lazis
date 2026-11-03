# Hafıza iş yükü incelemesi

**Tarih:** 2026-11-03. **Durum:** yalnızca inceleme; hafıza kodu ve kuralları değişmedi. Kod kaynağı `core/src/lazis/conversation/engine.py`, `learning.py`, `scheduler.py`. Ölçümler `p10p_daily.py` kısa denemesinden (4 mesaj, sıkıştırma yok), yani **büyüklük fikri verir, taban çizgisi değildir.** Uzun konuşmadaki toplamları günlük senaryolar ölçecek.

## 1. Her mesajda ne çalışıyor

| Ne zaman | İşlem | Model çağrısı | Maliyet |
|---|---|---|---|
| Yanıttan önce | Mesajı ve kalıcı öğrenme işini aynı işlemde kaydetme | Yok | Milisaniye |
| Yanıttan önce | Açık hafıza isteği, düzeltme ve gizli bilgi denetimi (kurallarla) | Yok | Milisaniye |
| Yanıttan önce | Hatırlama: veritabanından en çok yaklaşık 200 tokenlik not | Yok | Veritabanı milisaniye; kod yorumu 200 token için yaklaşık +0,8 s bildiriyor |
| Yanıttan önce, yalnızca açık istekte | "Şunu not al" gibi isteği yürütme | **Var** (en çok 400–700 token) | Önceki ölçümler 8–16 s |
| Yanıt | Yanıt | **Var** | |
| Yanıttan hemen sonra | Ön ısıtma (1 token) | **Var** | Ölçülen 0,2–0,5 s |
| En az 6 s boşta | Öğrenme: konuşma + yaklaşık 2200 tokenlik talimat, en çok 3 mesaj | **Var, ayrı çağrı** | Ölçülen 8,4 s ve 24,8 s |
| Listede eksik görülürse | Odaklı yeniden okuma, iş başına en çok 2 | **Var** | Bu denemede görülmedi |
| Öğrenmeden sonra | Yeniden ön ısıtma | **Var** | Ölçülen 0,2–0,3 s |
| En az 5 s boşta, tahmin 6144 token üstü | Sıkıştırma, parça başına bir çağrı | **Var** | Baseline'da parça 34–65 s |
| Yazarken, en çok 30 s'de bir | Ön ısıtma (arayüz isteği); çalışan öğrenmeyi keser | **Var** | |

**Yanıtlar:**
- **Her mesajda ayrı öğrenme çağrısı var mı?** Her mesaj için kalıcı iş açılıyor ve **elenmeden** modele gidiyor, ancak en çok 3 mesaj bir çağrıda toplanıyor. Açık istek olarak yürütülen ve boş mesajlar hariç.
- **Öğrenme ayrı model mi?** Aynı Gemma, aynı tek yuva. Ayrı bir model yüklenmiyor, ek RAM istemiyor; maliyeti model zamanı.
- **Kısa denemede:** 6,9 s yanıt üretimine karşı 33,2 s öğrenme harcandı. Bu oranı uzun konuşmaya genellemiyorum.

## 2. Sıkıştırmayla çakışma

Model tek yuva olduğu için iki iş aynı anda çalışmıyor. Çakışma üç biçimde oluyor:

1. **Sıkıştırma önce gelir, öğrenme aç kalır.** Bakım döngüsü önce sıkıştırma gerekip gerekmediğine bakıyor. Gerekliyse ön ısıtma ve öğrenmeye hiç sıra gelmiyor. Bir kullanıcı yazmayı sürdürürse sıkıştırma bitmediği için öğrenme de bekliyor. Baseline'da 6 s aralıklı iki koşu, sonda 300 s'de bile bitmemiş iş bıraktı. Yeni söylenen bir bilginin bu sürede hafızaya geçmemesi kod akışından çıkan bir sonuçtur; `REL-002` ile ilgisi **kanıtlanmadı**.
2. **Önbellek kaybı.** Sıkıştırma konuşmanın önbelleğini tamamen, öğrenme kısmen bozuyor. Bu yüzden ertesi tur konuşmayı yeniden işliyor. Baseline'daki 27–53 s'lik beklemelerin kaynağı bu.
3. **Boşa giden iş.** Yeni bir mesaj çalışan işi kesiyor. Sıkıştırmada tamamlanan parçalar korunuyor, kesilen parça kayboluyor; öğrenme kesilirse işler kuyruğa dönüyor ve deneme hakkından sayılmıyor. Veri kaybı yok, ama model zamanı boşa gidiyor.

## 3. Azaltılabilecek noktalar (henüz değişiklik yok)

Her madde uygulanmadan önce ayrı onay ve gerçek Gemma ile öğrenme altın setleri ister.

| # | Öneri | Beklenen kazanç | Risk | Değerlendirme |
|---|---|---|---|---|
| 1 | **Öğrenecek şey olmayan mesajlarda model çağırmamak** (yalnızca genel soru, selamlama) | Yüksek. Ölçülen: yalnızca bir soru için 8,4 s, 0 kayıt. 40 mesajlık sette 28 mesaj soruydu | "Eşim vejetaryen, ne pişirsem?" gibi bilgi taşıyan soruyu kaçırmak | **En umut verici.** Kuşkuluysa çağırmaya devam eden tutucu kural şart |
| 2 | Birikmiş işte daha büyük toplu okuma | Orta | Toplu okumada liste ve kişi hataları | Ölçmeden karar verilemez |
| 3 | Uzun konuşmada öğrenmeyi konuşma öneki yerine bağımsız istemle çalıştırmak | Orta, önbellek bozulmasını azaltabilir | Zamir ve bağlam kaybı, kişilik ve kimlik hataları | Yüksek risk, en sona |
| 4 | Sıkıştırma bekliyorken öğrenmenin aç kalmasını sınırlamak | Hafıza gecikmesi azalır | Sıkıştırma gecikir | C planında birlikte ele alınmalı |

**Dokunulmaması gerekenler:**
- **Kalıcı iş kuyruğu:** kapanmada bilgi kaybını önlüyor.
- **Gizli bilgi denetimi, açık istek yolu ve çıktı korumaları:** model çağırmıyor ya da doğruluk için şart.
- **Ön ısıtma:** kısa denemede çağrı başına 0,2–0,5 s; ilk token kazancı bilinen bir iş. Uzun konuşmadaki maliyeti ölçülecek.
- **Öğrenme talimatını kısaltmak:** hafıza kuralı değişikliği sayılır, bu çalışmanın kapsamı dışında.
- **Sıkıştırma ile öğrenmeyi birleştirmek:** amaçları farklı. Özetin yeni bir hatası hafızaya da yansır. Önermiyorum.

## 4. Günlük testlerde ölçülecekler

`p10p_daily.py` her model çağrısını türüyle, süresiyle ve nasıl bittiğiyle kaydediyor. Böylece öğrenmenin toplam payı, boşa giden çağrılar ve öğrenecek şey olmayan mesajların maliyeti gerçek konuşmada görülecek. Yukarıdaki tablo bu ölçümle güncellenecek.
