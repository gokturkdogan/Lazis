# Faz 13 ilk sürüm: Türkçe sesli asistan

**Tarih:** 2026-11-06. **Dal:** `phase13/voice`, `main`'den (`a5be761`) açıldı. **Durum:** Sahibin onayı bekleniyor; `main`'e alınmadı. Konuşma tanıma modeli **indirilmedi**; gerçek mikrofonla, gerçek konuşma tanımayla ve masaüstü penceresinde **denenmedi**.

## 1. Teknik seçim (kısa)

**STT (konuşmayı yazıya çevirme)**

| Seçenek | Türkçe | Kaynak | Kurulum | Karar |
|---|---|---|---|---|
| **whisper.cpp + large-v3-turbo (q5_0)** | İyi (Whisper ailesinin en iyilerine yakın) | Metal/GPU, yaklaşık 0,8–1 GB bellek (tahmin), yalnızca kullanılırken | Homebrew'de **zaten kurulu** (1.8.4); model ~574 MB | **Seçildi** |
| mlx-whisper (aynı model) | Aynı | Metal | Arka uca MLX ve ağır Python bağımlılıkları | İlk sürüm için ağır |
| faster-whisper | Aynı | Mac'te yalnızca işlemci | Ek bağımlılıklar | Daha yavaş |
| Whisper small | Zayıf | Küçük | ~466 MB | Türkçe doğruluk yetersiz |
| Apple konuşma tanıma | Türkçe cihaz üstü desteği belirsiz | Düşük | Yerel kod gerekir | Denenmedi |

**TTS (sesli okuma)**

| Seçenek | Türkçe | Lisans ve kaynak | Karar |
|---|---|---|---|
| **macOS sistem sesi (`say`, Yelda)** | Var, yerleşik, indirme yok | Apple, yerel, hafif | **Seçildi (geçici)**: kadın sesi, doğallık orta |
| Chatterbox Multilingual (MLX) | Var, doğal, erkek sesi seçilebilir | MIT; ~1,5–2 GB; ağır bağımlılıklar | Sonraki adım: indirme ve dinleme karşılaştırması gerekir |
| Piper `tr_TR-dfki` | Var | Çalışma zamanı artık GPL (aynı süreçte kullanılamaz) | Yalnızca ayrı süreçle |
| VoxCPM2, XTTS-v2 | Var | Çok ağır ya da ticari olmayan lisans | Hayır |

**Erkek, sıcak ve doğal ses hedefi bu sürümde karşılanmadı.** macOS'ta Türkçe erkek sistem sesi yok.

## 2. Mimari

- **Mikrofon:** Arayüz (WebView) yalnızca kullanıcı eylemiyle açar: bas-konuş basılıyken ya da kullanıcının başlattığı oturum açıkken. Biter bitmez bütün ses izleri durdurulur ve macOS mikrofon göstergesi söner.
- **STT:** Ses bellekte 16 kHz WAV'a çevrilir ve kabuğa ham bayt olarak gider. Kabuk, `whisper-server`'ı yalnızca ilk kullanımda başlatır; 2 dakika kullanılmazsa, oturum bitince ve uygulama kapanınca durdurur.
  - Sunucu kendi korumalı profiliyle çalışır (`sandbox/stt.sb`): dışarıya hiçbir ağ bağlantısı kuramaz, DNS çözemez; yalnızca yerel olarak dinler.
  - Kabuk çökerse bağlantı borusu kapanır ve sunucu öldürülür.
- **TTS:** Kabuk, `/usr/bin/say`'i Türkçe sistem sesiyle çalıştırır. Metin komut satırıyla değil, standart girişle verilir. Yanıt cümle cümle okunur; "Sesli yanıtı durdur" sesi hemen keser.
- **Arka uç:** Sesli mesajlar `channel = "voice"` ile normal tur olarak gelir. **Hafızaya kayıt, düzeltme ve silme yapılmaz; kalıcı üslup tercihi değişmez.** Hafıza isteğine benzeyen sesli mesajda model, bunun sesle yapılamadığını söylemeye yönlendirilir.
- **Yazılı sohbet değişmedi.** Ses bileşenleri ses kullanılmadıkça hiç başlamaz.

## 3. Sesli kullanım

| Özellik | Durum |
|---|---|
| Bas-konuş | Düğme basılıyken kayıt, bırakınca yazıya çevrilip normal sohbete sesli mesaj olarak gönderilir; yanıt tercihe göre sesli okunur |
| Eller serbest oturum | Kullanıcı başlatır ve bitirir. Konuşma sırası ses düzeyiyle algılanır (başlama 150 ms, bitiş 900 ms sessizlik, en çok 30 sn; model yok). LAZIS düşünürken ve konuşurken duyulan saklanmaz (kendi sesini yakalamaz). Oturum bitince mikrofon kapanır ve konuşma modeli bırakılır |
| Sesli yanıtı durdurma | Var; kalan cümleler de iptal edilir |
| Durum göstergesi | "Mikrofon kapalı", "Mikrofon açık — dinliyorum", "yazıya çevriliyor", "yanıt hazırlanıyor", "LAZIS konuşuyor"; mikrofon açıkken kırmızı nokta |
| Gürültü | Çok sessiz ya da çok kısa kayıt yazıya çevrilmez; Whisper'ın sessizlikte ürettiği tipik metinler ("Altyazı M.K.", "İzlediğiniz için teşekkürler") gönderilmez |
| İzin reddi, cihaz yok | Açıklayıcı mesaj; uygulama normal çalışır |
| Yok (bilerek) | Uyandırma kelimesi, sürekli dinleme, konuşmacı tanıma, LAZIS konuşurken sesle kesme, JARVIS animasyonları (Faz 14) |

