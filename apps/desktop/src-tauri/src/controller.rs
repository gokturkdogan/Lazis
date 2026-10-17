//! Shell controller: key resolution, backend lifecycle and the recovery flows.
//! Independent of Tauri so it can be tested against the real backend.

use std::collections::VecDeque;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, MutexGuard, OnceLock, Weak};
use std::time::{Duration, Instant};

use serde::Serialize;

use crate::backend::{self, BackendLaunch, BackendProcess, StartError, StopOutcome};
use crate::errors::ShellError;
use crate::keystore::{KeyResolution, KeyStore, resolve_key};
use crate::paths::Profile;
use crate::recovery;
use crate::secrets::{DbKey, SessionToken};
use crate::state_file::{DesktopState, Preferences, now_unix};
use crate::system;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Phase {
    Starting,
    Ready,
    Failed,
    NeedsRecovery,
    Stopped,
}

/// What the UI sees. The token is included only while the backend is ready.
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ConnectionDto {
    pub phase: Phase,
    pub port: Option<u16>,
    pub token: Option<String>,
    pub error_code: Option<String>,
    pub recovery_pending: bool,
    pub profile: String,
    pub data_dir: String,
    pub log_dir: String,
    /// "on" | "off" | "unknown" (`fdesetup isactive`); shown as a privacy warning when off.
    pub file_vault: &'static str,
    /// Automatic restart after an unexpected backend exit: attempt number (1-based) while one
    /// is scheduled or running, 0 otherwise.
    pub restart_attempt: u32,
    pub restart_limit: u32,
}

/// Bounded automatic restart after an unexpected backend exit: at most `max_restarts` within
/// `window`, waiting `base_delay` × 2^(n-1) before the n-th one. Never while the app quits.
#[derive(Debug, Clone, Copy)]
pub struct RestartPolicy {
    pub max_restarts: u32,
    pub window: Duration,
    pub base_delay: Duration,
}

impl Default for RestartPolicy {
    fn default() -> Self {
        Self { max_restarts: 3, window: Duration::from_secs(60), base_delay: Duration::from_secs(1) }
    }
}

type Notifier = Box<dyn Fn(ConnectionDto) + Send + Sync>;

struct Inner {
    phase: Phase,
    error_code: Option<String>,
    token: Option<SessionToken>,
    port: Option<u16>,
    recovery_pending: bool,
    backend: Option<BackendProcess>,
    generation: u64,
    restart_attempt: u32,
}

pub struct Controller {
    profile: Profile,
    launch: BackendLaunch,
    keystore: Arc<dyn KeyStore>,
    notifier: OnceLock<Notifier>,
    inner: Mutex<Inner>,
    /// Serializes start / restore so two backends can never be launched at once.
    op: Mutex<()>,
    shutting_down: AtomicBool,
    file_vault: OnceLock<&'static str>,
    weak_self: Weak<Controller>,
    restart_policy: Mutex<RestartPolicy>,
    restarts: Mutex<VecDeque<Instant>>,
    state_lock: Mutex<()>,
}

fn lock<T>(m: &Mutex<T>) -> MutexGuard<'_, T> {
    m.lock().unwrap_or_else(std::sync::PoisonError::into_inner)
}

impl Controller {
    pub fn new(profile: Profile, launch: BackendLaunch, keystore: Arc<dyn KeyStore>) -> Arc<Self> {
        Arc::new_cyclic(|weak| Self {
            profile,
            launch,
            keystore,
            notifier: OnceLock::new(),
            inner: Mutex::new(Inner {
                phase: Phase::Starting,
                error_code: None,
                token: None,
                port: None,
                recovery_pending: false,
                backend: None,
                generation: 0,
                restart_attempt: 0,
            }),
            op: Mutex::new(()),
            file_vault: OnceLock::new(),
            shutting_down: AtomicBool::new(false),
            weak_self: weak.clone(),
            restart_policy: Mutex::new(RestartPolicy::default()),
            restarts: Mutex::new(VecDeque::new()),
            state_lock: Mutex::new(()),
        })
    }

    pub fn set_restart_policy(&self, policy: RestartPolicy) {
        *lock(&self.restart_policy) = policy;
    }

    pub fn preferences(&self) -> Preferences {
        DesktopState::load(&self.profile.state_path).preferences
    }

