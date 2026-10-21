# LAZIS — Faz 7.1 Raporu: Hafıza Kaydı Bildirimlerinin Doğruluğu

- **Tarih:** 2026-10-21
- **Durum:** Uygulandı; gerçek Gemma 4 12B ile değerlendirildi. **Kullanıcı kabul testi ve açık onay bekleniyor.** Faz 8'e başlanmadı.
- **Karar:** [ADR-0017](adr/0017-truthful-memory-claims.md) (gerçek sonuca bağlı, belirlenimci, akış içinde çalışan iddia denetimi)
- **Mimari (uygulanmış hâli):** [MEMORY_ARCHITECTURE.md](MEMORY_ARCHITECTURE.md) Bölüm P7.1
- **Commit'ler (yerel, push edilmedi):**
  - `059af3e`: iddia denetimi (`lazis.memory.claims`), motor entegrasyonu, tanılama alanları, testler
  - `f8b29e0`: uzun bir cümlenin kesildiği yerde iddianın ikiye bölünmesi engellendi
  - `55e48d8`: gerçek modelle bulunan kalıp: iyelik ekli "not / kayıt" biçimleri ("Notunuzu aldım")
  - `31e9de9`: gerçek modelle bulunan kalıp: cümlenin başındaki depolama sözcüğü ("Not defterime … ekledim")
  - bu raporla birlikte: değerlendirme araçları, ölçüm raporları, ADR ve belgeler

Bu raporda "Gemma" birincil model `gemma4:12b-it-qat` demektir. Bütün testler **sentetik kişilerle** (Kerem, Ahmet, Mehmet, Elif, Burak…), geçici ve şifreli veritabanlarında (rastgele anahtar) yapıldı. Gerçek profilinize (`default`), `dev` profiline ve Ollama ayarlarına dokunulmadı. Gerçek verileriniz değiştirilmedi.

**Özet.** LAZIS artık yalnızca o turda gerçekten yapılmış bir hafıza işlemini bildirebiliyor. Model "not aldım" yazsa bile kullanıcı bunu hiçbir anda görmüyor. Denetim modelin metnine değil, hafıza işleminin gerçek sonucuna bakıyor. İkinci bir model çağrısı yok, öğrenme sistemi değişmedi, veritabanı yapısı değişmedi. Gerçek modelle iki kalıp başta yakalanamadı ve kullanıcıya ulaştı: 1. turda "Notunuzu aldım", ek kontrolde "Not defterime … ekledim". İkisini de düzelttim. **Son kodla yapılan 3. turda** model 13 yanıtta izinsiz iddia yazdı; **hiçbiri kullanıcıya ulaşmadı**, ne son metinde ne akışın herhangi bir anında. Gösterilen ve saklanan metin 44 yanıtın hepsinde aynıydı.

---

## 1. Kök neden

Bilgi bildiren bir mesaj ("Ahmet'in kardeşi Mehmet.") Faz 6'dan beri **yanıttan sonra**, arka planda öğreniliyor (ADR-0015). Kullanıcıyı 5–8 saniye bekletmemek için bilinçli bir tasarım. Bu yüzden yanıt üretilirken bilgi henüz yazılmamış oluyor.

Model ise bilgi bildiren mesajlara alışkanlıkla "not ettim / not aldım / öğrendim" diye karşılık veriyor. Mesaja eklenen bildirim ("Bu mesajdaki bilgiler henüz hafızaya yazılmadı … kaydetmekten söz etme") bunu azaltıyor ama durdurmuyor:

| Ölçüm | Sonuç |
|---|---|
| Faz 6 oturumları | 22 yanıtta 1 erken iddia |
| Faz 7 ilişki oturumları | 9 bildirimde 5 |
| Bildirim metni iyileştirildikten sonra (10 bildirim, A/B) | 3/10 → 1/10, tam oturumlarda düzelme yok |
| **Bu fazda, denetim kapalı** (37 konuşma, 44 yanıt) | **10 yanıtta yanlış kayıt iddiası kullanıcıya ulaştı**; bunların 9'u bilgi bildiren 24 mesajdan |
| Bu fazda, denetim açık, ham model metni (1. tur) | 44 yanıtın 15'inde iddia vardı (bilgi bildiren 24 mesajın 13'ü) |

