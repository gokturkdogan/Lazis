//! Host security checks shown to the user (read-only; nothing is changed).

use std::process::{Command, Stdio};
use std::thread;
use std::time::{Duration, Instant};

/// FileVault state from `/usr/bin/fdesetup isactive` (exit 0 = on, 1 = off; no admin rights
/// needed). SQLCipher protects the database either way; FileVault also protects logs, swap
/// and everything else on the disk, which the security model assumes.
pub fn filevault_status() -> &'static str {
    let spawned = Command::new("/usr/bin/fdesetup")
        .arg("isactive")
        .env_clear()
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn();
    let Ok(mut child) = spawned else { return "unknown" };
    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        match child.try_wait() {
            Ok(Some(status)) => {
                return match status.code() {
                    Some(0) => "on",
                    Some(1) => "off",
                    _ => "unknown",
                };
            }
            Ok(None) if Instant::now() < deadline => thread::sleep(Duration::from_millis(20)),
            _ => {
                let _ = child.kill();
                let _ = child.wait();
                return "unknown";
            }
        }
    }
}

/// Whether the screen is locked (Phase 15B), from the window server's session dictionary
/// (`CGSSessionScreenIsLocked`, present and true while the lock screen is up). `None` when
/// there is no window-server session (e.g. a test run over SSH). Read-only and cheap.
pub fn screen_locked() -> Option<bool> {
    use std::ffi::c_void;
    type CfRef = *const c_void;
    const UTF8: u32 = 0x0800_0100; // kCFStringEncodingUTF8
    #[link(name = "CoreGraphics", kind = "framework")]
    unsafe extern "C" {
        fn CGSessionCopyCurrentDictionary() -> CfRef;
    }
    #[link(name = "CoreFoundation", kind = "framework")]
    unsafe extern "C" {
        fn CFDictionaryGetValue(dict: CfRef, key: CfRef) -> CfRef;
        fn CFStringCreateWithCString(alloc: CfRef, s: *const std::ffi::c_char, encoding: u32) -> CfRef;
        fn CFGetTypeID(value: CfRef) -> usize;
        fn CFBooleanGetTypeID() -> usize;
        fn CFBooleanGetValue(value: CfRef) -> u8;
        fn CFRelease(value: CfRef);
    }
    // SAFETY: plain CoreFoundation calls on objects this function creates (and releases) or
    // borrows from them for the duration of the call; every pointer is null-checked first.
    unsafe {
        let dict = CGSessionCopyCurrentDictionary();
        if dict.is_null() {
            return None;
        }
        let key = CFStringCreateWithCString(std::ptr::null(), c"CGSSessionScreenIsLocked".as_ptr(), UTF8);
        let locked = if key.is_null() {
            false
        } else {
            let value = CFDictionaryGetValue(dict, key);
            let locked = !value.is_null()
                && CFGetTypeID(value) == CFBooleanGetTypeID()
                && CFBooleanGetValue(value) != 0;
            CFRelease(key);
            locked
        };
        CFRelease(dict);
        Some(locked)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_screen_is_reported_unlocked_while_tests_run() {
        // Tests run on an unlocked desktop (or without a window server: None).
        assert_ne!(screen_locked(), Some(true));
    }

    #[test]
    fn filevault_status_is_one_of_the_known_values() {
        assert!(["on", "off", "unknown"].contains(&filevault_status()));
    }
}
