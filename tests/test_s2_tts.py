from __future__ import annotations

from unittest.mock import patch
from urllib.error import URLError

import pytest

from aidn_hypervisor.main import _is_validator_consensus_write_path
from aidn_hypervisor.s2_tts import S2TtsError, synthesize


def _wav_bytes() -> bytes:
    # A minimal PCM-shaped RIFF header is sufficient for the client boundary;
    # the provider owns the full audio codec validation.
    return (
        b"RIFF"
        + (36).to_bytes(4, "little")
        + b"WAVEfmt "
        + (16).to_bytes(4, "little")
        + (1).to_bytes(2, "little")
        + (1).to_bytes(2, "little")
        + (16_000).to_bytes(4, "little")
        + (32_000).to_bytes(4, "little")
        + (2).to_bytes(2, "little")
        + (16).to_bytes(2, "little")
        + b"data"
        + (0).to_bytes(4, "little")
    )


class _Response:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit: int = -1) -> bytes:
        return self.payload


def test_synthesize_posts_bounded_multipart_and_validates_wav() -> None:
    with patch(
        "aidn_hypervisor.s2_tts.urllib_request.urlopen",
        return_value=_Response(_wav_bytes()),
    ) as urlopen:
        audio = synthesize("  Привет, агент!  ", endpoint="http://127.0.0.1:3030")

    assert audio.startswith(b"RIFF")
    request = urlopen.call_args.args[0]
    assert request.full_url == "http://127.0.0.1:3030/generate"
    assert request.get_header("Accept") == "audio/wav"
    assert b'name="text"' in request.data
    assert "Привет, агент!".encode("utf-8") in request.data
    assert b'name="params"' in request.data
    assert b'"max_new_tokens":256' in request.data


def test_synthesize_rejects_invalid_provider_audio() -> None:
    with patch(
        "aidn_hypervisor.s2_tts.urllib_request.urlopen",
        return_value=_Response(b"not wav"),
    ):
        with pytest.raises(S2TtsError, match="некорректный WAV"):
            synthesize("Проверка")


def test_synthesize_surfaces_loopback_unavailable_as_safe_error() -> None:
    with patch(
        "aidn_hypervisor.s2_tts.urllib_request.urlopen",
        side_effect=URLError("connection refused"),
    ):
        with pytest.raises(S2TtsError, match="недоступен"):
            synthesize("Проверка")


def test_validator_allows_ephemeral_local_tts_write() -> None:
    assert _is_validator_consensus_write_path("/operators/dashboard/speech/tts", "POST")
    assert not _is_validator_consensus_write_path("/operators/dashboard/speech/tts", "GET")
