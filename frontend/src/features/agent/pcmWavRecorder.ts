const OUTPUT_SAMPLE_RATE = 16_000;
const MAX_RECORDING_MS = 120_000;

export interface PcmWavRecorder {
  cancel(): void;
  finished: Promise<Blob | null>;
  stop(): void;
}

export function encodePcm16Wav(samples: Float32Array, sampleRate = OUTPUT_SAMPLE_RATE): Blob {
  const dataBytes = samples.length * 2;
  const buffer = new ArrayBuffer(44 + dataBytes);
  const view = new DataView(buffer);
  const text = (offset: number, value: string) => {
    for (let index = 0; index < value.length; index += 1) {
      view.setUint8(offset + index, value.charCodeAt(index));
    }
  };
  text(0, "RIFF");
  view.setUint32(4, 36 + dataBytes, true);
  text(8, "WAVE");
  text(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  text(36, "data");
  view.setUint32(40, dataBytes, true);
  for (let index = 0; index < samples.length; index += 1) {
    const bounded = Math.max(-1, Math.min(1, samples[index]));
    view.setInt16(44 + index * 2, bounded < 0 ? bounded * 0x8000 : bounded * 0x7fff, true);
  }
  return new Blob([buffer], { type: "audio/wav" });
}

export function resampleMono(
  samples: Float32Array,
  inputSampleRate: number,
  outputSampleRate = OUTPUT_SAMPLE_RATE,
): Float32Array {
  if (samples.length === 0 || inputSampleRate === outputSampleRate) return samples;
  const length = Math.max(1, Math.floor(samples.length * outputSampleRate / inputSampleRate));
  const output = new Float32Array(length);
  const scale = inputSampleRate / outputSampleRate;
  for (let index = 0; index < length; index += 1) {
    const position = index * scale;
    const left = Math.min(samples.length - 1, Math.floor(position));
    const right = Math.min(samples.length - 1, left + 1);
    const fraction = position - left;
    output[index] = samples[left] * (1 - fraction) + samples[right] * fraction;
  }
  return output;
}

function combined(chunks: readonly Float32Array[], frames: number): Float32Array {
  const output = new Float32Array(frames);
  let offset = 0;
  for (const chunk of chunks) {
    output.set(chunk, offset);
    offset += chunk.length;
  }
  return output;
}

export async function startPcmWavRecorder(
  maxDurationMs = MAX_RECORDING_MS,
): Promise<PcmWavRecorder> {
  if (
    typeof navigator === "undefined"
    || navigator.mediaDevices?.getUserMedia === undefined
    || typeof window === "undefined"
  ) throw new Error("microphone_unavailable");
  const AudioContextConstructor = window.AudioContext;
  if (AudioContextConstructor === undefined) throw new Error("microphone_unavailable");
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: false, noiseSuppression: false },
    video: false,
  });
  let context: AudioContext | null = null;
  let source: MediaStreamAudioSourceNode | null = null;
  let processor: ScriptProcessorNode | null = null;
  let silent: GainNode | null = null;
  let limitTimer: number | undefined;
  try {
    context = new AudioContextConstructor();
    source = context.createMediaStreamSource(stream);
    processor = context.createScriptProcessor(4096, 1, 1);
    silent = context.createGain();
    silent.gain.value = 0;
    const activeContext = context;
    const activeSource = source;
    const activeProcessor = processor;
    const activeSilent = silent;
    const chunks: Float32Array[] = [];
    const maxFrames = Math.max(1, Math.floor(activeContext.sampleRate * maxDurationMs / 1_000));
    let frames = 0;
    let settled = false;
    let resolveFinished: (blob: Blob | null) => void = () => undefined;
    const finished = new Promise<Blob | null>((resolve) => { resolveFinished = resolve; });

    const cleanup = () => {
      activeProcessor.onaudioprocess = null;
      try { activeProcessor.disconnect(); } catch { /* already disconnected */ }
      try { activeSource.disconnect(); } catch { /* already disconnected */ }
      try { activeSilent.disconnect(); } catch { /* already disconnected */ }
      for (const track of stream.getTracks()) {
        try { track.stop(); } catch { /* keep releasing the remaining tracks */ }
      }
      try { void activeContext.close().catch(() => undefined); } catch { /* already unavailable */ }
    };

    const settle = (cancelled: boolean) => {
      if (settled) return;
      settled = true;
      if (limitTimer !== undefined) window.clearTimeout(limitTimer);
      cleanup();
      if (cancelled || frames === 0) {
        resolveFinished(null);
        return;
      }
      const captured = combined(chunks, frames);
      resolveFinished(encodePcm16Wav(resampleMono(captured, activeContext.sampleRate)));
    };

    activeProcessor.onaudioprocess = (event) => {
      if (settled) return;
      const sourceSamples = event.inputBuffer.getChannelData(0);
      const remaining = maxFrames - frames;
      const take = Math.min(sourceSamples.length, remaining);
      if (take > 0) {
        chunks.push(sourceSamples.slice(0, take));
        frames += take;
      }
      if (frames >= maxFrames) settle(false);
    };
    if (activeContext.state === "suspended") await activeContext.resume();
    limitTimer = window.setTimeout(() => settle(false), maxDurationMs);
    activeSource.connect(activeProcessor);
    activeProcessor.connect(activeSilent);
    activeSilent.connect(activeContext.destination);
    return {
      cancel: () => settle(true),
      finished,
      stop: () => settle(false),
    };
  } catch (caught) {
    if (limitTimer !== undefined) window.clearTimeout(limitTimer);
    if (processor !== null) {
      processor.onaudioprocess = null;
      try { processor.disconnect(); } catch { /* setup did not complete */ }
    }
    if (source !== null) {
      try { source.disconnect(); } catch { /* setup did not complete */ }
    }
    if (silent !== null) {
      try { silent.disconnect(); } catch { /* setup did not complete */ }
    }
    for (const track of stream.getTracks()) {
      try { track.stop(); } catch { /* keep releasing the remaining tracks */ }
    }
    if (context !== null) {
      try { void context.close().catch(() => undefined); } catch { /* setup did not complete */ }
    }
    throw caught;
  }
}

export function microphoneCaptureAvailable(): boolean {
  return typeof navigator !== "undefined"
    && navigator.mediaDevices?.getUserMedia !== undefined
    && typeof window !== "undefined"
    && window.AudioContext !== undefined;
}
