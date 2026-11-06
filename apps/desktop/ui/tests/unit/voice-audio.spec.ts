import { describe, expect, it } from "vitest";
import { downsample, encodeWav, isNoise, rms, sentences, speakable, TurnDetector } from "@/voice/audio";

describe("voice audio helpers (Phase 13)", () => {
  it("resamples to 16 kHz and writes a 16-bit mono PCM WAV", () => {
    const input = new Float32Array(48_000).fill(0.5);
    const out = downsample(input, 48_000);
    expect(out.length).toBe(16_000);
    const wav = encodeWav(out);
    const view = new DataView(wav.buffer);
    expect(String.fromCharCode(...wav.slice(0, 4))).toBe("RIFF");
    expect(String.fromCharCode(...wav.slice(8, 12))).toBe("WAVE");
    expect(view.getUint16(20, true)).toBe(1);
    expect(view.getUint16(22, true)).toBe(1);
    expect(view.getUint32(24, true)).toBe(16_000);
    expect(view.getUint16(34, true)).toBe(16);
    expect(wav.length).toBe(44 + 32_000);
    expect(view.getInt16(44, true)).toBe(Math.round(0.5 * 0x7fff));
  });

  it("detects a turn from loudness: start after 150 ms, end after 900 ms of silence", () => {
    const d = new TurnDetector();
    const loud = 0.1;
    const quiet = 0.001;
    const events: (string | null)[] = [];
    for (let i = 0; i < 5; i++) events.push(d.feed(quiet, 50));
    for (let i = 0; i < 3; i++) events.push(d.feed(loud, 50));
    expect(events.filter(Boolean)).toEqual(["start"]);
    for (let i = 0; i < 17; i++) expect(d.feed(quiet, 50)).toBeNull();
    expect(d.feed(quiet, 50)).toBe("end");
    expect(d.speaking).toBe(false);
  });

  it("ends a turn that runs past the maximum", () => {
    const d = new TurnDetector(0.015, 50, 900, 1_000);
    expect(d.feed(0.1, 50)).toBe("start");
    let ended = false;
    for (let i = 0; i < 25 && !ended; i++) ended = d.feed(0.1, 50) === "end";
    expect(ended).toBe(true);
  });

  it("measures loudness", () => {
    expect(rms(new Float32Array([0.5, -0.5]))).toBeCloseTo(0.5);
    expect(rms(new Float32Array())).toBe(0);
  });

  it("drops what Whisper writes for silence", () => {
    for (const t of ["Altyazı M.K.", "İzlediğiniz için teşekkür ederim.", "[Müzik]", "Teşekkürler.", " . ", "Abone olmayı unutmayın"]) {
      expect(isNoise(t)).toBe(true);
    }
    for (const t of ["Bugün hava nasıl?", "Teşekkürler, peki yarın ne yapalım?"]) expect(isNoise(t)).toBe(false);
  });

  it("speaks the reply's words, not its Markdown", () => {
    const md = "## Başlık\n\n- **Birinci** madde, [kaynak](https://tr.wikipedia.org/wiki/X).\n```js\nkod()\n```\nSon cümle `kod` ile.";
    expect(speakable(md)).toBe("Başlık\nBirinci madde, kaynak.\nSon cümle kod ile.");
  });

  it("splits into sentences for speaking", () => {
    expect(sentences("Merhaba efendim. Nasılsınız? Bugün güzel!\nYeni satır")).toEqual([
      "Merhaba efendim.",
      "Nasılsınız?",
      "Bugün güzel!",
      "Yeni satır",
    ]);
  });
});
