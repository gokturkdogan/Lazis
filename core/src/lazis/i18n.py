"""Turkish user-facing messages for error codes.

The desktop UI has its own translations keyed by the same codes; these strings are the
backend's fallback and are also used by CLI output. Keep them short and non-technical.
"""

from __future__ import annotations

MESSAGES_TR: dict[str, str] = {
    "internal_error": (
        "Beklenmeyen bir hata oluştu. Ayrıntılar güvenli günlük dosyasına kaydedildi."
    ),
    "config_invalid": "Yapılandırma geçersiz. Lütfen ayar dosyasını kontrol edin.",
    "secrets_missing": "Güvenli başlatma bilgileri alınamadı. Uygulamayı yeniden başlatın.",
    "encryption_unavailable": (
        "Şifreli veritabanı altyapısı (SQLCipher) doğrulanamadı. "
        "Güvenlik nedeniyle şifresiz çalışılmıyor."
    ),
    "database_plaintext_detected": (
        "Beklenen konumda şifresiz bir veritabanı bulundu. Güvenlik nedeniyle açılmadı."
    ),
    "database_key_invalid": (
        "Veritabanı anahtarı bu veritabanını açamıyor. Kurtarma kodunuzla geri yükleyebilirsiniz."
    ),
    "database_corrupt": (
        "Veritabanı bütünlük denetiminden geçemedi. Yedekten geri yükleme gerekebilir."
    ),
    "database_error": "Veritabanına erişilemedi.",
    "instance_already_running": "LAZIS arka ucu zaten çalışıyor. Aynı veritabanı iki kez açılamaz.",
    "migration_failed": "Veritabanı şeması güncellenemedi. Ayrıntılar günlük dosyasında.",
    "unauthorized": "Yetkisiz istek.",
    "origin_not_allowed": "Bu kaynaktan gelen isteklere izin verilmiyor.",
    "host_not_allowed": "Geçersiz sunucu adresi.",
    "request_too_large": "İstek çok büyük.",
    "rate_limited": "Çok fazla istek gönderildi. Lütfen biraz bekleyin.",
    "not_found": "İstenen kaynak bulunamadı.",
    "validation_error": "İstek doğrulanamadı.",
    "network_blocked": "Ağ erişimi kapalı (çevrimdışı mod).",
    "network_sandbox_unavailable": (
        "İşletim sistemi ağ kısıtı uygulanamadı. Güvenlik nedeniyle arka uç başlatılmadı."
    ),
    "restore_failed": "Yedek geri yüklenemedi. Mevcut veritabanınız değiştirilmedi.",
    "llm_error": "Yerel model beklenmeyen bir hata verdi.",
    "llm_unavailable": (
        "Yerel model çalışma ortamına (Ollama) ulaşılamadı. Ollama kurulu ve çalışıyor mu?"
    ),
    "llm_model_not_found": "Seçilen model bu bilgisayarda yüklü değil.",
    "llm_model_not_allowed": "Bu model kullanılamaz (yalnızca yerel modellere izin verilir).",
    "llm_out_of_memory": "Model için yeterli bellek yok. Daha küçük bir model veya bağlam deneyin.",
    "llm_load_failed": "Model yüklenemedi.",
    "llm_timeout": "Model zamanında yanıt vermedi.",
    "llm_invalid_response": "Yerel modelden geçersiz bir yanıt geldi.",
    "llm_busy": "Şu anda başka bir yanıt üretiliyor. Bitmesini bekleyin veya iptal edin.",
    "llm_cancelled": "Yanıt üretimi iptal edildi.",
    "conversation_not_found": "Sohbet bulunamadı. Silinmiş olabilir.",
    "turn_duplicate": "Bu mesaj zaten gönderildi.",
    "database_busy": "Veritabanı şu anda meşgul. Birkaç saniye sonra yeniden deneyin.",
    "message_save_failed": "Mesaj kaydedilemedi. Sohbet değiştirilmedi; yeniden deneyin.",
    "context_failed": "Konuşma bağlamı hazırlanamadı. Yeniden deneyin.",
    "message_too_long": "Mesaj çok uzun. Lütfen daha kısa bir mesaj gönderin.",
    "session_not_active": "Konuşma güncellendi. Sayfayı yenileyip yeniden deneyin.",
}


def message_for(code: str) -> str:
    return MESSAGES_TR.get(code, MESSAGES_TR["internal_error"])
