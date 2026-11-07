/**
 * The living core (Phase 14): the LAZOS scene (apps/desktop/src/components/ai-core/CoreScene.tsx)
 * ported layer by layer from React Three Fiber to plain three.js, so LAZIS stays Vue and needs no
 * renderer framework. Same geometry, same shaders, same per-frame driver.
 *
 * The only per-frame CPU work is the driver: colours and energy ease towards the current state's
 * look (never a cut), the phase advances, and the audio level follows the real microphone while
 * listening and Yelda's real output while speaking.
 */
import {
  AdditiveBlending,
  BufferAttribute,
  BufferGeometry,
  CatmullRomCurve3,
  Color,
  EdgesGeometry,
  Group,
  IcosahedronGeometry,
  Line,
  LineSegments,
  Mesh,
  type Object3D,
  PerspectiveCamera,
  PlaneGeometry,
  Points,
  RingGeometry,
  Scene,
  ShaderMaterial,
  TubeGeometry,
  Vector2,
  Vector3,
  WebGLRenderer,
} from "three";
import { EffectComposer } from "three/examples/jsm/postprocessing/EffectComposer.js";
import { OutputPass } from "three/examples/jsm/postprocessing/OutputPass.js";
import { RenderPass } from "three/examples/jsm/postprocessing/RenderPass.js";
import { ShaderPass } from "three/examples/jsm/postprocessing/ShaderPass.js";
import { UnrealBloomPass } from "three/examples/jsm/postprocessing/UnrealBloomPass.js";
import { LOOKS, type CoreState } from "@/core/palette";
import * as S from "@/core/shaders";
import { createCoreUniforms, type CoreUniforms } from "@/core/uniforms";

export type Quality = "high" | "low";

/** Bloom strength at rest (Phase 14.1). It eases down as the voice gets louder, so a loud
 *  stretch of listening or speaking keeps its detail instead of melting into one glow. */
const BLOOM = 0.5;
const BLOOM_LEVEL_DROP = 0.55;
const BLOOM_THRESHOLD = 0.55;
/** Bloom picks what glows by luminance, and yellow and green are far brighter to the eye than
 *  purple or red at the same strength, so they used to bloom over everything. Above this
 *  luminance of the state's colour, bloom is toned down and starts higher. */
const BLOOM_LUMA_REF = 0.45;

type Extra = Record<string, { value: unknown }>;

function additive(u: CoreUniforms, vertexShader: string, fragmentShader: string, extra: Extra = {}): ShaderMaterial {
  return new ShaderMaterial({
    uniforms: { ...u, ...extra },
    vertexShader,
    fragmentShader,
    transparent: true,
    depthWrite: false,
    blending: AdditiveBlending,
    premultipliedAlpha: true,
  });
}

function randomDir(): Vector3 {
  return new Vector3(Math.random() * 2 - 1, Math.random() * 2 - 1, Math.random() * 2 - 1).normalize();
}

interface Layer {
  object: Object3D;
  update?: () => void;
}

// ── Layers (one function per LAZOS component) ───────────────────────────────
function backdrop(u: CoreUniforms): Layer & { aspect: Vector2 } {
  const aspect = new Vector2(1, 1);
  const mat = new ShaderMaterial({
    uniforms: { ...u, uAspect: { value: aspect }, uCenter: { value: new Vector2(0.5, 0.5) } },
    vertexShader: S.backdropVertex,
    fragmentShader: S.backdropFragment,
    depthWrite: false,
    depthTest: false,
  });
  const mesh = new Mesh(new PlaneGeometry(2, 2), mat);
  mesh.frustumCulled = false;
  mesh.renderOrder = -10;
  return { object: mesh, aspect };
}