    pub fn set_preferences(&self, preferences: Preferences) -> Result<Preferences, ShellError> {
        self.update_state(|s| s.preferences = preferences).map_err(|e| {
            log::error!("desktop_state.save_failed kind={:?}", e.kind());
            ShellError::new("internal_error")
        })?;
        log::info!("shell.preferences_saved");
        Ok(self.preferences())
    }

    /// Read-modify-write of the desktop state file, serialized so that saving preferences can
    /// never undo a concurrent recovery acknowledgement (or the reverse).
    fn update_state(&self, change: impl FnOnce(&mut DesktopState)) -> std::io::Result<()> {
        let _guard = lock(&self.state_lock);
        let mut state = DesktopState::load(&self.profile.state_path);
        change(&mut state);
        state.save(&self.profile.state_path)
    }

    pub fn set_notifier(&self, notifier: impl Fn(ConnectionDto) + Send + Sync + 'static) {
        let _ = self.notifier.set(Box::new(notifier));
    }

    pub fn profile(&self) -> &Profile {
        &self.profile
    }

    pub fn snapshot(&self) -> ConnectionDto {
        let inner = lock(&self.inner);
        let ready = inner.phase == Phase::Ready;
        ConnectionDto {
            phase: inner.phase,
            port: if ready { inner.port } else { None },
            token: if ready { inner.token.as_ref().map(|t| t.as_str().to_owned()) } else { None },
            error_code: inner.error_code.clone(),
            recovery_pending: inner.recovery_pending,
            profile: self.profile.name.clone(),
            data_dir: self.profile.data_dir.display().to_string(),
            log_dir: self.profile.log_dir.display().to_string(),
            file_vault: self.file_vault.get().copied().unwrap_or("unknown"),
            restart_attempt: inner.restart_attempt,
            restart_limit: lock(&self.restart_policy).max_restarts,
        }
    }

    fn notify(&self) {
        if let Some(n) = self.notifier.get() {
            n(self.snapshot());
        }
    }

    fn set_phase(&self, phase: Phase, error_code: Option<&str>) {
        {
            let mut inner = lock(&self.inner);
            inner.phase = phase;
            inner.error_code = error_code.map(str::to_owned);
            if phase != Phase::Ready {
                inner.token = None;
                inner.port = None;
            }
        }
        log::info!("shell.phase phase={phase:?} code={}", error_code.unwrap_or("-"));
        self.notify();
    }

    /// Initial start (called once from a background thread at app launch).
    pub fn start(&self) -> ConnectionDto {
        let _op = lock(&self.op);
        let file_vault = *self.file_vault.get_or_init(system::filevault_status);
        if file_vault == "on" {
            log::info!("shell.filevault status=on");
        } else {
            log::warn!("shell.filevault status={file_vault}");
        }
        let _ = self.start_locked(None);
        self.snapshot()
    }

    /// Retry after a failure. A no-op while starting or already running. A manual retry also
    /// resets the automatic-restart budget (the user asked for it).
    pub fn retry(&self) -> ConnectionDto {
        let Ok(_op) = self.op.try_lock() else { return self.snapshot() };
        let phase = lock(&self.inner).phase;
        if matches!(phase, Phase::Failed | Phase::Stopped | Phase::NeedsRecovery) {
            lock(&self.restarts).clear();
            lock(&self.inner).restart_attempt = 0;
            let _ = self.start_locked(None);
        }
        self.snapshot()
    }

