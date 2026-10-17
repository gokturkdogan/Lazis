//! Managed backend process (`python -I -m lazis serve --stdin-secrets`).
//!
//! Protocol (see core/src/lazis/app/handshake.py):
//! * stdin: one JSON line with the session token and database key, then kept OPEN as a
//!   lifeline — when this process goes away (even via SIGKILL) the pipe closes and the backend
//!   shuts down gracefully. Secrets never appear in argv or the environment.
//! * stdout: `LAZIS_READY {...}` or `LAZIS_FATAL {...}`; nothing secret is ever written there.
//! * stderr: drained into the shell log (truncated; the backend writes no secrets there).
//!
//! The backend always runs under the OS network sandbox (`sandbox/backend.sb`, applied with
//! `/usr/bin/sandbox-exec`): the kernel refuses every connection to another host, for the
//! backend and anything it starts, including native code. The backend re-checks this itself
//! (`--require-os-sandbox`) and refuses to start if it is not in effect.

use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc;
use std::thread;
use std::time::{Duration, Instant};

use serde::Deserialize;
use zeroize::Zeroizing;

use crate::secrets::{DbKey, SessionToken};

const READY_PREFIX: &str = "LAZIS_READY ";
const FATAL_PREFIX: &str = "LAZIS_FATAL ";
const PROTOCOL: u32 = 1;
pub const API_VERSION: &str = "v1";
const MAX_STDERR_LINE: usize = 500;
pub const SANDBOX_EXEC: &str = "/usr/bin/sandbox-exec";
/// Seatbelt profile, shared with the Python tests (core/tests/security/test_os_sandbox.py).
pub const SANDBOX_PROFILE: &str = include_str!("../sandbox/backend.sb");

#[derive(Debug, Clone)]
pub struct BackendLaunch {
    pub python: PathBuf,
    pub environment: &'static str,
    pub data_dir: PathBuf,
    pub log_dir: PathBuf,
    pub config_path: PathBuf,
    pub startup_timeout: Duration,
    pub shutdown_grace: Duration,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum StartError {
    /// The Python environment is missing (`uv sync` not run).
    NotFound,
    /// `/usr/bin/sandbox-exec` is missing: the backend is never started without the sandbox.
    SandboxUnavailable,
    /// The backend refused to start and said why (e.g. `database_key_invalid`).
    Fatal(String),
    Timeout,
    /// Spawn failure, protocol mismatch, or exit without a handshake.
    Failed,
}

impl StartError {
    pub fn code(&self) -> &str {
        match self {
            Self::NotFound => "backend_not_found",
            Self::SandboxUnavailable => "network_sandbox_unavailable",
            Self::Fatal(code) => code,
            Self::Timeout => "backend_start_timeout",
            Self::Failed => "backend_start_failed",
        }
    }
}

#[derive(Debug, Deserialize)]
struct ReadyLine {
    protocol: u32,
    port: u16,
    pid: u32,
    api_version: String,
}

#[derive(Debug, Deserialize)]
struct FatalLine {
    code: String,
}

enum Handshake {
    Ready(ReadyLine),
    Fatal(String),
    Eof,
}

pub struct BackendProcess {
    child: Child,
    /// The lifeline. Dropping it asks the backend to shut down.
    stdin: Option<ChildStdin>,
    pub port: u16,
    pub pid: u32,
    stopping: Arc<AtomicBool>,
    grace: Duration,
    reaped: bool,
}

impl std::fmt::Debug for BackendProcess {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("BackendProcess").field("pid", &self.pid).field("port", &self.port).finish()
    }
}

fn secrets_line(token: &SessionToken, key: &DbKey) -> Zeroizing<String> {
    let key_hex = key.hex();
    let mut line = Zeroizing::new(String::with_capacity(160));
    line.push_str("{\"version\":1,\"session_token\":\"");
    line.push_str(token.as_str());
    line.push_str("\",\"db_key\":\"");
    line.push_str(&key_hex);
    line.push_str("\"}\n");
    line
}

fn parse_handshake(line: &str) -> Option<Handshake> {
    if let Some(json) = line.strip_prefix(READY_PREFIX) {
        return serde_json::from_str::<ReadyLine>(json).ok().map(Handshake::Ready);
    }
    if let Some(json) = line.strip_prefix(FATAL_PREFIX) {
        let code = serde_json::from_str::<FatalLine>(json).map(|f| f.code).unwrap_or_default();
        let valid =
            !code.is_empty() && code.len() <= 64 && code.bytes().all(|b| b.is_ascii_lowercase() || b == b'_');
        return Some(Handshake::Fatal(if valid { code } else { "backend_start_failed".to_owned() }));
    }
    None
}