function energyCore(u: CoreUniforms, quality: Quality): Layer {
  const detail = quality === "high" ? 64 : 28;
  const shell = new Mesh(
    new IcosahedronGeometry(0.66, detail),
    additive(u, S.coreVertex, S.shellPlasmaFragment, { uAmp: { value: 1 } }),
  );
  const nucleus = new Mesh(
    new IcosahedronGeometry(0.27, Math.round(detail / 2)),
    new ShaderMaterial({ uniforms: { ...u, uAmp: { value: 1.6 } }, vertexShader: S.coreVertex, fragmentShader: S.nucleusFragment }),
  );
  const group = new Group();
  group.add(nucleus, shell);
  return {
    object: group,
    update: () => {
      const p = u.uPhase.value;
      shell.rotation.set(Math.sin(p * 0.15) * 0.25, p * 0.35, 0);
      nucleus.rotation.set(0, -p * 0.6, p * 0.2);
      nucleus.scale.setScalar(1 + u.uLevel.value * 0.35 + Math.sin(u.uTime.value * 1.7) * 0.03);
    },
  };
}

function glow(u: CoreUniforms, size: number, strength: number, falloff: number): Layer {
  const mesh = new Mesh(
    new PlaneGeometry(size, size),
    additive(u, S.glowVertex, S.glowFragment, { uStrength: { value: strength }, uFalloff: { value: falloff } }),
  );
  mesh.renderOrder = -1;
  return { object: mesh };
}

function geodesic(u: CoreUniforms): Layer {
  const group = new Group();
  const inner = new LineSegments(
    new EdgesGeometry(new IcosahedronGeometry(0.92, 1)),
    additive(u, S.shellVertex, S.shellFragment, { uOpacity: { value: 0.55 } }),
  );
  const outer = new LineSegments(
    new EdgesGeometry(new IcosahedronGeometry(1.08, 0)),
    additive(u, S.shellVertex, S.shellFragment, { uOpacity: { value: 0.3 } }),
  );
  group.add(inner, outer);
  return {
    object: group,
    update: () => {
      const p = u.uPhase.value;
      inner.rotation.set(p * 0.11, -p * 0.17, 0);
      outer.rotation.set(-p * 0.07, p * 0.09, p * 0.05);
      group.scale.setScalar(1 + u.uLevel.value * 0.06);
    },
  };
}

interface RingSpec {
  inner: number;
  outer: number;
  kind: number;
  segments: number;
  dir: number;
  spin: number;
  opacity: number;
  tilt: [number, number, number];
  react: number;
}

const RINGS: RingSpec[] = [
  { inner: 1.2, outer: 1.235, kind: 0, segments: 48, dir: 1, spin: 0.08, opacity: 0.9, tilt: [0, 0, 0], react: 0.05 },
  { inner: 1.32, outer: 1.42, kind: 1, segments: 120, dir: -1, spin: 0.03, opacity: 0.55, tilt: [0, 0, 0], react: 0.03 },
  { inner: 1.55, outer: 1.575, kind: 3, segments: 1, dir: 1, spin: 0.05, opacity: 0.7, tilt: [1.2, 0.2, 0], react: 0.06 },
  { inner: 1.7, outer: 1.78, kind: 2, segments: 1, dir: 1, spin: 0.22, opacity: 0.9, tilt: [0, 0, 0], react: 0.04 },
  { inner: 1.88, outer: 1.9, kind: 0, segments: 180, dir: -1, spin: 0.02, opacity: 0.6, tilt: [-1.05, -0.35, 0.2], react: 0.07 },
  { inner: 2.15, outer: 2.2, kind: 3, segments: 1, dir: -1, spin: 0.035, opacity: 0.45, tilt: [0.35, 0.9, 0], react: 0.05 },
  { inner: 2.45, outer: 2.53, kind: 1, segments: 240, dir: 1, spin: 0.012, opacity: 0.35, tilt: [0, 0, 0], react: 0.02 },
];

function rings(u: CoreUniforms): Layer {
  const group = new Group();
  const meshes = RINGS.map((r) => {
    const mesh = new Mesh(
      new RingGeometry(r.inner, r.outer, 256, 1),
      additive(u, S.ringVertex, S.ringFragment, {
        uInner: { value: r.inner },
        uOuter: { value: r.outer },
        uKind: { value: r.kind },
        uSegments: { value: r.segments },
        uDir: { value: r.dir },
        uSpin: { value: r.spin },
        uOpacity: { value: r.opacity },
      }),
    );
    group.add(mesh);
    return mesh;
  });
  return {
    object: group,
    update: () => {
      const p = u.uPhase.value;
      const lvl = u.uLevel.value;
      meshes.forEach((mesh, i) => {
        const spec = RINGS[i]!;
        const precess = p * 0.04 * (i % 2 === 0 ? 1 : -1);
        mesh.rotation.set(spec.tilt[0] + Math.sin(p * 0.1 + i) * 0.04, spec.tilt[1] + precess, spec.tilt[2]);
        mesh.scale.setScalar(1 + lvl * spec.react * (i % 2 === 0 ? 1.4 : -0.6) + u.uEnergy.value * 0.015);
      });
    },
  };
}

