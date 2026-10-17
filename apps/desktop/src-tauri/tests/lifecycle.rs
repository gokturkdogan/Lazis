//! Shell ↔ real backend lifecycle tests. They spawn `core/.venv/bin/python -m lazis serve`
//! (run `uv sync` in core/ first) against temporary profiles with an in-memory key store, so
//! the real Keychain and real user data are never touched. Synthetic data only.

use std::io::{Read, Write};
use std::net::TcpStream;
use std::path::Path;
use std::sync::Arc;
use std::time::{Duration, Instant};

use lazis_desktop_lib::backend::{self, BackendLaunch, StopOutcome};
use lazis_desktop_lib::controller::{Controller, Phase};
use lazis_desktop_lib::keystore::{KeyStore, MemoryKeyStore};
use lazis_desktop_lib::paths::{self, Profile};
use lazis_desktop_lib::recovery;
use lazis_desktop_lib::secrets::{DbKey, SessionToken};

fn launch_for(profile: &Profile) -> BackendLaunch {
    let python = paths::backend_python(&paths::core_dir(None, true));
    assert!(python.exists(), "backend venv missing: run `uv sync` in core/ ({})", python.display());
    BackendLaunch {
        python,
        environment: "test",
        data_dir: profile.data_dir.clone(),
        log_dir: profile.log_dir.clone(),
        config_path: profile.config_path.clone(),
        startup_timeout: Duration::from_secs(30),
        shutdown_grace: Duration::from_secs(7),
    }
}

fn controller(home: &Path, store: Arc<MemoryKeyStore>) -> Arc<Controller> {
    let profile = Profile::resolve(home, Some("itest"), true).unwrap();
    let launch = launch_for(&profile);
    Controller::new(profile, launch, store)
}

fn http_get(port: u16, path: &str, token: Option<&str>) -> (u16, String) {
    let mut stream = TcpStream::connect(("127.0.0.1", port)).unwrap();
    stream.set_read_timeout(Some(Duration::from_secs(5))).unwrap();
    let auth = token.map(|t| format!("Authorization: Bearer {t}\r\n")).unwrap_or_default();
    write!(stream, "GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n{auth}Connection: close\r\n\r\n")
        .unwrap();
    let mut response = String::new();
    stream.read_to_string(&mut response).unwrap();
    let status = response.split_whitespace().nth(1).and_then(|s| s.parse().ok()).unwrap_or(0);
    let body = response.split_once("\r\n\r\n").map(|(_, b)| b.to_owned()).unwrap_or_default();
    (status, body)
}

fn process_alive(pid: u32) -> bool {
    // SAFETY: signal 0 only checks for existence/permission.
    unsafe { libc::kill(pid as i32, 0) == 0 }
}

/// argv + environment of a same-user process, as the kernel reports them (KERN_PROCARGS2).
fn process_args_and_environment(pid: u32) -> String {
    let mut mib = [libc::CTL_KERN, libc::KERN_PROCARGS2, pid as i32];
    let mut size: libc::size_t = 0;
    // SAFETY: standard two-call sysctl pattern with a correctly sized buffer.
    let rc = unsafe {
        libc::sysctl(mib.as_mut_ptr(), 3, std::ptr::null_mut(), &mut size, std::ptr::null_mut(), 0)
    };
    assert_eq!(rc, 0);
    let mut buf = vec![0u8; size];
    let rc = unsafe {
        libc::sysctl(mib.as_mut_ptr(), 3, buf.as_mut_ptr().cast(), &mut size, std::ptr::null_mut(), 0)
    };
    assert_eq!(rc, 0);
    buf.truncate(size);
    String::from_utf8_lossy(&buf).replace('\0', " ")
}

fn wait_until(timeout: Duration, mut condition: impl FnMut() -> bool) -> bool {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if condition() {
            return true;
        }
        std::thread::sleep(Duration::from_millis(50));
    }
    condition()
}

/// Contents of every database file in the profile (the lock file is excluded).
fn data_fingerprint(profile: &Profile) -> Vec<(String, Vec<u8>)> {
    let mut files: Vec<(String, Vec<u8>)> = std::fs::read_dir(&profile.data_dir)
        .unwrap()
        .flatten()
        .filter(|e| e.file_name().to_string_lossy().starts_with("lazis.db"))
        .map(|e| (e.file_name().to_string_lossy().into_owned(), std::fs::read(e.path()).unwrap()))
        .collect();
    files.sort();
    assert!(!files.is_empty());
    files
}

fn assert_encrypted_database(profile: &Profile) {
    let db = std::fs::read(profile.data_dir.join("lazis.db")).expect("database file");
    assert!(db.len() >= 4096);
    assert_ne!(&db[..16], b"SQLite format 3\0", "database must not be plaintext");
}