/// Start the backend and wait for its handshake. `on_unexpected_exit` runs (on a background
/// thread) if the process later exits without `shutdown()` having been called.
pub fn start(
    launch: &BackendLaunch,
    token: &SessionToken,
    key: &DbKey,
    on_unexpected_exit: impl FnOnce() + Send + 'static,
) -> Result<BackendProcess, StartError> {
    if !launch.python.exists() {
        log::error!("backend.not_found python={}", launch.python.display());
        return Err(StartError::NotFound);
    }
    if !std::path::Path::new(SANDBOX_EXEC).exists() {
        log::error!("backend.sandbox_unavailable path={SANDBOX_EXEC}");
        return Err(StartError::SandboxUnavailable);
    }
    let started = Instant::now();
    // sandbox-exec applies the profile and then execs Python in the same process (same pid).
    let mut command = Command::new(SANDBOX_EXEC);
    command
        .arg("-p")
        .arg(SANDBOX_PROFILE)
        .arg(&launch.python)
        .args(["-I", "-m", "lazis", "serve", "--stdin-secrets", "--require-os-sandbox"])
        .args(["--environment", launch.environment])
        .arg("--data-dir")
        .arg(&launch.data_dir)
        .arg("--log-dir")
        .arg(&launch.log_dir)
        .arg("--config")
        .arg(&launch.config_path)
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

    let mut child = command.spawn().map_err(|e| {
        log::error!("backend.spawn_failed kind={:?}", e.kind());
        StartError::Failed
    })?;
    let pid = child.id();
    log::info!("backend.spawned pid={pid}");

    let mut stdin = child.stdin.take().ok_or(StartError::Failed)?;
    let stdout = child.stdout.take().ok_or(StartError::Failed)?;
    let stderr = child.stderr.take().ok_or(StartError::Failed)?;

    thread::Builder::new()
        .name("backend-stderr".into())
        .spawn(move || {
            for_each_line(stderr, |line| {
                let shown: String = line.chars().take(MAX_STDERR_LINE).collect();
                log::warn!("backend.stderr {shown}");
            });
        })
        .map_err(|_| StartError::Failed)?;

    let write_result = {
        let line = secrets_line(token, key);
        stdin.write_all(line.as_bytes()).and_then(|()| stdin.flush())
    };
    if write_result.is_err() {
        log::error!("backend.secrets_write_failed");
        let _ = child.kill();
        let _ = child.wait();
        return Err(StartError::Failed);
    }

    let stopping = Arc::new(AtomicBool::new(false));
    let (tx, rx) = mpsc::channel::<Handshake>();
    let exit_flag = Arc::clone(&stopping);
    thread::Builder::new()
        .name("backend-stdout".into())
        .spawn(move || {
            let mut handshake_sent = false;
            for_each_line(stdout, |line| {
                if handshake_sent {
                    return;
                }
                if let Some(h) = parse_handshake(line) {
                    handshake_sent = true;
                    let _ = tx.send(h);
                } else {
                    log::debug!("backend.stdout_ignored len={}", line.len());
                }
            });
            if !handshake_sent {
                let _ = tx.send(Handshake::Eof);
            } else if !exit_flag.load(Ordering::SeqCst) {
                on_unexpected_exit();
            }
        })
        .map_err(|_| StartError::Failed)?;

    let fail = |mut child: Child, err: StartError| {
        let _ = child.kill();
        let _ = child.wait();
        Err(err)
    };
    match rx.recv_timeout(launch.startup_timeout) {
        Ok(Handshake::Ready(ready))
            if ready.protocol == PROTOCOL && ready.api_version == API_VERSION && ready.port != 0 =>
        {
            if ready.pid != pid {
                log::warn!("backend.pid_mismatch spawned={pid} reported={}", ready.pid);
            }
            log::info!(
                "backend.ready pid={pid} port={} startup_ms={}",
                ready.port,
                started.elapsed().as_millis()
            );
            Ok(BackendProcess {
                child,
                stdin: Some(stdin),
                port: ready.port,
                pid,
                stopping,
                grace: launch.shutdown_grace,
                reaped: false,
            })
        }
        Ok(Handshake::Ready(_)) => {
            log::error!("backend.protocol_mismatch");
            stopping.store(true, Ordering::SeqCst);
            fail(child, StartError::Failed)
        }
        Ok(Handshake::Fatal(code)) => {
            log::error!("backend.fatal code={code}");
            stopping.store(true, Ordering::SeqCst);
            drop(stdin);
            let _ = wait_with_timeout(&mut child, Duration::from_secs(5));
            fail(child, StartError::Fatal(code))
        }
        Ok(Handshake::Eof) | Err(mpsc::RecvTimeoutError::Disconnected) => {
            let status = child.wait().ok();
            log::error!("backend.exited_before_ready status={status:?}");
            Err(StartError::Failed)
        }
        Err(mpsc::RecvTimeoutError::Timeout) => {
            log::error!("backend.start_timeout after_ms={}", launch.startup_timeout.as_millis());
            stopping.store(true, Ordering::SeqCst);
            fail(child, StartError::Timeout)
        }
    }
}

