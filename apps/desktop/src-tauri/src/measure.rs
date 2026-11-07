//! Opt-in local measurements (Phase 15B). Off unless the app is started with `LAZIS_METRICS=1`.
//! The UI may then report a few numbers (frame rate, speech timings); they go to the shell's
//! own log as `metrics.<kind> value=<n> detail=<d>`. Only the listed kinds and details are
//! accepted: no text, no content, nothing leaves the machine.

use std::sync::OnceLock;

const KINDS: &[&str] = &["fps", "stt_ms", "first_audio_ms", "voice_e2e_ms", "reply_ms"];
const DETAILS: &[&str] = &[
    "",
    "focused",
    "unfocused",
    "hidden",
    "high",
    "low",
    "idle",
    "listening",
    "thinking",
    "speaking",
    "error",
];

pub fn enabled() -> bool {
    static ON: OnceLock<bool> = OnceLock::new();
    *ON.get_or_init(|| std::env::var("LAZIS_METRICS").is_ok_and(|v| v == "1"))
}

/// The log line for a valid measurement, or `None` (unknown kind or detail, odd value).
pub fn line(kind: &str, value: f64, detail: &str) -> Option<String> {
    if !KINDS.contains(&kind)
        || !DETAILS.contains(&detail)
        || !value.is_finite()
        || !(0.0..=1e7).contains(&value)
    {
        return None;
    }
    Some(format!("metrics.{kind} value={value:.1} detail={}", if detail.is_empty() { "-" } else { detail }))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_known_numbers_are_logged() {
        assert_eq!(line("fps", 59.94, "focused").as_deref(), Some("metrics.fps value=59.9 detail=focused"));
        assert_eq!(line("stt_ms", 812.0, "").as_deref(), Some("metrics.stt_ms value=812.0 detail=-"));
        assert!(line("transcript", 1.0, "").is_none());
        assert!(line("fps", 60.0, "Merhaba LAZIS").is_none());
        assert!(line("fps", f64::NAN, "focused").is_none());
        assert!(line("fps", -1.0, "focused").is_none());
    }
}
