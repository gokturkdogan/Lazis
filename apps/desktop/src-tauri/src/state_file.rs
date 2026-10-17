//! Small non-secret desktop state (`desktop-state.json`, 0600): whether the user has confirmed
//! that the recovery code is stored safely, and the desktop preferences (window, menu bar,
//! motion). Never contains keys, codes, tokens or conversation content.

use std::fs::OpenOptions;
use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::time::{SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct DesktopState {
    pub version: u32,
    pub key_created_at_unix: Option<u64>,
    pub recovery_acknowledged_at_unix: Option<u64>,
    #[serde(default)]
    pub preferences: Preferences,
}

/// How motion in the UI is handled: follow macOS "Reduce motion", or force it on/off.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum ReduceMotion {
    #[default]
    System,
    On,
    Off,
}

/// Desktop preferences. Unknown or missing fields fall back to the defaults.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default, rename_all = "camelCase")]
pub struct Preferences {
    /// Closing the window keeps LAZIS running in the menu bar (true) or quits it (false).
    pub close_to_menu_bar: bool,
    /// Start with the window hidden (only the menu-bar icon).
    pub start_hidden: bool,
    pub reduce_motion: ReduceMotion,
}

impl Default for Preferences {
    fn default() -> Self {
        Self { close_to_menu_bar: true, start_hidden: false, reduce_motion: ReduceMotion::System }
    }
}

pub fn now_unix() -> u64 {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0)
}

impl DesktopState {
    pub fn recovery_pending(&self) -> bool {
        self.recovery_acknowledged_at_unix.is_none()
    }

    /// Missing or unreadable state means "not acknowledged": showing the code again is safe,
    /// silently assuming it was saved is not.
    pub fn load(path: &Path) -> Self {
        match std::fs::read(path) {
            Ok(bytes) => serde_json::from_slice(&bytes).unwrap_or_else(|_| {
                log::warn!("desktop_state.unreadable");
                Self::default()
            }),
            Err(_) => Self::default(),
        }
    }

    pub fn save(&self, path: &Path) -> std::io::Result<()> {
        let tmp = path.with_extension("json.tmp");
        let mut file = OpenOptions::new().write(true).create(true).truncate(true).mode(0o600).open(&tmp)?;
        let body = serde_json::to_vec_pretty(&Self { version: 1, ..self.clone() })?;
        file.write_all(&body)?;
        file.sync_all()?;
        std::fs::rename(&tmp, path)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::PermissionsExt;

    #[test]
    fn roundtrip_and_permissions() {
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("desktop-state.json");
        assert!(DesktopState::load(&path).recovery_pending());
        let state = DesktopState {
            version: 1,
            key_created_at_unix: Some(1),
            recovery_acknowledged_at_unix: Some(2),
            preferences: Preferences {
                close_to_menu_bar: false,
                start_hidden: true,
                reduce_motion: ReduceMotion::On,
            },
        };
        state.save(&path).unwrap();
        assert_eq!(DesktopState::load(&path), state);
        assert!(!DesktopState::load(&path).recovery_pending());
        assert_eq!(std::fs::metadata(&path).unwrap().permissions().mode() & 0o777, 0o600);
    }

    #[test]
    fn older_state_files_get_default_preferences() {
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("desktop-state.json");
        std::fs::write(&path, br#"{"version":1,"key_created_at_unix":5,"recovery_acknowledged_at_unix":6}"#)
            .unwrap();
        let state = DesktopState::load(&path);
        assert!(!state.recovery_pending());
        assert_eq!(state.preferences, Preferences::default());
        std::fs::write(&path, br#"{"version":1,"preferences":{"reduceMotion":"on","unknown":1}}"#).unwrap();
        let state = DesktopState::load(&path);
        assert_eq!(state.preferences.reduce_motion, ReduceMotion::On);
        assert!(state.preferences.close_to_menu_bar);
    }

    #[test]
    fn corrupt_state_is_treated_as_pending() {
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("desktop-state.json");
        std::fs::write(&path, b"{not json").unwrap();
        assert!(DesktopState::load(&path).recovery_pending());
    }
}
