"""Real provider adapters.

Every adapter here talks to a real vendor endpoint over HTTP — but **none of
this has been exercised against a live API from this environment**: there is
no network path to any vendor's docs and no real API key configured. Treat
every endpoint path, request shape and response field name below as "written
against the vendor's documented shape to the best of available knowledge, not
verified live" — each is called out with a comment where the shape is
genuinely uncertain, and every model id / base URL is overridable through
settings (`app/core/config.py`) precisely so an operator can correct it
without a code change once they've confirmed it against current vendor docs.

Degradation contract (unchanged from the previous placeholder version):
`available()` is true only when the adapter's key is present AND
`FORCE_MOCK_PROVIDERS` is false. Every public method returns an `ok=False`
`ProviderResult` instead of raising — the registry always has a working mock
to fall back to, so a vendor being down, misconfigured, or simply not yet
enabled must never surface as a stack trace.

Adding a provider:
    1. add its ModelSpec(s) to app/providers/catalog.py
    2. implement (or extend) its adapter class below
    3. list it in app/providers/registry.py's _REGISTRY
    4. set its API key (and, once confirmed, its model id / base URL) in .env
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import mimetypes
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.core.config import settings
from app.providers import catalog, http, pricing, schemas
from app.providers.base import (
    ImageProvider,
    LLMProvider,
    MusicProvider,
    ProviderCapability,
    ProviderResult,
    VideoProvider,
    VoiceProvider,
)

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Endpoint paths — every one of these is a best-effort guess at each
# vendor's current documented shape and MUST be confirmed before real
# traffic is sent. Kept as module constants (rather than inline strings) so
# correcting one is a one-line change, and paired with a settings-backed
# base URL so the host itself is also operator-overridable.
# --------------------------------------------------------------------------
OPENAI_CHAT_COMPLETIONS_PATH = "/chat/completions"
OPENAI_IMAGES_GENERATIONS_PATH = "/images/generations"
GEMINI_GENERATE_CONTENT_PATH = "/models/{model}:generateContent"
ANTHROPIC_MESSAGES_PATH = "/messages"
#: Anthropic pins behaviour to a dated API version rather than a URL version.
ANTHROPIC_VERSION = "2023-06-01"
ELEVENLABS_TTS_PATH = "/text-to-speech/{voice_id}"
ELEVENLABS_VOICES_PATH = "/voices"
# Veo (via the Gemini API's long-running-operation pattern): operation name
# and result field names below are unverified from this environment.
VEO_PREDICT_LONG_RUNNING_PATH = "/models/{model}:predictLongRunning"
# Runway ML: path, task-status shape and "ratio" enum values are unverified.
RUNWAY_IMAGE_TO_VIDEO_PATH = "/image_to_video"
RUNWAY_TASK_STATUS_PATH = "/tasks/{task_id}"
# Seedance: no confirmed public API reference was reachable from this
# environment. This follows the generic submit/poll/fetch shape most async
# video vendors use — host, paths and field names must be confirmed (and
# very possibly rewritten) against Seedance's actual current docs.
SEEDANCE_SUBMIT_PATH = "/video/generations"
SEEDANCE_STATUS_PATH = "/video/generations/{task_id}"
# Generic music provider: no vendor has been selected by the product yet.
# This is a working scaffold for whichever vendor gets picked, not a real
# integration — rewrite entirely once one is chosen.
MUSIC_GENERATE_PATH = "/generate"
MUSIC_STATUS_PATH = "/generate/{task_id}"


class ProviderJobFailed(Exception):
    """An async job (video/music) reported a failed or cancelled status."""


class ProviderJobTimeout(Exception):
    """An async job did not finish within PROVIDER_POLL_TIMEOUT_SEC."""


# --------------------------------------------------------------------------
# Shared adapter behaviour
# --------------------------------------------------------------------------
class RealAdapterMixin:
    """Shared behaviour for real (network-backed) adapters.

    `available()` mirrors the product rule from CLAUDE.md §6: a real adapter
    is only "live" when its key is present AND the operator has not forced
    mock mode. Every public method degrades to an `ok=False` ProviderResult
    on any failure — vendor HTTP errors, job failures, timeouts — instead of
    raising, so `registry.py` never needs to catch anything from here.
    """

    name: str = "unwired"
    key_setting: str = ""

    def available(self) -> bool:
        return bool(getattr(settings, self.key_setting, None)) and not settings.FORCE_MOCK_PROVIDERS

    def _api_key(self) -> Optional[str]:
        return getattr(settings, self.key_setting, None)

    def _unavailable(self, operation: str) -> ProviderResult:
        return ProviderResult(
            ok=False,
            provider=self.name,
            model="unconfigured",
            operation=operation,
            is_mock=False,
            error=(
                f"Provider '{self.name}' is not configured. Set {self.key_setting} in .env and set "
                "FORCE_MOCK_PROVIDERS=false to enable it."
            ),
        )

    def _error_result(self, operation: str, model: str, error: str) -> ProviderResult:
        catalog.record_failure(self.name, error)
        return ProviderResult(
            ok=False, provider=self.name, model=model, operation=operation, is_mock=False, error=http.redact(str(error))
        )

    def _run_async_media_job(
        self,
        *,
        operation: str,
        model_id: str,
        cost_units: float,
        submit: Callable[[], Dict[str, Any]],
        poll: Callable[[str], Dict[str, Any]],
        job_id_of: Callable[[Dict[str, Any]], str],
        status_of: Callable[[Dict[str, Any]], str],
        done_statuses: Tuple[str, ...],
        failed_statuses: Tuple[str, ...],
        result_url_of: Callable[[Dict[str, Any]], Optional[str]],
        key_prefix: str,
        suffix: str = ".mp4",
        extra_data: Optional[Dict[str, Any]] = None,
    ) -> ProviderResult:
        """Submit -> poll -> fetch, shared by every async (video/music) adapter."""
        started = time.time()
        try:
            submitted = submit()
            job_id = job_id_of(submitted)
            final = _poll_until_done(
                poll_once=lambda: poll(job_id), status_of=status_of,
                done_statuses=done_statuses, failed_statuses=failed_statuses,
            )
            output_url = result_url_of(final)
            if not output_url:
                raise ProviderJobFailed(f"{self.name} job completed but returned no output URL")
            stored_url = _persist_remote_media(output_url, suffix=suffix, key_prefix=key_prefix)
        except (http.ProviderHttpError, ProviderJobFailed, ProviderJobTimeout) as exc:
            return self._error_result(operation, model_id, str(exc))

        cost = pricing.price_for_model(model_id, units=cost_units)
        latency_ms = int((time.time() - started) * 1000)
        catalog.record_success(self.name)
        data: Dict[str, Any] = {"job_id": job_id}
        if extra_data:
            data.update(extra_data)
        return ProviderResult(
            ok=True, provider=self.name, model=model_id, operation=operation, is_mock=False,
            cost_usd=cost, latency_ms=latency_ms, url=stored_url, data=data,
        )


def _build_capability(provider_id: str, kind: str, key_setting: str) -> ProviderCapability:
    """Derive a `ProviderCapability` from the catalog instead of hand-listing models."""
    specs = catalog.candidates(kind, provider_id=provider_id, include_disabled=True)
    models = [catalog.configured_model_id(s) for s in specs]
    durations = [s.supported_durations[1] for s in specs if s.supported_durations]
    notes = "; ".join(dict.fromkeys(s.notes_en for s in specs if s.notes_en))
    return ProviderCapability(
        name=provider_id,
        kind=kind,
        models=models,
        requires_key=key_setting,
        supports_reference_image=any(s.supports_reference_image for s in specs),
        supports_image_to_video=any(s.supports_image_to_video for s in specs),
        max_duration_sec=max(durations) if durations else 8.0,
        notes=notes,
    )


def _select_spec(provider_id: str, kind: str, requested_model: Optional[str]) -> catalog.ModelSpec:
    """Resolve the ModelSpec to use: an explicit model id, else the top catalog candidate."""
    if requested_model:
        found = catalog.spec(provider_id, requested_model)
        if found is not None:
            return found
    ranked = catalog.candidates(kind, provider_id=provider_id)
    if ranked:
        return ranked[0]
    # An operator asked for a model the catalog doesn't know about yet. Don't
    # fail the call over a missing catalog entry — degrade to a conservative
    # flat price so cost accounting still works, and let it through.
    return catalog.ModelSpec(
        provider_id=provider_id, model_id=requested_model or "unknown", kind=kind,
        display_name=requested_model or "unknown", cost_unit="per_request", cost_per_unit=0.05,
    )


def _cost_for_llm(model_id: str, usage: Optional[Dict[str, Any]]) -> float:
    """Best-effort USD estimate for one structured LLM call.

    Real current per-token vendor pricing cannot be verified from this
    environment, so the catalog stores a flat, rough per-call price (this
    product's historical cost model — see pricing.MODEL_PRICING). This only
    nudges that estimate using actual reported token usage, when the vendor
    supplies it, so an unusually large call is not silently under-priced —
    it is not a claim of exact vendor pricing.
    """
    base = pricing.price_for_model(model_id, units=1.0)
    if usage:
        total_tokens = usage.get("total_tokens") or (
            (usage.get("prompt_tokens") or 0) + (usage.get("completion_tokens") or 0)
        )
        if total_tokens:
            scale = max(0.5, min(total_tokens / 1500.0, 4.0))
            return round(base * scale, 4)
    return base


def _poll_until_done(
    *,
    poll_once: Callable[[], Dict[str, Any]],
    status_of: Callable[[Dict[str, Any]], str],
    done_statuses: Tuple[str, ...],
    failed_statuses: Tuple[str, ...],
) -> Dict[str, Any]:
    """Bounded poll loop for an async vendor job — always polls at least once."""
    timeout_s = settings.PROVIDER_POLL_TIMEOUT_SEC
    interval_s = settings.PROVIDER_POLL_INTERVAL_SEC
    deadline = time.monotonic() + timeout_s
    while True:
        latest = poll_once()
        status = status_of(latest)
        if status in done_statuses:
            return latest
        if status in failed_statuses:
            raise ProviderJobFailed(f"job failed with status '{status}'")
        if time.monotonic() >= deadline:
            raise ProviderJobTimeout(f"job did not finish within {timeout_s:.0f}s (last status: '{status}')")
        time.sleep(interval_s)


def _persist_remote_media(source_url: str, *, suffix: str, key_prefix: str) -> str:
    """Pull a vendor-delivered asset into our own storage.

    Vendor result URLs are frequently short-lived signed URLs — the product
    must own a durable copy, not link the vendor's URL directly.
    """
    from app.services.storage import get_storage  # lazy: avoid an import cycle with the services layer

    tmp_fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    os.close(tmp_fd)
    try:
        http.download_to_file(source_url, tmp_path)
        digest = hashlib.md5(source_url.encode()).hexdigest()[:16]
        return get_storage().put_file(f"{key_prefix}/{digest}{suffix}", tmp_path)
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def _reference_parts_from_urls(urls: Optional[List[str]], *, max_inputs: int) -> List[Dict[str, Any]]:
    """Fetch reference images and return them as Gemini `inline_data` parts."""
    parts: List[Dict[str, Any]] = []
    for url in (urls or [])[:max_inputs]:
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=Path(url).suffix or ".bin")
        os.close(tmp_fd)
        try:
            http.download_to_file(url, tmp_path)
            data = Path(tmp_path).read_bytes()
            mime, _ = mimetypes.guess_type(url)
            parts.append(
                {"inline_data": {"mime_type": mime or "application/octet-stream", "data": base64.b64encode(data).decode()}}
            )
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
    return parts


def _first_inline_image(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for candidate in raw.get("candidates", []) or []:
        for part in (candidate.get("content", {}) or {}).get("parts", []) or []:
            inline = part.get("inline_data") or part.get("inlineData")
            if inline and inline.get("data"):
                return inline
    return None


def _flatten_image_prompt(prompt: Dict[str, Any]) -> str:
    """Serialise a compiled scene prompt (`prompt_compiler.py`) to plain text.

    The compiled prompt never contains the raw voice-over script (CLAUDE.md
    §6's Prompt Compiler rule) — this only rearranges what's already there.
    """
    order = ["subject", "environment", "composition", "camera", "lighting", "movement", "style", "constraints", "negative"]
    parts: List[str] = []
    for key in order:
        value = prompt.get(key)
        if not value:
            continue
        text = ", ".join(str(v) for v in value) if isinstance(value, (list, tuple)) else str(value)
        parts.append(f"{key}: {text}")
    if not parts:
        parts = [str(v) for v in prompt.values() if v]
    return " | ".join(parts)[:4000]


def _size_for_aspect_ratio(aspect_ratio: str) -> str:
    return {"9:16": "1024x1792", "16:9": "1792x1024", "1:1": "1024x1024"}.get(aspect_ratio, "1024x1792")


def _ratio_for_aspect(aspect_ratio: str) -> str:
    # NOTE: Runway's accepted "ratio" enum values are unverified from this
    # environment — confirm against current Runway ML API docs.
    return {"9:16": "768:1280", "16:9": "1280:768", "1:1": "960:960"}.get(aspect_ratio, "768:1280")


def _llm_system_prompt(task: str) -> str:
    schema = schemas.json_schema_for(task)
    return (
        "You are AdFlow AI's creative engine, producing Iraqi-Arabic-first real-estate "
        f"advertising content for the structured task '{task}'. Respond with ONLY a single JSON "
        "object — no prose, no markdown fences — matching this JSON Schema exactly: "
        f"{json.dumps(schema, ensure_ascii=False)}"
    )


def _first_json_object(text: str) -> str:
    """Recover the JSON object from a reply that may be wrapped.

    Some APIs have a response-format switch; some do not. Where they do not,
    a model that was asked for bare JSON still occasionally returns it inside
    a ```json fence or after a sentence. Slicing to the outermost braces costs
    nothing when the reply is already clean and saves the repair round-trip
    when it is not. Returns the input unchanged when there is no object in it,
    so the caller still sees a real parse error rather than a silent empty.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("```")[1] if "```" in stripped[3:] else stripped[3:]
        if stripped.lstrip().lower().startswith("json"):
            stripped = stripped.lstrip()[4:]
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        return text
    return stripped[start : end + 1]


def _complete_json_with_repair(
    *,
    task: str,
    make_request: Callable[[Optional[str]], Dict[str, Any]],
    extract_text: Callable[[Dict[str, Any]], str],
) -> Tuple[bool, Dict[str, Any], Optional[Dict[str, Any]], List[str]]:
    """Ask for structured JSON, validate, and allow exactly ONE repair retry.

    `make_request(repair_instruction)` performs one vendor call — `None` on
    the first attempt, `schemas.repair_prompt(...)` text on the second — and
    this never calls it a third time, matching CLAUDE.md's "never infinite
    retry" rule for structured-output specifically.
    """
    errors: List[str] = []
    raw: Optional[Dict[str, Any]] = None
    for attempt in range(2):
        instruction = schemas.repair_prompt(task, errors) if attempt == 1 else None
        raw = make_request(instruction)
        text = extract_text(raw)
        try:
            candidate = json.loads(text)
        except (TypeError, ValueError) as exc:
            errors = [f"response was not valid JSON: {exc}"]
            continue
        ok, instance, validation_errors = schemas.validate_llm_json(task, candidate)
        if ok:
            payload = instance.model_dump(mode="json") if instance is not None else candidate
            return True, payload, raw, []
        errors = validation_errors
    return False, {}, raw, errors


# --------------------------------------------------------------------------
# LLM
# --------------------------------------------------------------------------
class OpenAILLMAdapter(RealAdapterMixin, LLMProvider):
    name = "openai"
    key_setting = "OPENAI_API_KEY"

    def capability(self) -> ProviderCapability:
        return _build_capability(self.name, "llm", self.key_setting)

    def complete_json(self, *, task: str, context: Dict[str, Any], model: Optional[str] = None) -> ProviderResult:
        if not self.available():
            return self._unavailable(task)
        spec = _select_spec(self.name, "llm", model)
        model_id = model or catalog.configured_model_id(spec)
        url = f"{settings.OPENAI_BASE_URL}{OPENAI_CHAT_COMPLETIONS_PATH}"
        headers = {"Authorization": f"Bearer {self._api_key()}", "Content-Type": "application/json"}
        started = time.time()

        def make_request(repair_instruction: Optional[str]) -> Dict[str, Any]:
            messages = [
                {"role": "system", "content": _llm_system_prompt(task)},
                {"role": "user", "content": json.dumps(context, ensure_ascii=False, default=str)},
            ]
            if repair_instruction:
                messages.append({"role": "user", "content": repair_instruction})
            body = {"model": model_id, "messages": messages, "response_format": {"type": "json_object"}}
            return http.post_json(url, headers=headers, json=body)

        def extract_text(raw: Dict[str, Any]) -> str:
            return raw["choices"][0]["message"]["content"]

        try:
            ok, payload, raw, errors = _complete_json_with_repair(
                task=task, make_request=make_request, extract_text=extract_text
            )
        except http.ProviderHttpError as exc:
            return self._error_result(task, model_id, str(exc))

        latency_ms = int((time.time() - started) * 1000)
        if not ok:
            error = f"model returned invalid structured output after one repair attempt: {'; '.join(errors) or 'unknown error'}"
            return self._error_result(task, model_id, error)

        usage = (raw or {}).get("usage") or {}
        catalog.record_success(self.name)
        return ProviderResult(
            ok=True, provider=self.name, model=model_id, operation=task, is_mock=False,
            cost_usd=_cost_for_llm(model_id, usage), latency_ms=latency_ms, data=payload,
        )


class GeminiLLMAdapter(RealAdapterMixin, LLMProvider):
    name = "gemini"
    key_setting = "GEMINI_API_KEY"

    def capability(self) -> ProviderCapability:
        return _build_capability(self.name, "llm", self.key_setting)

    def complete_json(self, *, task: str, context: Dict[str, Any], model: Optional[str] = None) -> ProviderResult:
        if not self.available():
            return self._unavailable(task)
        spec = _select_spec(self.name, "llm", model)
        model_id = model or catalog.configured_model_id(spec)
        url = f"{settings.GEMINI_BASE_URL}{GEMINI_GENERATE_CONTENT_PATH.format(model=model_id)}"
        params = {"key": self._api_key()}
        started = time.time()

        def make_request(repair_instruction: Optional[str]) -> Dict[str, Any]:
            text = _llm_system_prompt(task) + "\n\nINPUT:\n" + json.dumps(context, ensure_ascii=False, default=str)
            if repair_instruction:
                text += "\n\n" + repair_instruction
            body = {
                "contents": [{"role": "user", "parts": [{"text": text}]}],
                "generationConfig": {"responseMimeType": "application/json"},
            }
            return http.post_json(url, params=params, json=body)

        def extract_text(raw: Dict[str, Any]) -> str:
            return raw["candidates"][0]["content"]["parts"][0]["text"]

        try:
            ok, payload, raw, errors = _complete_json_with_repair(
                task=task, make_request=make_request, extract_text=extract_text
            )
        except http.ProviderHttpError as exc:
            return self._error_result(task, model_id, str(exc))

        latency_ms = int((time.time() - started) * 1000)
        if not ok:
            error = f"model returned invalid structured output after one repair attempt: {'; '.join(errors) or 'unknown error'}"
            return self._error_result(task, model_id, error)

        usage_raw = (raw or {}).get("usageMetadata") or {}
        usage = {
            "prompt_tokens": usage_raw.get("promptTokenCount"),
            "completion_tokens": usage_raw.get("candidatesTokenCount"),
            "total_tokens": usage_raw.get("totalTokenCount"),
        }
        catalog.record_success(self.name)
        return ProviderResult(
            ok=True, provider=self.name, model=model_id, operation=task, is_mock=False,
            cost_usd=_cost_for_llm(model_id, usage), latency_ms=latency_ms, data=payload,
        )


class AnthropicLLMAdapter(RealAdapterMixin, LLMProvider):
    """Claude, for concepts and Iraqi-dialect script writing.

    The catalog has listed claude-sonnet-5 and claude-opus-5 as selectable for
    some time, but no adapter implemented them: the router would choose
    ("anthropic", "claude-sonnet-5"), the registry would find nothing under
    that name, and every call fell back to the Mock — with a real key present
    and the settings screen reporting production. Scripts kept coming out of a
    template and nothing anywhere said so.
    """

    name = "anthropic"
    key_setting = "ANTHROPIC_API_KEY"

    def capability(self) -> ProviderCapability:
        return _build_capability(self.name, "llm", self.key_setting)

    def complete_json(self, *, task: str, context: Dict[str, Any], model: Optional[str] = None) -> ProviderResult:
        if not self.available():
            return self._unavailable(task)
        spec = _select_spec(self.name, "llm", model)
        model_id = model or catalog.configured_model_id(spec)
        url = f"{settings.ANTHROPIC_BASE_URL}{ANTHROPIC_MESSAGES_PATH}"
        headers = {
            "x-api-key": self._api_key() or "",
            "anthropic-version": ANTHROPIC_VERSION,
            "Content-Type": "application/json",
        }
        started = time.time()

        def make_request(repair_instruction: Optional[str]) -> Dict[str, Any]:
            user = "INPUT:\n" + json.dumps(context, ensure_ascii=False, default=str)
            if repair_instruction:
                user += "\n\n" + repair_instruction
            body = {
                "model": model_id,
                "max_tokens": 4096,
                "system": _llm_system_prompt(task),
                # No assistant prefill: claude-sonnet-5 rejects it outright
                # ("This model does not support assistant message prefill"),
                # so the conversation ends with the user turn and the JSON is
                # extracted from whatever wrapping the reply arrives in.
                "messages": [{"role": "user", "content": user}],
            }
            return http.post_json(url, headers=headers, json=body)

        def extract_text(raw: Dict[str, Any]) -> str:
            blocks = raw.get("content") or []
            text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
            return _first_json_object(text)

        try:
            ok, payload, raw, errors = _complete_json_with_repair(
                task=task, make_request=make_request, extract_text=extract_text
            )
        except http.ProviderHttpError as exc:
            return self._error_result(task, model_id, str(exc))

        latency_ms = int((time.time() - started) * 1000)
        if not ok:
            error = (
                "model returned invalid structured output after one repair attempt: "
                f"{'; '.join(errors) or 'unknown error'}"
            )
            return self._error_result(task, model_id, error)

        usage_raw = (raw or {}).get("usage") or {}
        usage = {
            "prompt_tokens": usage_raw.get("input_tokens"),
            "completion_tokens": usage_raw.get("output_tokens"),
            "total_tokens": (usage_raw.get("input_tokens") or 0) + (usage_raw.get("output_tokens") or 0),
        }
        catalog.record_success(self.name)
        return ProviderResult(
            ok=True, provider=self.name, model=model_id, operation=task, is_mock=False,
            cost_usd=_cost_for_llm(model_id, usage), latency_ms=latency_ms, data=payload,
        )


# --------------------------------------------------------------------------
# Image
# --------------------------------------------------------------------------
class OpenAIImageAdapter(RealAdapterMixin, ImageProvider):
    name = "openai"
    key_setting = "OPENAI_API_KEY"

    def capability(self) -> ProviderCapability:
        return _build_capability(self.name, "image", self.key_setting)

    def generate_image(
        self, *, prompt: Dict[str, Any], model: Optional[str] = None,
        reference_urls: Optional[List[str]] = None, aspect_ratio: str = "9:16",
    ) -> ProviderResult:
        operation = "image_generation"
        if not self.available():
            return self._unavailable(operation)
        spec = _select_spec(self.name, "image", model)
        model_id = model or catalog.configured_model_id(spec)
        if reference_urls:
            # NOTE: this adapter only implements the text-to-image /images/generations
            # endpoint. Reference-image conditioning needs OpenAI's /images/edits
            # multipart endpoint, not implemented here — see catalog.py's notes_en
            # for this model. References are accepted but silently not applied.
            logger.info("openai image adapter: %d reference image(s) requested but not applied (unimplemented)", len(reference_urls))
        url = f"{settings.OPENAI_BASE_URL}{OPENAI_IMAGES_GENERATIONS_PATH}"
        headers = {"Authorization": f"Bearer {self._api_key()}", "Content-Type": "application/json"}
        body = {"model": model_id, "prompt": _flatten_image_prompt(prompt), "size": _size_for_aspect_ratio(aspect_ratio), "n": 1}
        started = time.time()
        try:
            raw = http.post_json(url, headers=headers, json=body)
            items = raw.get("data") or []
            if not items:
                raise http.ProviderHttpError(http.ErrorKind.UNKNOWN, "OpenAI image response had no 'data' entries")
            stored_url = _persist_image_item(items[0], key_prefix="providers/openai/images")
        except http.ProviderHttpError as exc:
            return self._error_result(operation, model_id, str(exc))

        cost = pricing.price_for_model(model_id, units=len(items) or 1)
        latency_ms = int((time.time() - started) * 1000)
        catalog.record_success(self.name)
        return ProviderResult(
            ok=True, provider=self.name, model=model_id, operation=operation, is_mock=False,
            cost_usd=cost, latency_ms=latency_ms, url=stored_url,
            data={"aspect_ratio": aspect_ratio, "references_used": []},
        )


def _persist_image_item(item: Dict[str, Any], *, key_prefix: str) -> str:
    from app.services.storage import get_storage  # lazy: avoid an import cycle with the services layer

    if item.get("url"):
        return _persist_remote_media(item["url"], suffix=".png", key_prefix=key_prefix)
    if item.get("b64_json"):
        data = base64.b64decode(item["b64_json"])
        digest = hashlib.md5(data).hexdigest()[:16]
        return get_storage().put_bytes(f"{key_prefix}/{digest}.png", data, content_type="image/png")
    raise http.ProviderHttpError(http.ErrorKind.UNKNOWN, "image response had neither 'url' nor 'b64_json'")


class GeminiImageAdapter(RealAdapterMixin, ImageProvider):
    name = "gemini"
    key_setting = "GEMINI_API_KEY"

    def capability(self) -> ProviderCapability:
        return _build_capability(self.name, "image", self.key_setting)

    def generate_image(
        self, *, prompt: Dict[str, Any], model: Optional[str] = None,
        reference_urls: Optional[List[str]] = None, aspect_ratio: str = "9:16",
    ) -> ProviderResult:
        operation = "image_generation"
        if not self.available():
            return self._unavailable(operation)
        spec = _select_spec(self.name, "image", model)
        model_id = model or catalog.configured_model_id(spec)
        url = f"{settings.GEMINI_BASE_URL}{GEMINI_GENERATE_CONTENT_PATH.format(model=model_id)}"
        params = {"key": self._api_key()}
        started = time.time()
        try:
            parts: List[Dict[str, Any]] = [{"text": _flatten_image_prompt(prompt)}]
            parts.extend(_reference_parts_from_urls(reference_urls, max_inputs=spec.max_inputs))
            # NOTE: "responseModalities": ["IMAGE"] is Gemini's documented image-output
            # signal at the time this was written; unverified against current docs.
            body = {"contents": [{"role": "user", "parts": parts}], "generationConfig": {"responseModalities": ["IMAGE"]}}
            raw = http.post_json(url, params=params, json=body)
            inline = _first_inline_image(raw)
            if inline is None:
                raise http.ProviderHttpError(http.ErrorKind.UNKNOWN, "Gemini image response had no inline image data")
            data = base64.b64decode(inline["data"])
            from app.services.storage import get_storage  # lazy: avoid an import cycle with the services layer

            digest = hashlib.md5(data).hexdigest()[:16]
            stored_url = get_storage().put_bytes(f"providers/gemini/images/{digest}.png", data, content_type="image/png")
        except http.ProviderHttpError as exc:
            return self._error_result(operation, model_id, str(exc))

        cost = pricing.price_for_model(model_id, units=1)
        latency_ms = int((time.time() - started) * 1000)
        catalog.record_success(self.name)
        return ProviderResult(
            ok=True, provider=self.name, model=model_id, operation=operation, is_mock=False,
            cost_usd=cost, latency_ms=latency_ms, url=stored_url,
            data={"aspect_ratio": aspect_ratio, "references_used": reference_urls or []},
        )


# --------------------------------------------------------------------------
# Video — async submit -> poll -> fetch, bounded by PROVIDER_POLL_TIMEOUT_SEC
# --------------------------------------------------------------------------
class VeoVideoAdapter(RealAdapterMixin, VideoProvider):
    name = "veo"
    key_setting = "VEO_API_KEY"

    def capability(self) -> ProviderCapability:
        return _build_capability(self.name, "video", self.key_setting)

    def generate_video(
        self, *, prompt: Dict[str, Any], model: Optional[str] = None, keyframe_url: Optional[str] = None,
        duration_sec: float = 4.0, aspect_ratio: str = "9:16",
    ) -> ProviderResult:
        operation = "video_generation"
        if not self.available():
            return self._unavailable(operation)
        spec = _select_spec(self.name, "video", model)
        model_id = model or catalog.configured_model_id(spec)
        params = {"key": self._api_key()}
        submit_url = f"{settings.VEO_BASE_URL}{VEO_PREDICT_LONG_RUNNING_PATH.format(model=model_id)}"

        def submit() -> Dict[str, Any]:
            instance: Dict[str, Any] = {"prompt": _flatten_image_prompt(prompt)}
            if keyframe_url:
                # NOTE: the field Veo expects for an image-to-video seed frame is
                # unverified from this environment.
                instance["image"] = {"uri": keyframe_url}
            body = {"instances": [instance], "parameters": {"aspectRatio": aspect_ratio, "durationSeconds": duration_sec}}
            return http.post_json(submit_url, params=params, json=body)

        def poll(operation_name: str) -> Dict[str, Any]:
            return http.get_json(f"{settings.VEO_BASE_URL}/{operation_name}", params=params)

        def job_id_of(resp: Dict[str, Any]) -> str:
            job_id = resp.get("name")
            if not job_id:
                raise http.ProviderHttpError(http.ErrorKind.UNKNOWN, "Veo submit response had no operation 'name'")
            return job_id

        def status_of(resp: Dict[str, Any]) -> str:
            if not resp.get("done"):
                return "RUNNING"
            return "FAILED" if resp.get("error") else "DONE"

        def result_url_of(resp: Dict[str, Any]) -> Optional[str]:
            # NOTE: exact field name for the delivered video URI is unverified.
            payload = resp.get("response") or {}
            return payload.get("videoUri") or (payload.get("video") or {}).get("uri")

        return self._run_async_media_job(
            operation=operation, model_id=model_id, cost_units=duration_sec,
            submit=submit, poll=poll, job_id_of=job_id_of, status_of=status_of,
            done_statuses=("DONE",), failed_statuses=("FAILED",), result_url_of=result_url_of,
            key_prefix="providers/veo/video", suffix=".mp4", extra_data={"duration_sec": duration_sec, "keyframe_url": keyframe_url},
        )


class RunwayVideoAdapter(RealAdapterMixin, VideoProvider):
    name = "runway"
    key_setting = "RUNWAY_API_KEY"

    def capability(self) -> ProviderCapability:
        return _build_capability(self.name, "video", self.key_setting)

    def generate_video(
        self, *, prompt: Dict[str, Any], model: Optional[str] = None, keyframe_url: Optional[str] = None,
        duration_sec: float = 4.0, aspect_ratio: str = "9:16",
    ) -> ProviderResult:
        operation = "video_generation"
        if not self.available():
            return self._unavailable(operation)
        spec = _select_spec(self.name, "video", model)
        model_id = model or catalog.configured_model_id(spec)
        headers = {"Authorization": f"Bearer {self._api_key()}", "Content-Type": "application/json"}
        submit_url = f"{settings.RUNWAY_BASE_URL}{RUNWAY_IMAGE_TO_VIDEO_PATH}"

        def submit() -> Dict[str, Any]:
            body = {
                "model": model_id, "promptText": _flatten_image_prompt(prompt), "promptImage": keyframe_url,
                "duration": duration_sec, "ratio": _ratio_for_aspect(aspect_ratio),
            }
            return http.post_json(submit_url, headers=headers, json=body)

        def poll(task_id: str) -> Dict[str, Any]:
            url = f"{settings.RUNWAY_BASE_URL}{RUNWAY_TASK_STATUS_PATH.format(task_id=task_id)}"
            return http.get_json(url, headers=headers)

        def job_id_of(resp: Dict[str, Any]) -> str:
            job_id = resp.get("id")
            if not job_id:
                raise http.ProviderHttpError(http.ErrorKind.UNKNOWN, "Runway submit response had no 'id'")
            return job_id

        def status_of(resp: Dict[str, Any]) -> str:
            return str(resp.get("status", "UNKNOWN")).upper()

        def result_url_of(resp: Dict[str, Any]) -> Optional[str]:
            output = resp.get("output") or []
            return output[0] if output else None

        return self._run_async_media_job(
            operation=operation, model_id=model_id, cost_units=duration_sec,
            submit=submit, poll=poll, job_id_of=job_id_of, status_of=status_of,
            done_statuses=("SUCCEEDED",), failed_statuses=("FAILED", "CANCELLED"), result_url_of=result_url_of,
            key_prefix="providers/runway/video", suffix=".mp4", extra_data={"duration_sec": duration_sec, "keyframe_url": keyframe_url},
        )


class SeedanceVideoAdapter(RealAdapterMixin, VideoProvider):
    name = "seedance"
    key_setting = "SEEDANCE_API_KEY"

    def capability(self) -> ProviderCapability:
        return _build_capability(self.name, "video", self.key_setting)

    def generate_video(
        self, *, prompt: Dict[str, Any], model: Optional[str] = None, keyframe_url: Optional[str] = None,
        duration_sec: float = 4.0, aspect_ratio: str = "9:16",
    ) -> ProviderResult:
        operation = "video_generation"
        if not self.available():
            return self._unavailable(operation)
        spec = _select_spec(self.name, "video", model)
        model_id = model or catalog.configured_model_id(spec)
        headers = {"Authorization": f"Bearer {self._api_key()}", "Content-Type": "application/json"}
        submit_url = f"{settings.SEEDANCE_BASE_URL}{SEEDANCE_SUBMIT_PATH}"

        def submit() -> Dict[str, Any]:
            body = {
                "model": model_id, "prompt": _flatten_image_prompt(prompt), "image_url": keyframe_url,
                "duration": duration_sec, "aspect_ratio": aspect_ratio,
            }
            return http.post_json(submit_url, headers=headers, json=body)

        def poll(task_id: str) -> Dict[str, Any]:
            url = f"{settings.SEEDANCE_BASE_URL}{SEEDANCE_STATUS_PATH.format(task_id=task_id)}"
            return http.get_json(url, headers=headers)

        def job_id_of(resp: Dict[str, Any]) -> str:
            job_id = resp.get("id") or resp.get("task_id")
            if not job_id:
                raise http.ProviderHttpError(http.ErrorKind.UNKNOWN, "Seedance submit response had no task id")
            return job_id

        def status_of(resp: Dict[str, Any]) -> str:
            return str(resp.get("status", "unknown")).lower()

        def result_url_of(resp: Dict[str, Any]) -> Optional[str]:
            return resp.get("video_url") or resp.get("output_url")

        return self._run_async_media_job(
            operation=operation, model_id=model_id, cost_units=duration_sec,
            submit=submit, poll=poll, job_id_of=job_id_of, status_of=status_of,
            done_statuses=("succeeded", "completed", "done"), failed_statuses=("failed", "error"),
            result_url_of=result_url_of, key_prefix="providers/seedance/video", suffix=".mp4",
            extra_data={"duration_sec": duration_sec, "keyframe_url": keyframe_url},
        )


# --------------------------------------------------------------------------
# Voice
# --------------------------------------------------------------------------
class ElevenLabsVoiceAdapter(RealAdapterMixin, VoiceProvider):
    name = "elevenlabs"
    key_setting = "ELEVENLABS_API_KEY"

    def capability(self) -> ProviderCapability:
        return _build_capability(self.name, "voice", self.key_setting)

    def list_voices(self) -> List[Dict[str, Any]]:
        if not self.available():
            return []
        url = f"{settings.ELEVENLABS_BASE_URL}{ELEVENLABS_VOICES_PATH}"
        headers = {"xi-api-key": self._api_key() or ""}
        try:
            raw = http.get_json(url, headers=headers)
        except http.ProviderHttpError as exc:
            catalog.record_failure(self.name, str(exc))
            logger.warning("elevenlabs list_voices failed: %s", http.redact(str(exc)))
            return []
        catalog.record_success(self.name)
        voices = raw.get("voices") or []
        return [
            {
                "id": v.get("voice_id"),
                "name": v.get("name", ""),
                "name_ar": "",
                "gender": (v.get("labels") or {}).get("gender", ""),
                "dialect": "",
                "style": (v.get("labels") or {}).get("accent", ""),
                "provider": self.name,
                "is_demo": False,
            }
            for v in voices
            if v.get("voice_id")
        ]

    def synthesize(
        self, *, text: str, voice_id: str, model: Optional[str] = None,
        speed: float = 1.0, energy: float = 0.6, emotion: float = 0.5,
    ) -> ProviderResult:
        operation = "voice_generation"
        if not self.available():
            return self._unavailable(operation)
        spec = _select_spec(self.name, "voice", model)
        model_id = model or catalog.configured_model_id(spec)
        url = f"{settings.ELEVENLABS_BASE_URL}{ELEVENLABS_TTS_PATH.format(voice_id=voice_id)}"
        headers = {"xi-api-key": self._api_key() or "", "Content-Type": "application/json", "Accept": "audio/mpeg"}
        body = {
            "text": text,
            "model_id": model_id,
            "voice_settings": {
                "stability": max(0.0, min(1.0, 1.0 - energy)),
                "similarity_boost": 0.75,
                "style": max(0.0, min(1.0, emotion)),
            },
        }
        started = time.time()
        try:
            audio_bytes = http.post_bytes(url, headers=headers, json=body)
        except http.ProviderHttpError as exc:
            return self._error_result(operation, model_id, str(exc))

        # Lazy imports: keep the providers layer free of a hard import-time
        # dependency on services (avoids an import cycle at module load).
        from app.services.dialect import estimate_speech_seconds
        from app.services.storage import get_storage

        duration = estimate_speech_seconds(text, speed)
        digest = hashlib.md5(f"{voice_id}:{text}:{speed}".encode()).hexdigest()[:16]
        stored_url = get_storage().put_bytes(f"providers/elevenlabs/voice/{digest}.mp3", audio_bytes, content_type="audio/mpeg")
        cost = pricing.estimate_voice_cost(len(text), model=model_id)
        latency_ms = int((time.time() - started) * 1000)
        catalog.record_success(self.name)
        return ProviderResult(
            ok=True, provider=self.name, model=model_id, operation=operation, is_mock=False,
            cost_usd=cost, latency_ms=latency_ms, url=stored_url,
            data={"duration_sec": duration, "voice_id": voice_id, "characters": len(text), "energy": energy, "emotion": emotion},
        )


# --------------------------------------------------------------------------
# Music — no vendor has been selected by the product yet (see the module
# docstring above MUSIC_GENERATE_PATH). This is a real, working scaffold
# against a generic async-generation shape, not a verified integration.
# --------------------------------------------------------------------------
class GenericMusicAdapter(RealAdapterMixin, MusicProvider):
    name = "music"
    key_setting = "MUSIC_API_KEY"

    def capability(self) -> ProviderCapability:
        return _build_capability(self.name, "music", self.key_setting)

    def generate_music(
        self, *, brief: Dict[str, Any], duration_sec: float = 30.0, model: Optional[str] = None
    ) -> ProviderResult:
        operation = "music_generation"
        if not self.available():
            return self._unavailable(operation)
        spec = _select_spec(self.name, "music", model)
        model_id = model or catalog.configured_model_id(spec)
        headers = {"Authorization": f"Bearer {self._api_key()}", "Content-Type": "application/json"}
        submit_url = f"{settings.MUSIC_BASE_URL}{MUSIC_GENERATE_PATH}"
        mood = brief.get("mood", "cinematic warm")

        def submit() -> Dict[str, Any]:
            body = {"model": model_id, "mood": mood, "duration_sec": duration_sec, "brief": dict(brief)}
            return http.post_json(submit_url, headers=headers, json=body)

        def poll(task_id: str) -> Dict[str, Any]:
            url = f"{settings.MUSIC_BASE_URL}{MUSIC_STATUS_PATH.format(task_id=task_id)}"
            return http.get_json(url, headers=headers)

        def job_id_of(resp: Dict[str, Any]) -> str:
            job_id = resp.get("id") or resp.get("task_id")
            if not job_id:
                raise http.ProviderHttpError(http.ErrorKind.UNKNOWN, "music provider submit response had no task id")
            return job_id

        def status_of(resp: Dict[str, Any]) -> str:
            return str(resp.get("status", "unknown")).lower()

        def result_url_of(resp: Dict[str, Any]) -> Optional[str]:
            return resp.get("audio_url") or resp.get("output_url")

        return self._run_async_media_job(
            operation=operation, model_id=model_id, cost_units=1.0,
            submit=submit, poll=poll, job_id_of=job_id_of, status_of=status_of,
            done_statuses=("succeeded", "completed", "done"), failed_statuses=("failed", "error"),
            result_url_of=result_url_of, key_prefix="providers/music/tracks", suffix=".mp3",
            extra_data={"mood": mood, "duration_sec": duration_sec},
        )
