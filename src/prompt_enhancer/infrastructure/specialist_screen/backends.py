"""Standard-Transformers backend for reviewed MiniLMv2 NLI snapshots."""

from __future__ import annotations

from collections.abc import Sequence
import gc
from pathlib import Path
import os
import time
from typing import Any

from prompt_enhancer.infrastructure.text_models.loader import transformers_network_closed
from prompt_enhancer.infrastructure.text_models.manifests import ModelManifest, TextModelTask
from prompt_enhancer.infrastructure.text_models.transformers_backends import resolve_device

from .contracts import SPECIALIST_LABEL_ORDER, SpecialistCase, SpecialistLabel
from .loader import require_registered_specialist_manifest


class SpecialistBackendError(RuntimeError):
    """A fixed-code backend failure; callers must not expose exception details."""


def _process_rss_mb() -> float | None:
    try:
        import psutil

        return round(psutil.Process().memory_info().rss / (1024 * 1024), 3)
    except (ImportError, OSError):
        return None


class MiniLmV2NliBackend:
    """One-model-at-a-time, offline NLI probability backend."""

    def __init__(
        self,
        manifest: ModelManifest,
        snapshot: Path,
        *,
        device: str = "auto",
        batch_size: int = 8,
    ) -> None:
        require_registered_specialist_manifest(manifest)
        if (
            manifest.task is not TextModelTask.SCOPED_NLI
            or manifest.architecture != "sequence_classifier"
        ):
            raise SpecialistBackendError("wrong_specialist_manifest_task")
        if not 1 <= batch_size <= manifest.max_batch_size:
            raise SpecialistBackendError("specialist_batch_size_outside_manifest_bound")
        self.manifest = manifest
        self.device = resolve_device(device)
        self.batch_size = batch_size
        self._rss_before_mb = _process_rss_mb()
        self._load_latency_ms = 0.0
        self._inference_latency_ms = 0.0
        self._closed = False
        self._torch: Any | None = None
        self.tokenizer: Any | None = None
        self.model: Any | None = None
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

        try:
            import torch

            self._torch = torch
            torch.manual_seed(0)
            if self.device == "cuda":
                torch.cuda.manual_seed_all(0)
                torch.cuda.empty_cache()
                torch.cuda.reset_peak_memory_stats()

            from transformers import AutoModelForSequenceClassification, AutoTokenizer

            started = time.perf_counter()
            with transformers_network_closed():
                self.tokenizer = AutoTokenizer.from_pretrained(
                    str(snapshot),
                    local_files_only=True,
                    trust_remote_code=False,
                )
                self.model = AutoModelForSequenceClassification.from_pretrained(
                    str(snapshot),
                    local_files_only=True,
                    trust_remote_code=False,
                    use_safetensors=True,
                )
            self.model.to(self.device)
            self.model.eval()
            self._load_latency_ms = (time.perf_counter() - started) * 1000
            self._validate_label_order()
        except SpecialistBackendError:
            self.close()
            raise
        except Exception:
            self.close()
            raise SpecialistBackendError("specialist_backend_load_failed") from None

    def _validate_label_order(self) -> None:
        if self.model is None:
            raise SpecialistBackendError("specialist_model_not_loaded")
        configured = {
            int(index): str(label).strip().casefold()
            for index, label in getattr(self.model.config, "id2label", {}).items()
        }
        expected = dict(self.manifest.output_label_by_index)
        semantic_values = {label.value for label in SPECIALIST_LABEL_ORDER}
        if configured and configured != expected:
            if set(configured.values()) == semantic_values:
                raise SpecialistBackendError("specialist_label_order_mismatch")
            if not all(label.startswith("label_") for label in configured.values()):
                raise SpecialistBackendError("specialist_labels_unrecognized")

    def predict_probabilities(
        self,
        cases: Sequence[SpecialistCase],
    ) -> tuple[tuple[tuple[SpecialistLabel, float], ...], ...]:
        if self._closed:
            raise SpecialistBackendError("specialist_backend_closed")
        if self.model is None or self.tokenizer is None:
            raise SpecialistBackendError("specialist_backend_not_loaded")
        if any(case.compatibility.value != "compatible" for case in cases):
            raise SpecialistBackendError("incompatible_case_reached_nli_backend")

        try:
            import torch

            rows: list[tuple[tuple[SpecialistLabel, float], ...]] = []
            started = time.perf_counter()
            with transformers_network_closed(), torch.inference_mode():
                for start in range(0, len(cases), self.batch_size):
                    batch = cases[start : start + self.batch_size]
                    encoded = self.tokenizer(
                        [case.premise for case in batch],
                        [case.hypothesis for case in batch],
                        max_length=self.manifest.max_sequence_length,
                        truncation=True,
                        padding=True,
                        return_tensors="pt",
                    )
                    encoded = {
                        key: value.to(self.device) for key, value in encoded.items()
                    }
                    probabilities = torch.softmax(
                        self.model(**encoded).logits,
                        dim=-1,
                    ).cpu()
                    for probability_row in probabilities.tolist():
                        if len(probability_row) != len(SPECIALIST_LABEL_ORDER):
                            raise SpecialistBackendError(
                                "specialist_probability_width_mismatch"
                            )
                        rows.append(
                            tuple(
                                (label, float(value))
                                for label, value in zip(
                                    SPECIALIST_LABEL_ORDER,
                                    probability_row,
                                    strict=True,
                                )
                            )
                        )
            self._inference_latency_ms += (time.perf_counter() - started) * 1000
            return tuple(rows)
        except SpecialistBackendError:
            raise
        except Exception:
            raise SpecialistBackendError("specialist_backend_inference_failed") from None

    def runtime_observation(self) -> dict[str, object]:
        import torch
        import transformers

        rss_after = _process_rss_mb()
        rss_delta = None
        if rss_after is not None and self._rss_before_mb is not None:
            rss_delta = round(max(0.0, rss_after - self._rss_before_mb), 3)
        return {
            "device": self.device,
            "accelerator_name": (
                torch.cuda.get_device_name(torch.cuda.current_device())
                if self.device == "cuda"
                else None
            ),
            "torch_build": str(torch.__version__),
            "transformers_version": str(transformers.__version__),
            "cuda_runtime_version": (
                str(torch.version.cuda) if self.device == "cuda" else None
            ),
            "batch_size": self.batch_size,
            "load_latency_ms": round(self._load_latency_ms, 3),
            "inference_latency_ms": round(self._inference_latency_ms, 3),
            "process_rss_after_load_and_inference_mb": rss_after,
            "process_rss_increase_mb": rss_delta,
            "peak_cuda_allocated_mb": (
                round(torch.cuda.max_memory_allocated() / (1024 * 1024), 3)
                if self.device == "cuda"
                else None
            ),
        }

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        model = self.model
        tokenizer = self.tokenizer
        torch_module = self._torch
        self.model = None
        self.tokenizer = None
        self._torch = None

        # A partially moved model can already own accelerator storage even
        # when ``__init__`` later fails.  Move it back when possible before
        # dropping the final backend-held reference.  Cleanup is best-effort:
        # one broken resource must not prevent the other resource or device
        # cache from being released.
        if model is not None and self.device in {"cuda", "mps"}:
            try:
                model.to("cpu")
            except Exception:
                pass
        for resource in (model, tokenizer):
            closer = getattr(resource, "close", None)
            if callable(closer):
                try:
                    closer()
                except Exception:
                    pass
        del model
        del tokenizer
        gc.collect()

        if torch_module is None:
            return
        try:
            if self.device == "cuda":
                torch_module.cuda.empty_cache()
            elif self.device == "mps" and hasattr(torch_module, "mps"):
                torch_module.mps.empty_cache()
        except Exception:
            pass

    def __enter__(self) -> "MiniLmV2NliBackend":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()
