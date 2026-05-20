"""Azure OpenAI streaming summarizer.

Reads connection details from environment variables:
- ``AZURE_OPENAI_ENDPOINT``     e.g. https://my-aoai.openai.azure.com
- ``AZURE_OPENAI_API_KEY``      AOAI key
- ``AZURE_OPENAI_DEPLOYMENT``   model deployment name
- ``AZURE_OPENAI_API_VERSION``  e.g. 2024-08-01-preview

This summarizer is the LLM half of the pipeline. It only ever receives
de-identified text (or, when the danger toggle is OFF, raw text - explicitly
labelled). Re-hydration of placeholders happens in the trusted server layer
afterwards.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable, Optional

from .safe_summarizer import summarize_safely


SYSTEM_PROMPT = (
    "You are a clinical summary assistant for a healthcare workflow. "
    "Your input has already been de-identified by an upstream pipeline; "
    "real PHI has been replaced with placeholder tokens such as "
    "[PATIENT_NAME_1], [MRN_1], [PROVIDER_NAME_1], [DATE_1], [PHONE_1]. "
    "A downstream trusted process re-substitutes the real values before a "
    "clinician sees the summary, so PRESERVE every placeholder verbatim - "
    "do not strip them, paraphrase them, or invent new ones."
    "\n\n"
    "When you would naturally name the patient, a provider, a date, an "
    "MRN, or any other entity that appears in the input as a placeholder, "
    "USE that placeholder in your output. For example:\n"
    "  chief_concern: 'Patient [PATIENT_NAME_1] reports worsening dyspnea.'\n"
    "  follow_up_questions: ['Confirm follow-up with [PROVIDER_NAME_1] on [DATE_1].']\n"
    "Doing this is critical - it lets the trusted re-hydration layer "
    "restore the real values without ever exposing them to you."
    "\n\n"
    "If you ever see what looks like raw PHI (a real-looking phone, email, "
    "MRN, address, or full personal name) in the input, set "
    "source_text_status='blocked' and refuse to copy any of it into the output."
    "\n\n"
    "Respond with a single JSON object and NOTHING else - no prose, no "
    "markdown fences. The JSON must have exactly these keys: "
    "summary_type (string, always 'clinical_workflow_support'), "
    "disclaimer (string, 'For clinician review only. Not a diagnosis.'), "
    "chief_concern (string - reference patient/providers using their "
    "placeholder tokens when relevant), "
    "relevant_history (array of strings), "
    "medications_mentioned (array of strings), "
    "risk_flags (array of strings), "
    "follow_up_questions (array of strings - include placeholder tokens "
    "where you would otherwise name the patient, a provider, or a date), "
    "source_text_status (string, 'deidentified' if you saw only "
    "placeholders, 'blocked' if you saw raw PHI)."
)


@dataclass
class LLMSummaryResult:
    summary: dict[str, Any]
    raw_text: str
    summary_source: str  # "azure_openai" or "fallback_local"
    error: str | None = None


def azure_openai_configured() -> bool:
    """True if all required Azure OpenAI env vars are set."""
    return all(
        os.environ.get(k)
        for k in (
            "AZURE_OPENAI_ENDPOINT",
            "AZURE_OPENAI_API_KEY",
            "AZURE_OPENAI_DEPLOYMENT",
            "AZURE_OPENAI_API_VERSION",
        )
    )


def _build_user_prompt(deidentified_text: str) -> str:
    return (
        "Below is a de-identified clinical note. Produce the structured "
        "summary as specified.\n\n"
        "----- BEGIN DE-IDENTIFIED NOTE -----\n"
        f"{deidentified_text}\n"
        "----- END DE-IDENTIFIED NOTE -----"
    )


async def stream_summary(
    text: str,
    *,
    on_token: Optional[Callable[[str], Awaitable[None]]] = None,
    timeout_seconds: float = 20.0,
) -> LLMSummaryResult:
    """Stream a structured summary from Azure OpenAI.

    Falls back to the deterministic local summarizer if Azure is not
    configured or the call fails. The fallback also runs if the model
    returns malformed JSON.
    """
    if not azure_openai_configured():
        local = summarize_safely(text)
        return LLMSummaryResult(
            summary=local,
            raw_text=json.dumps(local),
            summary_source="fallback_local",
            error="azure_openai_not_configured",
        )

    try:
        # Imported lazily so the dependency is optional for the CLI/tests.
        from openai import AsyncAzureOpenAI
    except ImportError:
        local = summarize_safely(text)
        return LLMSummaryResult(
            summary=local,
            raw_text=json.dumps(local),
            summary_source="fallback_local",
            error="openai_sdk_not_installed",
        )

    client = AsyncAzureOpenAI(
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        api_version=os.environ["AZURE_OPENAI_API_VERSION"],
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        timeout=timeout_seconds,
    )
    deployment = os.environ["AZURE_OPENAI_DEPLOYMENT"]

    accumulated: list[str] = []
    try:
        stream = await client.chat.completions.create(
            model=deployment,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": _build_user_prompt(text)},
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
            stream=True,
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            piece = getattr(delta, "content", None) or ""
            if not piece:
                continue
            accumulated.append(piece)
            if on_token is not None:
                await on_token(piece)
    except Exception as exc:  # noqa: BLE001 - fall back gracefully on any error
        local = summarize_safely(text)
        return LLMSummaryResult(
            summary=local,
            raw_text=json.dumps(local),
            summary_source="fallback_local",
            error=f"azure_openai_error: {type(exc).__name__}: {exc}",
        )

    raw = "".join(accumulated)
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("model response was not a JSON object")
        # Make sure required keys exist - fill missing with sane defaults.
        parsed.setdefault("summary_type", "clinical_workflow_support")
        parsed.setdefault(
            "disclaimer", "For clinician review only. Not a diagnosis."
        )
        for k in (
            "relevant_history",
            "medications_mentioned",
            "risk_flags",
            "follow_up_questions",
        ):
            parsed.setdefault(k, [])
        parsed.setdefault("chief_concern", "Not stated")
        parsed.setdefault("source_text_status", "deidentified")
        return LLMSummaryResult(
            summary=parsed,
            raw_text=raw,
            summary_source="azure_openai",
        )
    except (ValueError, json.JSONDecodeError) as exc:
        local = summarize_safely(text)
        return LLMSummaryResult(
            summary=local,
            raw_text=raw,
            summary_source="fallback_local",
            error=f"json_parse_error: {exc}",
        )
