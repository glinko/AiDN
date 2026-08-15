import shutil
import subprocess
from pathlib import Path

import pytest

PROVIDER_SCRIPTS = [
    Path("tools/aidn-provider-runtime-ubuntu.sh"),
    Path("tools/aidn-whisper-runtime-ubuntu.sh"),
    Path("tools/aidn-ollama-runtime-ubuntu.sh"),
    Path("tools/aidn-llamacpp-runtime-ubuntu.sh"),
    Path("tools/aidn-vllm-runtime-ubuntu.sh"),
]


def test_provider_runtime_dispatcher_is_an_exact_allowlist() -> None:
    script = PROVIDER_SCRIPTS[0].read_text(encoding="utf-8")

    assert "whisper)" in script
    assert "ollama)" in script
    assert "llama.cpp|llamacpp)" in script
    assert "vllm)" in script
    assert "unsupported Provider runtime" in script
    assert "eval " not in script
    assert "sh -c" not in script


def test_provider_runtime_installers_pin_reviewed_upstream_versions() -> None:
    whisper = PROVIDER_SCRIPTS[1].read_text(encoding="utf-8")
    ollama = PROVIDER_SCRIPTS[2].read_text(encoding="utf-8")
    llamacpp = PROVIDER_SCRIPTS[3].read_text(encoding="utf-8")
    vllm = PROVIDER_SCRIPTS[4].read_text(encoding="utf-8")

    assert "onerahmet/openai-whisper-asr-webservice:v1.9.1" in whisper
    assert 'DEFAULT_VERSION="0.32.12"' in ollama
    assert 'DEFAULT_REF="b10433"' in llamacpp
    assert 'DEFAULT_VERSION="0.27.1"' in vllm
    assert '[[ "$version" == "$DEFAULT_VERSION" ]]' in ollama
    assert '[[ "$ref" == "$DEFAULT_REF" ]]' in llamacpp
    assert '[[ "$version" == "$DEFAULT_VERSION" ]]' in vllm


def test_provider_runtime_installers_expose_remove_without_deleting_model_storage() -> None:
    for path in PROVIDER_SCRIPTS[1:]:
        script = path.read_text(encoding="utf-8")
        assert "remove)" in script, path
        assert "preserved" in script, path


def test_provider_runtime_installers_bind_services_to_loopback() -> None:
    for path in PROVIDER_SCRIPTS[1:]:
        script = path.read_text(encoding="utf-8")
        assert "127.0.0.1" in script, path
        assert "0.0.0.0" not in script, path


def test_provider_runtime_install_is_separate_from_model_configuration() -> None:
    ollama = PROVIDER_SCRIPTS[2].read_text(encoding="utf-8")
    llamacpp = PROVIDER_SCRIPTS[3].read_text(encoding="utf-8")
    vllm = PROVIDER_SCRIPTS[4].read_text(encoding="utf-8")

    assert "Optional model to pull after start" in ollama
    assert "does not download a model" in llamacpp
    assert "model download remains a start/configuration step" in vllm


def test_vllm_runtime_install_reuses_a_matching_environment() -> None:
    vllm = PROVIDER_SCRIPTS[4].read_text(encoding="utf-8")

    assert "runtime-version" in vllm
    assert "--clear" in vllm
    assert '"reused":%s' in vllm


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is unavailable")
@pytest.mark.parametrize("path", PROVIDER_SCRIPTS)
def test_provider_runtime_installers_have_valid_bash_syntax(path: Path) -> None:
    subprocess.run(["bash", "-n", str(path)], check=True)


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is unavailable")
@pytest.mark.parametrize("path", PROVIDER_SCRIPTS)
def test_provider_runtime_installers_expose_help_without_host_mutation(path: Path) -> None:
    subprocess.run(["bash", str(path), "--help"], check=True, capture_output=True, text=True)
