"""Shared async agent runner.

Every specialist agent is the same shape: take a small structured input
(the de-identified case), call Azure OpenAI with a tight JSON system prompt,
stream tokens, parse a strict JSON object out. On any failure (timeout,
bad JSON, API error) the agent falls back to a hand-written offline
implementation supplied by the specialist module, so the demo never
hard-fails on stage.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional


@dataclass
class AgentResult:
    name: str
    output: dict[str, Any] = field(default_factory=dict)
    raw_text: str = ""
    source: str = "azure_openai"  # "azure_openai" | "simulated_offline" | "fallback_local"
    error: Optional[str] = None
    elapsed_ms: int = 0


TokenCallback = Callable[[str, str], Awaitable[None]]  # (agent_name, delta)


def _azure_configured() -> bool:
    return all(
        os.environ.get(k)
        for k in (
            "AZURE_OPENAI_ENDPOINT",
            "AZURE_OPENAI_API_KEY",
            "AZURE_OPENAI_DEPLOYMENT",
            "AZURE_OPENAI_API_VERSION",
        )
    )


async def call_azure_streaming(
    *,
    name: str,
    system_prompt: str,
    user_prompt: str,
    on_token: Optional[TokenCallback],
    timeout: float = 18.0,
    temperature: float = 0.0,
) -> AgentResult:
    """Stream a single Azure OpenAI completion and parse the JSON object out."""
    started = time.monotonic()

    if not _azure_configured():
        return AgentResult(
            name=name,
            source="not_configured",
            error="azure_openai_not_configured",
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )

    try:
        from openai import AsyncAzureOpenAI
    except ImportError:
        return AgentResult(
            name=name,
            source="not_configured",
            error="openai_sdk_not_installed",
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )

    client = AsyncAzureOpenAI(
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        api_version=os.environ["AZURE_OPENAI_API_VERSION"],
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        timeout=timeout,
    )
    deployment = os.environ["AZURE_OPENAI_DEPLOYMENT"]

    pieces: list[str] = []
    try:
        async def _stream() -> None:
            stream = await client.chat.completions.create(
                model=deployment,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=temperature,
                stream=True,
            )
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                piece = getattr(delta, "content", None) or ""
                if not piece:
                    continue
                pieces.append(piece)
                if on_token is not None:
                    await on_token(name, piece)

        await asyncio.wait_for(_stream(), timeout=timeout)
    except asyncio.TimeoutError:
        return AgentResult(
            name=name,
            raw_text="".join(pieces),
            source="azure_openai",
            error="timeout",
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )
    except Exception as exc:  # noqa: BLE001
        return AgentResult(
            name=name,
            raw_text="".join(pieces),
            source="azure_openai",
            error=f"{type(exc).__name__}: {exc}",
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )

    raw = "".join(pieces)
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("response was not a JSON object")
    except (ValueError, json.JSONDecodeError) as exc:
        return AgentResult(
            name=name,
            raw_text=raw,
            source="azure_openai",
            error=f"json_parse_error: {exc}",
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )

    return AgentResult(
        name=name,
        output=parsed,
        raw_text=raw,
        source="azure_openai",
        error=None,
        elapsed_ms=int((time.monotonic() - started) * 1000),
    )


async def simulated_stream(
    *,
    name: str,
    output: dict[str, Any],
    on_token: Optional[TokenCallback],
    pause: float = 0.0,
) -> AgentResult:
    """Pretend to stream the JSON output of an offline simulated agent.

    Used (a) as the offline-engine choice for the whole co-pilot, and
    (b) as the fallback when an Azure call fails - so the stage never goes
    blank.
    """
    started = time.monotonic()
    raw = json.dumps(output, indent=2)
    if on_token is not None:
        chunk = 8
        for i in range(0, len(raw), chunk):
            await on_token(name, raw[i : i + chunk])
            if pause:
                await asyncio.sleep(pause)
    return AgentResult(
        name=name,
        output=output,
        raw_text=raw,
        source="simulated_offline",
        error=None,
        elapsed_ms=int((time.monotonic() - started) * 1000),
    )
