//! Desktop integration helpers that are pure enough to test: the webview navigation guard,
//! external-link validation, sleep/wake detection, menu-bar status texts and the tray icon.

use std::time::Duration;

use tauri::Url;

/// The webview may only show the app itself. Everything else (a link in a reply, an injected
/// redirect) is refused; external links go through `open_external_url` after confirmation.
pub fn navigation_allowed(url: &Url, dev: bool) -> bool {
    match url.scheme() {
        "tauri" => url.host_str() == Some("localhost"),
        "http" if dev => url.host_str() == Some("localhost") && url.port() == Some(1420),
        _ => false,
    }
}

pub const MAX_EXTERNAL_URL: usize = 2048;

/// A link the user confirmed: http(s) only, with a host, without embedded credentials or
/// control characters, of bounded length. Returns the normalised URL to hand to the OS.
pub fn validate_external_url(raw: &str) -> Option<Url> {
    if raw.len() > MAX_EXTERNAL_URL || raw.chars().any(|c| c.is_control() || c.is_whitespace()) {
        return None;
    }
    let url = Url::parse(raw).ok()?;
    let ok = matches!(url.scheme(), "http" | "https")
        && url.host_str().is_some_and(|h| !h.is_empty())
        && url.username().is_empty()
        && url.password().is_none();
    ok.then_some(url)
}

/// Hand a validated URL to the default browser. `open` returns at once; the child is reaped on
/// a short-lived thread.
pub fn open_in_browser(url: &Url) -> std::io::Result<()> {
    let mut child = std::process::Command::new("/usr/bin/open")
        .arg(url.as_str())
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn()?;
    std::thread::spawn(move || {
        let _ = child.wait();
    });
    Ok(())
}

/// How often the wake detector samples the clocks (one cheap wake-up per interval).
pub const WAKE_POLL: Duration = Duration::from_secs(15);
const WAKE_THRESHOLD: Duration = Duration::from_secs(30);

/// macOS's monotonic clock (`Instant`, CLOCK_UPTIME_RAW) stops while the Mac sleeps; the wall
/// clock does not. If the wall clock advanced clearly more than the monotonic one, the system
/// slept. (A manual clock change can look the same; the only consequence is one extra health
/// check.)
pub fn slept_between(monotonic: Duration, wall: Duration) -> bool {
    wall > monotonic + WAKE_THRESHOLD
}

/// Menu-bar status reported by the UI. Unknown values are rejected.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TrayStatus {
    Starting,
    Idle,
    Thinking,
    Speaking,
    Error,
    Offline,
}

impl TrayStatus {
    pub fn parse(s: &str) -> Option<Self> {
        Some(match s {
            "starting" => Self::Starting,
            "idle" => Self::Idle,
            "thinking" => Self::Thinking,
            "speaking" => Self::Speaking,
            "error" => Self::Error,
            "offline" => Self::Offline,
            _ => return None,
        })
    }

    pub fn label(self) -> &'static str {
        match self {
            Self::Starting => "LAZIS başlatılıyor",
            Self::Idle => "LAZIS hazır",
            Self::Thinking => "LAZIS düşünüyor",
            Self::Speaking => "LAZIS yanıtlıyor",
            Self::Error => "LAZIS: bir sorun var",
            Self::Offline => "LAZIS: arka uç bağlı değil",
        }
    }
}

/// Views a second launch (`--show=<view>`) or the menu bar may open.
pub fn parse_view(arg: &str) -> Option<&'static str> {
    match arg.strip_prefix("--show=")? {
        "assistant" => Some("conversation"),
        "diagnostics" => Some("diagnostics"),
        "memory" => Some("memory"),
        "settings" => Some("settings"),
        _ => None,
    }
}

pub const TRAY_ICON_SIZE: u32 = 44; // 22 pt @2x

