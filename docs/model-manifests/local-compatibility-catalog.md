# Local model resource-fit catalog

The local catalog is an advisory, content-free view over existing reviewed
manifests. It does not discover models from the Hub, resolve moving tags,
inspect model-cache contents, download artifacts, read login state or tokens,
run inference, choose a model, or activate a model for product metrics.

## Hardware inventory boundary

Discovery exposes only coarse aggregate classes:

- normalized CPU architecture, logical-core range, and system-RAM range;
- CUDA availability, reviewed memory class, and compute-capability family when
  an isolated child can report them consistently;
- a free-space range for the configured isolated model-cache volume, without
  creating or listing cache files.

User names, host names, device names, serial numbers, paths, account data, and
provider/session content are never returned. Missing observations remain
`null` with closed reason codes; an unavailable PyTorch observation is not
reported as proof that CUDA is absent. The response labels the inventory
`sensitive_derived`, `local_only=true`, `persisted=false`, and `synced=false`.

Torch and CUDA are never imported by the API parent for discovery. A minimal
isolated Python child receives no input and emits only a fixed schema of CUDA
state plus numeric memory and capability facts. The parent uses an isolated
process group, discards stderr, reads no more than 2,049 stdout bytes, enforces
one ten-second deadline while reading, and positively reaps the process tree
on timeout or overflow. Extra, malformed, oversized, nonzero, or timed-out
results become the fixed `cuda_inventory_unknown` code. Accepted numeric facts
are converted to classes before a response is built.

Only the bucketed inventory is held in a process-local, monotonic 30-second TTL
cache. A lock and single-flight refresh let the runtime and compatibility reads
share one child observation inside that window. The cache is never written to
disk or synchronized; an internal explicit refresh or TTL expiry starts a new
bounded probe.

## Frozen resource-fit policy

The catalog joins immutable safetensors manifests to aggregate resource
observations already reviewed in this directory. New Hub results, branch heads,
popularity, and unreviewed local files cannot enter it.

Compatibility targets nominal 16 GiB system RAM and 8 GiB CUDA hardware while
using reviewed class floors of 15,360 MiB RAM and 7,680 MiB CUDA. These floors
tolerate bounded firmware and driver reservations; they are class membership,
not claims of exact installed capacity. The exported `MIN_SYSTEM_RAM_MIB` and
`MIN_CUDA_VRAM_MIB` constants drive both bucketing and sufficiency checks.
One-model-at-a-time execution remains fixed. Every runtime configuration must
remain under both the 6,144 MiB peak GPU-allocation ceiling and the 8,192 MiB
child-RSS ceiling. A 16 GiB-class GPU therefore does not make the observed
7,769.893 MiB unquantized rubric allocation eligible.

Failure precedence is host-first: unknown or insufficient RAM, then unknown or
unavailable CUDA and insufficient CUDA class, then configuration GPU/RSS
ceilings, and only then measurement completeness. Consequently, an oversized
configuration cannot hide that CUDA discovery for the host is unknown or that
CUDA is unavailable.

Each runtime configuration has exactly one status:

- `research_only`: the configuration has only exploratory evidence, or lacks a
  complete GPU-allocation plus child-RSS measurement;
- `unavailable`: inventory is insufficient or unknown, a hard resource bound is
  exceeded, or the reviewed artifact is unsafe.

Tiny synthetic screens never promote or choose a model. Every response retains
`product_enabled=false`, `activation_allowed=false`, `download_allowed=false`,
and `trust_remote_code=false`.

Resource provenance is configuration-specific and includes quantization, dtype,
runtime, measurement method, precision, and source.
`torch.cuda.max_memory_allocated` is reported only as peak GPU allocation; it is
not total device VRAM. The older unquantized Qwen screen and the disposable NF4
configuration are separate records. The NF4 record preserves the documented
approximately 3.84 GiB GPU peak from
`real_metrics_campaign_diagnostic_2026_08_17` as an approximate, GPU-only
diagnostic; it is not relabeled as an exact Torch allocation. Child RSS remains
unknown, so the NF4 record is partial and remains
`resource_measurement_missing`.

The reviewed reports also lack complete child-RSS and artifact-size
measurements. Free cache-volume space is therefore inventory only and is not
used to invent a disk compatibility claim.

The authenticated loopback API exposes the projection at
`GET /v1/research/text-model-compatibility`. It is read-only and returned with
private, no-store caching headers. The Research Lab Models view validates the
entire response before showing grouped, human-readable configuration rows; it
does not expose an action control for the compatibility catalog.
