import { afterEach, describe, expect, it, vi } from "vitest";

import { encodePcm16Wav, resampleMono, startPcmWavRecorder } from "./pcmWavRecorder";

const originalMediaDevices = Object.getOwnPropertyDescriptor(navigator, "mediaDevices");
const originalAudioContext = Object.getOwnPropertyDescriptor(window, "AudioContext");

function ascii(view: DataView, offset: number, length: number): string {
  return Array.from({ length }, (_, index) => String.fromCharCode(view.getUint8(offset + index))).join("");
}

afterEach(() => {
  if (originalMediaDevices) Object.defineProperty(navigator, "mediaDevices", originalMediaDevices);
  else Reflect.deleteProperty(navigator, "mediaDevices");
  if (originalAudioContext) Object.defineProperty(window, "AudioContext", originalAudioContext);
  else Reflect.deleteProperty(window, "AudioContext");
});

function installRecorderBoundary() {
  const trackStop = vi.fn();
  const source = { connect: vi.fn(), disconnect: vi.fn() };
  const processor = { connect: vi.fn(), disconnect: vi.fn(), onaudioprocess: null as ((event: { inputBuffer: { getChannelData: () => Float32Array } }) => void) | null };
  const gain = { connect: vi.fn(), disconnect: vi.fn(), gain: { value: 1 } };
  const close = vi.fn(async () => undefined);
  const context = {
    sampleRate: 32000,
    state: "running",
    destination: {},
    createMediaStreamSource: vi.fn(() => source),
    createScriptProcessor: vi.fn(() => processor),
    createGain: vi.fn(() => gain),
    close,
    resume: vi.fn(async () => undefined),
  };
  const stream = { getTracks: () => [{ stop: trackStop }] };
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia: vi.fn(async () => stream) },
  });
  Object.defineProperty(window, "AudioContext", {
    configurable: true,
    value: vi.fn(function SyntheticAudioContext() { return context; }),
  });
  return { close, processor, trackStop };
}

describe("local PCM WAV encoding", () => {
  it("writes a bounded mono PCM16 WAV with clipped samples", async () => {
    const blob = encodePcm16Wav(new Float32Array([-2, -1, 0, 1, 2]), 16000);
    const view = new DataView(await blob.arrayBuffer());

    expect(blob.type).toBe("audio/wav");
    expect(blob.size).toBe(54);
    expect(ascii(view, 0, 4)).toBe("RIFF");
    expect(ascii(view, 8, 4)).toBe("WAVE");
    expect(view.getUint16(20, true)).toBe(1);
    expect(view.getUint16(22, true)).toBe(1);
    expect(view.getUint32(24, true)).toBe(16000);
    expect(view.getUint16(34, true)).toBe(16);
    expect(view.getUint32(40, true)).toBe(10);
    expect(view.getInt16(44, true)).toBe(-32768);
    expect(view.getInt16(52, true)).toBe(32767);
  });

  it("resamples deterministically and preserves an already matching rate", () => {
    const input = new Float32Array([0, 0.5, 1, -0.5]);
    expect(resampleMono(input, 32000, 16000)).toEqual(new Float32Array([0, 1]));
    expect(resampleMono(input, 16000, 16000)).toBe(input);
    expect(resampleMono(new Float32Array(), 48000, 16000)).toHaveLength(0);
  });

  it("stops capture idempotently, emits admitted PCM WAV, and releases the microphone", async () => {
    const boundary = installRecorderBoundary();
    const recorder = await startPcmWavRecorder(10_000);
    boundary.processor.onaudioprocess?.({
      inputBuffer: { getChannelData: () => new Float32Array([0, 0.25, 0.5, 0.75]) },
    });
    recorder.stop();
    recorder.stop();

    const result = await recorder.finished;
    expect(result).not.toBeNull();
    expect(result?.type).toBe("audio/wav");
    expect(result?.size).toBe(48);
    expect(boundary.trackStop).toHaveBeenCalledTimes(1);
    expect(boundary.close).toHaveBeenCalledTimes(1);
  });

  it("cancels without publishing audio and still releases the microphone", async () => {
    const boundary = installRecorderBoundary();
    const recorder = await startPcmWavRecorder(10_000);
    recorder.cancel();

    await expect(recorder.finished).resolves.toBeNull();
    expect(boundary.trackStop).toHaveBeenCalledTimes(1);
    expect(boundary.close).toHaveBeenCalledTimes(1);
  });

  it("releases the granted microphone and partial audio graph when setup fails", async () => {
    const trackStop = vi.fn();
    const source = { connect: vi.fn(), disconnect: vi.fn() };
    const processor = { connect: vi.fn(), disconnect: vi.fn(), onaudioprocess: null };
    const gain = { connect: vi.fn(), disconnect: vi.fn(), gain: { value: 1 } };
    const close = vi.fn(async () => undefined);
    const context = {
      sampleRate: 32_000,
      state: "suspended",
      destination: {},
      createMediaStreamSource: vi.fn(() => source),
      createScriptProcessor: vi.fn(() => processor),
      createGain: vi.fn(() => gain),
      close,
      resume: vi.fn(async () => { throw new Error("synthetic resume failure"); }),
    };
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia: vi.fn(async () => ({ getTracks: () => [{ stop: trackStop }] })) },
    });
    Object.defineProperty(window, "AudioContext", {
      configurable: true,
      value: vi.fn(function SyntheticAudioContext() { return context; }),
    });

    await expect(startPcmWavRecorder(10_000)).rejects.toThrow("synthetic resume failure");
    expect(trackStop).toHaveBeenCalledOnce();
    expect(close).toHaveBeenCalledOnce();
    expect(source.disconnect).toHaveBeenCalledOnce();
    expect(processor.disconnect).toHaveBeenCalledOnce();
    expect(gain.disconnect).toHaveBeenCalledOnce();
  });
});