function waveform(u: CoreUniforms): Layer {
  const group = new Group();
  for (const b of [
    { base: 1.0, w: 0.012, seed: 0, opacity: 0.9 },
    { base: 1.035, w: 0.006, seed: 3.7, opacity: 0.55 },
    { base: 0.97, w: 0.006, seed: 7.1, opacity: 0.45 },
  ]) {
    group.add(
      new Mesh(
        new RingGeometry(b.base - b.w, b.base + b.w, 512, 1),
        additive(u, S.waveVertex, S.waveFragment, {
          uBase: { value: b.base },
          uSeed: { value: b.seed },
          uOpacity: { value: b.opacity },
        }),
      ),
    );
  }
  return { object: group };
}

function particles(u: CoreUniforms, count: number): Layer {
  const g = new BufferGeometry();
  const radius = new Float32Array(count);
  const theta = new Float32Array(count);
  const y = new Float32Array(count);
  const speed = new Float32Array(count);
  const size = new Float32Array(count);
  const seed = new Float32Array(count);
  const tilt = new Float32Array(count);
  for (let i = 0; i < count; i++) {
    if (Math.random() < 0.68) {
      const plane = i % 3;
      radius[i] = 1.35 + Math.pow(Math.random(), 1.6) * 2.4;
      y[i] = (Math.random() - 0.5) * 0.12 * radius[i]!;
      tilt[i] = [0.18, -0.55, 1.05][plane]! + (Math.random() - 0.5) * 0.05;
      speed[i] = 0.25 + Math.random() * 0.35;
    } else {
      radius[i] = 1.15 + Math.random() * 1.6;
      y[i] = (Math.random() * 2 - 1) * radius[i]! * 0.8;
      tilt[i] = Math.random() * Math.PI;
      speed[i] = 0.08 + Math.random() * 0.2;
    }
    theta[i] = Math.random() * Math.PI * 2;
    size[i] = 1.2 + Math.pow(Math.random(), 3) * 4.5;
    seed[i] = Math.random();
  }
  g.setAttribute("position", new BufferAttribute(new Float32Array(count * 3), 3));
  g.setAttribute("aRadius", new BufferAttribute(radius, 1));
  g.setAttribute("aTheta", new BufferAttribute(theta, 1));
  g.setAttribute("aY", new BufferAttribute(y, 1));
  g.setAttribute("aSpeed", new BufferAttribute(speed, 1));
  g.setAttribute("aSize", new BufferAttribute(size, 1));
  g.setAttribute("aSeed", new BufferAttribute(seed, 1));
  g.setAttribute("aTilt", new BufferAttribute(tilt, 1));
  const points = new Points(g, additive(u, S.particleVertex, S.particleFragment));
  points.frustumCulled = false;
  return { object: points };
}

function streams(u: CoreUniforms, count: number): Layer {
  const group = new Group();
  for (let i = 0; i < count; i++) {
    const a = randomDir();
    const b = randomDir();
    const mid = a.clone().add(b).normalize();
    const reach = 1.35 + Math.random() * 1.0;
    const curve = new CatmullRomCurve3([
      a.clone().multiplyScalar(0.64),
      a.clone().lerp(mid, 0.5).normalize().multiplyScalar(reach * 0.85),
      mid.clone().multiplyScalar(reach),
      b.clone().lerp(mid, 0.5).normalize().multiplyScalar(reach * 0.85),
      b.clone().multiplyScalar(0.64),
    ]);
    group.add(
      new Mesh(
        new TubeGeometry(curve, 96, 0.0045 + Math.random() * 0.004, 5, false),
        additive(u, S.streamVertex, S.streamFragment, {
          uSeed: { value: i / count },
          uRate: { value: 0.18 + Math.random() * 0.25 },
        }),
      ),
    );
  }
  return { object: group, update: () => group.rotation.set(u.uPhase.value * 0.05, u.uPhase.value * 0.13, 0) };
}

