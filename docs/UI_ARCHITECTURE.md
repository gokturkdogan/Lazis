# LAZIS — UI Architecture (Neural Interface)

> Status: Phase 0.1 (revised) · Last updated: 2026-10-17
> Delivered in: **P4** (early functional interface), extended in P6–P13 (one view per capability), **P14** (final neural interface).
> Stack: Tauri 2.12 + Vue 3 + TypeScript (strict) + Vite + Pinia + vue-i18n + Three.js (WebGL2, P14). See [TECHNOLOGY_DECISIONS.md §5](TECHNOLOGY_DECISIONS.md).

## 0. Two interfaces, one application

LAZIS must be usable and testable as a desktop app **early**, but the cinematic interface depends on stable conversation, state and voice systems. The UI is therefore built in two stages **on the same shell, stores and API contracts**, so the final interface replaces presentation, not plumbing.

| | **Early functional interface (P4 →)** | **Final neural interface (P14)** |
|---|---|---|
| Purpose | Daily use and testing: conversations, responses, system state, memory, errors | The cinematic LAZIS identity |
| State display | `PulseIndicator`: a 2D CSS ring/dot with the same five state colors and sub-status text | `NeuralCore`: the Three.js energy core, holographic rings and particles (§4) |
| Layout | A plain two-pane layout: chat on the left, a **diagnostics panel** on the right (toggle) | Core-centered layout (§2) with the transcript as a side panel |
| Diagnostics | Always available: per-turn trace (retrieval ms, prompt tokens, `cache_reuse_ratio`, TTFT, tok/s), model and runner status, memory usage, an error console with redacted logs, and the assembled-prompt inspector (developer mode, local only) | Moved to the System view; the inspector remains in developer mode |
| Feature views | Added as capabilities land: Memory inspector (P6), People + Inbox (P7), Import (P8), Learning review feed (P9), Learned style (P10), Sources (P11), Research log and indicators (P12), Voice controls and level meter (P13) | Same views, restyled to the final visual language |
| Dependencies | P3 conversation engine + state machine | P13 voice (audio reactivity) + stable state events |

**As built in P4** ([ADR-0012](adr/0012-desktop-experience-and-resilience.md)):

- **State indicator.** `PresenceIndicator.vue` (2D CSS rings and core) plus a text label, fed by `stores/presence.ts`, which derives the state from real events.
- **Diagnostics.** A tab, not a side pane, so chat stays uncluttered. It shows model and runtime, backend and restart state, the last turn's TTFT/total/tokens/speed, context preparation and per-process memory. The assembled-prompt inspector is not built.
- **Replies.** Safe Markdown (`markdown.ts`, `MarkdownContent.vue`) with code copy and message copy.
- **Navigation.** Tabs (Sohbet, Genel bakış, Ayarlar, Tanılama) instead of a router; the menu bar and `--show` switch tabs.

Both indicators implement one interface, `StateVisual`. Its input is `visualState` (state, sub-status, mic level, TTS level) and its lifecycle methods are mount, pause and dispose. The final interface also keeps the 2D indicator as a **low-power / reduced-motion fallback**, so nothing built early is thrown away.

## 1. Design intent (final neural interface)

A cinematic AI presence with a **unique LAZIS identity**: a living **neural energy core** at the center, wrapped in **holographic mechanical rings**. The visual is never decoration for its own sake. It communicates state (idle, listening, thinking, speaking, error) at a glance and stays out of the way of reading, typing and managing memory.

Constraints:
- GPU-efficient: the core view targets **≤ 4 ms GPU time per frame** at 60 fps on the M4 Pro (to be measured). It pauses when hidden.
- Usability first: text is always readable (contrast ≥ WCAG AA), controls are standard, and every animated signal has a textual equivalent.

