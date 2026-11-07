import { describe, expect, it } from "vitest";
import { buildLattice, easeVoice, edgeArrays, flowRate, LATTICE } from "@/core/lattice";
import { LOOKS, STATE_COLOR } from "@/core/palette";

describe("Neural lattice (Phase 14.2)", () => {
  it("is the same structure every launch (fixed seed)", () => {
    const a = buildLattice(130);
    const b = buildLattice(130);
    expect(Array.from(a.nodes)).toEqual(Array.from(b.nodes));
    expect(a.edges).toEqual(b.edges);
  });

  it("spreads its nodes through the core's volume, not on one surface", () => {
    const l = buildLattice(130);
    expect(l.nodes.length / 3).toBe(130);
    const radii: number[] = [];
    for (let i = 0; i < l.nodes.length; i += 3) radii.push(Math.hypot(l.nodes[i]!, l.nodes[i + 1]!, l.nodes[i + 2]!));
    expect(Math.min(...radii)).toBeGreaterThanOrEqual(LATTICE.innerRadius - 1e-6);
    expect(Math.max(...radii)).toBeLessThanOrEqual(LATTICE.outerRadius + 1e-6);
    const inner = radii.filter((r) => r < 0.35).length;
    expect(inner).toBeGreaterThan(10); // depth: nodes inside, not only near the shell
  });

  it("connects every node, without duplicates or long spokes", () => {
    const l = buildLattice(130);
    const n = l.nodes.length / 3;
    const degree = new Array(n).fill(0);
    const keys = new Set<string>();
    for (const [i, j] of l.edges) {
      expect(i).not.toBe(j);
      const k = `${Math.min(i, j)}-${Math.max(i, j)}`;
      expect(keys.has(k)).toBe(false);
      keys.add(k);
      degree[i]++;
      degree[j]++;
    }
    expect(Math.min(...degree)).toBeGreaterThanOrEqual(1);
    expect(l.edges.length).toBeGreaterThan(n); // a web, not a chain
    expect(l.edges.length).toBeLessThan(n * LATTICE.neighbours);
  });

  it("stays light on the GPU: two draw calls, a few thousand vertices", () => {
    const high = edgeArrays(buildLattice(130));
    const low = edgeArrays(buildLattice(70));
    expect(high.t.length).toBeLessThan(6000);
    expect(low.t.length).toBeLessThan(high.t.length);
    // each connection starts and ends exactly on its nodes (the bend is zero at both ends)
    expect(Math.min(...high.t)).toBe(0);
    expect(Math.max(...high.t)).toBe(1);
  });

  it("follows the real voice: up quickly, back slowly, and exactly still without sound", () => {
    let v = 0;
    for (let i = 0; i < 6; i++) v = easeVoice(v, 0.8, 1 / 60);
    expect(v).toBeGreaterThan(0.6); // ~0.1 s to follow the voice
    let settle = v;
    for (let i = 0; i < 30; i++) settle = easeVoice(settle, 0, 1 / 60);
    expect(settle).toBeGreaterThan(0.1); // half a second later still settling, not cut off
    for (let i = 0; i < 600; i++) settle = easeVoice(settle, 0, 1 / 60);
    expect(settle).toBe(0); // and then truly still
    // no sound at all never produces any voice activity
    let quiet = 0;
    for (let i = 0; i < 600; i++) quiet = easeVoice(quiet, 0, 1 / 60);
    expect(quiet).toBe(0);
  });

  it("moves energy at the state's own pace, faster only with real voice", () => {
    const idle = flowRate(LOOKS.idle.speed, 0);
    const thinking = flowRate(LOOKS.thinking.speed, 0);
    expect(thinking).toBeGreaterThan(idle);
    expect(flowRate(LOOKS.speaking.speed, 0.8)).toBeGreaterThan(flowRate(LOOKS.speaking.speed, 0));
    expect(idle).toBeGreaterThan(0); // idle still breathes, slowly
  });

  it("keeps the owner's five state colours as the primary tone", () => {
    expect(STATE_COLOR).toEqual({
      idle: "#00BFFF",
      listening: "#A855F7",
      thinking: "#FFD600",
      speaking: "#00E676",
      error: "#FF1744",
    });
  });
});