    fn start_locked(&self, candidate: Option<DbKey>) -> Result<(), ShellError> {
        if self.shutting_down.load(Ordering::SeqCst) {
            return Err(ShellError::new("backend_exited"));
        }
        self.set_phase(Phase::Starting, None);
        if let Err(e) = self.profile.ensure_dirs() {
            log::error!("shell.dirs_failed kind={:?}", e.kind());
            self.set_phase(Phase::Failed, Some("backend_start_failed"));
            return Err(ShellError::new("backend_start_failed"));
        }

        let restoring = candidate.is_some();
        let (key, recovery_pending) = match candidate {
            Some(key) => (key, false),
            None => match resolve_key(self.keystore.as_ref(), self.profile.database_exists()) {
                Ok(KeyResolution::Existing(key)) => {
                    log::info!("shell.key source=keychain");
                    (key, DesktopState::load(&self.profile.state_path).recovery_pending())
                }
                Ok(KeyResolution::Generated(key)) => {
                    log::info!("shell.key source=generated");
                    // Keep the desktop preferences if a state file already exists.
                    let saved = self.update_state(|s| {
                        s.key_created_at_unix = Some(now_unix());
                        s.recovery_acknowledged_at_unix = None;
                    });
                    if let Err(e) = saved {
                        log::warn!("desktop_state.save_failed kind={:?}", e.kind());
                    }
                    (key, true)
                }
                Ok(KeyResolution::NeedsRecovery) => {
                    log::warn!("shell.key source=missing database_exists=true");
                    self.set_phase(Phase::NeedsRecovery, Some("database_key_missing"));
                    return Err(ShellError::new("database_key_missing"));
                }
                Err(e) => {
                    log::error!("shell.key_failed code={}", e.code);
                    self.set_phase(Phase::Failed, Some(&e.code));
                    return Err(e);
                }
            },
        };

        let token = match SessionToken::generate() {
            Ok(t) => t,
            Err(e) => {
                self.set_phase(Phase::Failed, Some(&e.code));
                return Err(e);
            }
        };
        let generation = {
            let mut inner = lock(&self.inner);
            inner.generation += 1;
            inner.generation
        };
        let weak = self.weak_self.clone();
        let result = backend::start(&self.launch, &token, &key, move || {
            if let Some(controller) = weak.upgrade() {
                controller.on_unexpected_exit(generation);
            }
        });

        let process = match result {
            Ok(p) => p,
            Err(StartError::Fatal(code)) if code == "database_key_invalid" => {
                self.set_phase(Phase::NeedsRecovery, Some("database_key_invalid"));
                return Err(ShellError::new(if restoring {
                    "recovery_code_wrong_database"
                } else {
                    "database_key_invalid"
                }));
            }
            Err(e) => {
                self.set_phase(Phase::Failed, Some(e.code()));
                return Err(ShellError::new(e.code()));
            }
        };

        if restoring {
            // The code opened the database: make it the stored key again. If that fails the
            // backend must not keep running on a key that would be lost on the next launch.
            let stored = self.keystore.store(&key).and_then(|()| self.keystore.load());
            if !matches!(stored, Ok(Some(ref k)) if *k == key) {
                let code = stored.err().map_or("keychain_unavailable", |e| e.code());
                log::error!("shell.restore_store_failed code={code}");
                process.shutdown();
                self.set_phase(Phase::NeedsRecovery, Some(code));
                return Err(ShellError::new(code));
            }
            let saved = self.update_state(|s| s.recovery_acknowledged_at_unix = Some(now_unix()));
            if let Err(e) = saved {
                log::warn!("desktop_state.save_failed kind={:?}", e.kind());
            }
            log::info!("shell.restored");
        }

        {
            let mut inner = lock(&self.inner);
            // Checked under the lock: `shutdown()` sets the flag before taking this lock, so
            // either it sees this backend or this start sees the flag.
            if self.shutting_down.load(Ordering::SeqCst) {
                drop(inner);
                process.shutdown();
                return Err(ShellError::new("backend_exited"));
            }
            inner.port = Some(process.port);
            inner.token = Some(token);
            inner.recovery_pending = recovery_pending;
            inner.backend = Some(process);
            inner.phase = Phase::Ready;
            inner.error_code = None;
            inner.restart_attempt = 0;
        }
        log::info!("shell.phase phase=Ready code=-");
        self.notify();
        Ok(())
    }

    fn on_unexpected_exit(&self, generation: u64) {
        let process = {
            let mut inner = lock(&self.inner);
            if inner.generation != generation || inner.phase != Phase::Ready {
                return;
            }
            inner.backend.take()
        };
        log::error!("backend.exited_unexpectedly");
        if let Some(p) = process {
            p.shutdown(); // reap
        }
        self.schedule_restart();
    }

