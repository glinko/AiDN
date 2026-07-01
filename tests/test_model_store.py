from aidn_hypervisor.model_store import FileModelStore


def test_file_model_store_reserves_provider_scoped_target_path(tmp_path) -> None:
    store = FileModelStore(tmp_path)

    target_path = store.reserve_target_path("llama.cpp", "phi-4/mini.gguf")

    assert target_path == tmp_path / "llama.cpp" / "phi-4_mini.gguf"
    assert target_path.parent.exists()
