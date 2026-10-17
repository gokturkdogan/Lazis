//! Error type returned to the UI: a stable code (the UI translates it) plus a Turkish fallback.

use serde::Serialize;

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ShellError {
    pub code: String,
    pub message: String,
}

impl ShellError {
    pub fn new(code: &str) -> Self {
        Self { code: code.to_owned(), message: message_for(code).to_owned() }
    }
}

impl std::fmt::Display for ShellError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.code)
    }
}

impl std::error::Error for ShellError {}

fn message_for(code: &str) -> &'static str {
    match code {
        "backend_not_found" => "Arka uç kurulumu bulunamadı.",
        "backend_start_failed" => "Arka uç başlatılamadı.",
        "backend_start_timeout" => "Arka uç zamanında yanıt vermedi.",
        "backend_exited" => "Arka uç beklenmedik biçimde kapandı.",
        "network_sandbox_unavailable" => "İşletim sistemi ağ kısıtı uygulanamadı; arka uç başlatılmadı.",
        "keychain_unavailable" => "macOS Anahtar Zinciri'ne erişilemedi.",
        "keychain_denied" => "Anahtar Zinciri erişimi reddedildi.",
        "recovery_code_invalid" => "Kurtarma kodu geçersiz.",
        "recovery_code_wrong_database" => "Bu kurtarma kodu mevcut veritabanını açmıyor.",
        "recovery_not_available" => "Kurtarma kodu şu anda gösterilemez.",
        "database_key_missing" => "Veritabanı anahtarı bulunamadı.",
        "database_key_invalid" => "Veritabanı anahtarı bu veritabanını açamıyor.",
        _ => "Beklenmeyen bir hata oluştu.",
    }
}
