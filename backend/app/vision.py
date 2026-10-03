"""Replaceable vision providers for structured footwear image observations."""
from __future__ import annotations

import base64
import json
import mimetypes
import os
from pathlib import Path
from typing import Literal, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field, ValidationError

from .domain import Evidence, EvidenceBundle, EvidenceSource
from .providers import VisionProvider


class VisionConfigurationError(FileNotFoundError):
    """The replaceable vision adapter has no configured credential."""


class VisionProviderError(RuntimeError):
    """The configured vision service could not return usable observations."""


class VisionObservation(BaseModel):
    attribute: Literal[
        "brand", "model", "sku", "style_code", "colourway", "size", "visible_label",
        "packaging", "visible_marking", "physical_observation",
    ]
    value: str = Field(max_length=240)
    visual_basis: str = Field(max_length=500)
    confidence: float = Field(ge=0.0, le=1.0)


class VisionObservations(BaseModel):
    observations: list[VisionObservation] = Field(max_length=48)


class ResponsesTransport(Protocol):
    def create(
        self, payload: dict[str, object], *, api_key: str, timeout_seconds: float
    ) -> dict[str, object]: ...


class OpenAIResponsesTransport:
    endpoint = "https://api.openai.com/v1/responses"

    def create(
        self, payload: dict[str, object], *, api_key: str, timeout_seconds: float
    ) -> dict[str, object]:
        request = Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            raise VisionProviderError(
                f"OpenAI vision request failed with HTTP {error.code}"
            ) from error
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            raise VisionProviderError("OpenAI vision request could not be completed") from error
        if not isinstance(result, dict):
            raise VisionProviderError("OpenAI vision returned an invalid response")
        return result


class InteractionsTransport(Protocol):
    def create(
        self, payload: dict[str, object], *, api_key: str, timeout_seconds: float
    ) -> dict[str, object]: ...


class GeminiInteractionsTransport:
    """Google Gemini Interactions API transport using the current steps schema."""

    endpoint = "https://generativelanguage.googleapis.com/v1beta/interactions"

    def create(
        self, payload: dict[str, object], *, api_key: str, timeout_seconds: float
    ) -> dict[str, object]:
        request = Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "x-goog-api-key": api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Api-Revision": "2026-05-20",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            raise VisionProviderError(
                f"Gemini vision request failed with HTTP {error.code}"
            ) from error
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            raise VisionProviderError("Gemini vision request could not be completed") from error
        if not isinstance(result, dict):
            raise VisionProviderError("Gemini vision returned an invalid response")
        return result


OBSERVATION_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "observations": {
            "type": "array",
            "maxItems": 48,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "attribute": {
                        "type": "string",
                        "enum": [
                            "brand", "model", "sku", "style_code", "colourway", "size",
                            "visible_label", "packaging", "visible_marking",
                            "physical_observation",
                        ],
                    },
                    "value": {"type": "string"},
                    "visual_basis": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["attribute", "value", "visual_basis", "confidence"],
            },
        }
    },
    "required": ["observations"],
}

VISION_INSTRUCTIONS = """Inspect the supplied footwear photo and report only observable details.
Do not decide authenticity and do not use outside or memorized product knowledge.
Never infer a model, SKU, style code, colourway, size, material, label text, or
packaging detail that is not clearly visible in this image. Transcribe text only
when legible. Omit unobserved attributes. For every observation, provide a short
visual_basis describing the exact visible cue and a 0-to-1 model-reported
confidence that the cue was read correctly. This value is not an authenticity
probability. Use the exact output schema. Physical observations should describe
visible construction/shape/colour only, not quality or authenticity conclusions."""

_SUBJECTS: dict[str, str] = {
    "brand": "brand",
    "model": "product_name",
    "sku": "sku",
    "style_code": "style_code",
    "colourway": "colorway",
    "size": "size",
    "visible_label": "label_info",
    "packaging": "packaging",
    "visible_marking": "visible_marking",
    "physical_observation": "physical_observation",
}
_EMPTY_VALUES = {"unknown", "not visible", "not readable", "unreadable", "n/a", "none", "null"}


def _image_media_type(image_path: Path) -> str:
    media_type = mimetypes.guess_type(image_path.name)[0]
    if media_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise VisionProviderError("Vision supports JPEG, PNG, and WebP uploads")
    return media_type


def _response_text(response: dict[str, object]) -> str:
    text_parts: list[str] = []
    output = response.get("output")
    if not isinstance(output, list):
        raise VisionProviderError("OpenAI vision response did not contain output items")
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "refusal":
                raise VisionProviderError("OpenAI declined to analyze this image")
            if part.get("type") == "output_text" and isinstance(part.get("text"), str):
                text_parts.append(part["text"])
    if not text_parts:
        raise VisionProviderError("OpenAI vision response contained no structured observations")
    return "".join(text_parts)


def _gemini_response_text(response: dict[str, object]) -> str:
    text_parts: list[str] = []
    # The current Interactions API uses `steps`; `outputs` is accepted as a
    # defensive compatibility path for older stored/mock responses.
    steps = response.get("steps", response.get("outputs"))
    if not isinstance(steps, list):
        raise VisionProviderError("Gemini vision response did not contain output steps")
    for step in steps:
        if not isinstance(step, dict):
            continue
        if step.get("type") not in {"model_output", "output"}:
            continue
        content = step.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text" and isinstance(part.get("text"), str):
                text_parts.append(part["text"])
    if not text_parts and isinstance(response.get("output_text"), str):
        text_parts.append(response["output_text"])
    if not text_parts:
        raise VisionProviderError("Gemini vision response contained no structured observations")
    return "".join(text_parts)


