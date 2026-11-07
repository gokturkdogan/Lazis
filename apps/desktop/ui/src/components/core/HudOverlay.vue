<script setup lang="ts">
/**
 * The HUD around the core (Phase 14, after LAZOS's HudOverlay): a slowly turning reticle, the
 * state label, real telemetry, live audio meters and a caption. Meters are updated with direct
 * DOM writes from requestAnimationFrame: no Vue re-render per frame. Every value shown is real;
 * what is not known is shown as "—".
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useCore } from "@/core/useCore";
import { useAssistantStore } from "@/stores/assistant";
import { currentApiClient } from "@/stores/connection";
import { useVoiceStore } from "@/stores/voice";
import { micLevel, speechLevel } from "@/voice/levels";

const props = defineProps<{ chatOpen: boolean }>();
const { t } = useI18n();
const core = useCore();
const voice = useVoiceStore();
const assistant = useAssistantStore();

const ticks = Array.from({ length: 120 }, (_, i) => {
  const a = (i / 120) * Math.PI * 2;
  const major = i % 10 === 0;
  const r1 = major ? 338 : 344;
  return { x1: Math.cos(a) * r1, y1: Math.sin(a) * r1, x2: Math.cos(a) * 350, y2: Math.sin(a) * 350, major };
});
const marks = ["LZ-01 · NEURAL CORE", "YEREL ÇIKARIM", "TÜRKÇE", "GÜVENLİ · YEREL"];

const label = computed(() =>
  voice.phase === "transcribing" ? t("core.transcribing") : t(`core.state.${core.state.value}`),
);
const sublabel = computed(() => (core.state.value === "listening" ? t("core.listeningSub") : t("core.tagline")));

// ----- telemetry (real values only) -----
const research = ref<string>("—");
const lastTurn = ref<{ ttft: number | null; rate: number | null }>({ ttft: null, rate: null });

async function loadTelemetry() {
  const client = currentApiClient();
  if (client === null) return;
  try {
    const mode = (await client.researchSettings()).mode;
    research.value = mode === "ask" ? t("core.researchAsk") : t("core.researchOff");
  } catch {
    research.value = "—";
  }
  try {
    const turn = (await client.diagnostics()).last_turn;
    if (turn) {
      const gen = turn.total_ms !== null && turn.ttft_ms !== null ? (turn.total_ms - turn.ttft_ms) / 1000 : null;
      lastTurn.value = {
        ttft: turn.ttft_ms,
        rate: turn.output_tokens && gen && gen > 0 ? turn.output_tokens / gen : null,
      };
    }
  } catch {
    // keep the last known values
  }
}

watch(
  () => assistant.phase,
  (phase, before) => {
    if (phase === "idle" && before !== "idle") void loadTelemetry();
  },
);

const ms = (v: number | null | undefined) => (v === null || v === undefined ? "—" : v >= 1000 ? `${(v / 1000).toFixed(2)} s` : `${Math.round(v)} ms`);

const caption = computed(() => {
  if (voice.phase === "speaking" && voice.saying) return voice.saying;
  if ((voice.phase === "transcribing" || voice.phase === "thinking") && voice.heard) return voice.heard;
  return null;
});
const showCaption = computed(() => caption.value !== null && (!props.chatOpen || voice.phase === "speaking"));

// ----- live meters: direct DOM writes -----
const micBars = ref<HTMLDivElement | null>(null);
const ttsBars = ref<HTMLDivElement | null>(null);
const BARS = 24;
let raf = 0;
function dim() {
  for (const el of [micBars.value, ttsBars.value]) {
    if (!el) continue;
    for (let i = 0; i < el.children.length; i++) (el.children[i] as HTMLElement).style.opacity = "0.14";
  }
}
/** Runs only while there is real audio to show (listening or speaking). */
function render() {
  raf = 0;
  if (core.state.value !== "listening" && core.state.value !== "speaking") {
    dim();
    return;
  }
  raf = requestAnimationFrame(render);
  if (document.hidden) return;
  for (const [el, lvl] of [
    [micBars.value, core.state.value === "listening" ? micLevel() : 0],
    [ttsBars.value, core.state.value === "speaking" ? speechLevel() : 0],
  ] as const) {
    if (!el) continue;
    const lit = Math.round(lvl * BARS);
    for (let i = 0; i < el.children.length; i++) {
      (el.children[i] as HTMLElement).style.opacity = i < lit ? "1" : "0.14";
    }
  }
}

