"""Small, bounded HTTP client for the local Fish Audio S2 Pro runtime.

The S2 runtime is intentionally kept outside the Hypervisor process.  This
module only translates a dashboard utterance into the multipart request used
by ``s2.cpp`` and validates the returned bytes before they cross the browser
boundary.
"""

from __future__ import annotations

import json
import os
import secrets
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import urlparse

DEFAULT_ENDPOINT = "http://127.0.0.1:3030"
DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_MAX_NEW_TOKENS = 256
MAX_TEXT_CHARS = 16_384
MAX_AUDIO_BYTES = 25 * 1024 * 1024


class S2TtsError(RuntimeError):
    """A safe, user-facing failure from the local S2 Pro runtime."""


def _runtime_endpoint(endpoint: str | None = None) -> str:
    value = (endpoint or os.getenv("AIDN_S2_TTS_ENDPOINT") or DEFAULT_ENDPOINT).strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise S2TtsError("Некорректный адрес S2 Pro TTS runtime.")
    if parsed.username or parsed.password or parsed.fragment:
        raise S2TtsError("Адрес S2 Pro TTS runtime не должен содержать учётные данные или fragment.")
    return value.rstrip("/")


def _multipart_form(text: str, params: dict[str, object]) -> tuple[bytes, str]:
    boundary = f"----AiDN-S2-{secrets.token_hex(16)}"
    chunks: list[bytes] = []
    for name, value in (("text", text), ("params", json.dumps(params, ensure_ascii=False, separators=(",", ":")))):
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("ascii"),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("ascii"),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _validate_wav(audio: bytes) -> bytes:
    if len(audio) > MAX_AUDIO_BYTES:
        raise S2TtsError("Ответ S2 Pro TTS слишком большой.")
    if len(audio) < 44 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
        raise S2TtsError("S2 Pro TTS вернул некорректный WAV.")
    return audio


def synthesize(
    text: str,
    *,
    endpoint: str | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_new_tokens: int = DEFAULT_MAX_NEW_TOKENS,
) -> bytes:
    """Generate one WAV response from the loopback S2 Pro server.

    The caller supplies only text; generation parameters remain bounded here
    so a browser request cannot turn the provider into an unbounded workload.
    """

    normalized = text.strip()
    if not normalized:
        raise S2TtsError("Нельзя озвучить пустой текст.")
    if len(normalized) > MAX_TEXT_CHARS:
        raise S2TtsError("Текст для озвучивания слишком длинный.")
    try:
        bounded_timeout = min(max(float(timeout_seconds), 1.0), 180.0)
        bounded_tokens = min(max(int(max_new_tokens), 32), 512)
    except (TypeError, ValueError) as exc:
        raise S2TtsError("Некорректные параметры S2 Pro TTS.") from exc

    body, content_type = _multipart_form(
        normalized,
        {
            "max_new_tokens": bounded_tokens,
            "temperature": 0.58,
            "top_p": 0.88,
            "top_k": 40,
        },
    )
    url = f"{_runtime_endpoint(endpoint)}/generate"
    http_request = urllib_request.Request(
        url,
        data=body,
        headers={
            "Accept": "audio/wav",
            "Content-Type": content_type,
            "Content-Length": str(len(body)),
            "User-Agent": "AiDN-Hypervisor-S2-TTS/1",
        },
        method="POST",
    )

    try:
        with urllib_request.urlopen(http_request, timeout=bounded_timeout) as response:
            audio = response.read(MAX_AUDIO_BYTES + 1)
    except urllib_error.HTTPError as exc:
        if exc.status == 503:
            raise S2TtsError("S2 Pro TTS сейчас занят; повторите через несколько секунд.") from exc
        raise S2TtsError(f"S2 Pro TTS отклонил запрос ({exc.status}).") from exc
    except (urllib_error.URLError, TimeoutError, OSError) as exc:
        raise S2TtsError("S2 Pro TTS runtime на ноде недоступен.") from exc

    return _validate_wav(audio)


__all__ = ["S2TtsError", "synthesize"]
