//! LAZIS desktop shell: window, Keychain-held database key, and the managed backend process.
//!
//! The webview never sees the database key. It receives only the backend port and the
//! per-launch session token (via `backend_connection` / the connection event).
//!
//! Phase 4 adds the menu-bar item, close-to-menu-bar, sleep/wake detection, desktop
//! preferences, on-demand process memory for the diagnostics panel, a navigation guard and a
//! validated way to open confirmed external links.

pub mod backend;
pub mod controller;
pub mod desktop;
pub mod errors;
pub mod keystore;
pub mod metrics;
pub mod paths;
pub mod recovery;
pub mod secrets;
pub mod state_file;
pub mod system;

use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant, SystemTime};

use tauri::image::Image;
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::webview::NewWindowResponse;
use tauri::{AppHandle, Emitter, Manager, RunEvent, State, WebviewUrl, WebviewWindowBuilder, WindowEvent};
use tauri_plugin_log::{RotationStrategy, Target, TargetKind};
use zeroize::Zeroizing;

use crate::backend::BackendLaunch;
use crate::controller::{ConnectionDto, Controller, Phase};
use crate::desktop::TrayStatus;
use crate::errors::ShellError;
use crate::keystore::KeychainStore;
use crate::metrics::ProcessMetrics;
use crate::paths::{KEYCHAIN_SERVICE, Profile};
use crate::state_file::Preferences;

pub const CONNECTION_EVENT: &str = "lazis://backend-connection";
pub const WAKE_EVENT: &str = "lazis://system-woke";
pub const NAVIGATE_EVENT: &str = "lazis://navigate";
const MAIN_WINDOW: &str = "main";
const TRAY_ID: &str = "lazis";

type Shared = Arc<Controller>;

/// The menu bar's status line (a disabled menu item) and tooltip.
struct Tray {
    status_item: MenuItem<tauri::Wry>,
    current: Mutex<TrayStatus>,
}

impl Tray {
    fn set(&self, app: &AppHandle, status: TrayStatus) {
        {
            let mut current = self.current.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
            if *current == status {
                return;
            }
            *current = status;
        }
        let _ = self.status_item.set_text(status.label());
        if let Some(tray) = app.tray_by_id(TRAY_ID) {
            let _ = tray.set_tooltip(Some(status.label()));
        }
    }
}

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

#[tauri::command]
async fn get_preferences(state: State<'_, Shared>) -> Result<Preferences, ShellError> {
    blocking(&state, |c| Ok(c.preferences())).await
}

#[tauri::command]
async fn set_preferences(
    state: State<'_, Shared>,
    preferences: Preferences,
) -> Result<Preferences, ShellError> {
    blocking(&state, move |c| c.set_preferences(preferences)).await
}

#[tauri::command]
fn set_tray_status(app: AppHandle, tray: State<'_, Tray>, status: String) -> Result<(), ShellError> {
    let status = TrayStatus::parse(&status).ok_or_else(|| ShellError::new("invalid_request"))?;
    tray.set(&app, status);
    Ok(())
}

/// Opens a link the user confirmed in the UI, in the default browser. Only validated
/// http(s) URLs; the webview itself never navigates away (see `desktop::navigation_allowed`).
#[tauri::command]
fn open_external_url(url: String) -> Result<(), ShellError> {
    let url = desktop::validate_external_url(&url).ok_or_else(|| ShellError::new("invalid_request"))?;
    desktop::open_in_browser(&url).map_err(|_| ShellError::new("internal_error"))?;
    log::info!("shell.external_link_opened scheme={}", url.scheme()); // never the URL itself
    Ok(())
}

/// Per-process memory (phys_footprint) for the diagnostics panel; read only when asked.
#[tauri::command]
async fn process_metrics(state: State<'_, Shared>) -> Result<ProcessMetrics, ShellError> {
    blocking(&state, |c| Ok(metrics::collect(c.backend_pid()))).await
}

fn show_main_window(app: &AppHandle, view: Option<&str>) {
    if let Some(window) = app.get_webview_window(MAIN_WINDOW) {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
        if let Some(view) = view
            && let Err(e) = app.emit_to(MAIN_WINDOW, NAVIGATE_EVENT, view)
        {
            log::warn!("shell.emit_failed {e}");
        }
    }
}

fn build_main_window(
    app: &AppHandle,
    visible: bool,
    initial_view: Option<&'static str>,
) -> tauri::Result<()> {
    let dev = cfg!(debug_assertions);
    let mut builder = WebviewWindowBuilder::new(app, MAIN_WINDOW, WebviewUrl::default())
        .title("LAZIS")
        .inner_size(1180.0, 760.0)
        .min_inner_size(900.0, 600.0)
        .center()
        .resizable(true)
        .visible(visible)
        .background_color(tauri::window::Color(6, 10, 19, 255))
        .on_navigation(move |url| {
            let allowed = desktop::navigation_allowed(url, dev);
            if !allowed {
                log::warn!("shell.navigation_blocked scheme={}", url.scheme());
            }
            allowed
        })
        .on_new_window(|url, _features| {
            log::warn!("shell.new_window_blocked scheme={}", url.scheme());
            NewWindowResponse::Deny
        });
    if let Some(view) = initial_view {
        // `view` is one of a fixed set of identifiers (desktop::parse_view).
        builder = builder.initialization_script(format!("window.__LAZIS_INITIAL_VIEW__ = {view:?};"));
    }
    builder.build()?;
    Ok(())
}

