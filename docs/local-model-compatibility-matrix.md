# Local model compatibility matrix

Generated from `local-model-compatibility.v1` using adapter
`llama.cpp-openai-gguf.v1`. Every row uses synthetic identity data;
this document contains no installed model, path, account, prompt, or transcript data.

| Contract scenario | State | Closed reason | Meaning / next step |
|---|---|---|---|
| Registered GGUF; no execution yet | `unknown` | `model_not_executed` | Activate and pass the exact live text probe. |
| llama.cpp binary unavailable | `unknown` | `runtime_unavailable` | Install or select a documented llama-server binary. |
| Exact artifact passed live text probe | `supported` | `live_text_probe_verified` | Usable for the capabilities separately verified by the live probe. |
| Exact artifact failed live text probe | `unsupported` | `live_text_probe_failed` | Do not advertise it as usable with this adapter/runtime. |
| Registered artifact is missing | `unsupported` | `artifact_missing` | Restore the exact artifact or remove the stale registry row. |

## Admission rules

- Catalog discovery and GGUF metadata are identity evidence, not executable compatibility.
- `supported` requires a successful live text request for the exact currently served alias.
- Architecture, tokenizer, training context, runtime version, model digest, runtime-binary digest, licence, and source revision remain `unknown` when unavailable; names never fill them in.
- Vision, audio, tools, structured output, and recording are admitted separately by live capability probes.
- Exact context admission uses llama.cpp's chat-template-aware [`POST /v1/chat/completions/input_tokens`](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md). If that interface is absent or malformed, input use remains unknown; the app does not substitute a character estimate or another tokenizer.
- On a measured overflow, Agent removes only whole older conversation units and recounts. System instructions, tool definitions, and the current request are protected; if those cannot fit, inference is refused.

The runtime adapter follows the official [llama.cpp server interface](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md). Additional formats or runtime families must receive a new versioned adapter and contract row before they can be advertised.
