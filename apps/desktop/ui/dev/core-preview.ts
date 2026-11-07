/**
 * Dev-only preview of the living core (Phase 14.1), for visual checks without the backend,
 * the model or the microphone. Not part of the app build (Vite builds only ui/index.html).
 *
 *   http://localhost:1420/dev/core-preview.html?state=thinking&level=0.4
 *
 * With ?shot=1 it steps the scene deterministically (fixed 60 fps steps, so the colours have
 * fully eased into the state) and leaves the frame as a PNG data URL in `window.__shot`, which
 * scripts/core-snapshots.swift reads through WebKit; ?seq=N does the same for an N-frame clip.
 * Without either, it just runs live.
 */
import type { CoreState } from "@/core/palette";
import { CoreRenderer } from "@/core/scene";

const q = new URLSearchParams(location.search);
const state = (q.get("state") ?? "idle") as CoreState;
const level = Number(q.getAll("level").pop() ?? "0"); // the last one wins (overrides)
const dpr = Number(q.get("dpr") ?? String(Math.min(1.5, window.devicePixelRatio || 1)));
const canvas = document.getElementById("c") as HTMLCanvasElement;
const renderer = new CoreRenderer(canvas, { quality: "high", dpr, reducedMotion: false });
renderer.resize(canvas.clientWidth, canvas.clientHeight);

// Diagnosis only: ?bloom=STRENGTH and ?hide=0,2 (layer indexes in build order).
const inside = renderer as unknown as { bloom: { strength: number }; layers: { object: { visible: boolean } }[] };
if (q.has("bloom")) inside.bloom.strength = Number(q.get("bloom"));
const b = inside.bloom as unknown as { radius: number; threshold: number };
if (q.has("radius")) b.radius = Number(q.get("radius"));
if (q.has("threshold")) b.threshold = Number(q.get("threshold"));
for (const i of (q.get("hide") ?? "").split(",").filter(Boolean)) inside.layers[Number(i)]!.object.visible = false;

// A level that moves like speech, around the requested mean (0 stays 0).
const levelAt = (t: number) => (level > 0 ? Math.max(0, level * (0.75 + 0.25 * Math.sin(t * 9) + 0.15 * Math.sin(t * 23))) : 0);

if (q.has("seq")) {
  // A clip: after the same warm-up, N frames at 30 fps as JPEG data URLs in `window.__frames`
  // (read one by one by scripts/core-snapshots.swift --clip=N).
  const w = window as unknown as { __frames: string[]; __done: boolean };
  w.__frames = [];
  w.__done = false;
  let t = 0;
  for (let i = 0; i < 300; i++) {
    t += 1 / 60;
    renderer.frame(1 / 60, { state, level: levelAt(t) });
  }
  const n = Number(q.get("seq"));
  for (let i = 0; i < n; i++) {
    t += 1 / 30;
    renderer.frame(1 / 30, { state, level: levelAt(t) });
    w.__frames.push(canvas.toDataURL("image/jpeg", 0.92));
  }
  w.__done = true;
} else if (q.get("shot") === "1") {
  const w = window as unknown as { __shot: string | null };
  w.__shot = null;
  let t = 0;
  for (let i = 0; i < 300; i++) {
    t += 1 / 60;
    renderer.frame(1 / 60, { state, level: levelAt(t) });
  }
  // Same task as the last draw, so the drawing buffer is still there.
  w.__shot = canvas.toDataURL("image/png");
} else {
  let last = performance.now();
  const loop = (now: number) => {
    requestAnimationFrame(loop);
    renderer.frame((now - last) / 1000, { state, level: levelAt(now / 1000) });
    last = now;
  };
  requestAnimationFrame(loop);
}
