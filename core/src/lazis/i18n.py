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
}


def message_for(code: str) -> str:
    return MESSAGES_TR.get(code, MESSAGES_TR["internal_error"])
