# LAZIS — Checkpoint Sınırı 8 ve 4 Karşılaştırması

- **Tarih:** 2026-11-04, 11:37–12:07
- **Durum:** Kısa test tamam. O tarihte gerçek servise uygulanmamıştı; sonraki durum için [MEMORY_DIAGNOSIS_REPORT.md](MEMORY_DIAGNOSIS_REPORT.md), Kapanış.
- **Ortam:** Yalnızca geçici Ollama süreci (port 11499), ayar yalnızca o sürecin ortamında verildi. Gerçek servis ayarları aynı kaldı (`LLAMA_ARG_CACHE_RAM=2048`, checkpoint ayarı yok). Gerçek profil, model, hafıza kuralları ve ürün kodu değişmedi.
- **Ham veri:** `evals/reports/phase10/perf/memdiag-learning/` (`cp8_*`, `cp4_*`, kısa araç denemesi `cp-smoke_*`).

## 1. Sonuç

**Öneri: sınır 8.** İki sınır da kısa testte bellek sorununu kaldırdı. Ama sınır 4, her öğrenmeden sonra konuşmanın neredeyse tamamını yeniden işletiyor; bu maliyet konuşma uzadıkça büyür. Sınır 8'de bu yok.

**Bu sonuç uzun konuşmayı ve sıkıştırmayı kanıtlamaz.** Bu testlerde sıkıştırma olmadı, ekran uykudan uyanmadı.

## 2. Karşılaştırma

Aynı 10 mesaj, öğrenme açık, 45 s aralık, ardından 5 dakika boşta. 32 satırı önceki A koşusudur, **tekrarlanmadı** ve 7. mesajda güvenlik sınırında durmuştu.

| | Sınır 32 (A, önceki) | **Sınır 8** | **Sınır 4** |
|---|---|---|---|
| Tamamlanma | 7/10, swap sınırında durdu | **10/10** | **10/10** |
| Başlangıç swap / diğer programlar | 1,7 / 13,3 GB | 2,7 / 12,6 GB | 2,6 / 12,7 GB |
| Kritik baskı | Yok | Yok | Yok |
| Uyarı süresi | 217 s, sürüyordu | **0** | **0** |
| Swap artışı | +4,1 GB | **0** | **0** |
| Sıkıştırılmış bellek, tepe | 8,0 GB | 3,3 GB | 1,2 GB |
| Model süreci ayak izi, tepe | 10,6 GB ve büyüyordu | **5,5 GB, sabit** | **4,2 GB** |
| Canlı checkpoint, tepe | 23 ve büyüyordu | 7 (2,2 GB) | 3 (1,0 GB) |
| Önbellek | 1,7 GB | 1,7 GB | 1,1 GB |
| Soğuk ilk token | 6,5 s | 6,5 s | 6,4 s |
| Sıcak ilk token, medyan | 0,95 s | 0,92 s | 0,88 s |
| Sıcak ilk token, en kötü | 1,9 s | 1,2 s | 1,2 s |
| Baştan işlenen istem | Sayılmadı | 0 | 0 |
| İşlenen istem tokeni | Sayılmadı | 26 293 | **41 747 (+%59)** |
| İstem işleme süresi | Sayılmadı | 100 s | **153 s (+%53)** |
| Yeniden ısıtma toplamı (21 çağrı) | Karşılaştırılamaz | 14,7 s | **68,3 s** |
| Yanıt toplamı (10 çağrı) | Karşılaştırılamaz | 29,1 s | 24,7 s |
| Öğrenme toplamı (10 çağrı) | Karşılaştırılamaz | 106,6 s | 106,1 s |
| Çıktı hızı | Sayılmadı | 34,4 ms/token | 34,4 ms/token |
| Program başlatma, en kötü | 4,9 ms | 2,8 ms | 2,8 ms |

**Bellek tahminleri tuttu:** önceki raporda hesapla 8 için yaklaşık 5,6 GB, 4 için yaklaşık 4,3 GB demiştim; ölçülen 5,5 ve 4,2 GB.

**Sınırın uygulandığının kanıtı:** Ollama'nın kendi kaydı "created context checkpoint N of 8" ve "of 4" yazıyor. Görülen en yüksek N sırasıyla 7 ve 3.

## 3. Sınır 4'ün gizli bedeli

Öğrenmeden sonraki yeniden ısıtmada, sınır 8 konuşmanın sonuna yakın bir checkpoint'ten dönebiliyor. Sınır 4'te o checkpoint kalmıyor ve 212. tokene kadar geri dönülüyor:

| Öğrenme sonrası yeniden ısıtma | Sınır 8 | Sınır 4 |
|---|---|---|
| Geri dönülen konum (10 kez) | 1 232–2 302, sonlara yakın | **Her seferinde 212** |
| İşlenen token | 25–334 | **1 138 → 2 069** |
| Süre | 0,2–1,3 s | **4,1 → 7,3 s, her turda artıyor** |

Bu bekleme kullanıcıya bu testte yansımadı, çünkü sonraki mesaj 45 s sonra geldi. Ama süre konuşmayla büyüyor. Ölçülen 3,7 ms/token ile hesap: 6 000 tokende yaklaşık 22 s, 12 000 tokende yaklaşık 44 s, her öğrenme çağrısından sonra. O sırada yazan kullanıcı bunu bekleyebilir. Bu hesaptır, ölçülmedi.

Sınırınız burada geçerli: "4 daha az bellek kullansa bile bağlam işleme maliyetini belirgin artırıyorsa 8'i tercih edebiliriz."

## 4. Sınıra ulaşınca eski kayıtlara ne oluyor

Kayıtlara göre (her iki koşuda 82 oluşturma, 48 geçersiz kılınma, 2 yerine yazma):

