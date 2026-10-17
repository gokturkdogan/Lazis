//! Profiles keep development and normal use fully separate: their own data directory, logs,
//! config, desktop state and Keychain item.
//!
//! default: ~/Library/Application Support/LAZIS/{data.noindex,config.toml,desktop-state.json}
//!          ~/Library/Logs/LAZIS                      Keychain account: database-key-v1
//! <name>:  ~/Library/Application Support/LAZIS/<name>/...
//!          ~/Library/Logs/LAZIS/<name>               Keychain account: database-key-v1-<name>
//!
//! Debug builds use the `dev` profile, release builds `default`; `LAZIS_PROFILE` overrides.

use std::fs::DirBuilder;
use std::os::unix::fs::{DirBuilderExt, PermissionsExt};
use std::path::{Path, PathBuf};

use crate::errors::ShellError;

pub const KEYCHAIN_SERVICE: &str = "com.lazis.app";
const KEYCHAIN_ACCOUNT: &str = "database-key-v1";
pub const DEFAULT_PROFILE: &str = "default";
pub const DEV_PROFILE: &str = "dev";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Profile {
    pub name: String,
    pub root: PathBuf,
    pub data_dir: PathBuf,
    pub log_dir: PathBuf,
    pub config_path: PathBuf,
    pub state_path: PathBuf,
    pub keychain_account: String,
}

fn valid_profile_name(name: &str) -> bool {
    let bytes = name.as_bytes();
    (1..=32).contains(&bytes.len())
        && bytes[0].is_ascii_alphanumeric()
        && bytes.iter().all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || *b == b'-')
}

impl Profile {
    pub fn resolve(home: &Path, requested: Option<&str>, debug_build: bool) -> Result<Self, ShellError> {
        let name = match requested.map(str::trim).filter(|s| !s.is_empty()) {
            Some(n) if valid_profile_name(n) => n.to_owned(),
            Some(_) => return Err(ShellError::new("config_invalid")),
            None if debug_build => DEV_PROFILE.to_owned(),
            None => DEFAULT_PROFILE.to_owned(),
        };
        let support = home.join("Library/Application Support/LAZIS");
        let logs = home.join("Library/Logs/LAZIS");
        let (root, log_dir, keychain_account) = if name == DEFAULT_PROFILE {
            (support, logs, KEYCHAIN_ACCOUNT.to_owned())
        } else {
            (support.join(&name), logs.join(&name), format!("{KEYCHAIN_ACCOUNT}-{name}"))
        };
        Ok(Self {
            data_dir: root.join("data.noindex"),
            config_path: root.join("config.toml"),
            state_path: root.join("desktop-state.json"),
            root,
            log_dir,
            keychain_account,
            name,
        })
    }

    /// Whether an encrypted database already exists. Any `*.db` at the top of the data
    /// directory counts, so a renamed database is never mistaken for a fresh install.
    pub fn database_exists(&self) -> bool {
        let Ok(entries) = std::fs::read_dir(&self.data_dir) else { return false };
        entries.flatten().any(|e| {
            e.path().extension().is_some_and(|ext| ext == "db") && e.file_type().is_ok_and(|t| t.is_file())
        })
    }

    pub fn ensure_dirs(&self) -> std::io::Result<()> {
        for dir in [&self.root, &self.log_dir] {
            ensure_private_dir(dir)?;
        }
        Ok(())
    }
}

/// Create `dir` (and parents) and make sure the leaf is owner-only (0700).
pub fn ensure_private_dir(dir: &Path) -> std::io::Result<()> {
    DirBuilder::new().recursive(true).mode(0o700).create(dir)?;
    let mut perms = std::fs::metadata(dir)?.permissions();
    if perms.mode() & 0o077 != 0 {
        perms.set_mode(0o700);
        std::fs::set_permissions(dir, perms)?;
    }
    Ok(())
}

/// Locate the backend's Python environment.
///
/// Phase 1 runs the backend from the repository's `core/` virtualenv (`uv sync`). Debug builds
/// may point elsewhere with `LAZIS_CORE_DIR`; release builds always use the compile-time path.
/// Packaging an embedded runtime is a later phase.
pub fn core_dir(env_override: Option<&str>, debug_build: bool) -> PathBuf {
    let dir = match env_override.filter(|d| debug_build && !d.is_empty()) {
        Some(dir) => PathBuf::from(dir),
        None => Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../core"),
    };
    std::fs::canonicalize(&dir).unwrap_or(dir)
}

pub fn backend_python(core_dir: &Path) -> PathBuf {
    core_dir.join(".venv/bin/python")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_and_dev_profiles_are_separate() {
        let home = Path::new("/Users/test");
        let release = Profile::resolve(home, None, false).unwrap();
        let debug = Profile::resolve(home, None, true).unwrap();
        assert_eq!(release.name, "default");
        assert_eq!(release.data_dir, home.join("Library/Application Support/LAZIS/data.noindex"));
        assert_eq!(release.log_dir, home.join("Library/Logs/LAZIS"));
        assert_eq!(release.keychain_account, "database-key-v1");
        assert_eq!(debug.name, "dev");
        assert_eq!(debug.data_dir, home.join("Library/Application Support/LAZIS/dev/data.noindex"));
        assert_eq!(debug.log_dir, home.join("Library/Logs/LAZIS/dev"));
        assert_eq!(debug.keychain_account, "database-key-v1-dev");
        assert_ne!(release.state_path, debug.state_path);
    }

    #[test]
    fn profile_override_is_validated() {
        let home = Path::new("/Users/test");
        let p = Profile::resolve(home, Some("verify-1"), false).unwrap();
        assert_eq!(p.keychain_account, "database-key-v1-verify-1");
        for bad in ["../x", "UPPER", "a b", "-lead", &"x".repeat(33), "a.b"] {
            assert_eq!(Profile::resolve(home, Some(bad), false).unwrap_err().code, "config_invalid", "{bad}");
        }
        assert_eq!(Profile::resolve(home, Some("  "), false).unwrap().name, "default");
    }

    #[test]
    fn database_detection_and_private_dirs() {
        let tmp = tempfile::tempdir().unwrap();
        let p = Profile::resolve(tmp.path(), Some("t"), false).unwrap();
        assert!(!p.database_exists());
        p.ensure_dirs().unwrap();
        ensure_private_dir(&p.data_dir).unwrap();
        std::fs::create_dir(p.data_dir.join("backups")).unwrap();
        std::fs::write(p.data_dir.join(".lazis-core.lock"), b"").unwrap();
        assert!(!p.database_exists());
        std::fs::write(p.data_dir.join("renamed.db"), b"x").unwrap();
        assert!(p.database_exists());
        let mode = std::fs::metadata(&p.root).unwrap().permissions().mode() & 0o777;
        assert_eq!(mode, 0o700);
    }
}