Sonuç: sorun modelin eğilimi; talimatla güvenilir biçimde çözülemiyor. Bu yüzden çözüm uygulama katmanında. Bir şeyin söylenmesine, gerçekten olup olmadığına bakarak izin veriliyor.

Ek gözlem: açık "bunu unutma" isteklerinde iddia doğruydu. İstek, yanıttan önce işleniyor (Faz 6) ve sonuç biliniyor. Yanlış iddialar yalnızca iki durumda çıktı: arka planda öğrenmenin beklendiği bildirimlerde ve başarısız açık isteklerde.

## 2. Değiştirilen dosyalar

| Dosya | Değişiklik |
|---|---|
| `core/src/lazis/memory/claims.py` (yeni, ~590 satır) | Durum eşlemesi (`state_for`), Türkçe iddia kuralları, en az değişiklikle yeniden ifade, akış denetimi (`ClaimGuard`) |
| `core/src/lazis/conversation/engine.py` | Model akışı denetimden geçiyor; gösterilen, kaydedilen, iptal veya hata durumunda saklanan metin denetimden çıkan metin. Son tur tanılamasına üç alan eklendi. |
| `core/src/lazis/api/schemas.py`, `apps/desktop/ui/src/api/openapi.json`, `schema.d.ts` | Tanılama alanları: `claim_state`, `claims_rewritten`, `first_shown_ms` |
| `core/tests/unit/test_memory_claims.py` (yeni) | 263 test (§5) |
| `core/tests/integration/test_claims_in_turns.py` (yeni) | 12 motor testi (gerçek motor, betikli model) |
| `evals/runners/p71_claims.py`, `p71_perf.py` (yeni) | Gerçek model değerlendirmesi ve performans ölçümü |
| `docs/adr/0017-truthful-memory-claims.md` (yeni), `MEMORY_ARCHITECTURE.md` (P7.1), `DEVELOPMENT_ROADMAP.md` | Belgeler |

**Değişmeyenler:** Gemma çıkarım politikası, çıkarım istemi, ilişki grafiği, öğrenme kuyruğu ve zamanlaması (arka planda, yanıttan sonra), hatırlama, açık isteklerin işlenişi, model bildirimleri, veritabanı şeması (migration yok).

## 3. Yaklaşım

**Durum gerçek işlemden geliyor.** Açık istekler (kaydet, unut, düzelt, onay) Faz 6'dan beri yanıttan önce çalışıyor; sonuçları (`saved`, `failed`, `confirm_needed`…) yanıt başlamadan belli. `state_for` bu sonucu bir duruma çeviriyor:

| Durum | Ne zaman | İzin verilen iddia |
|---|---|---|
| `save_succeeded` | kayıt yapıldı | "kaydettim", "not aldım" |
| `update_succeeded` | düzeltme / birleştirme yapıldı | "güncelledim", "kaydettim" |
| `delete_succeeded` | silme yapıldı | "sildim", "unuttum" |
| `save_pending`, `delete_pending` | kullanıcının onayı / seçimi bekleniyor | yok ("henüz kaydetmedim / silmedim") |
| `save_failed`, `update_failed`, `delete_failed` | hata, bulunamadı, ret, sır, güvenilmeyen model | yok ("kaydedemedim / güncelleyemedim / silmedim") |
| `auto_learning_pending` | istek yok, mesaj bilgi bildiriyor, öğrenme açık | yok ("anladım") |
| `no_memory_action` | geri kalan her şey | yok |

"Daha önce kaydettiğimiz bilgiye göre…", "hafızamdaki bilgiye göre…" gibi **mevcut kayda atıflara** yalnızca bu turda hatırlama gerçekten kayıt getirdiyse izin var. Yoksa ifade sohbete yöneltiliyor ("konuştuğumuz bilgiye göre").