watch(
  () => core.state.value,
  (s) => {
    if ((s === "listening" || s === "speaking") && raf === 0) raf = requestAnimationFrame(render);
  },
);

onMounted(() => void loadTelemetry());
onBeforeUnmount(() => cancelAnimationFrame(raf));
</script>

<template>
  <div class="hud" data-testid="hud">
    <svg class="reticle" width="760" height="760" viewBox="-380 -380 760 760" aria-hidden="true">
      <g class="animate-spin-slow">
        <line
          v-for="(k, i) in ticks"
          :key="i"
          :x1="k.x1"
          :y1="k.y1"
          :x2="k.x2"
          :y2="k.y2"
          stroke="var(--accent)"
          :stroke-opacity="k.major ? 0.45 : 0.16"
          :stroke-width="k.major ? 1.2 : 0.8"
        />
        <text
          v-for="(m, i) in marks"
          :key="m"
          :transform="`rotate(${i * 90}) translate(0 -360)`"
          text-anchor="middle"
          class="mark"
        >
          {{ m }}
        </text>
      </g>
      <g class="animate-spin-rev">
        <circle r="318" fill="none" stroke="var(--accent)" stroke-opacity="0.12" stroke-dasharray="2 10" />
        <path d="M -300 0 A 300 300 0 0 1 -212 -212" fill="none" stroke="var(--accent)" stroke-opacity="0.5" stroke-width="1.5" />
        <path d="M 300 0 A 300 300 0 0 1 212 212" fill="none" stroke="var(--accent)" stroke-opacity="0.5" stroke-width="1.5" />
      </g>
      <circle r="372" fill="none" stroke="var(--accent)" stroke-opacity="0.06" />
    </svg>

    <div class="state">
      <Transition name="label" mode="out-in">
        <div :key="label" class="label accent-text accent-glow" data-testid="core-label">{{ label }}</div>
      </Transition>
      <div class="sub">{{ sublabel }}</div>
    </div>

    <div class="panel-hud brackets system" data-testid="hud-system">
      <div class="hud-label accent-text title">{{ t("core.system") }}</div>
      <div class="row"><span class="hud-label key">{{ t("core.model") }}</span><span class="val">{{ assistant.selectedModel || "—" }}</span></div>
      <div class="row"><span class="hud-label key">{{ t("core.stt") }}</span><span class="val">{{ voice.status?.stt_available ? "whisper-turbo" : t("core.none") }}</span></div>
      <div class="row"><span class="hud-label key">{{ t("core.tts") }}</span><span class="val">{{ voice.status?.tts_available ? "macOS Yelda" : t("core.none") }}</span></div>
      <div class="row"><span class="hud-label key">{{ t("core.research") }}</span><span class="val">{{ research }}</span></div>
    </div>
    <div class="panel-hud brackets turn" data-testid="hud-turn">
      <div class="hud-label accent-text title">{{ t("core.lastTurn") }}</div>
      <div class="row"><span class="hud-label key">{{ t("core.ttft") }}</span><span class="val">{{ ms(lastTurn.ttft) }}</span></div>
      <div class="row"><span class="hud-label key">{{ t("core.rate") }}</span><span class="val">{{ lastTurn.rate ? lastTurn.rate.toFixed(1) : "—" }}<span v-if="lastTurn.rate" class="unit">tok/s</span></span></div>
      <div class="row"><span class="hud-label key">{{ t("core.sttMs") }}</span><span class="val">{{ ms(voice.lastSttMs) }}</span></div>
      <div class="row"><span class="hud-label key">{{ t("core.firstAudio") }}</span><span class="val">{{ ms(voice.lastFirstAudioMs) }}</span></div>
    </div>

    <div class="panel-hud brackets meters" data-testid="hud-meters">
      <div class="hud-label accent-text title">{{ t("core.audio") }}</div>
      <div class="row">
        <span class="hud-label key">{{ t("core.mic") }}</span>
        <div ref="micBars" class="bars"><i v-for="i in BARS" :key="i" :style="{ height: `${40 + (i / BARS) * 60}%` }" /></div>
      </div>
      <div class="row">
        <span class="hud-label key">LAZIS</span>
        <div ref="ttsBars" class="bars"><i v-for="i in BARS" :key="i" :style="{ height: `${40 + (i / BARS) * 60}%` }" /></div>
      </div>
    </div>

    <Transition name="caption">
      <p v-if="showCaption" :key="caption ?? ''" class="caption" data-testid="hud-caption">{{ caption }}</p>
    </Transition>
  </div>