#[test]
fn first_run_restart_and_recovery_flow() {
    let home = tempfile::tempdir().unwrap();
    let store = Arc::new(MemoryKeyStore::default());

    // 1. First run: key generated, stored, backend ready, recovery code pending.
    let c = controller(home.path(), Arc::clone(&store));
    let dto = c.start();
    assert_eq!(dto.phase, Phase::Ready, "{dto:?}");
    assert!(dto.recovery_pending);
    let (port, token) = (dto.port.unwrap(), dto.token.clone().unwrap());
    let (status, body) = http_get(port, "/api/v1/health", Some(&token));
    assert_eq!(status, 200, "{body}");
    assert!(body.contains("\"status\":\"ok\""), "{body}");
    let (status, body) = http_get(port, "/api/v1/system/status", Some(&token));
    assert_eq!(status, 200, "{body}");
    assert!(body.contains("\"encrypted\":true"), "{body}");
    // The backend runs under the OS network sandbox and confirmed it itself.
    assert!(body.contains("\"os_network_sandbox\":\"enforced\""), "{body}");
    assert!(["on", "off", "unknown"].contains(&dto.file_vault));
    assert_eq!(http_get(port, "/api/v1/health", None).0, 401);
    let key = store.load().unwrap().expect("key stored before the database was created");
    let code = c.reveal_recovery_code().unwrap();
    assert_eq!(recovery::decode(&code).unwrap(), key);
    assert!(!c.acknowledge_recovery().unwrap().recovery_pending);
    assert_eq!(c.reveal_recovery_code().unwrap_err().code, "recovery_not_available");
    let pid = c.backend_pid().unwrap();
    assert_eq!(c.shutdown(), Some(StopOutcome::Graceful));
    assert!(!process_alive(pid), "backend must be gone after shutdown");
    assert_eq!(c.snapshot().phase, Phase::Stopped);
    assert!(c.snapshot().token.is_none());
    let profile = c.profile().clone();
    assert_encrypted_database(&profile);
    drop(c);

    // 2. Restart: same key from the store, acknowledgement remembered, new session token.
    let c = controller(home.path(), Arc::clone(&store));
    let dto = c.start();
    assert_eq!(dto.phase, Phase::Ready);
    assert!(!dto.recovery_pending);
    assert_ne!(dto.token.as_deref(), Some(token.as_str()), "token must be per-launch");
    assert_eq!(http_get(dto.port.unwrap(), "/api/v1/health", Some(&token)).0, 401, "old token rejected");
    c.shutdown();
    drop(c);

    // 3. Keychain item lost while the database exists → needs recovery; no new key generated.
    let empty = Arc::new(MemoryKeyStore::default());
    let c = controller(home.path(), Arc::clone(&empty));
    let dto = c.start();
    assert_eq!(dto.phase, Phase::NeedsRecovery);
    assert_eq!(dto.error_code.as_deref(), Some("database_key_missing"));
    assert!(empty.load().unwrap().is_none());
    assert_eq!(c.retry().phase, Phase::NeedsRecovery);

    let before = data_fingerprint(&profile);
    // 3a. Malformed code.
    assert_eq!(c.restore_from_recovery_code("LZR1-NOPE").unwrap_err().code, "recovery_code_invalid");
    // 3a'. Right length, one character changed (checksum catches it).
    let mut corrupted: Vec<char> = code.chars().collect();
    corrupted[10] = if corrupted[10] == 'X' { 'Y' } else { 'X' };
    let corrupted: String = corrupted.into_iter().collect();
    assert_eq!(c.restore_from_recovery_code(&corrupted).unwrap_err().code, "recovery_code_invalid");
    // 3b. Well-formed code for a different key: refused, nothing stored.
    let other = recovery::encode(&DbKey::generate().unwrap());
    assert_eq!(c.restore_from_recovery_code(&other).unwrap_err().code, "recovery_code_wrong_database");
    assert_eq!(c.snapshot().phase, Phase::NeedsRecovery);
    assert!(empty.load().unwrap().is_none());
    // Failed attempts never modify the encrypted database.
    assert_eq!(data_fingerprint(&profile), before, "a failed recovery attempt changed the database");
    // 3c. Correct code (typed sloppily): database opens, key is stored again.
    let sloppy = code.to_lowercase().replace('-', " ");
    let dto = c.restore_from_recovery_code(&sloppy).unwrap();
    assert_eq!(dto.phase, Phase::Ready);
    assert!(!dto.recovery_pending);
    assert_eq!(empty.load().unwrap(), Some(key));
    assert_eq!(http_get(dto.port.unwrap(), "/api/v1/health", dto.token.as_deref()).0, 200);
    c.shutdown();
}

