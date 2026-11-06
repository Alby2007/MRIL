"""Agent drivers — how a model call becomes workspace changes.

The driver contract is deliberately narrow: given a model_id, instruction,
workspace view and prior verifier feedback, produce changes and report usage.
The runner owns attempts, verification and routing; the driver owns prompting
and file materialization. A LangChain driver can slot in later without the
runner or arms changing.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
import zlib
from dataclasses import dataclass, field
from typing import Protocol

from mril.eval.spec import TaskSpec
from mril.eval.workspace import Workspace


@dataclass(frozen=True)
class DriverResult:
    text: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None  # None => provider didn't report
    latency_ms: float | None = None
    api_error: str | None = None
    provider_request_id: str | None = None
    files_written: tuple[str, ...] = field(default_factory=tuple)


class AgentDriver(Protocol):
    def generate(
        self,
        *,
        model_id: str,
        spec: TaskSpec,
        workspace: Workspace,
        attempt_index: int,
        prior_feedback: str | None,
        seed: int | None = None,
    ) -> DriverResult: ...


_FENCE = re.compile(r"```(?:\w+)?\s*(.*?)```", re.DOTALL)


def _extract_code(text: str) -> str | None:
    m = _FENCE.search(text)
    if m:
        return m.group(1).strip()
    return text.strip() if text.strip() else None


class OllamaDriver:
    """Single-shot generation against a local Ollama server, stdlib only.

    `models` maps registry model_id -> ollama tag. Ollama reports prompt and
    completion counts but no cache-read usage, so switch costs on this driver
    are always ledger-labelled `estimated` — and token counts are usage, not
    an invoice. Cost figures are normalized API-equivalent prices, never
    money billed.
    """

    def __init__(
        self,
        models: dict[str, str],
        host: str = "http://127.0.0.1:11434",
        timeout: int = 300,
        num_predict: int = 2048,
        temperature: float = 0.2,
        top_p: float = 0.9,
        num_ctx: int = 8192,
    ) -> None:
        self.models = models
        self.host = host.rstrip("/")
        self.timeout = timeout
        # Pinned sampling parameters — every run in a matrix must generate
        # under identical options or arm comparisons mix two experimental
        # configurations. Recorded in the manifest via `generation_options`.
        self.options = {
            "num_predict": num_predict,
            "temperature": temperature,
            "top_p": top_p,
            "num_ctx": num_ctx,
        }

    @staticmethod
    def gen_seed(run_seed: int, task_id: str, model_tag: str, attempt_index: int) -> int:
        """Deterministic generation seed per (run, task, model, attempt).

        Same task+model+attempt under the same run_seed draws the same
        sampling seed across arms — paired comparisons aren't confounded by
        different random draws, while different seeds still probe generation
        reliability. temperature>0 is what makes seed meaningful.
        """
        return zlib.crc32(f"{run_seed}:{task_id}:{model_tag}:{attempt_index}".encode())

    @property
    def generation_options(self) -> dict:
        return {**self.options, "seed_rule": "crc32(run_seed:task_id:model_tag:attempt_index)"}

    def generate(
        self,
        *,
        model_id: str,
        spec: TaskSpec,
        workspace: Workspace,
        attempt_index: int,
        prior_feedback: str | None,
        seed: int | None = None,
    ) -> DriverResult:
        tag = self.models.get(model_id, model_id)
        current = workspace.read(spec.target_file)
        prompt = (
            f"{spec.instruction}\n\n"
            f"Repository files:\n{workspace.tree()}\n\n"
            f"Current {spec.target_file}:\n{current or '<missing>'}\n\n"
            + (
                f"The previous attempt failed verification:\n{prior_feedback}\n\n"
                if prior_feedback
                else ""
            )
            + f"Reply with ONLY the complete new contents of {spec.target_file}."
        )
        options = dict(self.options)
        if seed is not None:
            options["seed"] = self.gen_seed(seed, spec.task_id, tag, attempt_index)
        body = json.dumps(
            {
                "model": tag,
                "prompt": prompt,
                "stream": False,
                "options": options,
            }
        ).encode()
        req = urllib.request.Request(
            f"{self.host}/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read())
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            return DriverResult(api_error=f"{type(exc).__name__}: {exc}")

        text = payload.get("response", "")
        code = _extract_code(text)
        written: tuple[str, ...] = ()
        if code is not None:
            workspace.write(spec.target_file, code)
            written = (spec.target_file,)
        return DriverResult(
            text=text,
            input_tokens=payload.get("prompt_eval_count"),
            output_tokens=payload.get("eval_count"),
            cached_input_tokens=None,  # ollama doesn't report cache reads
            latency_ms=(payload.get("total_duration") or 0) / 1e6 or None,
            provider_request_id=None,
            files_written=written,
        )
