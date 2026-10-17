//! Shell controller: key resolution, backend lifecycle and the recovery flows.
//! Independent of Tauri so it can be tested against the real backend.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, MutexGuard, OnceLock, Weak};

use serde::Serialize;

use crate::backend::{self, BackendLaunch, BackendProcess, StartError, StopOutcome};
use crate::errors::ShellError;
use crate::keystore::{KeyResolution, KeyStore, resolve_key};
use crate::paths::Profile;
use crate::recovery;
use crate::secrets::{DbKey, SessionToken};
use crate::state_file::{DesktopState, now_unix};

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
    weak_self: Weak<Controller>,
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
            }),
            op: Mutex::new(()),
            shutting_down: AtomicBool::new(false),
            weak_self: weak.clone(),
        })
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
        let _ = self.start_locked(None);
        self.snapshot()
    }

    /// Retry after a failure. A no-op while starting or already running.
    pub fn retry(&self) -> ConnectionDto {
        let Ok(_op) = self.op.try_lock() else { return self.snapshot() };
        let phase = lock(&self.inner).phase;
        if matches!(phase, Phase::Failed | Phase::Stopped | Phase::NeedsRecovery) {
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
                    let state =
                        DesktopState { key_created_at_unix: Some(now_unix()), ..DesktopState::default() };
                    if let Err(e) = state.save(&self.profile.state_path) {
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
            let state = DesktopState {
                recovery_acknowledged_at_unix: Some(now_unix()),
                ..DesktopState::load(&self.profile.state_path)
            };
            if let Err(e) = state.save(&self.profile.state_path) {
                log::warn!("desktop_state.save_failed kind={:?}", e.kind());
            }
            log::info!("shell.restored");
        }

        if self.shutting_down.load(Ordering::SeqCst) {
            process.shutdown();
            return Err(ShellError::new("backend_exited"));
        }
        {
            let mut inner = lock(&self.inner);
            inner.port = Some(process.port);
            inner.token = Some(token);
            inner.recovery_pending = recovery_pending;
            inner.backend = Some(process);
            inner.phase = Phase::Ready;
            inner.error_code = None;
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
        self.set_phase(Phase::Failed, Some("backend_exited"));
        if let Some(p) = process {
            p.shutdown(); // reap
        }
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
        let state = DesktopState {
            recovery_acknowledged_at_unix: Some(now_unix()),
            ..DesktopState::load(&self.profile.state_path)
        };
        state.save(&self.profile.state_path).map_err(|e| {
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
