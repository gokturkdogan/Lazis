import { Color } from "three";

/**
 * One uniform set shared by every material of the core (as in LAZOS): uniform objects are shared
 * by reference, so one update per frame drives the whole entity.
 */
export function createCoreUniforms() {
  return {
    uTime: { value: 0 },
    uPhase: { value: 0 },
    uColorA: { value: new Color("#00BFFF") },
    uColorB: { value: new Color("#00E5FF") },
    uColorC: { value: new Color("#0066FF") },
    uEnergy: { value: 0.28 },
    uLevel: { value: 0 },
    uTurb: { value: 0.18 },
    uPulse: { value: 0 },
    uMotion: { value: 1 },
    uPixelRatio: { value: 1 },
    /** Phase 14.2: how far energy has travelled through the neural lattice (advanced per frame
     *  from the state's pace and the real voice; never jumps). */
    uFlow: { value: 0 },
    /** Phase 14.2: the real voice level as the lattice feels it (eases back slowly). */
    uVoice: { value: 0 },
  };
}

export type CoreUniforms = ReturnType<typeof createCoreUniforms>;
