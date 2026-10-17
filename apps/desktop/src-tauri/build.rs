// Declaring the app's commands makes them subject to the capability ACL: a window may call only
// the commands its capability allows (see capabilities/main.json).
const COMMANDS: &[&str] = &[
    "backend_connection",
    "retry_backend",
    "reveal_recovery_code",
    "acknowledge_recovery",
    "restore_from_recovery_code",
    "get_preferences",
    "set_preferences",
    "set_tray_status",
    "open_external_url",
    "process_metrics",
];

fn main() {
    tauri_build::try_build(
        tauri_build::Attributes::new().app_manifest(tauri_build::AppManifest::new().commands(COMMANDS)),
    )
    .expect("failed to run tauri-build");
}