## 2. Window layout (final neural interface, P14)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ ● LAZIS [Sohbet] [Hafıza] [Kişiler] [Öğrendiklerim] [Onay ③] [Kaynaklar] [⚙] │  ← nav (top or left rail)
│                                                       ⦿ Çevrimdışı  🎙 Kapalı │  ← privacy HUD (network, mic, off-record)
├───────────────────────────────────────────────┬──────────────────────────────┤
│                                               │  Transcript / chat history   │
│              ╭───── rings ─────╮              │  (collapsible side panel)    │
│            ╭─┤   NEURAL CORE   ├─╮            │                              │
│            ╰─┤   (Three.js)    ├─╯            │  LAZIS: …                    │
│              ╰─────────────────╯              │  Sen: …                      │
│            "Dinliyorum…"  (status line)       │                              │
├───────────────────────────────────────────────┴──────────────────────────────┤
│ [🎙 Bas-konuş ⌥Space]  [ Mesaj yaz…                              ] [Gönder ⏎] │  ← input bar
│ model: <aktif model> · TTFT <s> · <tok/s> · RAM <GB>     ▸ öğreniyor (2)       │  ← status strip (live values)
└──────────────────────────────────────────────────────────────────────────────┘
```

- **Responsive:** ≥ 1280 px wide → core and side panel side by side; 900–1280 px → the side panel overlays as a drawer; full-screen "focus mode" → core only, with captions. The minimum window is 900 × 600.
- **Views** (each introduced in the phase that delivers its capability):
  - Conversation (core or indicator + transcript) — P4
  - Memory (search, filters, edit, history, sources, status) — P6
  - People (list + graph; entity editor with merge/unmerge/split) — P7
  - Inbox ("Onay Kutusu": Level C confirmations only) — P7
  - Import (bootstrap upload → preview → apply → rollback) — P8
  - **Learning review feed** ("Öğrendiklerim": approve / correct / reject / delete / mark uncertain / view source / view related entities) — P9
  - **Sources** ("Kaynaklar": authorized folders, files, sync status, import history) — P11
  - **Research log** ("Araştırma günlüğü") — P12
  - Settings (models, voice, persona preferences, learning review mode, research permission mode and rules, privacy and network, backups, appearance) — P4 →
  - System (health, per-stage latency p50/p95, cache reuse, memory usage, logs viewer with redaction) — P4 →
- **Research indicators:** while research is running, the privacy HUD shows a "🔎 araştırıyor" chip with the current query (public or scrubbed), and the state shows the `THINKING.researching` sub-status. Pending approvals appear as an inline card. Citations are numbered badges under the answer.

## 3. Front-end architecture

```
ui/src/
├── app/              main.ts, router, i18n (tr default), theme tokens
├── api/              generated OpenAPI types, rest client, ws client (reconnect, turn_id filtering)
├── stores/           pinia: connection, assistantState, conversation, memory, people, inbox, review, sources, research, settings, system
├── features/         conversation/ diagnostics/ memory/ people/ inbox/ import/ review/ sources/ research/ settings/ system/
├── state-visual/     StateVisual interface, PulseIndicator (2D, P4), shared state colors
├── neural-core/
│   ├── NeuralCore.vue          mounts canvas, owns renderer lifecycle
│   ├── engine/renderer.ts      WebGL2 renderer, resize, DPR policy, frame scheduler
│   ├── engine/scene.ts         core, rings, particles, post-processing
│   ├── shaders/                core.vert/frag, ring.frag, particles.vert, bloom
│   ├── state-visuals.ts        state → visual parameter targets
│   └── audio-reactive.ts       level ring buffer, envelope follower
└── components/       shared UI (buttons, dialogs, diff viewer, entity chip, source badge)
```

- **State ownership:** the backend is authoritative for assistant state. `assistantState` store = the last `state.changed` event. Visual parameters are derived from it, never the reverse.
- **High-frequency data bypasses Vue reactivity.** `audio.level` events (30 Hz) go into a plain typed-array ring buffer read by the render loop. Token deltas are batched per animation frame before touching reactive state.
- **Typed contracts:** REST and WS types are generated from the backend schemas. A CI check fails on drift.
- **Tauri integration** (minimal Rust): sidecar spawn/supervise, token handoff, Keychain, global shortcut (PTT), file dialog for import and folder authorization, tray icon with state color, single-instance lock. The Tauri **capabilities** file grants only the plugins we use (no shell plugin, no arbitrary fs).

## 4. Neural core: visual design

### 4.1 Scene elements

| Element | Technique | Cost control |
|---|---|---|
| **Energy core** | Icosphere (detail ~5) with `ShaderMaterial`: vertex displacement by 3D simplex noise (time + audio energy), fresnel rim glow, inner emissive gradient, additive blending | single draw call; noise in the vertex shader |
| **Inner filaments** | 64–128 animated line strips (curl-noise paths) suggesting neural activity; density rises in THINKING | one `LineSegments` buffer, updated in the shader via time uniform |
| **Holographic rings** | 3–4 concentric rings: a thin torus plus **instanced tick segments** (machined-metal look), slow rotation on different axes; fragment shader adds scanlines, edge glow, and alpha falloff | instancing (1 draw per ring) |
| **Particle halo** | 2–4k points orbiting the core, GPU-animated (position computed in the vertex shader from a seed + time) | no CPU per-particle updates |
| **Glow** | single **half-resolution bloom** pass (mip-chain bloom) | disabled in low-power mode; fake glow via fresnel |
| **Background** | subtle radial gradient + faint grid (CSS, not WebGL) | zero GPU in WebGL |

### 4.2 State → visual mapping

| State | Color (sRGB) | Core motion | Rings | Particles | Reactivity |
|---|---|---|---|---|---|
| **IDLE** | blue `#3AA0FF` | slow breathing (0.15 Hz), low displacement | slow drift | calm orbit | none |
| **LISTENING** | purple `#9B5CFF` | displacement follows **mic RMS**, ripples on onsets | rings tilt toward the user, slight speed-up | pulled inward slightly | mic envelope (attack 30 ms / release 200 ms) |
| **THINKING** | yellow `#FFC83A` | internal swirl, filaments brighten | rings accelerate and counter-rotate; ticks shimmer sequentially (a "computing" sweep) | faster spiral | sub-status: `retrieving` (soft sweep), `researching` (outer ring segments light up), `reasoning` (slow deep pulse) |
| **SPEAKING** | green `#3DFF9A` | radial pulses synced to the **TTS amplitude envelope** | steady rotation, ring brightness ∝ speech energy | outward bursts on syllable peaks | TTS envelope from `audio.level{source:tts}` |
| **ERROR** | red `#FF3B3B` | brief flicker (≤ 300 ms, no strobing) then a slow, steady pulse | rings slow, segments dim | sparse | none; the status line shows a recovery hint |

