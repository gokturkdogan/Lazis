//! LAZIS desktop shell: window, Keychain-held database key, and the managed backend process.
//!
//! The webview never sees the database key. It receives only the backend port and the
//! per-launch session token (via `backend_connection` / the connection event).

pub mod backend;
pub mod controller;
pub mod errors;
pub mod keystore;
pub mod paths;
pub mod recovery;
pub mod secrets;
pub mod state_file;
pub mod system;

use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use tauri::{Emitter, Manager, RunEvent, State};
use tauri_plugin_log::{RotationStrategy, Target, TargetKind};
use zeroize::Zeroizing;

use crate::backend::BackendLaunch;
use crate::controller::{ConnectionDto, Controller};
use crate::errors::ShellError;
use crate::keystore::KeychainStore;
use crate::paths::{KEYCHAIN_SERVICE, Profile};

pub const CONNECTION_EVENT: &str = "lazis://backend-connection";
const MAIN_WINDOW: &str = "main";

type Shared = Arc<Controller>;

async fn blocking<T: Send + 'static>(
    controller: &Shared,
    f: impl FnOnce(&Controller) -> Result<T, ShellError> + Send + 'static,
) -> Result<T, ShellError> {
    let controller = Arc::clone(controller);
    tauri::async_runtime::spawn_blocking(move || f(&controller))
        .await
        .map_err(|_| ShellError::new("internal_error"))?
}

#[tauri::command]
fn backend_connection(state: State<'_, Shared>) -> ConnectionDto {
    state.snapshot()
}

#[tauri::command]
async fn retry_backend(state: State<'_, Shared>) -> Result<ConnectionDto, ShellError> {
    blocking(&state, |c| Ok(c.retry())).await
}

#[tauri::command]
async fn reveal_recovery_code(state: State<'_, Shared>) -> Result<String, ShellError> {
    blocking(&state, Controller::reveal_recovery_code).await
}

#[tauri::command]
async fn acknowledge_recovery(state: State<'_, Shared>) -> Result<ConnectionDto, ShellError> {
    blocking(&state, Controller::acknowledge_recovery).await
}

#[tauri::command]
async fn restore_from_recovery_code(
    state: State<'_, Shared>,
    code: String,
) -> Result<ConnectionDto, ShellError> {
    // The code is equivalent to the key: wipe this copy when done (the IPC layer's own
    // buffers are outside our control).
    let code = Zeroizing::new(code);
    blocking(&state, move |c| c.restore_from_recovery_code(&code)).await
}

fn resolve_profile(debug: bool) -> Result<Profile, ShellError> {
    let home =
        std::env::var_os("HOME").map(PathBuf::from).ok_or_else(|| ShellError::new("config_invalid"))?;
    let requested = std::env::var("LAZIS_PROFILE").ok();
    Profile::resolve(&home, requested.as_deref(), debug)
}

fn log_plugin(profile: &Profile, debug: bool) -> tauri::plugin::TauriPlugin<tauri::Wry> {
    let mut targets = vec![Target::new(TargetKind::Folder {
        path: profile.log_dir.clone(),
        file_name: Some("desktop".into()),
    })];
    if debug {
        targets.push(Target::new(TargetKind::Stdout));
    }
    tauri_plugin_log::Builder::new()
        .clear_targets()
        .targets(targets)
        .level(log::LevelFilter::Info)
        // Framework internals can log IPC details; keep them quiet.
        .level_for("tauri", log::LevelFilter::Warn)
        .level_for("wry", log::LevelFilter::Warn)
        .level_for("tao", log::LevelFilter::Warn)
        .max_file_size(5 * 1024 * 1024)
        .rotation_strategy(RotationStrategy::KeepSome(5))
        .build()
}

pub fn run() {
    // Everything the shell creates (logs, desktop state, directories) is owner-only.
    // SAFETY: umask(2) only changes this process's file-creation mask.
    unsafe {
        libc::umask(0o077);
    }
    let debug = cfg!(debug_assertions);
    let profile = match resolve_profile(debug) {
        Ok(p) => p,
        Err(e) => {
            eprintln!("lazis: invalid profile ({}); LAZIS_PROFILE must match [a-z0-9-]{{1,32}}", e.code);
            std::process::exit(2);
        }
    };
    if let Err(e) = profile.ensure_dirs() {
        eprintln!("lazis: cannot create profile directories ({:?})", e.kind());
        std::process::exit(2);
    }

    let core_dir = paths::core_dir(std::env::var("LAZIS_CORE_DIR").ok().as_deref(), debug);
    let launch = BackendLaunch {
        python: paths::backend_python(&core_dir),
        environment: if debug { "development" } else { "production" },
        data_dir: profile.data_dir.clone(),
        log_dir: profile.log_dir.clone(),
        config_path: profile.config_path.clone(),
        startup_timeout: Duration::from_secs(30),
        shutdown_grace: Duration::from_secs(7),
    };
    let keystore = Arc::new(KeychainStore::new(KEYCHAIN_SERVICE, &profile.keychain_account));
    let controller = Controller::new(profile.clone(), launch, keystore);

    let app = tauri::Builder::default()
        // Must be first: a second launch focuses the existing window instead of starting a
        // second shell (the backend additionally holds a per-profile file lock).
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            if let Some(window) = app.get_webview_window(MAIN_WINDOW) {
                let _ = window.unminimize();
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .plugin(log_plugin(&profile, debug))
        .manage(Arc::clone(&controller))
        .invoke_handler(tauri::generate_handler![
            backend_connection,
            retry_backend,
            reveal_recovery_code,
            acknowledge_recovery,
            restore_from_recovery_code
        ])
        .setup(move |app| {
            log::info!(
                "shell.starting version={} profile={} debug={debug}",
                env!("CARGO_PKG_VERSION"),
                controller.profile().name
            );
            let handle = app.handle().clone();
            controller.set_notifier(move |dto| {
                if let Err(e) = handle.emit_to(MAIN_WINDOW, CONNECTION_EVENT, dto) {
                    log::warn!("shell.emit_failed {e}");
                }
            });
            let starter = Arc::clone(&controller);
            std::thread::Builder::new().name("backend-start".into()).spawn(move || {
                starter.start();
            })?;
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build the LAZIS desktop app");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            handle.state::<Shared>().shutdown();
        }
    });
}