/// Menu-bar template icon (ring + centre dot, black with alpha; macOS tints it for light and
/// dark menu bars). Drawn here so no image decoder is needed.
pub fn tray_icon_rgba() -> Vec<u8> {
    let size = TRAY_ICON_SIZE as f32;
    let alpha = |x: f32, y: f32| {
        let d = (x - size / 2.0).hypot(y - size / 2.0);
        let ring = (1.0 - (d - 16.5).abs() / 2.0).max(0.0);
        let dot = (7.0 - d).clamp(0.0, 1.0);
        (ring + dot).min(1.0)
    };
    let mut rgba = Vec::with_capacity((TRAY_ICON_SIZE * TRAY_ICON_SIZE * 4) as usize);
    for y in 0..TRAY_ICON_SIZE {
        for x in 0..TRAY_ICON_SIZE {
            let mut a = 0.0;
            for (sx, sy) in [(0.25, 0.25), (0.75, 0.25), (0.25, 0.75), (0.75, 0.75)] {
                a += alpha(x as f32 + sx, y as f32 + sy) / 4.0;
            }
            rgba.extend_from_slice(&[0, 0, 0, (a * 255.0).round() as u8]);
        }
    }
    rgba
}

#[cfg(test)]
mod tests {
    use super::*;

    fn url(s: &str) -> Url {
        Url::parse(s).unwrap()
    }

    #[test]
    fn navigation_guard_allows_only_the_app() {
        assert!(navigation_allowed(&url("tauri://localhost/index.html"), false));
        assert!(navigation_allowed(&url("tauri://localhost/"), true));
        assert!(navigation_allowed(&url("http://localhost:1420/"), true));
        assert!(!navigation_allowed(&url("http://localhost:1420/"), false));
        for bad in [
            "https://example.com/",
            "http://localhost:8080/",
            "http://127.0.0.1:1420/",
            "tauri://evil.example/",
            "file:///etc/passwd",
            "javascript:alert(1)",
            "data:text/html,<script>alert(1)</script>",
            "about:blank",
        ] {
            assert!(!navigation_allowed(&url(bad), true), "{bad}");
        }
    }

    #[test]
    fn external_urls_are_http_only_and_well_formed() {
        assert_eq!(
            validate_external_url("https://example.com/a?b=c#d").unwrap().as_str(),
            "https://example.com/a?b=c#d"
        );
        assert!(validate_external_url("http://example.com").is_some());
        for bad in [
            "javascript:alert(1)",
            "file:///etc/passwd",
            "data:text/html,x",
            "vbscript:x",
            "lazis://x",
            "x-apple.systempreferences:com.apple.preference.security",
            "ftp://example.com/",
            "https://user:pw@example.com/",
            "https://example.com@evil.example/",
            "https://exa mple.com/",
            "https://example.com/\n",
            "https://example.com/\u{0}",
            "/relative",
            "",
        ] {
            assert!(validate_external_url(bad).is_none(), "{bad:?}");
        }
        let long = format!("https://example.com/{}", "a".repeat(MAX_EXTERNAL_URL));
        assert!(validate_external_url(&long).is_none());
    }

    #[test]
    fn sleep_is_detected_from_clock_drift_only() {
        let s = Duration::from_secs;
        assert!(!slept_between(s(15), s(15)));
        assert!(!slept_between(s(15), s(40))); // scheduling jitter, NTP slew
        assert!(slept_between(s(15), s(15 + 600))); // ten minutes asleep
    }

    #[test]
    fn tray_status_and_views_are_validated() {
        assert_eq!(TrayStatus::parse("thinking"), Some(TrayStatus::Thinking));
        assert_eq!(TrayStatus::parse("listening"), None); // no microphone in Phase 4
        assert_eq!(TrayStatus::parse("<b>"), None);
        assert_eq!(parse_view("--show=diagnostics"), Some("diagnostics"));
        assert_eq!(parse_view("--show=memory"), Some("memory"));
        assert_eq!(parse_view("--show=assistant"), Some("conversation"));
        assert_eq!(parse_view("--show=../x"), None);
        assert_eq!(parse_view("diagnostics"), None);
    }

    #[test]
    fn tray_icon_is_a_template_ring_with_a_dot() {
        let rgba = tray_icon_rgba();
        assert_eq!(rgba.len(), (TRAY_ICON_SIZE * TRAY_ICON_SIZE * 4) as usize);
        let px = |x: u32, y: u32| &rgba[((y * TRAY_ICON_SIZE + x) * 4) as usize..][..4];
        assert_eq!(px(22, 22), &[0, 0, 0, 255]); // centre dot
        assert_eq!(px(0, 0)[3], 0); // transparent corner
        assert!(px(22 + 16, 22)[3] > 200); // on the ring
        assert!(rgba.chunks(4).all(|p| p[..3] == [0, 0, 0])); // pure template colour
    }
}
