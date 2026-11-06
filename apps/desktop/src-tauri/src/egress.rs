//! The research helper process (Phase 12, ADR-0009):
//! `python -I -B -m lazis.providers.web.helper --socket <path>` under `sandbox/egress.sb`.
//!
//! The backend keeps its own profile and never reaches the internet. This helper is the only
//! LAZIS process allowed outbound HTTPS (port 443 and DNS, nothing else), it holds no secret,
//! and it does a web request only when the backend asks for a search the user approved.
//! Its stdin is a lifeline: when the shell goes away the helper stops. If the helper cannot
//! start, the app runs as before and research reports itself unavailable.

use std::fs;
use std::os::unix::fs::DirBuilderExt;
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::thread;
use std::time::{Duration, Instant};

use crate::backend::{SANDBOX_EXEC, for_each_line};

/// Seatbelt profile of the helper, shared with the Python tests.
pub const EGRESS_PROFILE: &str = include_str!("../sandbox/egress.sb");
const READY: &str = "LAZIS_EGRESS_READY";
const MAX_STDERR_LINE: usize = 300;
/// macOS limits a Unix socket path to 104 bytes.
const MAX_SOCKET_PATH: usize = 100;

pub struct EgressHelper {
    child: Child,
    stdin: Option<ChildStdin>,
    dir: PathBuf,
    pub socket: PathBuf,
}

impl std::fmt::Debug for EgressHelper {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("EgressHelper").field("pid", &self.child.id()).finish()
    }
}

/// A fresh owner-only directory for the socket, by its real path (the profile matches real
/// paths: `/tmp` is `/private/tmp`).
fn socket_dir() -> Option<PathBuf> {
    let candidates = [std::env::temp_dir(), PathBuf::from("/private/tmp")];
    for base in candidates {
        let Ok(base) = base.canonicalize() else { continue };
        let dir = base.join(format!("lazis-research-{}", std::process::id()));
        if dir.join("helper.sock").as_os_str().len() > MAX_SOCKET_PATH {
            continue;
        }
        let _ = fs::remove_dir_all(&dir);
        if fs::DirBuilder::new().mode(0o700).create(&dir).is_ok() {
            return Some(dir);
        }
    }
    None
}

/// Start the helper without waiting for it: the backend connects only when the user approves a
/// search, and a missing socket reads as "research unavailable". `None` when it cannot start.
pub fn start(python: &Path) -> Option<EgressHelper> {
    if !python.exists() || !Path::new(SANDBOX_EXEC).exists() {
        log::warn!("egress.unavailable reason=missing_runtime");
        return None;
    }
    let dir = socket_dir()?;
    let socket = dir.join("helper.sock");
    let mut command = Command::new(SANDBOX_EXEC);
    command
        .arg("-p")
        .arg(EGRESS_PROFILE)
        .arg("-D")
        .arg(format!("EGRESS_SOCKET={}", socket.to_string_lossy()))
        .arg(python)
        .args(["-I", "-B", "-m", "lazis.providers.web.helper", "--socket"])
        .arg(&socket)
        .env_clear()
        .current_dir("/")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    for var in ["HOME", "TMPDIR", "LANG"] {
        if let Some(value) = std::env::var_os(var) {
            command.env(var, value);
        }
    }
    command.env("PATH", "/usr/bin:/bin:/usr/sbin:/sbin");
    let mut child = match command.spawn() {
        Ok(child) => child,
        Err(e) => {
            log::warn!("egress.spawn_failed kind={:?}", e.kind());
            let _ = fs::remove_dir_all(&dir);
            return None;
        }
    };
    let stdin = child.stdin.take();
    let pid = child.id();
    let started = Instant::now();
    if let Some(stdout) = child.stdout.take() {
        let _ = thread::Builder::new().name("egress-stdout".into()).spawn(move || {
            let mut ready = false;
            for_each_line(stdout, |line| {
                if !ready && line.trim() == READY {
                    ready = true;
                    log::info!("egress.ready pid={pid} ms={}", started.elapsed().as_millis());
                }
            });
            if !ready {
                log::warn!("egress.exited_before_ready pid={pid}");
            }
        });
    }
    if let Some(stderr) = child.stderr.take() {
        let _ = thread::Builder::new().name("egress-stderr".into()).spawn(move || {
            for_each_line(stderr, |line| {
                let shown: String = line.chars().take(MAX_STDERR_LINE).collect();
                log::warn!("egress.stderr {shown}");
            });
        });
    }
    log::info!("egress.spawned pid={pid}");
    Some(EgressHelper { child, stdin, dir, socket })
}

impl Drop for EgressHelper {
    fn drop(&mut self) {
        drop(self.stdin.take()); // lifeline closed: the helper stops on its own
        let until = Instant::now() + Duration::from_secs(2);
        while Instant::now() < until {
            if let Ok(Some(_)) = self.child.try_wait() {
                break;
            }
            thread::sleep(Duration::from_millis(50));
        }
        if let Ok(None) = self.child.try_wait() {
            let _ = self.child.kill();
            let _ = self.child.wait();
        }
        let _ = fs::remove_dir_all(&self.dir);
    }
}
