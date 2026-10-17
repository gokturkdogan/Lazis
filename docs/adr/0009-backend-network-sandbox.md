# ADR-0009: OS-enforced network sandbox for the backend

- **Status:** Accepted (Phase 1.1, 2026-10-17), subject to the owner's approval
- **Related:** [SECURITY_MODEL.md §5.3](../SECURITY_MODEL.md), [ARCHITECTURE.md §3.1](../ARCHITECTURE.md), `apps/desktop/src-tauri/sandbox/backend.sb`, ADR-0008 (runtime packaging, planned)

## Context

Phase 1 protected the backend's network access with a PEP 578 audit hook. An external review and our own verification in Phase 1.1 showed what that does and does not cover:

- Covered: everything that goes through CPython's `socket` module.
- **Not covered:** native code (C extensions, `ctypes`, Rust/C HTTP clients shipped in wheels — e.g. `primp` under the `ddgs` search library considered for P12), child processes, and already-connected sockets inherited from the parent.
- Verified bypasses without an OS layer: a `libc.connect()` through `ctypes` and a `curl` child process both reached the network while the hook was active.
- The backend itself started a child process (`uname -p`, from `platform.platform()`) on every launch.

The Phase 1 documents described the hook as "process-level" isolation, which overstated it.

## Decision

1. The desktop shell starts the backend through `/usr/bin/sandbox-exec -p <profile>`. The Seatbelt profile allows everything except networking; networking is allowed only to this machine:
   - `(deny network*)`
   - allow `network-outbound` to `remote ip "localhost:*"`;
   - allow `network-bind` and `network-inbound` on `local ip "localhost:*"`.

   The kernel enforces this for the backend and every process it starts.
2. The profile lives in one file (`apps/desktop/src-tauri/sandbox/backend.sb`). The shell includes it at compile time; the Python tests read the same file.
3. **Fail closed:**
   - If `sandbox-exec` is missing, the shell does not start the backend (`network_sandbox_unavailable`).
   - The backend is started with `--require-os-sandbox` and verifies the sandbox itself. It connects to the local DNS daemon's Unix socket (`/var/run/mDNSResponder`), which the profile denies. EPERM means "enforced"; the probe sends nothing off the machine. If the sandbox is not enforced, the backend refuses to start.
   - The status is reported in `/system/status` and shown in the UI.
4. The application-level hook stays as the first layer, with the following changes:
   - it now requires loopback IP literals for socket addresses;
   - it refuses all process creation;
   - the backend closes inherited descriptors at startup.

## Evidence

All evidence below was gathered on macOS 27.0.1. Tests use TEST-NET-1 (192.0.2.1) and the local DNS daemon socket only, so nothing contacts another host.

| Attempt inside the sandbox | Result |
|---|---|
| Python `socket` connect / UDP `sendto` to another host | EPERM (kernel) |
| `ctypes` → `libc.connect()` to another host (bypasses Python) | EPERM |
| Child process connecting to another host | EPERM (the profile is inherited) |
| Name resolution (resolver daemon socket) | EPERM → `getaddrinfo` fails |
| Loopback listener + connect | allowed |
| Real backend: handshake, encrypted DB, API on 127.0.0.1 | works; startup 0.34–0.40 s, unchanged |
| Real app (release build): `os_network_sandbox` | `enforced` (logged and shown in the UI) |

Found during the same work: the shell leaked two descriptors into the backend. They were read-only Metal shader libraries opened by Apple's graphics frameworks without close-on-exec. They were harmless, but they show the class of risk; the descriptors are now closed at startup.

## Limits (accepted, documented)

- **Listening is not OS-restricted.** In a Seatbelt *local* filter, `"localhost"` means any local address. Binding to 0.0.0.0 or the LAN IP was still possible under the profile, and SBPL rejects IP literals. Loopback-only listening therefore remains an application guarantee:
  - the config only allows a loopback IP;
  - the server binds explicitly to that IP;
  - the audit hook refuses non-loopback binds.
- **Own addresses are reachable.** `remote ip "localhost"` also matches this host's own addresses (e.g. its LAN IP). Traffic to them never leaves the machine.
- **`sandbox-exec` is deprecated** (still functional, used widely). If Apple removes it, the app fails closed instead of running unprotected. The long-term replacement is App Sandbox entitlements for a signed, packaged backend (ADR-0008, P15).
- **Not covered by this profile:** the Rust shell and the WebKit processes (no network code; the webview is restricted by the CSP).
- **P12 implication:** internet research needs outbound access. It must run in a separate helper process with its own narrower profile and the egress gateway; the main backend keeps this profile.

## Alternatives considered

- **Audit hook only:** rejected; it is bypassable by native code and subprocesses (demonstrated).
- **Packet filter (`pf`) rules or a Network Extension:** need root or an entitlement and a system extension; too heavy for P1.
- **App Sandbox for the Python backend now:** needs a signed bundle with entitlements and an embedded runtime (packaging phase).
- **Blocking only in-process (seccomp-like):** not available on macOS.

## Amendment 1 (Phase 2, 2026-10-17): one outbound port for local inference

Local inference needs the backend to reach Ollama on `127.0.0.1:11434`. The P1.1 profile allowed outbound to `localhost:*` — every local port. That would let the backend reach any other local service, e.g. an HTTP/SOCKS proxy that forwards to the internet. The profile now allows **only** `(remote ip "localhost:11434")`; verified on macOS 27: Ollama reachable, any other local port EPERM, the backend's own listener unaffected. `models.endpoint` must use port 11434 (config validation), so the two cannot drift apart silently. Ollama itself is not sandboxed by LAZIS; its cloud features are switched off at the server (`OLLAMA_NO_CLOUD=1`) and refused in the adapter, and the adapter cannot call model-management endpoints (SECURITY_MODEL §5.13).