    /// Decide on an automatic restart after an unexpected exit (bounded, with backoff).
    fn schedule_restart(&self) {
        let policy = *lock(&self.restart_policy);
        let attempt = {
            let mut times = lock(&self.restarts);
            let now = Instant::now();
            while times.front().is_some_and(|t| now.duration_since(*t) > policy.window) {
                times.pop_front();
            }
            if self.shutting_down.load(Ordering::SeqCst) || times.len() as u32 >= policy.max_restarts {
                None
            } else {
                times.push_back(now);
                Some(times.len() as u32)
            }
        };
        let Some(attempt) = attempt else {
            let limit_reached = !self.shutting_down.load(Ordering::SeqCst);
            lock(&self.inner).restart_attempt = 0;
            log::error!("backend.restart_not_attempted limit_reached={limit_reached}");
            self.set_phase(
                Phase::Failed,
                Some(if limit_reached { "backend_restart_limit" } else { "backend_exited" }),
            );
            return;
        };
        lock(&self.inner).restart_attempt = attempt;
        self.set_phase(Phase::Failed, Some("backend_exited"));
        let delay = policy.base_delay * 2u32.saturating_pow(attempt - 1);
        log::warn!("backend.restart_scheduled attempt={attempt} delay_ms={}", delay.as_millis());
        let weak = self.weak_self.clone();
        let spawned = std::thread::Builder::new().name("backend-restart".into()).spawn(move || {
            std::thread::sleep(delay);
            if let Some(controller) = weak.upgrade() {
                controller.run_scheduled_restart(attempt);
            }
        });
        if spawned.is_err() {
            lock(&self.inner).restart_attempt = 0;
        }
    }

    fn run_scheduled_restart(&self, attempt: u32) {
        let _op = lock(&self.op); // never two starts at once
        let still_wanted = {
            let inner = lock(&self.inner);
            inner.phase == Phase::Failed
                && inner.restart_attempt == attempt
                && inner.error_code.as_deref() == Some("backend_exited")
        };
        if !still_wanted || self.shutting_down.load(Ordering::SeqCst) {
            return; // the user retried, quit, or something else changed meanwhile
        }
        log::info!("backend.restarting attempt={attempt}");
        if self.start_locked(None).is_err() {
            lock(&self.inner).restart_attempt = 0;
            self.notify();
        }
    }

    /// The Mac woke from sleep: report the backend's real state so the UI can re-check.
    pub fn on_wake(&self) -> ConnectionDto {
        log::info!("shell.system_woke phase={:?}", lock(&self.inner).phase);
        self.snapshot()
    }

    pub fn reveal_recovery_code(&self) -> Result<String, ShellError> {
        {
            let inner = lock(&self.inner);
            if !inner.recovery_pending || inner.phase != Phase::Ready {
                return Err(ShellError::new("recovery_not_available"));
            }
        }
        match self.keystore.load() {
            Ok(Some(key)) => {
                log::info!("shell.recovery_code_revealed");
                Ok(recovery::encode(&key).to_string())
            }
            Ok(None) => Err(ShellError::new("recovery_not_available")),
            Err(e) => Err(ShellError::new(e.code())),
        }
    }

    pub fn acknowledge_recovery(&self) -> Result<ConnectionDto, ShellError> {
        if !lock(&self.inner).recovery_pending {
            return Ok(self.snapshot());
        }
        self.update_state(|s| s.recovery_acknowledged_at_unix = Some(now_unix())).map_err(|e| {
            log::error!("desktop_state.save_failed kind={:?}", e.kind());
            ShellError::new("internal_error")
        })?;
        lock(&self.inner).recovery_pending = false;
        log::info!("shell.recovery_acknowledged");
        self.notify();
        Ok(self.snapshot())
    }

    pub fn restore_from_recovery_code(&self, code: &str) -> Result<ConnectionDto, ShellError> {
        if lock(&self.inner).phase != Phase::NeedsRecovery {
            return Err(ShellError::new("recovery_not_available"));
        }
        let key = recovery::decode(code).map_err(|e| {
            log::warn!("shell.recovery_code_rejected reason={e:?}");
            ShellError::new("recovery_code_invalid")
        })?;
        let _op = lock(&self.op);
        if lock(&self.inner).phase != Phase::NeedsRecovery {
            return Err(ShellError::new("recovery_not_available"));
        }
        self.start_locked(Some(key))?;
        Ok(self.snapshot())
    }

    /// Stop the backend (app exit). Does not wait for an in-flight start: that start sees
    /// `shutting_down` and stops its own process, and if this process exits first the closed
    /// lifeline makes the backend shut itself down.
    pub fn shutdown(&self) -> Option<StopOutcome> {
        self.shutting_down.store(true, Ordering::SeqCst);
        let process = {
            let mut inner = lock(&self.inner);
            inner.phase = Phase::Stopped;
            inner.token = None;
            inner.port = None;
            inner.backend.take()
        };
        let outcome = process.map(BackendProcess::shutdown);
        log::info!("shell.shutdown backend={outcome:?}");
        outcome
    }

    /// Test helper: the running backend's pid.
    pub fn backend_pid(&self) -> Option<u32> {
        lock(&self.inner).backend.as_ref().map(|b| b.pid)
    }
}