</template>

<style scoped>
.hud {
  position: absolute;
  inset: 0;
  pointer-events: none;
  user-select: none;
}
.reticle {
  position: absolute;
  left: 50%;
  top: 50%;
  transform: translate(-50%, -50%);
  max-width: 92%;
  max-height: 92%;
}
.reticle g {
  transform-origin: 0 0;
  transform-box: view-box;
}
.mark {
  fill: var(--accent);
  font-family: ui-monospace, "SF Mono", monospace;
  font-size: 8px;
  letter-spacing: 0.25em;
  opacity: 0.5;
}
.state {
  position: absolute;
  left: 50%;
  top: calc(50% + 250px);
  transform: translateX(-50%);
  text-align: center;
}
.label {
  font-family: var(--font-display);
  font-size: 13px;
  font-weight: 500;
  letter-spacing: 0.45em;
}
.sub {
  margin-top: 4px;
  font-family: ui-monospace, "SF Mono", monospace;
  font-size: 9.5px;
  letter-spacing: 0.3em;
  color: var(--text-faint);
}
.label-enter-active,
.label-leave-active {
  transition: opacity 0.5s, letter-spacing 0.5s;
}
.label-enter-from {
  opacity: 0;
  letter-spacing: 0.6em;
}
.label-leave-to {
  opacity: 0;
}
.panel-hud {
  position: absolute;
  padding: 10px 12px;
}
.system {
  left: 24px;
  top: 20px;
  width: 250px;
}
.turn {
  right: 24px;
  top: 20px;
  width: 230px;
}
.meters {
  left: 24px;
  bottom: 110px;
  width: 220px;
}
.title {
  margin-bottom: 6px;
}
.row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 20px;
  padding: 3px 0;
}
.key {
  font-size: 9px;
  white-space: nowrap;
}
.val {
  font-family: ui-monospace, "SF Mono", monospace;
  font-size: 11px;
  color: var(--text);
  white-space: nowrap;
}
.unit {
  margin-left: 4px;
  color: var(--text-faint);
}
.bars {
  display: flex;
  align-items: flex-end;
  gap: 3px;
  height: 10px;
}
.bars i {
  width: 3px;
  border-radius: 1px;
  background: var(--accent);
  opacity: 0.14;
  transition: opacity 75ms;
}
.caption {
  position: absolute;
  left: 50%;
  bottom: 104px;
  transform: translateX(-50%);
  max-width: min(680px, 80%);
  margin: 0;
  text-align: center;
  font-size: 15px;
  line-height: 1.6;
  color: rgb(219 233 255 / 0.9);
  text-shadow: 0 2px 20px rgb(0 0 0 / 0.9);
}
.caption-enter-active,
.caption-leave-active {
  transition: opacity 0.35s, filter 0.35s;
}
.caption-enter-from,
.caption-leave-to {
  opacity: 0;
  filter: blur(4px);
}
</style>
