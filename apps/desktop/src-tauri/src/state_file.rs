//! Small non-secret desktop state (`desktop-state.json`, 0600): whether the user has confirmed
//! that the recovery code is stored safely. Never contains keys, codes or tokens.

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
        let state =
            DesktopState { version: 1, key_created_at_unix: Some(1), recovery_acknowledged_at_unix: Some(2) };
        state.save(&path).unwrap();
        assert_eq!(DesktopState::load(&path), state);
        assert!(!DesktopState::load(&path).recovery_pending());
        assert_eq!(std::fs::metadata(&path).unwrap().permissions().mode() & 0o777, 0o600);
    }

    #[test]
    fn corrupt_state_is_treated_as_pending() {
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("desktop-state.json");
        std::fs::write(&path, b"{not json").unwrap();
        assert!(DesktopState::load(&path).recovery_pending());
    }
}
