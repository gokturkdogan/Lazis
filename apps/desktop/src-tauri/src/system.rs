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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn filevault_status_is_one_of_the_known_values() {
        assert!(["on", "off", "unknown"].contains(&filevault_status()));
    }
}
