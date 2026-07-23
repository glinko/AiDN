from __future__ import annotations


def certification_status_from_validation_status(validation_status: str) -> str:
    return {
        "validated": "certified",
        "pending_initial": "pending_initial",
        "revoked": "revoked",
        "superseded": "superseded",
        "validation_failed": "uncertified",
        "unvalidated": "uncertified",
    }.get(validation_status, "uncertified")


def validation_status_from_certification_status(certification_status: str) -> str:
    return {
        "certified": "validated",
        "certified_with_issues": "validated",
        "pending_initial": "pending_initial",
        "revoked": "revoked",
        "superseded": "superseded",
        "uncertified": "unvalidated",
    }.get(certification_status, "unvalidated")


def compat_validation_status_from_certification_status(
    certification_status: str,
) -> str:
    return {
        "uncertified": "unvalidated",
        "pending_initial": "pending_initial",
        "maintenance_due": "pending_maintenance",
        "maintenance_in_progress": "pending_maintenance",
        "certified": "validated",
        "certified_with_issues": "validated",
        "revoked": "validation_failed",
        "superseded": "superseded",
    }.get(certification_status, "unvalidated")


def expanded_validation_summary(summary: dict) -> dict:
    expanded = dict(summary)
    certification_status = expanded.get("certification_status")
    validation_status = expanded.get("validation_status")
    if certification_status is None and validation_status is not None:
        certification_status = certification_status_from_validation_status(
            str(validation_status)
        )
    if validation_status is None and certification_status is not None:
        validation_status = validation_status_from_certification_status(
            str(certification_status)
        )
    expanded["certification_status"] = certification_status or "uncertified"
    expanded["validation_status"] = validation_status or "unvalidated"
    expanded["latest_recommendation"] = expanded.get("latest_recommendation")
    expanded["critical_issue_count"] = int(expanded.get("critical_issue_count", 0))
    expanded["warning_issue_count"] = int(expanded.get("warning_issue_count", 0))
    expanded["maintenance_report_count"] = int(
        expanded.get("maintenance_report_count", 0)
    )
    return expanded


def validation_summary_for(
    validation_service,
    *,
    endpoint_id: str,
    configuration_hash: str | None,
) -> dict | None:
    if validation_service is None or configuration_hash is None:
        return None
    return expanded_validation_summary(
        validation_service.validation_summary(
            endpoint_id,
            configuration_hash=configuration_hash,
        )
    )


def response_validation_snapshot(snapshot) -> dict:
    payload = expanded_validation_summary(snapshot.model_dump(mode="json"))
    payload["validation_status"] = compat_validation_status_from_certification_status(
        str(payload["certification_status"])
    )
    payload["status"] = payload["validation_status"]
    return payload


def build_endpoint_validation_summary_payload(
    *,
    endpoint_id: str,
    validation_service,
    endpoint_service=None,
) -> dict:
    if endpoint_service is not None:
        endpoint = endpoint_service.get_endpoint(endpoint_id).endpoint
        return expanded_validation_summary(
            validation_service.validation_summary(
                endpoint_id,
                configuration_hash=endpoint.configuration_hash,
            )
        )
    return expanded_validation_summary(validation_service.validation_summary(endpoint_id))


def build_endpoint_validation_history_payload(
    *,
    endpoint_id: str,
    validation_service,
) -> dict:
    return validation_service.validation_history(endpoint_id)


def build_validation_request_payload(result) -> dict:
    return {
        "request": result.request.model_dump(mode="json"),
        "bond": result.bond.model_dump(mode="json"),
        "snapshot": response_validation_snapshot(result.snapshot),
    }


def build_validation_epoch_payload(result) -> dict:
    return {
        "epoch": result.epoch.model_dump(mode="json"),
        "assignments": [item.model_dump(mode="json") for item in result.assignments],
        "authorizations": [
            item.model_dump(mode="json") for item in result.authorizations
        ],
    }


def build_validation_report_payload(result) -> dict:
    return {
        "request": result.request.model_dump(mode="json"),
        "snapshot": response_validation_snapshot(result.snapshot),
        "report": result.report.model_dump(mode="json"),
    }


def build_validation_maintenance_payload(result) -> dict:
    return {
        "request": result.request.model_dump(mode="json"),
        "bond": result.bond.model_dump(mode="json"),
        "snapshot": response_validation_snapshot(result.snapshot),
        "report": result.report.model_dump(mode="json"),
    }


def build_publication_validation_payload(
    *,
    record,
    endpoint_id: str,
    endpoint_configuration_hash: str | None,
    validation_service,
    onboarding: dict | None,
) -> dict:
    validation_summary = None
    if validation_service is not None and endpoint_configuration_hash is not None:
        validation_summary = expanded_validation_summary(
            validation_service.validation_summary(
                endpoint_id,
                configuration_hash=endpoint_configuration_hash,
            )
        )
    return {
        "publication": record.model_dump(mode="json"),
        "validation_summary": validation_summary,
        "onboarding": onboarding,
    }


def build_endpoint_proof_payload(
    *,
    endpoint,
    node_id: str,
    local_publication_configuration_hash: str,
    publication_sync_status: str,
    validation_summary: dict | None,
    published_validation_summary: dict | None,
    current_publication,
) -> dict:
    return {
        "proof": {
            "endpoint_id": endpoint.endpoint_id,
            "node_id": node_id,
            "configuration_hash": endpoint.configuration_hash,
            "local_publication_configuration_hash": (
                local_publication_configuration_hash
            ),
            "publication_sync_status": publication_sync_status,
            "bundle_hash": endpoint.bundle_hash,
            "runtime_status": endpoint.status,
            "publication": endpoint.publication.model_dump(mode="json"),
            "validation_summary": validation_summary,
            "published_validation_summary": published_validation_summary,
            "current_publication": (
                current_publication.model_dump(mode="json")
                if current_publication is not None
                else None
            ),
        }
    }


def build_operator_endpoint_validation_payload(
    *,
    manifest,
    validation_service,
    published_endpoint_configuration_hash: str | None,
    current_publication,
) -> dict:
    validation_requested = bool(
        manifest.validation.enabled or manifest.publication.validation == "enabled"
    )
    validation_summary = (
        expanded_validation_summary(
            validation_service.validation_summary(
                manifest.endpoint_id,
                configuration_hash=manifest.configuration_hash,
            )
        )
        if validation_service is not None
        else None
    )
    published_validation_summary = (
        validation_summary_for(
            validation_service,
            endpoint_id=manifest.endpoint_id,
            configuration_hash=published_endpoint_configuration_hash,
        )
        if current_publication is not None
        else None
    )
    return {
        "validation_mode": "requested" if validation_requested else "disabled",
        "validation": manifest.validation.model_dump(mode="json"),
        "validation_summary": validation_summary,
        "published_validation_summary": published_validation_summary,
    }
