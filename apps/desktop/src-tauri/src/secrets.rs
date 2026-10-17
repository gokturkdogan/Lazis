//! Secret material: the 256-bit database key and the per-launch session token.
//!
//! Generated with Apple's CSPRNG (`SecRandomCopyBytes`), wiped on drop (`zeroize`), and never
//! printed: `Debug` is redacted. Secrets leave this process only through the backend's stdin.

use std::fmt;

use security_framework::random::SecRandom;
use zeroize::{Zeroize, Zeroizing};

use crate::errors::ShellError;

pub const KEY_LEN: usize = 32;

fn random_bytes(buf: &mut [u8]) -> Result<(), ShellError> {
    SecRandom::default().copy_bytes(buf).map_err(|_| ShellError::new("backend_start_failed"))
}

pub fn to_hex(bytes: &[u8]) -> Zeroizing<String> {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut out = Zeroizing::new(String::with_capacity(bytes.len() * 2));
    for b in bytes {
        out.push(HEX[(b >> 4) as usize] as char);
        out.push(HEX[(b & 0x0f) as usize] as char);
    }
    out
}

/// The SQLCipher database key.
#[derive(Clone)]
pub struct DbKey(Zeroizing<[u8; KEY_LEN]>);

impl DbKey {
    pub fn generate() -> Result<Self, ShellError> {
        let mut key = Zeroizing::new([0u8; KEY_LEN]);
        random_bytes(key.as_mut())?;
        Ok(Self(key))
    }

    pub fn from_slice(bytes: &[u8]) -> Option<Self> {
        if bytes.len() != KEY_LEN {
            return None;
        }
        let mut key = Zeroizing::new([0u8; KEY_LEN]);
        key.copy_from_slice(bytes);
        Some(Self(key))
    }

    pub fn as_bytes(&self) -> &[u8; KEY_LEN] {
        &self.0
    }

    pub fn hex(&self) -> Zeroizing<String> {
        to_hex(self.0.as_ref())
    }
}

impl PartialEq for DbKey {
    fn eq(&self, other: &Self) -> bool {
        // Constant-time comparison is not needed here (no attacker-controlled timing oracle),
        // but avoid short-circuiting anyway.
        self.0.iter().zip(other.0.iter()).fold(0u8, |acc, (a, b)| acc | (a ^ b)) == 0
    }
}

impl fmt::Debug for DbKey {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("DbKey(****)")
    }
}

/// Per-launch bearer token for the local API (never persisted).
#[derive(Clone)]
pub struct SessionToken(Zeroizing<String>);

impl SessionToken {
    pub fn generate() -> Result<Self, ShellError> {
        let mut raw = [0u8; 32];
        random_bytes(&mut raw)?;
        let token = to_hex(&raw);
        raw.zeroize();
        Ok(Self(token))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl fmt::Debug for SessionToken {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("SessionToken(****)")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn keys_are_random_and_redacted() {
        let a = DbKey::generate().unwrap();
        let b = DbKey::generate().unwrap();
        assert_ne!(a, b);
        assert_eq!(format!("{a:?}"), "DbKey(****)");
        assert_eq!(a.hex().len(), 64);
    }

    #[test]
    fn tokens_are_64_hex_chars_and_redacted() {
        let t = SessionToken::generate().unwrap();
        assert_eq!(t.as_str().len(), 64);
        assert!(t.as_str().chars().all(|c| c.is_ascii_hexdigit() && !c.is_ascii_uppercase()));
        assert_eq!(format!("{t:?}"), "SessionToken(****)");
    }

    #[test]
    fn from_slice_checks_length() {
        assert!(DbKey::from_slice(&[0u8; 31]).is_none());
        assert!(DbKey::from_slice(&[0u8; 32]).is_some());
    }
}