### 4.3 Transitions
- Every visual parameter is a **target**. Each frame applies critically-damped spring interpolation toward the target, typically settling in 400–700 ms. There are no hard cuts.
- Colors are interpolated in **OKLab** for perceptually smooth blue→purple→yellow→green paths, with no muddy midpoints.
- Rapid state flapping (e.g., LISTENING ↔ THINKING within 150 ms) is smoothed by a minimum dwell time on visual targets. The logical state stays exact.
- Accessibility: `prefers-reduced-motion` → static glow plus a color-only state change. Error flicker respects WCAG 2.3.1 (no more than 3 flashes per second).

## 5. Rendering performance strategy

| Technique | Detail |
|---|---|
| Frame scheduler | 60 fps in active states; **30 fps in IDLE**; **0 fps** (loop paused) when the window is hidden, minimized or occluded (`visibilitychange`, Tauri window events) |
| Dynamic resolution | render the core canvas at `min(devicePixelRatio, 2)`; if the frame time exceeds budget for 1 s, step down to 0.75× DPR, and recover when headroom returns |
| Power profiles | Battery: 30 fps cap, no bloom, half particle count |
| Draw calls | target < 20 per frame (instancing, merged geometries) |
| Allocation | no per-frame allocations in the loop (reused vectors and buffers) |
| Shader precompile | compile on startup (`renderer.compile`) to avoid first-transition hitches |
| Context loss | handle `webglcontextlost/restored` gracefully (re-create resources) |
| Measurement | built-in perf overlay (dev): CPU frame ms, GPU time via `EXT_disjoint_timer_query_webgl2` where available, draw calls |

**WebGPU:** WebKit on recent macOS supports WebGPU, and Three.js offers a `WebGPURenderer`. This is evaluated later, after the WebGL2 version meets its budget. It is not on the critical path.

