//! Per-process memory for the diagnostics panel, read on demand (only while the panel is open).
//!
//! Source: the kernel's `phys_footprint` (`proc_pid_rusage`, RUSAGE_INFO_V2), the value Activity
//! Monitor shows as "Memory". It is per process, not system RAM, and it needs no extra
//! permissions for processes of the same user. A process that cannot be read is reported as
//! unknown, never estimated.

use serde::Serialize;

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct ProcessMemory {
    /// "shell" | "backend" | "ollama_server" | "ollama_runner"
    pub role: &'static str,
    pub pid: u32,
    /// `None` when the kernel refused or the process exited meanwhile.
    pub footprint_bytes: Option<u64>,
}

#[derive(Debug, Clone, Serialize)]
pub struct ProcessMetrics {
    pub source: &'static str,
    pub processes: Vec<ProcessMemory>,
    /// The Ollama server was not found among this user's processes.
    pub ollama_found: bool,
}

pub fn footprint_bytes(pid: u32) -> Option<u64> {
    let pid = i32::try_from(pid).ok()?;
    // SAFETY: rusage_info_v2 is plain data; the kernel fills it for RUSAGE_INFO_V2.
    let mut info: libc::rusage_info_v2 = unsafe { std::mem::zeroed() };
    let rc = unsafe {
        libc::proc_pid_rusage(pid, libc::RUSAGE_INFO_V2, (&raw mut info).cast::<libc::rusage_info_t>())
    };
    (rc == 0).then_some(info.ri_phys_footprint)
}

fn process_name(pid: i32) -> Option<String> {
    let mut buf = [0u8; 256];
    // SAFETY: the buffer and its length are passed together.
    let n = unsafe { libc::proc_name(pid, buf.as_mut_ptr().cast(), buf.len() as u32) };
    (n > 0).then(|| String::from_utf8_lossy(&buf[..n as usize]).into_owned())
}

fn parent_pid(pid: i32) -> Option<i32> {
    // SAFETY: proc_bsdinfo is plain data, sized by the call.
    let mut info: libc::proc_bsdinfo = unsafe { std::mem::zeroed() };
    let size = std::mem::size_of::<libc::proc_bsdinfo>() as i32;
    let n = unsafe { libc::proc_pidinfo(pid, libc::PROC_PIDTBSDINFO, 0, (&raw mut info).cast(), size) };
    (n == size).then_some(info.pbi_ppid as i32)
}

fn pid_list(fill: impl Fn(*mut libc::c_void, i32) -> i32) -> Vec<i32> {
    let mut pids = vec![0i32; 4096];
    let bytes = (pids.len() * std::mem::size_of::<i32>()) as i32;
    let n = fill(pids.as_mut_ptr().cast(), bytes);
    if n <= 0 {
        return Vec::new();
    }
    // proc_listallpids returns a count; proc_listchildpids returns a count too on macOS 14+.
    pids.truncate((n as usize).min(pids.len()));
    pids.retain(|p| *p > 0);
    pids
}

/// The Ollama server: a process named `ollama` whose parent is not itself an `ollama` process
/// (Ollama's runners can carry the same name).
fn ollama_server() -> Option<i32> {
    // SAFETY: buffer pointer and size come from pid_list.
    let all = pid_list(|buf, size| unsafe { libc::proc_listallpids(buf, size) });
    all.into_iter().find(|pid| {
        process_name(*pid).as_deref() == Some("ollama")
            && parent_pid(*pid).and_then(process_name).as_deref() != Some("ollama")
    })
}

pub fn collect(backend_pid: Option<u32>) -> ProcessMetrics {
    let mut processes = vec![ProcessMemory {
        role: "shell",
        pid: std::process::id(),
        footprint_bytes: footprint_bytes(std::process::id()),
    }];
    if let Some(pid) = backend_pid {
        processes.push(ProcessMemory { role: "backend", pid, footprint_bytes: footprint_bytes(pid) });
    }
    let server = ollama_server();
    if let Some(server) = server {
        let pid = server as u32;
        processes.push(ProcessMemory { role: "ollama_server", pid, footprint_bytes: footprint_bytes(pid) });
        // SAFETY: buffer pointer and size come from pid_list.
        let children = pid_list(|buf, size| unsafe { libc::proc_listchildpids(server, buf, size) });
        for child in children {
            let pid = child as u32;
            processes.push(ProcessMemory {
                role: "ollama_runner",
                pid,
                footprint_bytes: footprint_bytes(pid),
            });
        }
    }
    ProcessMetrics { source: "phys_footprint", processes, ollama_found: server.is_some() }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn own_footprint_is_readable_and_plausible() {
        let bytes = footprint_bytes(std::process::id()).expect("own process");
        assert!(bytes > 1024 * 1024 && bytes < 64 * 1024 * 1024 * 1024);
    }

    #[test]
    fn missing_process_is_unknown_not_zero() {
        assert_eq!(footprint_bytes(u32::MAX), None);
        assert_eq!(footprint_bytes(999_999), None);
    }

    #[test]
    fn collect_reports_the_shell_and_a_child_backend() {
        let mut child = std::process::Command::new("/bin/sleep").arg("5").spawn().unwrap();
        let metrics = collect(Some(child.id()));
        assert_eq!(metrics.source, "phys_footprint");
        assert_eq!(metrics.processes[0].role, "shell");
        let backend = metrics.processes.iter().find(|p| p.role == "backend").unwrap();
        assert_eq!(backend.pid, child.id());
        assert!(backend.footprint_bytes.is_some());
        // Ollama is optional on the test machine; when found its server is listed.
        if metrics.ollama_found {
            assert!(metrics.processes.iter().any(|p| p.role == "ollama_server"));
        }
        let _ = child.kill();
        let _ = child.wait();
    }

    #[test]
    fn child_listing_finds_a_spawned_child() {
        let mut child = std::process::Command::new("/bin/sleep").arg("5").spawn().unwrap();
        let me = std::process::id() as i32;
        // SAFETY: buffer pointer and size come from pid_list.
        let kids = pid_list(|buf, size| unsafe { libc::proc_listchildpids(me, buf, size) });
        assert!(kids.contains(&(child.id() as i32)), "{kids:?}");
        assert_eq!(parent_pid(child.id() as i32), Some(me));
        assert_eq!(process_name(child.id() as i32).as_deref(), Some("sleep"));
        let _ = child.kill();
        let _ = child.wait();
    }
}

#[cfg(test)]
mod probe {
    #[test]
    #[ignore = "manual: prints what the panel would show on this machine"]
    fn print_metrics() {
        println!("{:#?}", super::collect(None));
    }
}
