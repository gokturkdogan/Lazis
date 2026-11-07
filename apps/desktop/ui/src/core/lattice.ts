/**
 * The neural lattice inside the core (Phase 14.2): nodes spread through the core's volume and
 * thin, slightly curved connections between near neighbours. Built once per quality level from
 * a fixed seed, so the structure is the same every launch and testable without a GPU. All
 * motion happens in the shaders; the CPU only advances two numbers per frame (flow and voice).
 */

export interface Lattice {
  /** xyz per node */
  nodes: Float32Array;
  /** 0…1 per node, offsets its rhythm */
  seeds: Float32Array;
  /** point size per node */
  sizes: Float32Array;
  /** node index pairs */
  edges: [number, number][];
}

export const LATTICE = {
  innerRadius: 0.1,
  outerRadius: 0.56,
  /** nearest neighbours each node reaches for */
  neighbours: 3,
  /** no connection longer than this (keeps it a web, not a star) */
  maxEdge: 0.36,
  /** straight segments per connection (curved by a sideways bend) */
  segments: 8,
} as const;

/** Small, fast, deterministic PRNG (mulberry32). */
export function rng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function buildLattice(count: number, seed = 1402): Lattice {
  const rand = rng(seed);
  const { innerRadius: r0, outerRadius: r1 } = LATTICE;
  const nodes = new Float32Array(count * 3);
  const seeds = new Float32Array(count);
  const sizes = new Float32Array(count);
  const minGap = 0.075;
  let placed = 0;
  let guard = 0;
  while (placed < count && guard++ < count * 400) {
    // Uniform in the shell's volume, then spaced a little so nodes do not clump.
    const u = rand() * 2 - 1;
    const phi = rand() * Math.PI * 2;
    const r = Math.cbrt(r0 ** 3 + rand() * (r1 ** 3 - r0 ** 3));
    const s = Math.sqrt(1 - u * u);
    const x = r * s * Math.cos(phi);
    const y = r * u;
    const z = r * s * Math.sin(phi);
    let ok = true;
    for (let j = 0; j < placed && ok; j++) {
      const dx = nodes[j * 3]! - x;
      const dy = nodes[j * 3 + 1]! - y;
      const dz = nodes[j * 3 + 2]! - z;
      ok = dx * dx + dy * dy + dz * dz >= minGap * minGap;
    }
    if (!ok) continue;
    nodes.set([x, y, z], placed * 3);
    seeds[placed] = rand();
    sizes[placed] = 2.0 + Math.pow(rand(), 2.5) * 3.2;
    placed++;
  }
  const n = placed;
  const key = (a: number, b: number) => (a < b ? a * 100000 + b : b * 100000 + a);
  const seen = new Set<number>();
  const edges: [number, number][] = [];
  const dist = (a: number, b: number) =>
    Math.hypot(nodes[a * 3]! - nodes[b * 3]!, nodes[a * 3 + 1]! - nodes[b * 3 + 1]!, nodes[a * 3 + 2]! - nodes[b * 3 + 2]!);
  for (let i = 0; i < n; i++) {
    const near = [...Array(n).keys()]
      .filter((j) => j !== i)
      .sort((a, b) => dist(i, a) - dist(i, b))
      .slice(0, LATTICE.neighbours);
    near.forEach((j, rank) => {
      // The nearest is always joined (no node is left alone); the others only if close enough.
      if (rank > 0 && dist(i, j) > LATTICE.maxEdge) return;
      const k = key(i, j);
      if (seen.has(k)) return;
      seen.add(k);
      edges.push([i, j]);
    });
  }
  return { nodes: nodes.slice(0, n * 3), seeds: seeds.slice(0, n), sizes: sizes.slice(0, n), edges };
}

/** Vertex arrays for the connections, drawn as one LineSegments (one draw call). */
export function edgeArrays(l: Lattice, segments: number = LATTICE.segments, seed = 2207) {
  const rand = rng(seed);
  const count = l.edges.length * segments * 2;
  const a = new Float32Array(count * 3);
  const b = new Float32Array(count * 3);
  const bend = new Float32Array(count * 3);
  const t = new Float32Array(count);
  const s = new Float32Array(count);
  let v = 0;
  for (const [i, j] of l.edges) {
    const A = [l.nodes[i * 3]!, l.nodes[i * 3 + 1]!, l.nodes[i * 3 + 2]!] as const;
    const B = [l.nodes[j * 3]!, l.nodes[j * 3 + 1]!, l.nodes[j * 3 + 2]!] as const;
    const len = Math.hypot(B[0] - A[0], B[1] - A[1], B[2] - A[2]);
    // A sideways bend, perpendicular-ish to the connection, a fraction of its length.
    const r = [rand() * 2 - 1, rand() * 2 - 1, rand() * 2 - 1];
    const dir = [(B[0] - A[0]) / len, (B[1] - A[1]) / len, (B[2] - A[2]) / len];
    const dot = r[0]! * dir[0]! + r[1]! * dir[1]! + r[2]! * dir[2]!;
    const p = [r[0]! - dot * dir[0]!, r[1]! - dot * dir[1]!, r[2]! - dot * dir[2]!];
    const pl = Math.hypot(p[0]!, p[1]!, p[2]!) || 1;
    const amount = len * (0.04 + rand() * 0.1);
    const bendV = [(p[0]! / pl) * amount, (p[1]! / pl) * amount, (p[2]! / pl) * amount];
    const edgeSeed = rand();
    for (let k = 0; k < segments; k++) {
      for (const tt of [k / segments, (k + 1) / segments]) {
        a.set(A, v * 3);
        b.set(B, v * 3);
        bend.set(bendV, v * 3);
        t[v] = tt;
        s[v] = edgeSeed;
        v++;
      }
    }
  }
  return { a, b, bend, t, seed: s };
}

/**
 * The voice as the lattice feels it: follows the real level (microphone or Yelda) quickly up,
 * and settles back slowly, so the network calms down naturally when the sound stops. With no
 * sound it decays to exactly zero: nothing is invented.
 */
export function easeVoice(current: number, target: number, dt: number): number {
  const rate = target > current ? 14 : 2.4;
  const next = current + (target - current) * (1 - Math.exp(-dt * rate));
  return next < 1e-4 && target === 0 ? 0 : next;
}

/** How fast energy moves through the lattice: the state's own pace, faster with real voice. */
export function flowRate(stateSpeed: number, voice: number): number {
  return 0.22 + stateSpeed * 0.42 + voice * 1.5;
}