## 6. Conversation UI
- Streaming tokens render into the transcript with Markdown (sanitized, with links that open in the system browser after confirmation).
- **Memory transparency:** subtle chips under a reply show "📌 not edildi: Elif'in doğum günü 14 Mayıs" (from `memory.saved`) with undo. A "neden böyle dedin?" affordance shows which memories and sources were used for the turn.
- Research: citations as numbered badges; the source list is expandable; a pending-approval card for queries (`research.pending_approval`).
- Voice: live partial transcript (if enabled) and captions of LAZIS speech, synced to playback marks.

## 7. Memory and people management
- **Memory view:** full-text plus semantic search (backend), filters (kind, person, sensitivity, origin, status, date), an inline editor (content, dates, sensitivity), history timeline with revert, source viewer (jump to the message with the evidence quote highlighted), bulk delete with a preview of effects.
- **People view:** a searchable list plus a force-directed graph centered on the user (Three.js instanced nodes, or SVG if fewer than 300 nodes), relationship editor with dates, merge/unmerge, "farklı kişiler" (mark distinct), forget person (count preview).
- **Inbox:** cards per Level C item type with one-click resolutions; count badge in the nav.
- **Learning review feed:** newly learned memories, relationships and entities, grouped by learning run (conversation, document or import). Each item shows level (A/B), confidence, risk and the policy reason ("neden?"). Actions: approve, correct, reject, delete, mark uncertain, view source, view related entities. Filters: level, person, source, sensitivity, date. Bulk "undo this learning run". The badge is non-blocking ([MEMORY_ARCHITECTURE.md §12](MEMORY_ARCHITECTURE.md)).
- **Import:** drag-and-drop YAML → validation errors with line numbers → grouped diff preview (accept/reject/edit per item) → apply → result summary → rollback button for the change set.
- **Sources:** see [LOCAL_INGESTION_ARCHITECTURE.md §9](LOCAL_INGESTION_ARCHITECTURE.md).

## 8. Settings (selected)
- **Models:** installed models, pinned digests, active model and runner, bake-off report link.
- **Voice:** devices, mode, voice profile preview, hotkey, headphone mode, fallback.
- **Persona preferences:** address form, verbosity, humor, follow-ups; shows *learned* preferences with their source.
- **Learning:** review mode (calibration / digest / off / strict), calibration length, category overrides.
- **Privacy:** network kill switch; **research mode** (offline / ask per session / auto public / custom) and rules; sensitive-topic handling; off-record default; debug logging with expiry; sensitive-memory behavior.
- **Data:** backups, export, recovery code, wipe.
- **Appearance:** theme, reduced motion, performance profile, 2D/3D state visual.

## 9. Internationalization and theming
- `vue-i18n` with `tr` as the primary locale (all strings externalized; `en` optional later). Dates and numbers are formatted with `Intl` (`tr-TR`).
- Design tokens (CSS custom properties): dark theme by default (cinematic), plus a light theme for daytime readability. State colors are shared between CSS and the shaders from a single source (`theme/state-colors.ts`).

## 10. UI testing
- **Early interface (P4):** E2E covers chat streaming, cancellation, the diagnostics panel showing real per-turn metrics, error display when the core or Ollama is down, and state colors in the 2D indicator.
- **Unit:** Vitest for stores, the WS client (turn_id filtering, reconnect), formatters, the state-visual mapping (pure functions), and `StateVisual` contract tests run against both implementations.
- **Component:** Vue Test Utils for forms, diff viewer, inbox cards.
- **E2E:** Playwright (**WebKit** engine, the closest available proxy for WKWebView) against the Vite dev server and a backend running with `FakeLLMProvider`.
- **Visual regression:** screenshot tests of static views. The core scene uses deterministic time (`?seed&t=` debug params) for stable snapshots.
- **Performance:** a scripted 5 min state-cycling run that records frame times. Gate: p95 frame CPU time ≤ 8 ms, no long tasks > 50 ms during streaming.
- **Manual Tauri smoke checklist** per release (sidecar start, hotkey, mic permission, tray, sleep/wake), because `tauri-driver` does not support macOS.