**Kurallar belirlenimci.** Türkçe biçimbilgisine dayanan küçük bir kural kümesi, katlanmış metinde (Türkçe küçük harf ve aksansız) cümle cümle çalışıyor:

- **İddia sayılanlar:** birinci tekil veya çoğul şahısta tamamlanmış ya da söz verilmiş hafıza eylemi ("kaydettim", "not aldım", "notunuzu aldım", "kayda geçirdim", "hafızama ekledim", "listeme yazdım", "Not defterime X'i ekledim", "kaydedildi", "unutmayacağım", "aklımda tutacağım", "öğrendim"). Silme ve güncelleme fiilleri yalnızca bir hafıza sözcüğünün yanında ya da açık hafıza isteğinde iddia sayılıyor: bir metin düzenleme görevindeki "o cümleyi sildim" iddia değil.
- **İddia sayılmayanlar:**
  - olumsuz ve yetersizlik ("kaydetmedim", "kaydedemedim");
  - teklif ve yetenek ("kaydedebilirim", "kaydedeyim mi");
  - soru ("kaydettim mi?");
  - başkasının eylemi ("kaydettiniz", "Ahmet not etmiş");
  - tırnak içi;
  - sözü edilen ifade ("not aldım gibi", "kaydettim diye");
  - hiçbir şey kayıtlı olmadığını söylemek ("hafızamda bu konuda bilgi yok").

Kural tercih edildi çünkü denetimin öngörülebilir olması, ifade ifade test edilebilmesi, maliyetsiz olması ve denetlediği metin tarafından ikna edilememesi gerekiyor. İkinci bir LLM çağrısı hem gecikme ekler hem de kendisi yanılabilir.

**En az değişiklik.** Yalnızca iddia yeniden ifade ediliyor; içerik, kişilik ve hitap korunuyor:

| Model | Kullanıcının gördüğü |
|---|---|
| "Ahmet'in kardeşinin Mehmet olduğunu hafızama kaydettim efendim. Mehmet'in mesleğini de biliyor muyuz?" | "Ahmet'in kardeşinin Mehmet olduğunu anladım efendim. Mehmet'in mesleğini de biliyor muyuz?" |
| "Anladım ve not aldım." | "Anladım." (tekrar eden kısım düşüyor) |
| "Toplantının notunu aldım." | "Toplantının bilgisini anladım." (dilbilgisi korunuyor) |
| (kayıt başarısız) "Notunuzu aldım; Burak'ın düğünü haziranda olacak." | "Kaydedemedim; Burak'ın düğünü haziranda olacak." |
| (silme onay bekliyor) "Ahmet'i hafızamdan sildim." | "Ahmet'i hafızamdan henüz silmedim." |
| (kayıt başarılı) "Kaydettim efendim." | aynen |

Yeni bilgi eklenmiyor, kayıt başlatılmıyor, teknik açıklama eklenmiyor.

**Model bildirimi duruyor.** Faz 7'deki olumlu bildirim metni korunuyor; iddiaları seyrekleştiriyor, yani denetim daha az şey değiştiriyor. Güvence denetimde, ilk savunma bildirimde.

## 4. Akış güvenliği

`ClaimGuard`, model akışıyla diğer her şeyin arasında duruyor: arayüze giden parçalar, ara kayıtlar, son mesaj, iptal ve hata durumu.

- Metin geldiği gibi iletiliyor, **bir sözcük geriden**. Son sözcük, iddia başlatabilecek bir kökün başıysa ("n", "ka", "hafı") **iki sözcük geriden**: "Anladım ve n" + "ot aldım." akışında "ve" bile erken gösterilmiyor.
- İddia başlatabilecek ilk sözcükten (kayd-, kayıt, not, hafıza, aklım, unut-, hatırla-, öğren-, bilgilerime, listeme…; sil-, güncelle- yalnızca hafıza bağlamında) itibaren **o cümle bitene kadar** metin tutuluyor, sonra sınıflandırılıp gerekirse yeniden ifade ediliyor.
- Gösterilmiş metin **asla geri alınmıyor**; yeniden ifade yalnızca henüz gösterilmemiş kısma dokunuyor. Gösterilmiş bir bağlaç silmeyi bozacaksa iddia düşürülmek yerine yeniden ifade ediliyor ("Tamam efendim, bunu not aldım." → "Tamam efendim, bunu anladım.").
- Cümle sonu gelmezse en çok 240 karakter tutuluyor, sonra karar veriliyor. Kesme noktası tutulan penceredeki son riskli sözcüğün önüne alınıyor, böylece "…not" | "aldım" ayrılamıyor.
- Motor yalnızca `guard.released` metnini saklıyor ve gönderiyor. **Gösterilen = kaydedilen = (ileride) seslendirilecek metin.** İptal edilen bir yanıt da tam olarak gösterilen kısımla saklanıyor.