#[test]
fn wrong_key_in_keychain_needs_recovery() {
    let home = tempfile::tempdir().unwrap();
    let store = Arc::new(MemoryKeyStore::default());
    let c = controller(home.path(), Arc::clone(&store));
    assert_eq!(c.start().phase, Phase::Ready);
    c.shutdown();
    let profile = c.profile().clone();
    drop(c);
    let before = data_fingerprint(&profile);

    let wrong = Arc::new(MemoryKeyStore::with_key(DbKey::generate().unwrap()));
    let c = controller(home.path(), wrong);
    let dto = c.start();
    assert_eq!(dto.phase, Phase::NeedsRecovery);
    assert_eq!(dto.error_code.as_deref(), Some("database_key_invalid"));
    assert!(c.backend_pid().is_none());
    assert_eq!(data_fingerprint(&profile), before, "opening with a wrong key changed the database");
}

#[test]
fn unexpected_backend_exit_is_reported_and_retry_recovers() {
    let home = tempfile::tempdir().unwrap();
    let c = controller(home.path(), Arc::new(MemoryKeyStore::default()));
    assert_eq!(c.start().phase, Phase::Ready);
    let pid = c.backend_pid().unwrap();
    // SAFETY: SIGKILL to the backend we just started.
    unsafe {
        libc::kill(pid as i32, libc::SIGKILL);
    }
    assert!(wait_until(Duration::from_secs(10), || c.snapshot().phase == Phase::Failed));
    assert_eq!(c.snapshot().error_code.as_deref(), Some("backend_exited"));
    assert!(c.snapshot().token.is_none());
    let dto = c.retry();
    assert_eq!(dto.phase, Phase::Ready, "{dto:?}");
    assert_ne!(c.backend_pid(), Some(pid));
    c.shutdown();
}

#[test]
fn missing_backend_runtime_fails_clearly() {
    let home = tempfile::tempdir().unwrap();
    let profile = Profile::resolve(home.path(), Some("itest"), true).unwrap();
    let mut launch = launch_for(&profile);
    launch.python = home.path().join("does-not-exist/python");
    let c = Controller::new(profile, launch, Arc::new(MemoryKeyStore::default()));
    let dto = c.start();
    assert_eq!(dto.phase, Phase::Failed);
    assert_eq!(dto.error_code.as_deref(), Some("backend_not_found"));
}

#[test]
fn dropped_handle_still_stops_and_reaps_the_backend() {
    let home = tempfile::tempdir().unwrap();
    let profile = Profile::resolve(home.path(), Some("itest"), true).unwrap();
    profile.ensure_dirs().unwrap();
    let launch = launch_for(&profile);
    let process =
        backend::start(&launch, &SessionToken::generate().unwrap(), &DbKey::generate().unwrap(), || {})
            .unwrap();
    let pid = process.pid;
    assert!(process_alive(pid));
    drop(process);
    assert!(!process_alive(pid), "no orphan or zombie after drop");
}

#[test]
fn second_backend_on_same_profile_is_refused() {
    let home = tempfile::tempdir().unwrap();
    let profile = Profile::resolve(home.path(), Some("itest"), true).unwrap();
    profile.ensure_dirs().unwrap();
    let launch = launch_for(&profile);
    let key = DbKey::generate().unwrap();
    let first = backend::start(&launch, &SessionToken::generate().unwrap(), &key, || {}).unwrap();
    let second = backend::start(&launch, &SessionToken::generate().unwrap(), &key, || {});
    assert_eq!(second.unwrap_err().code(), "instance_already_running");
    assert_eq!(first.shutdown(), StopOutcome::Graceful);
}

#[test]
fn secrets_never_in_backend_argv_environment_or_logs() {
    let home = tempfile::tempdir().unwrap();
    let store = Arc::new(MemoryKeyStore::default());
    let c = controller(home.path(), Arc::clone(&store));
    let dto = c.start();
    assert_eq!(dto.phase, Phase::Ready);
    let token = dto.token.unwrap();
    let key_hex = store.load().unwrap().unwrap().hex().to_string();
    let code = c.reveal_recovery_code().unwrap();
    let listing = process_args_and_environment(c.backend_pid().unwrap());
    assert!(listing.contains("--stdin-secrets"), "argv not captured");
    assert!(listing.contains("HOME="), "environment not captured");
    c.shutdown();
    let core_log = std::fs::read_to_string(c.profile().log_dir.join("core.log")).unwrap();
    assert!(core_log.contains("app.ready"));
    for secret in [token.as_str(), key_hex.as_str(), code.as_str()] {
        assert!(!listing.contains(secret), "secret visible in the process listing");
        assert!(!core_log.contains(secret), "secret leaked into core.log");
    }
}
