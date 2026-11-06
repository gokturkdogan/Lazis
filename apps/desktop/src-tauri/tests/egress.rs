//! The research helper (Phase 12) starts under its own sandbox, answers on its Unix socket,
//! and is gone with its socket directory when dropped. No network request is made.

use std::io::{BufRead, BufReader, Write};
use std::os::unix::net::UnixStream;
use std::time::{Duration, Instant};

use lazis_desktop_lib::egress;
use lazis_desktop_lib::paths;

#[test]
fn helper_answers_on_its_socket_and_cleans_up() {
    let python = paths::backend_python(&paths::core_dir(None, true));
    assert!(python.exists(), "backend venv missing: run `uv sync` in core/");
    let helper = egress::start(&python).expect("helper starts");
    let socket = helper.socket.clone();
    let until = Instant::now() + Duration::from_secs(15);
    let mut stream = loop {
        match UnixStream::connect(&socket) {
            Ok(s) => break s,
            Err(_) if Instant::now() < until => std::thread::sleep(Duration::from_millis(50)),
            Err(e) => panic!("helper never listened: {e}"),
        }
    };
    stream.write_all(b"{\"op\": \"ping\"}\n").unwrap();
    let mut line = String::new();
    BufReader::new(&stream).read_line(&mut line).unwrap();
    assert_eq!(line.trim(), "{\"ok\": true}");
    let dir = socket.parent().unwrap().to_path_buf();
    drop(helper);
    assert!(!dir.exists(), "socket directory removed");
}