function arcs(u: CoreUniforms, count: number): Layer {
  const n = 28;
  const geo = new BufferGeometry();
  const t = new Float32Array(n);
  for (let i = 0; i < n; i++) t[i] = i / (n - 1);
  geo.setAttribute("position", new BufferAttribute(new Float32Array(n * 3), 3));
  geo.setAttribute("aT", new BufferAttribute(t, 1));
  const group = new Group();
  for (let i = 0; i < count; i++) {
    const a = randomDir();
    const b = a.clone().add(randomDir().multiplyScalar(0.7)).normalize();
    const line = new Line(
      geo,
      additive(u, S.arcVertex, S.arcFragment, { uSeed: { value: i * 0.37 + Math.random() }, uStart: { value: a }, uEnd: { value: b } }),
    );
    line.frustumCulled = false;
    group.add(line);
  }
  return { object: group };
}

function scanRing(u: CoreUniforms): Layer {
  const mat = additive(u, S.ringVertex, S.ringFragment, {
    uInner: { value: 0.98 },
    uOuter: { value: 1.0 },
    uKind: { value: 0 },
    uSegments: { value: 64 },
    uDir: { value: 1 },
    uSpin: { value: 0.3 },
    uOpacity: { value: 0 },
  });
  const mesh = new Mesh(new RingGeometry(0.98, 1.0, 128, 1), mat);
  mesh.rotation.set(Math.PI / 2, 0, 0);
  return {
    object: mesh,
    update: () => {
      const yy = Math.sin(u.uTime.value * 1.3 * u.uMotion.value) * 0.62;
      mesh.position.y = yy;
      mesh.scale.setScalar((Math.sqrt(Math.max(0.0001, 0.7 * 0.7 - yy * yy)) / 0.7) * 0.74);
      (mat.uniforms.uOpacity as { value: number }).value = Math.max(0, (u.uEnergy.value - 0.55) * 3.2);
    },
  };
}

function dispose(object: Object3D): void {
  object.traverse((o) => {
    const m = o as Mesh;
    m.geometry?.dispose();
    const material = m.material as ShaderMaterial | ShaderMaterial[] | undefined;
    (Array.isArray(material) ? material : material ? [material] : []).forEach((x) => x.dispose());
  });
}

// ── The renderer ────────────────────────────────────────────────────────────
export interface FrameInputs {
  state: CoreState;
  /** 0…1 from the real source of this state (microphone or Yelda), 0 otherwise. */
  level: number;
}

export class CoreRenderer {
  readonly u = createCoreUniforms();
  private readonly renderer: WebGLRenderer;
  private readonly scene = new Scene();
  private readonly camera = new PerspectiveCamera(42, 1, 0.1, 50);
  private readonly composer: EffectComposer;
  private readonly bloom: UnrealBloomPass;
  private readonly back = backdrop(this.u);
  private layers: Layer[] = [];
  private content = new Group();
  private speed = 0.35;
  private level = 0;
  private readonly tmp = [new Color(), new Color(), new Color()] as const;
  pointer = new Vector2(0, 0);
  quality: Quality;
  dpr: number;

  constructor(
    canvas: HTMLCanvasElement,
    options: { quality: Quality; dpr: number; reducedMotion: boolean },
  ) {
    this.quality = options.quality;
    this.dpr = options.dpr;
    this.reducedMotion = options.reducedMotion;
    this.renderer = new WebGLRenderer({ canvas, antialias: false, powerPreference: "high-performance", alpha: false, stencil: false });
    this.renderer.setPixelRatio(this.dpr);
    this.camera.position.set(0, 0, 7.4);
    this.scene.add(this.back.object, this.content);
    this.composer = new EffectComposer(this.renderer);
    this.composer.addPass(new RenderPass(this.scene, this.camera));
    // Phase 14.1: bloom starts higher, is gentler and stays close to what glows (a wide radius
    // spread a haze over the whole core and washed the centre to white);
    // the final pass keeps the vignette and rolls bright colours off without whitening them.
    this.bloom = new UnrealBloomPass(new Vector2(256, 256), BLOOM, 0.1, BLOOM_THRESHOLD);
    this.composer.addPass(this.bloom);
    this.composer.addPass(new ShaderPass(S.gradeShader));
    this.composer.addPass(new OutputPass());
    this.build();
  }