def _evidence_bundle(
    observations: VisionObservations, image_path: Path, provider: str
) -> EvidenceBundle:
    source = EvidenceSource(
        source_type="vision_output",
        trust_level="unrated",
        provider=provider,
        uri=f"upload://{image_path.stem}",
    )
    evidence: list[Evidence] = []
    for observation in observations.observations:
        value = observation.value.strip()
        if not value or value.casefold() in _EMPTY_VALUES:
            continue
        subject = _SUBJECTS[observation.attribute]
        evidence.append(Evidence(
            source_id=source.source_id,
            evidence_type="visual_observation",
            subject=subject,
            observation=f"Visible {observation.attribute.replace('_', ' ')}: {value}",
            exact_claim=f"{subject}: {value}",
            source_url=source.uri,
            retrieved_at=source.retrieved_at,
            provider=source.provider,
            supporting_text=observation.visual_basis.strip() or None,
            confidence=observation.confidence,
            source_trust_level="unrated",
        ))
    return EvidenceBundle(sources=[source], evidence=evidence)


class OpenAIVisionProvider:
    """Analyze one stored footwear image; no network request occurs without a key."""

    provider_name = "openai_responses_vision"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        model: str | None = None,
        timeout_seconds: float = 60.0,
        transport: ResponsesTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model or os.environ.get("OPENAI_VISION_MODEL", "gpt-6-luna")
        self.timeout_seconds = timeout_seconds
        self.transport = transport or OpenAIResponsesTransport()

    def analyze(self, check, image_path: Path) -> EvidenceBundle:
        api_key = self.api_key or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise VisionConfigurationError("OPENAI_API_KEY is required for image analysis")
        try:
            image_bytes = image_path.read_bytes()
        except OSError as error:
            raise VisionProviderError("Stored footwear image could not be read") from error
        media_type = _image_media_type(image_path)
        data_url = f"data:{media_type};base64,{base64.b64encode(image_bytes).decode('ascii')}"
        payload: dict[str, object] = {
            "model": self.model,
            "instructions": VISION_INSTRUCTIONS,
            "input": [{
                "role": "user",
                "content": [
                    {"type": "input_text", "text": (
                        "Record visible footwear product details in this image. "
                        "Return an empty observations array if no details can be read."
                    )},
                    {"type": "input_image", "image_url": data_url, "detail": "high"},
                ],
            }],
            "text": {"format": {
                "type": "json_schema",
                "name": "footwear_image_observations",
                "strict": True,
                "schema": OBSERVATION_SCHEMA,
            }},
            "max_output_tokens": 1800,
            "store": False,
        }
        response = self.transport.create(
            payload, api_key=api_key, timeout_seconds=self.timeout_seconds
        )
        try:
            observations = VisionObservations.model_validate_json(_response_text(response))
        except ValidationError as error:
            raise VisionProviderError("OpenAI vision returned observations outside the schema") from error
        except json.JSONDecodeError as error:
            raise VisionProviderError("OpenAI vision returned invalid structured output") from error

        return _evidence_bundle(observations, image_path, f"{self.provider_name}:{self.model}")


class GeminiVisionProvider:
    """Gemini implementation of the unchanged VisionProvider contract."""

    provider_name = "gemini_interactions_vision"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        model: str | None = None,
        timeout_seconds: float = 60.0,
        transport: InteractionsTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model or os.environ.get(
            "GEMINI_VISION_MODEL", "gemini-3.1-flash-lite"
        )
        self.timeout_seconds = timeout_seconds
        self.transport = transport or GeminiInteractionsTransport()

    def analyze(self, check, image_path: Path) -> EvidenceBundle:
        api_key = self.api_key or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise VisionConfigurationError("GEMINI_API_KEY is required for image analysis")
        try:
            image_bytes = image_path.read_bytes()
        except OSError as error:
            raise VisionProviderError("Stored footwear image could not be read") from error
        media_type = _image_media_type(image_path)
        payload: dict[str, object] = {
            "model": self.model,
            "input": [
                {"type": "text", "text": VISION_INSTRUCTIONS + (
                    "\n\nRecord visible footwear product details in the supplied photo. "
                    "Return an empty observations array if no details can be read."
                )},
                {
                    "type": "image",
                    "mime_type": media_type,
                    "data": base64.b64encode(image_bytes).decode("ascii"),
                },
            ],
            "response_format": {
                "type": "text",
                "mime_type": "application/json",
                "schema": OBSERVATION_SCHEMA,
            },
        }
        response = self.transport.create(
            payload, api_key=api_key, timeout_seconds=self.timeout_seconds
        )
        try:
            observations = VisionObservations.model_validate_json(_gemini_response_text(response))
        except ValidationError as error:
            raise VisionProviderError("Gemini vision returned observations outside the schema") from error
        except json.JSONDecodeError as error:
            raise VisionProviderError("Gemini vision returned invalid structured output") from error
        if response.get("status") not in (None, "completed"):
            raise VisionProviderError("Gemini vision interaction did not complete")
        return _evidence_bundle(observations, image_path, f"{self.provider_name}:{self.model}")


def create_vision_provider(provider_name: str | None = None) -> VisionProvider:
    """Select a replaceable image analyzer from VISION_PROVIDER."""
    selected = (provider_name or os.environ.get("VISION_PROVIDER", "gemini")).strip().lower()
    if selected == "openai":
        return OpenAIVisionProvider()
    if selected == "gemini":
        return GeminiVisionProvider()
    raise ValueError("VISION_PROVIDER must be 'openai' or 'gemini'")