**Kanıt:**

- 54 yeniden ifade vakasının her birinde tek parça, karakter karakter, bütün iki parçalı bölünmeler ve 20 rastgele bölünme denendi; toplam 2.802 akış. Hiçbir ara çıktıda yasak ifade yok, son metin her bölünmede aynı.
- Görevdeki örnek bölünmelerin tamamı ayrıca test edildi: "Not"+" aldım.", "Hafızama"+" kaydettim.", "Kay"+"dettim.", "Bunu"+" unutmayacağım.", "N"+"ot al"+"dım.".
- Sıradan 30 yanıt için 1.162 akış: metin hiç değişmedi.
- Motor testlerinde altı farklı parça boyuyla tüm ara görüntüler kontrol edildi. Ayrıca kontrol edilenler: `delta` birleşimi = `done` mesajı = veritabanındaki metin; iptalde saklanan = gösterilen; loglarda içerik yok.
- Gerçek modelde her yanıtın her ara görüntüsü kaydedildi ve ayrı bir sözcük listesiyle tarandı (§6).

## 5. Yanlış pozitif testleri

`test_memory_claims.py`: 263 test, 0 hata.

| Grup | Sayı | Ne doğrulanıyor |
|---|---|---|
| (A) Yeni iddia, işlem yok → engellenir | 54 | tam beklenen çıktı, ifade ifade |
| Değiştirilmemesi gerekenler | 59 | teklifler, olasılıklar, olumsuzlar, sorular, başkasının eylemi, tırnak, sözü edilen ifade, sıradan metin ("not defteri", "Bunu not etmek isterseniz…") |
| (B) Mevcut kayda atıf | 5 × 2 | kayıt hatırlandıysa aynen, hatırlanmadıysa sohbete yöneltilmiş |
| (C) Alıntı → izin | (değiştirilmeyenlerde) | "Arkadaşım 'not aldım' dedi" |
| (D) Gelecekteki olasılık → izin | (değiştirilmeyenlerde) | "İsterseniz kaydedebilirim", "Kaydedeyim mi?" |
| (E) Açık başarı → korunur; başarısızlık ve bekleme | 29 | kaydet / sil / güncelle × başarılı / başarısız / bekliyor |
| Durum eşlemesi | 21 | her istek × sonuç kombinasyonu |
| Akış | 95 | §4 |

Kural dışı kalan biçimler, gerçek modelde kullanılan daha geniş bir sözcük listesiyle arandı (§6, §9).

## 6. Gerçek Gemma sonuçları

`evals/runners/p71_claims.py`. 37 sentetik konuşma ve 44 yanıt, dört geçici profilde. Her konuşma yeni bir oturumda başladı; erken iddialar en çok yeni oturumların ilk mesajlarında çıkıyordu. Kategoriler ve konuşma sayıları:

| Kategori | Konuşma |
|---|---|
| kişisel bilgi | 2 |
| aile | 4 |
| arkadaşlık | 4 |
| proje | 3 |
| tercih | 3 |
| açık kaydetme | 4 |
| belirsiz kaydetme ("bir kenara yaz", "aklında olsun", iki Ahmet) | 3 |
| başarısız kaydetme (komut modelinin cevabı bilerek bozuldu) | 3 |
| silme (biri onaylı) | 2 |
| düzeltme | 1 |
| hatırlama | 3 |
| alıntı, teklif, soru içeren bildirim, sohbet, sır | 5 |