fn build_tray(app: &AppHandle) -> tauri::Result<Tray> {
    let status_item = MenuItem::with_id(app, "status", TrayStatus::Starting.label(), false, None::<&str>)?;
    let menu = Menu::with_items(
        app,
        &[
            &status_item,
            &PredefinedMenuItem::separator(app)?,
            &MenuItem::with_id(app, "open", "LAZIS'i aç", true, None::<&str>)?,
            &MenuItem::with_id(app, "memory", "Hafıza", true, None::<&str>)?,
            &MenuItem::with_id(app, "diagnostics", "Sistem durumu", true, None::<&str>)?,
            &MenuItem::with_id(app, "settings", "Ayarlar", true, None::<&str>)?,
            &PredefinedMenuItem::separator(app)?,
            &MenuItem::with_id(app, "quit", "LAZIS'ten çık", true, None::<&str>)?,
        ],
    )?;
    let icon = Image::new_owned(desktop::tray_icon_rgba(), desktop::TRAY_ICON_SIZE, desktop::TRAY_ICON_SIZE);
    TrayIconBuilder::with_id(TRAY_ID)
        .icon(icon)
        .icon_as_template(true)
        .tooltip(TrayStatus::Starting.label())
        .menu(&menu)
        .show_menu_on_left_click(true)
        .on_menu_event(|app, event| match event.id().as_ref() {
            "open" => show_main_window(app, None),
            "memory" => show_main_window(app, Some("memory")),
            "diagnostics" => show_main_window(app, Some("diagnostics")),
            "settings" => show_main_window(app, Some("settings")),
            "quit" => app.exit(0),
            _ => {}
        })
        .build(app)?;
    Ok(Tray { status_item, current: Mutex::new(TrayStatus::Starting) })
}

/// One cheap wake-up per `WAKE_POLL`: compares the monotonic and wall clocks (see
/// `desktop::slept_between`) and tells the UI to re-check the backend and runtime.
fn spawn_wake_detector(app: AppHandle) -> std::io::Result<()> {
    std::thread::Builder::new().name("wake-detector".into()).spawn(move || {
        let mut mono = Instant::now();
        let mut wall = SystemTime::now();
        loop {
            std::thread::sleep(desktop::WAKE_POLL);
            let (m, w) = (Instant::now(), SystemTime::now());
            let wall_elapsed = w.duration_since(wall).unwrap_or_default();
            if desktop::slept_between(m.duration_since(mono), wall_elapsed) {
                let dto = app.state::<Shared>().on_wake();
                let _ = app.emit_to(MAIN_WINDOW, CONNECTION_EVENT, dto);
                let _ = app.emit_to(MAIN_WINDOW, WAKE_EVENT, wall_elapsed.as_secs());
            }
            (mono, wall) = (m, w);
        }
    })?;
    Ok(())
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
        .plugin(tauri_plugin_single_instance::init(|app, argv, _cwd| {
            let view = argv.iter().find_map(|a| desktop::parse_view(a));
            log::info!("shell.second_launch view={}", view.unwrap_or("-"));
            show_main_window(app, view);
        }))
        .plugin(log_plugin(&profile, debug))
        .manage(Arc::clone(&controller))
        .invoke_handler(tauri::generate_handler![
            backend_connection,
            retry_backend,
            reveal_recovery_code,
            acknowledge_recovery,
            restore_from_recovery_code,
            get_preferences,
            set_preferences,
            set_tray_status,
            open_external_url,
            process_metrics
        ])
        .on_window_event(|window, event| {
            // Closing the window keeps LAZIS in the menu bar (default) or quits, per preference.
            if let WindowEvent::CloseRequested { api, .. } = event
                && window.label() == MAIN_WINDOW
                && window.app_handle().state::<Shared>().preferences().close_to_menu_bar
            {
                api.prevent_close();
                let _ = window.hide();
                log::info!("shell.window_hidden reason=close_to_menu_bar");
            }
        })
        .setup(move |app| {
            log::info!(
                "shell.starting version={} profile={} debug={debug}",
                env!("CARGO_PKG_VERSION"),
                controller.profile().name
            );
            let preferences = controller.preferences();
            let initial_view = std::env::args().find_map(|a| desktop::parse_view(&a));
            build_main_window(
                app.handle(),
                !preferences.start_hidden || initial_view.is_some(),
                initial_view,
            )?;
            app.manage(build_tray(app.handle())?);
            let handle = app.handle().clone();
            controller.set_notifier(move |dto| {
                // The UI refines Ready into idle/thinking/speaking; other phases are the shell's.
                let status = match dto.phase {
                    Phase::Starting => Some(TrayStatus::Starting),
                    Phase::Failed | Phase::NeedsRecovery => Some(TrayStatus::Error),
                    Phase::Stopped => Some(TrayStatus::Offline),
                    Phase::Ready => None,
                };
                if let Some(status) = status {
                    handle.state::<Tray>().set(&handle, status);
                }
                if let Err(e) = handle.emit_to(MAIN_WINDOW, CONNECTION_EVENT, dto) {
                    log::warn!("shell.emit_failed {e}");
                }
            });
            spawn_wake_detector(app.handle().clone())?;
            let starter = Arc::clone(&controller);
            std::thread::Builder::new().name("backend-start".into()).spawn(move || {
                starter.start();
            })?;
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build the LAZIS desktop app");

    app.run(|handle, event| match event {
        RunEvent::Exit => {
            handle.state::<Shared>().shutdown();
        }
        // Dock icon clicked while the window is hidden in the menu bar.
        RunEvent::Reopen { has_visible_windows: false, .. } => show_main_window(handle, None),
        _ => {}
    });
}
