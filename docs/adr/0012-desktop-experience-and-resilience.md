# ADR-0012: Desktop experience, system management and resilience (Phase 4)

- **Status:** Accepted for Phase 4 (2026-10-18). The owner reviews it with [PHASE_4_REPORT.md](../PHASE_4_REPORT.md).
- **Related:** [ADR-0011](0011-single-assistant-timeline.md) (one assistant, unchanged), [ARCHITECTURE.md](../ARCHITECTURE.md) §3, §9, [SECURITY_MODEL.md](../SECURITY_MODEL.md) §5.15, [UI_ARCHITECTURE.md](../UI_ARCHITECTURE.md).

## Context

Phase 3 delivered one persistent assistant. The desktop app around it still had gaps:

- the visible state was connection health only;
- an unexpected backend exit needed a manual retry;
- there were no menu-bar item, sleep/wake handling or desktop preferences;
- replies were plain text;
- the thread always jumped to the bottom;
- the UI polled `/health` and `/system/status` every 5 s, even while hidden, and the status call ran `PRAGMA quick_check` each time;
- the logo animation ran continuously.

Measured on the Phase 3 build with an idle, visible window: shell 4.8 % CPU, WebContent 6.1 %.

Constraints: single user, local only, minimal new dependencies, no microphone, no global hotkey, no telemetry, and no changes to Ollama or system settings without the owner's approval.

## Decisions

1. **Assistant state is derived, not simulated.** `derivePresence()` (UI) maps three real inputs to five states:
   - **Inputs:** the shell's backend phase, the runtime check, and the turn stream's events.
   - **States:**
     - `idle`
     - `thinking`: sent, context or model being prepared
     - `speaking`: tokens arriving
     - `error`
     - `listening`: reserved for P13; nothing produces it
   - **No timers.** A cancellation is not an error. A new backend session clears a stale stream error.
   - The backend-authoritative `state.changed` WebSocket of ARCHITECTURE §9 is still not built. With text only, the turn stream already carries the authoritative events. That design returns with voice (P13), when the backend owns audio state.
2. **Low-cost indicator.**
   - CSS transform/opacity only, animated only while thinking or speaking; idle and error are still.
   - Turned off by macOS Reduce Motion or the app's own preference.
   - Always accompanied by a text label (`aria-live`).
   - The menu-bar status line follows the same state through a validated `set_tray_status` command, sent only when the state changes.
3. **Bounded automatic restart in the shell.**
   - After an unexpected backend exit: at most 3 restarts within 60 s, waiting 1/2/4 s.
   - Each restart runs under the same `op` lock as every other start, so two backends can never run.
   - Never while quitting: `shutting_down` is checked under the state lock, closing the race with `shutdown()`.
   - When the budget is exhausted: `backend_restart_limit` and a manual retry, which resets the budget.
   - Keys and the auth model are unchanged: each start gets a new session token, and the UI rebuilds its client from the pushed connection.
4. **Ollama is observed, never managed.**
   - When unreachable, the UI re-checks `/llm/status` at 2/4/8/15/30 s while the window is visible, and re-warms the session once Ollama is back.
   - LAZIS never starts, stops or reconfigures Ollama or its LaunchAgent.
   - There is no automatic switch to the fallback model; diagnostics shows it as "no automatic fallback".
5. **Sleep/wake from clock drift.**
   - On macOS, `Instant` (CLOCK_UPTIME_RAW) stops during sleep and the wall clock does not.
   - A thread compares the two every 15 s. Wall-clock drift above 30 s is reported as a wake, and the UI re-checks health and the runtime and re-warms.
   - Chosen over NSWorkspace notifications because it needs no Objective-C bridge dependency. A manual clock change costs at most one extra health check.
6. **Menu bar and window behaviour.**
   - One template icon, drawn in code, so no image-decoder feature is needed.
   - Menu: status line, open, system status, settings, quit.
   - Closing the window hides it to the menu bar (default) or quits, per preference. Clicking the Dock icon reopens the window. ⌘Q and "Quit" always quit cleanly.
   - Optional start hidden.
   - A second launch with `--show=<assistant|diagnostics|settings>` opens that view (single-instance handoff). That also serves measurements.
   - No launch-at-login: it needs `SMAppService` and a signed bundle. No notifications.
7. **The window is created in code** so it gets a navigation guard: only `tauri://localhost` (plus the dev server in debug builds). New windows are refused. The webview can never navigate to content from a reply.
8. **Safe Markdown with markdown-it** (new dependency, justified: correct CommonMark plus tables; a hand-written parser would be a larger XSS risk).
   - `html: false`, images disabled, no linkify or typographer, only absolute http(s) links.
   - Links are intercepted, confirmed by the user, and opened by the shell's `open_external_url` after it validates the URL: http(s), a host, no credentials, no control characters, at most 2048 bytes.
   - Fenced code gets a language label (sanitized) and a copy button. No syntax highlighting.
   - Streaming replies stay plain text until complete.
   - The production CSP (no inline scripts) remains a second layer.
9. **Scrolling.** The thread follows new text only while the reader is within 48 px of the bottom; otherwise it shows a "new message" button. Loading older messages keeps the reading position. No virtualization: 200 long messages mount in about 0.12 s in the indicative test (happy-dom), and paging limits what is on screen.
10. **Diagnostics without content.**
    - `GET /api/v1/diagnostics` reports runtime, model (active, installed, loaded, keep-alive, fallback), the last turn's timings and token counts (outcome, failed stage) and the pre-warm state.
    - Pre-warm scope is `context` or `model_only`: a system-prompt-only pre-warm is not reported as a warm conversation, which fixes PHASE_3_REPORT §13.D.
    - Cache warmth is shown as an expectation ("Ollama bunu doğrulamaz"), never as a guarantee.
    - Process memory comes from the shell: `phys_footprint` via libproc for the shell, the backend, the Ollama server and its runners. Unreadable values are shown as unknown.
    - All of it is measured only while the panel is open and the window visible.
11. **Cheaper background work.**
    - Health is polled every 15 s, `/health` only, paused while the window is hidden, and re-checked immediately when it becomes visible or the Mac wakes.
    - A backend crash needs no polling: the shell pushes it.
    - `/system/status` is fetched only by the views that show it, and its integrity check is cached for 10 minutes. The startup integrity check still runs in full.
12. **Desktop preferences** live in the shell's `desktop-state.json` (no secrets, 0600). Writes are serialized with the recovery acknowledgement. A malformed preferences object falls back to defaults on its own and can never mark the recovery code as unconfirmed again.

## Consequences

- Idle, visible window: shell 0.02 %, WebContent 0.07 % CPU (Phase 3: 4.8 % / 6.1 %).
- Hidden: about 0 %.
- Diagnostics open: each process below 0.5 %.
- A killed backend is back in about 1.5 s without user action. Measurements are in PHASE_4_REPORT §E.
- New IPC surface: five commands (`get_preferences`, `set_preferences`, `set_tray_status`, `open_external_url`, `process_metrics`), each in the capability ACL and validated in Rust.
- **Not done:** launch at login, notifications, syntax highlighting, list virtualization, the backend state WebSocket (P13), automatic model fallback, and a sleep/wake test on real hardware (owner verification).
