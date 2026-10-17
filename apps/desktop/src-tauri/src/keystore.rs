//! Database-key storage. Production: the macOS login Keychain (generic password item owned by
//! the LAZIS app). Tests: an in-memory store.

use std::sync::Mutex;

use security_framework::passwords::{
    PasswordOptions, delete_generic_password_options, generic_password, set_generic_password_options,
};
use zeroize::Zeroizing;

use crate::errors::ShellError;
use crate::secrets::DbKey;

const ERR_SEC_ITEM_NOT_FOUND: i32 = -25300;
const ERR_SEC_AUTH_FAILED: i32 = -25293;
const ERR_SEC_INTERACTION_NOT_ALLOWED: i32 = -25308;
const ERR_SEC_USER_CANCELED: i32 = -128;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum KeyStoreError {
    /// The user denied access (or the keychain is locked and interaction is not allowed).
    Denied,
    /// Any other Keychain failure, with the OSStatus code for diagnostics.
    Unavailable(i32),
    /// The stored item exists but is not a 32-byte key.
    Malformed,
}

impl KeyStoreError {
    pub fn code(&self) -> &'static str {
        match self {
            Self::Denied => "keychain_denied",
            Self::Unavailable(_) | Self::Malformed => "keychain_unavailable",
        }
    }
}

pub trait KeyStore: Send + Sync {
    fn load(&self) -> Result<Option<DbKey>, KeyStoreError>;
    fn store(&self, key: &DbKey) -> Result<(), KeyStoreError>;
    fn delete(&self) -> Result<(), KeyStoreError>;
}

pub struct KeychainStore {
    service: String,
    account: String,
}

impl KeychainStore {
    pub fn new(service: &str, account: &str) -> Self {
        Self { service: service.to_owned(), account: account.to_owned() }
    }

    fn options(&self) -> PasswordOptions {
        PasswordOptions::new_generic_password(&self.service, &self.account)
    }
}

fn map_error(code: i32) -> KeyStoreError {
    match code {
        ERR_SEC_AUTH_FAILED | ERR_SEC_INTERACTION_NOT_ALLOWED | ERR_SEC_USER_CANCELED => {
            KeyStoreError::Denied
        }
        other => KeyStoreError::Unavailable(other),
    }
}

impl KeyStore for KeychainStore {
    fn load(&self) -> Result<Option<DbKey>, KeyStoreError> {
        match generic_password(self.options()) {
            Ok(bytes) => {
                let bytes = Zeroizing::new(bytes);
                DbKey::from_slice(&bytes).map(Some).ok_or(KeyStoreError::Malformed)
            }
            Err(e) if e.code() == ERR_SEC_ITEM_NOT_FOUND => Ok(None),
            Err(e) => Err(map_error(e.code())),
        }
    }

    fn store(&self, key: &DbKey) -> Result<(), KeyStoreError> {
        // Not synchronizable: the key never leaves this Mac through iCloud Keychain.
        let mut options = self.options();
        options.set_label("LAZIS database key");
        options.set_description("LAZIS encrypted database key (SQLCipher)");
        options.set_access_synchronized(Some(false));
        set_generic_password_options(key.as_bytes(), options).map_err(|e| map_error(e.code()))
    }

    fn delete(&self) -> Result<(), KeyStoreError> {
        match delete_generic_password_options(self.options()) {
            Ok(()) => Ok(()),
            Err(e) if e.code() == ERR_SEC_ITEM_NOT_FOUND => Ok(()),
            Err(e) => Err(map_error(e.code())),
        }
    }
}

/// In-memory store for tests and the integration suite.
#[derive(Default)]
pub struct MemoryKeyStore {
    key: Mutex<Option<DbKey>>,
    pub fail_with: Mutex<Option<KeyStoreError>>,
}

impl MemoryKeyStore {
    pub fn with_key(key: DbKey) -> Self {
        Self { key: Mutex::new(Some(key)), fail_with: Mutex::new(None) }
    }
}