## 4. Mikrofon ve ses verisi

- Uygulama açılışında mikrofon kapalıdır; hiçbir kod onu kendiliğinden açmaz (test edildi).
- Ham ses diske yazılmaz: arayüzde ve kabukta bellekte kalır, yalnızca yerel konuşma sunucusuna gider. Sunucu dosya dönüştürme (`--convert`) kullanmadığı için geçici dosya oluşturmaz.
- Ses ve yazıya çevrilmiş metin buluta gitmez. Konuşma sunucusunun ağ izni yoktur.
- Yazıya çevrilen metin normal mesaj gibi sohbet geçmişinde saklanır (yazılı mesajla aynı).
- Sesle söylenen hiçbir şey kalıcı hafızaya yazılmaz (otomatik öğrenme zaten kapalı; açık komutlar da sesle çalışmaz).
- macOS mikrofon izni açıklaması `Info.plist`'e eklendi.

## 5. Bağımlılıklar, model, kaynak

| Bileşen | Boyut | Not |
|---|---|---|
| whisper.cpp 1.8.4 (Homebrew) | kurulu | MIT; uygulamaya gömülü değil, Homebrew'den kullanılır |
| `ggml-large-v3-turbo-q5_0.bin` | **~574 MB, indirilmedi** | `make voice-model APPROVED=yes` ile, onayınızdan sonra |
| macOS sistem sesi Yelda | yerleşik | indirme yok |
| Yeni Python, Rust ya da npm paketi | yok | |

**Tahmini kaynak (ölçülmedi):** konuşma modeli yüklüyken yaklaşık 0,8–1 GB bellek; 5 saniyelik konuşma için M4 Pro'da tahminen 0,5–1,5 sn. İlk kullanımda model yükleme birkaç saniye sürer. Ses kullanılmazken ek bellek yok. Gemma ile birlikte yaklaşık 9–10 GB.

## 6. Testler (modelsiz)

`make check` geçti (çıkış kodu 0): 3.496 çekirdek, 151 arayüz, 8 arayüz–arka uç, 45 Rust testi; lint ve tip denetimleri temiz.

| Konu | Doğrulanan |
|---|---|
| Sesli hafıza güvenliği | Sesle "Bunu hatırla" ve "Derya'yı unut": hafıza değişmez, komut modele gitmez (otomatik öğrenme zorla açıkken bile); üslup tercihi değişmez; mesajlar `voice` kanalıyla saklanır |
| STT sunucusu profili | Yerel dinleme var; Ollama dahil hiçbir yere bağlantı yok, DNS yok |
| Kabuk | WAV denetimi (16 kHz, mono, 16-bit, 60 sn), çok parçalı istek, sahte sunucuyla gidiş-dönüş, parçalı yanıt, hata kodları, eksik model veya sunucuda hiçbir şeyin başlamaması |
| Arayüz | Mikrofon kendiliğinden açılmaz; bas-konuş açılır, kapanır, mesaj `voice` kanalıyla gider, yanıt cümle cümle okunur; sessizlik ve gürültü gönderilmez; izin reddi; eller serbest oturumda bir tur ve kapanışta mikrofonun kapanıp modelin bırakılması; okumanın durdurulması; model eksikken açıklama |
| Ses yardımcıları | 16 kHz'e indirgeme, WAV, sıra algılama, Markdown temizleme, cümleye bölme |
| Sistem sesi | Yelda bir Türkçe cümleyi 4 sn sese çevirdi (dosyaya, hoparlöre değil) |

## 7. Açık eksikler ve riskler

- **Gerçek konuşma tanıma denenmedi.** Model indirilmedi; Türkçe doğruluk ve gecikme ölçülmedi.
- **Masaüstünde mikrofon izni denenmedi.** Tauri'nin WebView'u `getUserMedia` için macOS izin akışını doğru yönetiyor mu, gerçek pencerede görülmedi. Geliştirme modunda izin, uygulama yerine terminale atfedilebilir.
- **Ses kalitesi:** Yelda kadın sesi, doğallık sınırlı; erkek ses hedefi sonraki adımda.
- **Yankı:** Hoparlörle eller serbest kullanımda LAZIS konuşurken dinleme durur; kullanıcı LAZIS'i sesle kesemez. Kulaklıksız ortamda okuma bittikten hemen sonraki yankı nadiren bir tur başlatabilir.
- **Ses düzeyine dayalı sıra algılama** gürültülü ortamda yanlış başlayıp bitebilir; Silero VAD sonraki adım.
- **Whisper uydurmaları** filtrelenir ama liste sınırlı; yanlış anlaşılan bir cümle normal mesaj olarak gider (hafızaya yazılmaz).
- **Konuşma sunucusu yerel bir porttan dinler.** Aynı kullanıcı hesabındaki başka bir süreç, sunucu açıkken ona ses gönderebilir (yalnızca yazıya çevirir; dışarıya erişimi yok).
- **Homebrew bağımlılığı:** `whisper-server` uygulamayla paketlenmiyor.
- **Gerçek Gemma ile sesli yanıt kalitesi** (kısa, konuşma diline uygun yanıt) ölçülmedi; ses için ayrı üslup kuralı yok.
