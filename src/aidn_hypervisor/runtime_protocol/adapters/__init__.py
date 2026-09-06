from aidn_hypervisor.runtime_protocol.adapters.llamacpp import LlamaCppOpenAIAdapter
from aidn_hypervisor.runtime_protocol.adapters.nemo_speech import NemoSpeechHttpAdapter
from aidn_hypervisor.runtime_protocol.adapters.ollama import OllamaGenerateAdapter
from aidn_hypervisor.runtime_protocol.adapters.proxy import ProxyOpenAIAdapter
from aidn_hypervisor.runtime_protocol.adapters.vllm import VllmOpenAIAdapter

__all__ = [
    "LlamaCppOpenAIAdapter",
    "NemoSpeechHttpAdapter",
    "OllamaGenerateAdapter",
    "ProxyOpenAIAdapter",
    "VllmOpenAIAdapter",
]