impl KeyStore for MemoryKeyStore {
    fn load(&self) -> Result<Option<DbKey>, KeyStoreError> {
        if let Some(err) = self.fail_with.lock().unwrap().clone() {
            return Err(err);
        }
        Ok(self.key.lock().unwrap().clone())
    }

    fn store(&self, key: &DbKey) -> Result<(), KeyStoreError> {
        *self.key.lock().unwrap() = Some(key.clone());
        Ok(())
    }

    fn delete(&self) -> Result<(), KeyStoreError> {
        *self.key.lock().unwrap() = None;
        Ok(())
    }
}

#[derive(Debug)]
pub enum KeyResolution {
    /// The Keychain holds the key.
    Existing(DbKey),
    /// First run: a new key was generated and persisted (and read back) before any database
    /// exists, so a database can never be created with a key that was not stored.
    Generated(DbKey),
    /// A database exists but its key is gone: only the user's recovery code can open it.
    /// A new key is deliberately NOT generated here.
    NeedsRecovery,
}

pub fn resolve_key(store: &dyn KeyStore, database_exists: bool) -> Result<KeyResolution, ShellError> {
    let to_shell = |e: KeyStoreError| ShellError::new(e.code());
    match store.load().map_err(to_shell)? {
        Some(key) => Ok(KeyResolution::Existing(key)),
        None if database_exists => Ok(KeyResolution::NeedsRecovery),
        None => {
            let key = DbKey::generate()?;
            store.store(&key).map_err(to_shell)?;
            match store.load().map_err(to_shell)? {
                Some(stored) if stored == key => Ok(KeyResolution::Generated(key)),
                _ => Err(ShellError::new("keychain_unavailable")),
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn existing_key_is_used() {
        let key = DbKey::generate().unwrap();
        let store = MemoryKeyStore::with_key(key.clone());
        match resolve_key(&store, true).unwrap() {
            KeyResolution::Existing(k) => assert_eq!(k, key),
            other => panic!("{other:?}"),
        }
    }

    #[test]
    fn first_run_generates_and_persists() {
        let store = MemoryKeyStore::default();
        let KeyResolution::Generated(key) = resolve_key(&store, false).unwrap() else { panic!() };
        assert_eq!(store.load().unwrap(), Some(key));
    }

    #[test]
    fn missing_key_with_database_needs_recovery_and_generates_nothing() {
        let store = MemoryKeyStore::default();
        assert!(matches!(resolve_key(&store, true).unwrap(), KeyResolution::NeedsRecovery));
        assert_eq!(store.load().unwrap(), None);
    }

    #[test]
    fn keychain_errors_are_reported_not_bypassed() {
        let store = MemoryKeyStore::default();
        *store.fail_with.lock().unwrap() = Some(KeyStoreError::Denied);
        assert_eq!(resolve_key(&store, false).unwrap_err().code, "keychain_denied");
        *store.fail_with.lock().unwrap() = Some(KeyStoreError::Unavailable(-1));
        assert_eq!(resolve_key(&store, false).unwrap_err().code, "keychain_unavailable");
    }

    /// Touches the real login Keychain with a dedicated test item; run explicitly:
    /// `cargo test -- --ignored keychain`
    #[test]
    #[ignore = "touches the real macOS Keychain"]
    fn keychain_roundtrip_with_test_item() {
        let store = KeychainStore::new("com.lazis.app.test", "phase1-keychain-test");
        store.delete().unwrap();
        assert_eq!(store.load().unwrap(), None);
        let key = DbKey::generate().unwrap();
        store.store(&key).unwrap();
        assert_eq!(store.load().unwrap(), Some(key));
        store.delete().unwrap();
        assert_eq!(store.load().unwrap(), None);
    }

    #[test]
    fn error_mapping() {
        assert_eq!(map_error(ERR_SEC_AUTH_FAILED).code(), "keychain_denied");
        assert_eq!(map_error(ERR_SEC_USER_CANCELED).code(), "keychain_denied");
        assert_eq!(map_error(-1).code(), "keychain_unavailable");
    }
}