  reducedMotion: boolean;

  private build(): void {
    this.layers.forEach((l) => dispose(l.object));
    this.content.clear();
    const high = this.quality === "high";
    this.layers = [
      glow(this.u, 6, 0.2, 6),
      glow(this.u, 2.3, 0.4, 7.5),
      particles(this.u, high ? 4200 : 1800),
      streams(this.u, high ? 9 : 5),
      rings(this.u),
      waveform(this.u),
      geodesic(this.u),
      arcs(this.u, high ? 5 : 3),
      scanRing(this.u),
      energyCore(this.u, this.quality),
    ];
    this.layers.forEach((l) => this.content.add(l.object));
  }

  setQuality(quality: Quality): void {
    if (quality === this.quality) return;
    this.quality = quality;
    this.build();
  }

  setPixelRatio(dpr: number): void {
    this.dpr = dpr;
    this.renderer.setPixelRatio(dpr);
    this.u.uPixelRatio.value = dpr;
  }

  resize(width: number, height: number): void {
    if (width <= 0 || height <= 0) return;
    this.renderer.setSize(width, height, false);
    this.composer.setPixelRatio(this.dpr);
    this.composer.setSize(width, height);
    this.bloom.resolution.set(width / 2, height / 2);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.back.aspect.set(width / height, 1);
    this.u.uPixelRatio.value = this.renderer.getPixelRatio();
  }

  /** One frame. `dt` in seconds. */
  frame(dt: number, inputs: FrameInputs): void {
    const u = this.u;
    dt = Math.min(dt, 0.05);
    const look = LOOKS[inputs.state];
    const k = 1 - Math.exp(-dt * 2.6);
    const motion = this.reducedMotion ? 0.35 : 1;
    u.uMotion.value += (motion - u.uMotion.value) * k;
    u.uColorA.value.lerp(this.tmp[0].set(look.colors[0]), k);
    u.uColorB.value.lerp(this.tmp[1].set(look.colors[1]), k);
    u.uColorC.value.lerp(this.tmp[2].set(look.colors[2]), k);
    u.uEnergy.value += (look.energy - u.uEnergy.value) * k;
    u.uTurb.value += (look.turbulence - u.uTurb.value) * k;
    u.uPulse.value += (look.pulse - u.uPulse.value) * k;
    this.speed += (look.speed - this.speed) * k;
    u.uPhase.value += dt * this.speed * u.uMotion.value;
    u.uTime.value += dt;

    const target = this.reducedMotion ? inputs.level * 0.4 : inputs.level;
    const rate = target > this.level ? 22 : 7; // fast attack, slower release
    this.level += (target - this.level) * (1 - Math.exp(-dt * rate));
    u.uLevel.value = this.level;
    const c = u.uColorA.value;
    const luma = 0.2126 * c.r + 0.7152 * c.g + 0.0722 * c.b;
    this.bloom.strength = BLOOM * Math.min(1, BLOOM_LUMA_REF / Math.max(luma, 0.05)) * (1 - BLOOM_LEVEL_DROP * this.level);
    this.bloom.threshold = BLOOM_THRESHOLD + 0.4 * Math.max(0, luma - BLOOM_LUMA_REF);

    const px = this.reducedMotion ? 0 : this.pointer.x * 0.28;
    const py = this.reducedMotion ? 0 : this.pointer.y * 0.18;
    this.camera.position.x += (px - this.camera.position.x) * (1 - Math.exp(-dt * 1.6));
    this.camera.position.y += (py - this.camera.position.y) * (1 - Math.exp(-dt * 1.6));
    this.camera.lookAt(0, 0, 0);

    for (const layer of this.layers) layer.update?.();
    this.composer.render(dt);
  }

  dispose(): void {
    this.layers.forEach((l) => dispose(l.object));
    dispose(this.back.object);
    this.composer.dispose();
    this.renderer.dispose();
  }
}
