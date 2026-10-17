//! Recovery-code codec, format `LZR1` — byte-for-byte compatible with
//! `core/src/lazis/security/recovery.py` (shared test vectors in core/tests/fixtures).
//!
//! payload = key (32 B) || SHA-256("LAZIS-RECOVERY-v1" || key)[..4]
//! code    = "LZR1-" + Crockford-base32(payload) in groups of 5 (58 symbols)

use sha2::{Digest, Sha256};
use zeroize::Zeroizing;

use crate::secrets::{DbKey, KEY_LEN};

const PREFIX: &str = "LZR1";
const CHECK_CONTEXT: &[u8] = b"LAZIS-RECOVERY-v1";
const CHECK_LEN: usize = 4;
const GROUP: usize = 5;
const ALPHABET: &[u8; 32] = b"0123456789ABCDEFGHJKMNPQRSTVWXYZ";
const SYMBOLS: usize = ((KEY_LEN + CHECK_LEN) * 8).div_ceil(5); // 58

#[derive(Debug, PartialEq, Eq)]
pub enum RecoveryError {
    Prefix,
    Length,
    Character,
    Checksum,
}

fn checksum(key: &[u8]) -> [u8; CHECK_LEN] {
    let mut hasher = Sha256::new();
    hasher.update(CHECK_CONTEXT);
    hasher.update(key);
    let digest = hasher.finalize();
    let mut out = [0u8; CHECK_LEN];
    out.copy_from_slice(&digest[..CHECK_LEN]);
    out
}

fn decode_symbol(c: char) -> Option<u8> {
    let c = match c {
        'O' => '0',
        'I' | 'L' => '1',
        other => other,
    };
    ALPHABET.iter().position(|&a| a as char == c).map(|p| p as u8)
}

pub fn encode(key: &DbKey) -> Zeroizing<String> {
    let mut payload = Zeroizing::new(Vec::with_capacity(KEY_LEN + CHECK_LEN));
    payload.extend_from_slice(key.as_bytes());
    payload.extend_from_slice(&checksum(key.as_bytes()));

    let mut body = Zeroizing::new(String::with_capacity(SYMBOLS));
    let (mut acc, mut bits) = (0u32, 0u32);
    for &byte in payload.iter() {
        acc = (acc << 8) | u32::from(byte);
        bits += 8;
        while bits >= 5 {
            bits -= 5;
            body.push(ALPHABET[((acc >> bits) & 0x1f) as usize] as char);
        }
        acc &= (1 << bits) - 1;
    }
    if bits > 0 {
        body.push(ALPHABET[((acc << (5 - bits)) & 0x1f) as usize] as char);
    }

    let mut out = Zeroizing::new(String::from(PREFIX));
    for (i, ch) in body.chars().enumerate() {
        if i % GROUP == 0 {
            out.push('-');
        }
        out.push(ch);
    }
    out
}

pub fn decode(code: &str) -> Result<DbKey, RecoveryError> {
    let cleaned: Zeroizing<String> = Zeroizing::new(
        code.chars()
            .filter(|c| !matches!(c, ' ' | '-' | '\t' | '\r' | '\n'))
            .flat_map(char::to_uppercase)
            .collect(),
    );
    let body = cleaned.strip_prefix(PREFIX).ok_or(RecoveryError::Prefix)?;
    if body.chars().count() != SYMBOLS {
        return Err(RecoveryError::Length);
    }
    let mut payload = Zeroizing::new(Vec::with_capacity(KEY_LEN + CHECK_LEN));
    let (mut acc, mut bits) = (0u32, 0u32);
    for c in body.chars() {
        let value = decode_symbol(c).ok_or(RecoveryError::Character)?;
        acc = (acc << 5) | u32::from(value);
        bits += 5;
        if bits >= 8 {
            bits -= 8;
            payload.push(((acc >> bits) & 0xff) as u8);
        }
        acc &= (1 << bits) - 1;
    }
    if payload.len() != KEY_LEN + CHECK_LEN || acc != 0 {
        return Err(RecoveryError::Length);
    }
    let (key_bytes, check) = payload.split_at(KEY_LEN);
    if checksum(key_bytes) != check {
        return Err(RecoveryError::Checksum);
    }
    DbKey::from_slice(key_bytes).ok_or(RecoveryError::Length)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn vectors() -> Vec<(String, String)> {
        let path = concat!(env!("CARGO_MANIFEST_DIR"), "/../../../core/tests/fixtures/recovery_vectors.json");
        let raw = std::fs::read_to_string(path).expect("shared recovery vectors");
        let parsed: Vec<serde_json::Value> = serde_json::from_str(&raw).unwrap();
        parsed
            .iter()
            .map(|v| (v["key_hex"].as_str().unwrap().to_owned(), v["code"].as_str().unwrap().to_owned()))
            .collect()
    }

    fn key_from_hex(hex: &str) -> DbKey {
        let bytes: Vec<u8> =
            (0..hex.len()).step_by(2).map(|i| u8::from_str_radix(&hex[i..i + 2], 16).unwrap()).collect();
        DbKey::from_slice(&bytes).unwrap()
    }

    #[test]
    fn matches_python_vectors() {
        let all = vectors();
        assert!(all.len() >= 4);
        for (hex, code) in all {
            let key = key_from_hex(&hex);
            assert_eq!(encode(&key).as_str(), code);
            assert_eq!(decode(&code).unwrap(), key);
        }
    }

    #[test]
    fn roundtrip_and_forgiving_input() {
        let key = DbKey::generate().unwrap();
        let code = encode(&key);
        assert_eq!(decode(&code).unwrap(), key);
        let messy = format!("  {}  ", code.to_lowercase().replace('-', " "));
        assert_eq!(decode(&messy).unwrap(), key);
    }

    #[test]
    fn detects_typos_and_bad_input() {
        let key = DbKey::generate().unwrap();
        let code = encode(&key).to_string();
        let mut chars: Vec<char> = code.chars().collect();
        chars[7] = if chars[7] == '2' { '3' } else { '2' };
        let typo: String = chars.into_iter().collect();
        assert_eq!(decode(&typo), Err(RecoveryError::Checksum));
        assert_eq!(decode("LZR2-ABCDE"), Err(RecoveryError::Prefix));
        assert_eq!(decode("LZR1-ABC"), Err(RecoveryError::Length));
        let bad = format!("LZR1-{}", "U".repeat(58));
        assert_eq!(decode(&bad), Err(RecoveryError::Character));
    }
}