Her yanıt için şunlar saklandı: ham model metni, akış sırasında görülen her ara metin, saklanan metin, gerçek işlem sonucu ve durum.

**Sayım yöntemi.** İddia sayımı denetimin kendi kurallarıyla değil, ondan **bağımsız ve daha geniş bir sözcük listesiyle** yapıldı ("not aldım", "kaydettim", "notunuzu aldım", "listeme ekledim", "unutmayacağım", "sildim"…), her biri durumun izin verip vermediğine göre. Bütün yanıtları ayrıca tek tek okudum.

| Koşu | Model ham metninde izinsiz iddia | Kullanıcıya ulaşan | Yalnızca ara görüntüde | Gösterilen ≠ saklanan |
|---|---|---|---|---|
| Denetim kapalı | 10 / 44 | **10** | — | 0 |
| Denetim açık, 1. tur | 15 / 44 | **1** | 0 | 0 |
| Denetim açık, 2. tur (`55e48d8`) | 10 / 44 | 0 | 0 | 0 |
| **Denetim açık, 3. tur (son kod, `31e9de9`)** | 13 / 44 | **0** | **0** | **0** |

**1. turdaki kaçak (#24).** Açık istek: "Lütfen şunu not al: Burak'ın düğünü haziranda." Komut adımı kaydedecek bir şey bulmadı (`nothing` → `save_failed`). Model buna rağmen "**Notunuzu aldım**; Burak'ın düğünü haziranda olacak." yazdı. Kurallar iyelik ekli "notunuzu" biçimini tanımıyordu; ilk sözcük listem de tanımıyordu. Bunu yanıtları tek tek okurken buldum. Kurallar genişletildi (iyelik ve belirtme ekli "not / kayıt", "kayda aldım", "bir kayıt oluşturdum", "bilgilerime / listeme / ajandama ekledim"), sözcük listesi de aynı biçimde genişletildi. Genişletilmiş listeyle 1. tur yeniden tarandı: başka kaçak yok. Kaçak sayısı 1 olarak raporlandı.

**2. tur.** Aynı 37 konuşma, `55e48d8` sonrası kodla. Model 10 yanıtta izinsiz iddia yazdı ("not ettim" 9, "not aldım" 1); 10'u da yeniden ifade edildi; kullanıcıya ulaşan 0. #24 bu kez "…haziran ayında olduğunu **kaydedemedim**." oldu; komut adımı yine boş döndüğü için bu doğru (§9-5).

**Ek kontrolde ikinci kaçak.** #29'daki iki Ahmet durumunu ayrıca denedim (aşağıda). Bir tekrarda kayıt "hangi Ahmet?" seçimini bekliyordu (`ambiguous` → `save_pending`), model ise "**Not defterime** Ahmet'in doğum gününün 5 Mayıs olduğunu **ekledim**." yazdı ve bu kullanıcıya ulaştı. Kurallar depolama sözcüğünü yalnızca fiilin hemen önündeyse tanıyordu. `31e9de9` ile düzelttim:

- Yönelme hâlindeki bir depolama sözcüğünden (hafızama, defterime, listeme…) sonra aynı cümlede gelen birinci şahıs kaydetme fiili artık iddia.
- "anladım" durumunda depolama sözcüğü düşüyor: "Ahmet'in doğum gününün 5 Mayıs olduğunu anladım."
- Bekleme ve hata durumunda korunuyor: "Not defterime … **henüz kaydetmedim**."

**3. tur (kabul ölçümü).** Aynı 37 konuşma, son kodla. Model 13 yanıtta izinsiz iddia yazdı; 13'ü de yeniden ifade edildi. Kullanıcıya ulaşan **0**, yalnızca ara görüntüde beliren **0**, gösterilen ile saklanan arasında fark **0**. Bağımsız sözcük listesiyle yeniden tarandı: 0. Bütün yanıtları tek tek okudum ve listenin dışında kalan bir iddia görmedim.

**Yeniden ifade örnekleri** (1. tur, ham → gösterilen):

- "Annenizin adının Süheyla olduğunu ve emekli bir öğretmen olduğunu **not ettim**." → "…olduğunu **anladım**."
- "Deniz'in köpeğinin adının Pamuk olduğunu **öğrendim** efendim." → "…olduğunu **anladım** efendim."
- "Ekip yapısını **not ettim**; Can backend tarafında…" → "Ekip yapısını **anladım**; Can backend tarafında…"
- (başarısız kayıt) "Dişçi randevunuzu salı günü saat üçte olarak **not aldım**. Ancak … kaydedemedim." → "…saat üçte olarak **kaydedemedim**. Ancak … kaydedemedim." (doğru ama tekrarlı; §9)

**Doğru bırakılanlar:**

- açık başarılar ("Kaydettim efendim.", "Elif'in doğum gününü 12 Mart olarak kaydettim efendim.");
- gerçekleşen silme ("Deniz hakkındaki bilgileri hafızamdan sildim.") ve düzeltme ("…bilgisini güncelledim");
- onay bekleyen silmede "onayınız gerekiyor";
- alıntı ("arkadaşım 'tamam, not aldım' dedi"), teklif ("İsterseniz yemek tariflerinizi hatırlayabilirim").

**Sıradan yanıtlar bozulmadı:** 1. turda 14 yanıt yeniden ifade edildi ve hepsinde yalnızca iddia fiili değişti. İddiasız 29 yanıt hiç değişmedi; kalan 1 yanıt yukarıdaki #24.

**İki Ahmet kontrolü** (5 tekrar: 2'si 2. turdan sonra, 3'ü son kodla). Önce "İki Ahmet tanıyorum: biri komşum Ahmet, diğeri iş arkadaşım Ahmet." yazıldı, yeni oturumda "Bunu unutma: Ahmet'in doğum günü 5 Mayıs." Sonuçlar:

- **İddialar:** 5 tekrarın 4'ünde kayıt yapıldı ve "kaydettim" doğruydu. Kalan 1 tekrardaki kaçak yukarıda anlatıldı ve düzeltildi.
- **Kimlik (Faz 7 bulgusu, bu fazın kapsamı dışında):** arka plan öğrenmesi 5 tekrarın 5'inde yalnızca **bir** Ahmet kaydetti (komşu). Bu yüzden 4 tekrarda açık istek, sormadan bu Ahmet'e yazıldı. Faz 7'nin "aynı adlı kişiler tahminle bağlanmaz" ilkesine aykırı bir sonuç. Sorun çıkarımda: tek mesajdaki iki aynı adlı kişiden biri öğrenilmiyor. Öğrenmeye ve grafiğe dokunmama koşulu nedeniyle düzeltmedim (§9-9).

## 7. Regresyon sonuçları

Hepsi bu fazın koduyla, gerçek Gemma ile.

| Değerlendirme | Faz 7 sonu | Faz 7.1 | Yorum |
|---|---|---|---|
| Faz 5 kişilik (111 yanıt, sert kontroller) | 108/111 | **108/111** | Aynı. Hatalar E5 (2) ve F4 (1); aynı kategorilerde önceki koşularda da görülen model değişkenliği. Hiçbir yanıtta iddia ifadesi yok. |
| Faz 5 kimlik soruları | 9/12 | **10/12** | |
| Faz 6 çıkarım altın seti | 40/41, 0 kritik | **40/41, 0 kritik** | Aynı |
| Faz 6 oturumları | 56/56 | **53/56** | Aşağıda |
| Faz 7 ilişki altın seti | 46/50, 0 kritik, 0 yanlış | **44/50, 0 kritik, 0 yanlış** | Faz 7'deki son koşular 44–47 arasında; çıkarım yolu değişmedi. |
| Faz 7 kabul oturumları | 53/54 (tek hata erken "not aldım") | **54/54** | Erken iddia kontrolü de geçti. |
| `make check` | yeşil | **yeşil** | Python 1052, UI 113 + 7, Rust 30 + 9 |

**Faz 6 oturumlarındaki 3 hata** tek adımda: "Ahmet artık yazılım geliştirmiyor, kendi restoranını açtı." Arka plan öğrenmesi eski kaydı geçmişe almak yerine "güncelledi"; meslek hafızada yazılımcı kaldı. Sonraki soruya yanıt yine doğruydu ("restoranını açtı"), çünkü sohbet bağlamında vardı.

Bu adım denetimden önce de kararsızdı: Faz 7 regresyon koşularının 6'sından 4'ünde (p7reg, p7reg4, p7reg5, p7reg6) en az bir kontrolü başarısızdı; 56/56 olan son koşu (p7reg7) bunlardan biri değildi. Denetim yalnızca yanıt metnini değiştiriyor (çıkarım istemi son yanıtı da görüyor; orada fark "not ettim" yerine "anladım"). Bu yüzden bunu Faz 7.1 kaynaklı bir gerileme olarak değil, Faz 6'dan kalan bir çıkarım kararsızlığı olarak görüyorum. Ayrı bir iş olarak ele alınmalı.

## 8. Performans

`evals/runners/p71_perf.py`. Aynı 10 mesajlık konuşma (bildirimler, sorular, açık kayıt, sıradan mesajlar; 1.000 sentetik kayıtla hafıza açık) denetim açık ve kapalı olarak, sırayla ikişer kez koşuldu; ilk mesaj (soğuk başlangıç) hariç 18'er tur.

| Ölçü (ortanca) | Denetim kapalı | Denetim açık |
|---|---|---|
| İlk model sözcüğü (TTFT) | 909 ms | 955 ms (model tarafı; denetim bunu etkilemez, fark çalışma değişkenliği) |
| Kullanıcının ilk metni görmesi | 909 ms | 1.099 ms |
| İlk metin gecikmesi (görülen − TTFT) | 0 ms | **139 ms** (en çok 251 ms) |
| Karakter başına gecikme (modelden ekrana) | 0,1 ms | **70 ms** (tutulan cümlelerde en çok 520 ms) |
| Sözcük başına süre (ilk sözcükten sonra) | 33,9 ms | 33,9 ms |
| Toplam yanıt süresi | 2,16 sn | 2,46 sn (yanıt uzunluğu farkı; sözcük başına süre aynı) |

- **Gecikme sözcük düzeyinde.** Bir sözcük geriden gelmek, bu modelin hızında (~30 sözcük/sn) 70 ms civarı. Yalnızca riskli bir kök içeren cümle, cümle sonuna kadar tutuluyor; en kötü durum yarım saniye. 5–10 saniyelik bekleme yok; öğrenme hâlâ arka planda.
- **İşlemci:** parça başına ortanca 34 µs, %95'lik dilim 269 µs; bir model sözcüğünün 30 ms'sine göre önemsiz. Tek bir 28 ms'lik ölçüm, büyük olasılıkla Python çöp toplayıcısı.
- **Bellek:** tek bir yanıtı denetlerken en çok 219 KiB (tracemalloc); tutulan metin en çok 25 karakter. Ölçüm sürecinin RSS'i 64 MiB.
- Açık kayıt turunda (~14 sn) süreyi komut modeli belirliyor; Faz 6'dan beri bilinen durum, denetimle ilgisi yok.

## 9. Sınırlamalar

1. **Kural dışı yeni bir kalıp kaçabilir.** Denetim, bilinen Türkçe biçimleri tanıyor. Bu fazda gerçek modelle iki kalıp böyle bulundu ("Notunuzu aldım", "Not defterime … ekledim"). Yeni bir kalıp çıkarsa ve bildirim onu önleyemezse kullanıcıya ulaşır. Yeni kalıp eklemek tek satır ve bir test. Değerlendirme listesi, kaçakları görmek için kurallardan geniş tutuldu.
2. **Üslup tekrarı.** "Anladım efendim. … olduğunu anladım." gibi aynı yanıtta iki "anladım" çıkabiliyor; başarısız kayıtta "kaydedemedim" iki kez geçebiliyor. Doğru ama biraz tekrarlı. Bilerek yalnızca iddiayı değiştirdim, cümleyi yeniden yazmadım.
3. **Hatırlatma vaadi.** Denetim kapalı koşuda model bir kez "toplantınızı hatırlatacağım" dedi. LAZIS'te henüz hatırlatıcı yok. Bu bir hafıza iddiası değil, yetenek vaadi; kapsam dışında bıraktım. İleride hatırlatıcılar gelene kadar benzer bir kural eklenebilir.
4. **Teknik bilgi sızıntısı.** Teklif yanıtında ("İstersem tariflerimi hatırlar mısın?") model üç turun üçünde de iç bildirimin adını ("'HAFIZA İŞLEMİ' bildirimi") kullanıcıya söyledi. Model metninden geliyor, denetim kaynaklı değil; kişilik tarafında ayrıca ele alınmalı.
5. **Açık kaydetmede "nothing".** "Lütfen şunu not al: Burak'ın düğünü haziranda." dört koşunun dördünde de komut adımında boş döndü. Kullanıcıya artık "kaydedemedim" deniyor, yani dürüst. Ama kaydın yapılmaması Faz 6'dan kalan bir çıkarım sorunu; Gemma politikası bu fazın kapsamı dışında olduğu için dokunmadım.
6. **Faz 6 oturum adımı** (§7): meslek değişikliğinin arka planda kararsız işlenmesi, ayrı iş.
7. **Ses.** Henüz ses yok. İleride ses hattı model akışını değil, denetimden çıkan metni okumalı (ADR-0017).
8. **240 karakterden uzun, noktalamasız ve iddiası uzak bir cümle:** "hafızama, [240 karakter] ekledim" gibi bir yapı teorik olarak kaçabilir. Gerçek yanıtlarda tutulan metin en çok 25 karakter oldu.
9. **Aynı mesajdaki iki aynı adlı kişi** (§6, Faz 7 bulgusu): yalnızca biri öğreniliyor; ardından gelen açık istek sormadan ona yazılıyor. Çıkarım tarafında ayrı bir düzeltme gerektiriyor; onayınızla ele alınabilir.

## 10. Kullanıcı kabul testi

Uygulamayı yeniden başlattıktan sonra (migration yok, veritabanı değişmiyor) şunları deneyebilirsiniz:

| # | Siz yazın | Beklenen |
|---|---|---|
| 1 | "Ahmet'in kardeşi Mehmet." | "Anladım / Anlaşıldı" türü bir yanıt; **"not aldım / kaydettim / unutmayacağım" yok**, akış sırasında bir an bile görünmüyor. |
| 2 | Birkaç saniye sonra Hafıza ekranı | Bilgi arka planda yazılmış: Ahmet ve kardeşi Mehmet. |
| 3 | "Bunu unutma: perşembe saat ikide toplantım var." | "Kaydettim" denebilir; Hafıza ekranında kayıt var. |
| 4 | "Ahmet hakkında bildiğin her şeyi unut." | Onay sorusu; "sildim" **denmiyor**. "Evet, sil." → ancak şimdi "sildim". |
| 4b | Ayrı mesajlarda "Kuzenim Mehmet öğretmen." ve "İş arkadaşım Mehmet muhasebeci."; Hafıza ekranında iki Mehmet göründükten sonra "Bunu unutma: Mehmet'in doğum günü 3 Nisan." | "Hangi Mehmet?" sorusu; "kaydettim / not aldım / ekledim" **denmiyor**. |
| 5 | "Kahvemi şekersiz içerim." ardından "Kahvemi nasıl içiyordum?" | İlki iddiasız; ikincisi doğru yanıt. |
| 6 | Tanılama ekranı, son tur | `claim_state` (ör. `auto_learning_pending`), `claims_rewritten`, `first_shown_ms` görünür. |
| 7 | Genel sohbet | Akış eskisi kadar akıcı; sözcükler bir sözcük geriden geliyor, fark edilmemeli. |

Onayınızı bekliyorum. Faz 8'e onayınız olmadan başlamayacağım.