/// Read until EOF, tolerating invalid UTF-8, so the pipe is always drained and EOF really
/// means the process closed it.
fn for_each_line(stream: impl std::io::Read, mut f: impl FnMut(&str)) {
    let mut reader = BufReader::new(stream);
    let mut buf = Vec::with_capacity(256);
    loop {
        buf.clear();
        match reader.read_until(b'\n', &mut buf) {
            Ok(0) => return,
            Ok(_) => f(String::from_utf8_lossy(&buf).trim_end_matches(['\r', '\n'])),
            Err(e) if e.kind() == std::io::ErrorKind::Interrupted => {}
            Err(_) => return,
        }
    }
}

fn wait_with_timeout(child: &mut Child, timeout: Duration) -> Option<std::process::ExitStatus> {
    let deadline = Instant::now() + timeout;
    loop {
        match child.try_wait() {
            Ok(Some(status)) => return Some(status),
            Ok(None) if Instant::now() < deadline => thread::sleep(Duration::from_millis(25)),
            _ => return None,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StopOutcome {
    /// Exited by itself after the lifeline closed (normal case).
    Graceful,
    /// Needed SIGTERM.
    Terminated,
    /// Needed SIGKILL.
    Killed,
}

impl BackendProcess {
    pub fn is_running(&mut self) -> bool {
        matches!(self.child.try_wait(), Ok(None))
    }

    /// Close the lifeline and wait; escalate to SIGTERM, then SIGKILL. Always reaps the child,
    /// so no zombie or orphan is left behind.
    pub fn shutdown(mut self) -> StopOutcome {
        self.stop()
    }

    fn stop(&mut self) -> StopOutcome {
        self.stopping.store(true, Ordering::SeqCst);
        let started = Instant::now();
        drop(self.stdin.take());
        let outcome = if wait_with_timeout(&mut self.child, self.grace).is_some() {
            StopOutcome::Graceful
        } else {
            log::warn!("backend.shutdown_escalate signal=SIGTERM pid={}", self.pid);
            if let Ok(pid) = i32::try_from(self.pid) {
                // SAFETY: plain kill(2) on our own child's pid; the child is not reaped yet,
                // so the pid cannot have been recycled.
                unsafe {
                    libc::kill(pid, libc::SIGTERM);
                }
            }
            if wait_with_timeout(&mut self.child, Duration::from_secs(3)).is_some() {
                StopOutcome::Terminated
            } else {
                log::error!("backend.shutdown_escalate signal=SIGKILL pid={}", self.pid);
                let _ = self.child.kill();
                let _ = self.child.wait();
                StopOutcome::Killed
            }
        };
        log::info!(
            "backend.stopped pid={} outcome={outcome:?} ms={}",
            self.pid,
            started.elapsed().as_millis()
        );
        self.reaped = true;
        outcome
    }
}

impl Drop for BackendProcess {
    /// A handle dropped without `shutdown()` (panic, early return) still stops the backend.
    fn drop(&mut self) {
        if !self.reaped {
            self.stop();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn handshake_parsing() {
        let ready = parse_handshake(
            r#"LAZIS_READY {"protocol": 1, "port": 5555, "pid": 9, "api_version": "v1", "version": "0.1.0"}"#,
        );
        assert!(matches!(ready, Some(Handshake::Ready(r)) if r.port == 5555 && r.pid == 9));
        let fatal =
            parse_handshake(r#"LAZIS_FATAL {"protocol": 1, "code": "database_key_invalid", "message": "x"}"#);
        assert!(matches!(fatal, Some(Handshake::Fatal(c)) if c == "database_key_invalid"));
        let weird = parse_handshake(r#"LAZIS_FATAL {"code": "<script>"}"#);
        assert!(matches!(weird, Some(Handshake::Fatal(c)) if c == "backend_start_failed"));
        assert!(parse_handshake("hello").is_none());
        assert!(parse_handshake("LAZIS_READY {broken").is_none());
    }

    #[test]
    fn secrets_line_format() {
        let key = DbKey::from_slice(&[0xab; 32]).unwrap();
        let token = SessionToken::generate().unwrap();
        let line = secrets_line(&token, &key);
        assert!(line.ends_with("\"}\n"));
        let v: serde_json::Value = serde_json::from_str(line.trim_end()).unwrap();
        assert_eq!(v["version"], 1);
        assert_eq!(v["db_key"], "ab".repeat(32));
        assert_eq!(v["session_token"], token.as_str());
    }
}