- **"En eskiyi sil" kaydı hiç görülmedi (0).** Sınıra gelmeden önce başka bir kural devreye giriyor: "birbirine çok yakın" olan checkpoint siliniyor.
- **Sınır 4:** 29 yakınlık silmesi sayıldı. Hesap tutuyor: 82 − 48 − 29 − 2 = 3 canlı.
- **Sınır 8:** Araç bu olayı o koşuda henüz saymıyordu. Aynı hesapla yaklaşık 25. Daha önce size "yaklaşık 27" demiştim; yerine yazma 2'yi saymamıştım, doğrusu yaklaşık 25.
- En düşük konumdaki küçük checkpoint (212. token, 66 MiB) kalıyor. Sınır 4'te geriye dönüş bu yüzden oraya düşüyor.
- Checkpoint boyutu konuşmayla büyümüyor gibi: gerçek servisin eski kaydında 9 172 tokende de 320 MiB. Bu yüzden 8 sınırının bellek tepesi uzun konuşmada da benzer olmalı. Ölçülmedi.

## 5. Yanıt ve öğrenme doğruluğu

| | Sınır 8 | Sınır 4 |
|---|---|---|
| Sorular | 2/2 | 2/2 |
| Mesaj bütünlüğü, kayıt = gösterilen | Tam | Tam |
| Öğrenme işleri | 10/10 bitti | 10/10 bitti |
| Oluşan hafıza | 3 | 3 |

Tüm yanıtları ve hafızaları elle okudum. Sınıra bağlanabilecek bir hata görmedim. **Mevcut hatalar ikisinde de sürüyor, sınır çözmüyor:**

- **REL-001:** Mehmet kaydı ikisinde de "10 Kasım'da İzmir'e gidecek" diye kesin yazıldı. Sorulunca yanıt yine belirsizliği koruyor.
- **Yan hata:** Mehmet mesajına verilen yanıtta kullanıcının söylemediği "taşınma" geçiyor (ikisinde de, önceden kayıtlı).

Aynı istemde bile yanıtlar koşudan koşuya değişiyor (ilk yanıt 54–74 token). Bu yüzden iki koşunun yanıtları birebir karşılaştırılamaz; bu değerlendirme elle okumaya ve iki soruya dayanır.

**Boşta davranış:** İki sınırda da ayak izi 5 dakika boşta aynı kaldı, swap'a taşınma görülmedi (önceki B koşusunda 7 GB'ın çoğu taşınmıştı). Son çağrıdan yaklaşık 4 dakika sonra sistem kablolu belleği yine yaklaşık 10,2 GB'tan 2,0–2,2 GB'a düştü.

**Seçici öğrenme için yeni veri:** 10 çağrının 7'si hiçbir şey kaydetmedi: 58 s, öğrenme süresinin %54'ü. Sınır bunu değiştirmiyor.

## 6. Hâlâ ölçülmeyen riskler

1. **Sıkıştırma:** Hiç olmadı. Bağlam 2,4 bin tokende kaldı. Sıkıştırma sonrası ilk token, kesilen sıkıştırma ve kesin sınırdaki bekleme ölçülmedi. **En büyük açık bu.**
2. **Özet ve bilgi koruma:** REL-003 taban çizgisine etkisi ölçülmedi. Sınırın özet metnini değiştirmesini beklemiyorum, ama ölçülmeden kabul edilemez.
3. **Ekran uyanması:** Kritik baskı hafif testte ekran açılınca geldi. Bu koşularda ekran hiç kapanıp açılmadı.
4. **Kesinti:** Öğrenme ya da yeniden ısıtma sürerken gelen mesaj sınanmadı (45 s aralık).
5. **Daha dolu sistem:** Diğer programlar 12,5 GB idi. Cursor gibi uygulamalar da açıkken ne olacağı bilinmiyor.
6. **Doğal zamanlama:** Hafif testin 2–5 dakikalık aralıkları bu sınırla sınanmadı.
7. **Tekrar:** Her sınır tek koşu; sınır 8 önce çalıştı.
8. **Uzun oturum:** Saatlik kullanım, model boşaltma ve yeniden yükleme.

**Sonraki ölçüm:** 40 mesajlık uzun konuşma yapıldı, sonuç [LONG_CONVERSATION_LIMIT8_REPORT.md](LONG_CONVERSATION_LIMIT8_REPORT.md).

## 7. En düşük riskli sonraki adım (onay bekliyor, başlatılmadı)

Yine yalnızca geçici Ollama sürecinde, **sınır 8**, öğrenme açık:

1. **40 mesajlık konuşma, 60 s aralık** (önce en sakin hız). Eski taban çizgisiyle aynı mesajlar; sıkıştırma birkaç kez çalışır, yaklaşık 50 dakika. İlk token, sıkıştırma süresi, sıkıştırma sonrası ilk token, bellek ve özet sürümleri karşılaştırılır. Aynı durma kuralları.
2. **Test sırasında ekranın bir kez uyanması:** Ekran uykudayken bir kez sizin açmanız ya da kendiliğinden olması; böylece 3. risk doğrudan görülür.
3. **Sonuç temizse, ayrı onayla:** 30 s aralık (kesinti ve tur içi sıkıştırma) ve çoklu sıkıştırma kalite testi (62→56/64 sınırıyla).
4. **Gerçek servis:** Ancak bunlar geçerse ve ayrı onayınızla `scripts/ollama-agent.sh`. Geri dönüş tek ayar.

Bu sürede bugünkü gerçek servis 32 sınırıyla çalışmaya devam ediyor; yani hafif testteki bellek davranışı gerçek uygulamada da geçerli sayılmalı.
