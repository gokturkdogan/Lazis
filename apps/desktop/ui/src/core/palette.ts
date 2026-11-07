/**
 * The five states of the core and how each looks (Phase 14). Motion parameters follow LAZOS;
 * the primary colours are the owner's: idle #00BFFF, listening #A855F7, thinking #FFD600,
 * speaking #00E676, error #FF1744. Each look has a highlight and a deep tint around the primary.
 */
export type CoreState = "idle" | "listening" | "thinking" | "speaking" | "error";

export interface CoreLook {
  /** primary / highlight / deep tint */
  colors: [string, string, string];
  speed: number;
  energy: number;
  turbulence: number;
  pulse: number;
}

export const LOOKS: Record<CoreState, CoreLook> = {
  idle: { colors: ["#00BFFF", "#00E5FF", "#0066FF"], speed: 0.35, energy: 0.28, turbulence: 0.18, pulse: 0 },
  listening: { colors: ["#A855F7", "#D8B4FE", "#6D28D9"], speed: 0.55, energy: 0.5, turbulence: 0.3, pulse: 0 },
  thinking: { colors: ["#FFD600", "#FFF176", "#FF8F00"], speed: 1.45, energy: 0.78, turbulence: 0.85, pulse: 0 },
  speaking: { colors: ["#00E676", "#69F0AE", "#00A86B"], speed: 0.75, energy: 0.62, turbulence: 0.4, pulse: 0 },
  error: { colors: ["#FF1744", "#FF4D6A", "#B0002A"], speed: 0.22, energy: 0.45, turbulence: 0.3, pulse: 1 },
};

/** The primary colour of each state: text, HUD accents and the core all follow it. */
export const STATE_COLOR: Record<CoreState, string> = {
  idle: LOOKS.idle.colors[0],
  listening: LOOKS.listening.colors[0],
  thinking: LOOKS.thinking.colors[0],
  speaking: LOOKS.speaking.colors[0],
  error: LOOKS.error.colors[0],
};
