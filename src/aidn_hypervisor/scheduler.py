from aidn_hypervisor.domain.models import BundleConfig, TaskRequest

_TASK_WORKLOAD_TYPES = {
    "llm_text.generate": "llm_text",
    "audio.transcribe": "speech_to_text",
}


class Scheduler:
    def select_bundle(
        self, request: TaskRequest, bundles: list[BundleConfig]
    ) -> BundleConfig:
        expected_workload = _TASK_WORKLOAD_TYPES.get(request.task_type)
        if expected_workload is None:
            raise ValueError(f"No workload mapping for task type: {request.task_type}")

        if request.mode == "manual":
            if not request.bundle_override:
                raise ValueError("Manual mode requires bundle_override")
            for bundle in bundles:
                if bundle.bundle_id != request.bundle_override:
                    continue
                if not bundle.enabled:
                    raise ValueError(f"Requested bundle is disabled: {bundle.bundle_id}")
                if bundle.workload_type != expected_workload:
                    raise ValueError(f"Requested bundle is incompatible: {bundle.bundle_id}")
                return bundle
            raise ValueError(f"Requested bundle is missing: {request.bundle_override}")

        compatible = [
            bundle
            for bundle in bundles
            if bundle.enabled and bundle.workload_type == expected_workload
        ]
        if not compatible:
            raise ValueError(f"No compatible bundle for task type: {request.task_type}")
        return sorted(
            compatible, key=lambda bundle: bundle.priority_class, reverse=True
        )[0]
