from __future__ import annotations

from uuid import uuid4

from aidn_hypervisor.bundle_hash import bundle_config_hash
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.endpoint_publications.models import PublishedEndpointConfiguration
from aidn_hypervisor.endpoint_publications.signing import (
    sign_consensus_bytes,
    verify_publication_signature,
)
from aidn_hypervisor.endpoints.models import (
    CreateEndpointCommand,
    UpdateEndpointCommand,
)
from aidn_hypervisor.runtime_parameter_policy import (
    normalize_runtime_parameter_policy,
    policy_json,
)


class RemoteEndpointServiceUnavailableError(RuntimeError):
    """Raised when proxy attachment is requested without remote endpoint support."""


class RemoteEndpointNotFoundError(KeyError):
    """Raised when the requested remote endpoint does not exist."""


class EndpointApplicationService:
    """Application-layer orchestration for endpoint write flows."""

    def __init__(
        self,
        *,
        endpoint_service,
        hypervisor_service=None,
        endpoint_publication_service=None,
        remote_endpoint_service=None,
        validation_service=None,
    ) -> None:
        self._endpoint_service = endpoint_service
        self._hypervisor_service = hypervisor_service
        self._endpoint_publication_service = endpoint_publication_service
        self._remote_endpoint_service = remote_endpoint_service
        self._validation_service = validation_service

    def create_endpoint(self, payload: dict) -> dict:
        command_data = dict(payload)
        runtime_binding_id = command_data.get("runtime_binding_id")
        if runtime_binding_id and self._hypervisor_service is not None:
            admission = self._hypervisor_service.runtime_binding_endpoint_admission(
                str(runtime_binding_id),
                endpoint_payload=command_data,
            )
            if not admission["ready"]:
                raise ValueError("endpoint_admission_blocked")
            compatibility_bundle = self._hypervisor_service.bundle_for_runtime_binding(
                str(runtime_binding_id)
            )
            # Runtime bindings identify the provider/model execution path, while
            # endpoint drafts may deliberately pin an immutable Bundle revision
            # (for example, a 128K context revision).  Historically we always
            # replaced the requested bundle with the compatibility projection,
            # silently pinning new endpoints to the old revision.  Once that
            # revision was retired, local-agent credentials started returning
            # ``Requested bundle is disabled`` even though the new runtime was
            # healthy.  Preserve an explicit revision after validating that it
            # belongs to this runtime binding's provider/model lineage.
            requested_bundle_id = str(command_data.get("bundle_id") or "").strip()
            selected_bundle = compatibility_bundle
            if requested_bundle_id and requested_bundle_id != compatibility_bundle.bundle_id:
                selected_bundle = self._bundle_for_runtime_binding_revision(
                    requested_bundle_id=requested_bundle_id,
                    compatibility_bundle=compatibility_bundle,
                )
                if selected_bundle is None:
                    raise ValueError("runtime_binding_bundle_mismatch")
            command_data["bundle_id"] = selected_bundle.bundle_id
            requested_bundle_hash = str(command_data.get("bundle_hash") or "").strip()
            selected_bundle_hash = selected_bundle.bundle_hash or (
                self._hypervisor_service.bundle_hash_for_runtime_binding(
                    str(runtime_binding_id)
                )
            )
            if (
                requested_bundle_hash
                and selected_bundle.bundle_hash
                and requested_bundle_hash != selected_bundle.bundle_hash
            ):
                raise ValueError("runtime_binding_bundle_hash_mismatch")
            command_data["bundle_hash"] = requested_bundle_hash or selected_bundle_hash
        elif self._hypervisor_service is not None and not command_data.get("bundle_hash"):
            bundle_id = str(command_data.get("bundle_id") or "")
            bundle = next(
                (
                    candidate
                    for candidate in self._hypervisor_service.bundle_config()
                    if candidate.bundle_id == bundle_id
                ),
                None,
            )
            if bundle is not None:
                command_data["bundle_hash"] = bundle.bundle_hash or bundle_config_hash(bundle)

        # Endpoint publication owns the consumer-facing copy of the runtime
        # contract.  Default it from the selected Bundle, while still allowing
        # the operator to submit an explicit value/toggle table before the
        # draft is created.
        bundle = self._bundle_for_command(command_data)
        if bundle is not None:
            selected_policy = command_data.get("runtime_parameter_policy")
            if not selected_policy:
                selected_policy = policy_json(bundle.runtime_parameter_policy)
            command_data["runtime_parameter_policy"] = policy_json(
                normalize_runtime_parameter_policy(bundle.provider_type, selected_policy)
            )

        command = CreateEndpointCommand(**command_data)
        created = self._endpoint_service.create_endpoint(command)
        onboarding = None
        if self._hypervisor_service is not None:
            onboarding = self._hypervisor_service.sync_operator_onboarding_state(
                endpoint_items=[
                    {
                        "endpoint_id": created.endpoint.endpoint_id,
                        "bundle_id": created.endpoint.bundle_id,
                        "publication_status": "configured",
                        "visibility": created.endpoint.publication.visibility,
                    }
                ]
            )
        return {
            "created": created,
            "onboarding": onboarding,
            "payload": {
                "endpoint": created.endpoint.model_dump(mode="json"),
                "snapshot": created.snapshot.model_dump(mode="json"),
                "onboarding": onboarding,
            },
        }

    def publish_endpoint(self, endpoint_id: str) -> dict:
        """Publish an Endpoint through the same canonical path as the operator UI.

        Endpoint publication is a wallet operation when CometBFT is enabled.
        Keeping this orchestration here lets MCP call the application boundary
        without duplicating a local-only ``store.append`` shortcut or exposing
        the wallet private key to the agent.
        """
        if (
            self._hypervisor_service is None
            or self._endpoint_service is None
            or self._endpoint_publication_service is None
        ):
            raise ValueError("Endpoint publication service is not configured")

        self._reconcile_remote_endpoint_publication(endpoint_id)
        wallet = self._hypervisor_service.owner_wallet_state()
        if not wallet.get("configured"):
            raise ValueError(
                "Owner wallet must be configured before publishing endpoint configuration"
            )
        record = self._endpoint_publication_service.prepare_configuration(
            endpoint_id=endpoint_id,
            owner_wallet=wallet["wallet_id"],
            owner_public_key=wallet.get("public_key"),
            node_id=self._hypervisor_service.node_id,
            wallet_private_key=self._hypervisor_service.owner_wallet_private_key(),
        )
        current = self._endpoint_publication_service.current_publication(endpoint_id)
        if current is not None and current.publication_id == record.publication_id:
            return {
                "status": "FINALIZED",
                "endpoint_id": endpoint_id,
                "publication": record.model_dump(mode="json"),
            }

        consensus = getattr(self._hypervisor_service, "consensus_service", None)
        if consensus is None or not getattr(consensus, "is_enabled", False):
            committed = self._endpoint_publication_service.commit_prepared_configuration(record)
            return {
                "status": "FINALIZED",
                "endpoint_id": endpoint_id,
                "publication": committed.model_dump(mode="json"),
            }

        identity_read = self._hypervisor_service.wallet_identity_read_model(record.owner_wallet)
        identity_source = str(identity_read.get("source") or "")
        canonical_identity_provider = getattr(
            self._hypervisor_service, "canonical_wallet_identity_provider", None
        )
        canonical_identity_query = getattr(consensus, "query_wallet_identity", None)
        canonical_identity_required = callable(canonical_identity_provider) or callable(
            canonical_identity_query
        )
        if canonical_identity_required and identity_read.get("identity") is None:
            if identity_read.get("error"):
                raise ValueError(
                    "canonical Wallet identity is unavailable; check the configured CometBFT RPC "
                    "before publishing"
                )
            raise ValueError(
                "Owner Wallet identity is not registered on the current canonical chain; "
                "open Wallet and click Register in network before publishing"
            )
        if canonical_identity_required and identity_source in {
            "local_projection",
            "local_projection_unverified",
        }:
            raise ValueError(
                "Wallet identity is available only in a local projection; register the Wallet "
                "in the current canonical network before publishing"
            )

        local_sequence = self._hypervisor_service.ledger_operation_service.wallet_next_sequence(
            record.owner_wallet
        )
        sequence_provider = getattr(
            self._hypervisor_service, "canonical_wallet_sequence_provider", None
        )
        query_sequence = getattr(consensus, "query_wallet_next_sequence", None)
        if callable(sequence_provider):
            try:
                canonical_sequence = int(sequence_provider(record.owner_wallet))
            except (RuntimeError, OSError, ValueError, TypeError) as error:
                raise ValueError(
                    f"canonical Wallet sequence is unavailable; check the configured CometBFT RPC ({error})"
                ) from error
        elif callable(query_sequence):
            canonical_sequence = query_sequence(record.owner_wallet)
            if canonical_sequence is None:
                raise ValueError(
                    "canonical Wallet sequence is unavailable; check the configured CometBFT RPC "
                    "and try again"
                )
        else:
            canonical_sequence = local_sequence
        if canonical_sequence is not None:
            if self._hypervisor_service.ledger_operation_service.reconcile_wallet_sequence(
                record.owner_wallet, canonical_sequence
            ):
                self._hypervisor_service._persist_state()
            local_sequence = canonical_sequence

        def build_envelope(
            publication_record: PublishedEndpointConfiguration,
            sequence: int,
            retry_nonce: str | None = None,
        ) -> LedgerOperationEnvelope:
            evidence = [
                publication_record.publication_id,
                publication_record.endpoint_id,
                publication_record.configuration_hash,
            ]
            if retry_nonce is not None:
                evidence.append(f"retry:{retry_nonce}")
            unsigned = LedgerOperationEnvelope(
                operation_type="ENDPOINT_PUBLISH",
                operation_version="1.0.0",
                protocol_version="0.1",
                origin_type="wallet",
                initiator_id=publication_record.endpoint_id,
                sender_wallet=publication_record.owner_wallet,
                sender_sequence=sequence,
                fee_payer=publication_record.owner_wallet,
                fee_class="standard",
                created_at=publication_record.published_at,
                payload={"publication": publication_record.model_dump(mode="json")},
                evidence_references=evidence,
                signatures=[],
            )
            signature = sign_consensus_bytes(
                private_key=self._hypervisor_service.owner_wallet_private_key(),
                payload=unsigned.signing_bytes(),
            )
            return unsigned.model_copy(update={"signatures": [signature]})

        candidates = [
            envelope
            for envelope in self._hypervisor_service.list_pending_consensus_envelopes()
            if envelope.operation_type == "ENDPOINT_PUBLISH"
            and envelope.payload.get("publication", {}).get("endpoint_id") == endpoint_id
            and envelope.payload.get("publication", {}).get("configuration_hash")
            == record.configuration_hash
        ]
        pending = next(
            (
                envelope
                for envelope in reversed(candidates)
                if envelope.sender_sequence == local_sequence
            ),
            None,
        )
        if pending is None:
            pending = build_envelope(record, local_sequence)
            self._hypervisor_service.stage_pending_consensus_envelope(pending)
        previous_submission = consensus.get_submission(pending.operation_id)
        if previous_submission is not None and previous_submission.status.value == "failed":
            pending = build_envelope(record, local_sequence, uuid4().hex)
            self._hypervisor_service.stage_pending_consensus_envelope(pending)
        submission = consensus.submit_operation(pending, retry_existing=True)
        if (
            submission.status.value == "failed"
            and "configuration_hash does not match canonical payload"
            in (submission.error or "")
        ):
            compatibility_record = self._endpoint_publication_service.legacy_compatible_configuration(
                record,
                wallet_private_key=self._hypervisor_service.owner_wallet_private_key(),
            )
            if compatibility_record.configuration_hash != record.configuration_hash:
                record = compatibility_record
                pending = build_envelope(record, local_sequence, uuid4().hex)
                self._hypervisor_service.stage_pending_consensus_envelope(pending)
                submission = consensus.submit_operation(pending, retry_existing=True)

        finality = self._hypervisor_service.ledger_operation_finality(pending.operation_id)
        if finality.get("consensus_finalized"):
            committed = self._endpoint_publication_service.commit_prepared_configuration(
                record,
                record_operations=False,
            )
            self._hypervisor_service.discard_pending_consensus_envelopes(pending.operation_id)
            self._hypervisor_service.discard_pending_consensus_operations(pending.operation_id)
            return {
                "status": "FINALIZED",
                "endpoint_id": endpoint_id,
                "publication": committed.model_dump(mode="json"),
                "consensus": {
                    "operation_id": pending.operation_id,
                    "submission": submission.status.value,
                    "finality": finality,
                },
            }
        if submission.status.value == "failed":
            raise ValueError(submission.error or "Consensus rejected Endpoint publication")
        return {
            "status": "CONSENSUS_PENDING",
            "endpoint_id": endpoint_id,
            "operation_id": pending.operation_id,
            "submission": submission.status.value,
            "publication": record.model_dump(mode="json"),
            "finality": finality,
        }

    def _reconcile_remote_endpoint_publication(self, endpoint_id: str) -> bool:
        if self._endpoint_publication_service is None:
            return False
        consensus = getattr(self._hypervisor_service, "consensus_service", None)
        query_publication = getattr(consensus, "query_endpoint_publication", None)
        if consensus is None or not getattr(consensus, "is_enabled", False) or not callable(
            query_publication
        ):
            return False
        payload = query_publication(endpoint_id)
        if payload is None:
            return False
        try:
            record = PublishedEndpointConfiguration.model_validate(payload)
            endpoint = self._endpoint_service.get_endpoint(endpoint_id).endpoint
            if record.endpoint_id != endpoint_id or record.owner_wallet != endpoint.owner_wallet:
                return False
            verify_publication_signature(
                public_key=record.owner_public_key,
                signature=record.wallet_signature,
                payload=record.signed_payload(),
            )
            current = self._endpoint_publication_service.current_publication(endpoint_id)
            if current is not None and current.publication_id == record.publication_id:
                return False
            self._endpoint_publication_service.commit_prepared_configuration(
                record,
                record_operations=False,
            )
            return True
        except (KeyError, TypeError, ValueError):
            return False

    def update_endpoint(self, endpoint_id: str, command: UpdateEndpointCommand) -> dict:
        if command.endpoint_id != endpoint_id:
            command = command.model_copy(update={"endpoint_id": endpoint_id})
        current = self._endpoint_service.get_endpoint(endpoint_id).endpoint
        if command.runtime_parameter_policy is not None:
            bundle = self._bundle_for_command(
                {"bundle_id": current.bundle_id, "runtime_binding_id": current.runtime_binding_id}
            )
            if bundle is not None:
                command = command.model_copy(
                    update={
                        "runtime_parameter_policy": normalize_runtime_parameter_policy(
                            bundle.provider_type,
                            policy_json(command.runtime_parameter_policy),
                        )
                    }
                )
        consensus = getattr(self._hypervisor_service, "consensus_service", None)
        if (
            consensus is not None
            and getattr(consensus, "is_validator", False)
            and self._endpoint_publication_service is not None
            and self._endpoint_publication_service.current_publication(endpoint_id)
            is not None
        ):
            raise ValueError(
                "published endpoint updates require a canonical consensus transition"
            )
        updated = self._endpoint_service.update_endpoint(command)
        self._supersede_validation_if_needed(
            endpoint_id=endpoint_id,
            previous_configuration_hash=current.configuration_hash,
            updated=updated,
        )
        return {
            "updated": updated,
            "payload": {
                "endpoint": updated.endpoint.model_dump(mode="json"),
                "snapshot": (
                    updated.snapshot.model_dump(mode="json")
                    if updated.snapshot is not None
                    else None
                ),
            },
        }

    def _bundle_for_command(self, command_data: dict):
        if self._hypervisor_service is None:
            return None
        runtime_binding_id = command_data.get("runtime_binding_id")
        if runtime_binding_id:
            try:
                requested_bundle_id = str(command_data.get("bundle_id") or "").strip()
                compatibility_bundle = self._hypervisor_service.bundle_for_runtime_binding(
                    str(runtime_binding_id)
                )
            except (KeyError, ValueError):
                return None
            if requested_bundle_id and requested_bundle_id != compatibility_bundle.bundle_id:
                selected_bundle = self._bundle_for_runtime_binding_revision(
                    requested_bundle_id=requested_bundle_id,
                    compatibility_bundle=compatibility_bundle,
                )
                if selected_bundle is not None:
                    return selected_bundle
            return compatibility_bundle
        bundle_id = str(command_data.get("bundle_id") or "")
        return next(
            (
                bundle
                for bundle in self._hypervisor_service.bundle_config()
                if bundle.bundle_id == bundle_id
            ),
            None,
        )

    def _bundle_for_runtime_binding_revision(
        self,
        *,
        requested_bundle_id: str,
        compatibility_bundle,
    ):
        """Resolve an enabled immutable revision for a Runtime Binding.

        A Bundle revision is safe to pin when it is enabled and describes the
        same provider/model/workload lineage as the binding compatibility
        projection.  The binding remains the execution identity; the revision
        only selects the operator-owned runtime contract.
        """
        try:
            candidates = self._hypervisor_service.bundle_config()
        except (AttributeError, KeyError, ValueError):
            return None
        for candidate in candidates:
            if candidate.bundle_id != requested_bundle_id or not candidate.enabled:
                continue
            same_lineage = all(
                getattr(candidate, field, None) == getattr(compatibility_bundle, field, None)
                for field in ("plugin_id", "provider_type", "workload_type", "model_id")
            )
            if not same_lineage:
                return None
            # A revision created from this compatibility bundle is the normal
            # case.  Accept a direct compatibility id as well, but never allow
            # a disabled or unrelated bundle to be smuggled into an endpoint.
            lineage_ids = {compatibility_bundle.bundle_id}
            current = candidate
            while getattr(current, "revision_of", None):
                parent_id = current.revision_of
                lineage_ids.add(parent_id)
                current = next(
                    (item for item in candidates if item.bundle_id == parent_id),
                    current,
                )
                if current.bundle_id == parent_id and not getattr(
                    current, "revision_of", None
                ):
                    break
            if (
                candidate.bundle_id == compatibility_bundle.bundle_id
                or compatibility_bundle.bundle_id in lineage_ids
            ):
                return candidate
        return None

    def delete_endpoint(self, endpoint_id: str) -> dict:
        """Soft-delete an Endpoint and schedule its report custody grace."""
        deleted = self._endpoint_service.delete_endpoint(endpoint_id)
        retirements = []
        if self._validation_service is not None:
            retirements = self._validation_service.request_endpoint_retirement(
                endpoint_id=endpoint_id,
            )
        return {
            "deleted": deleted,
            "retirements": retirements,
            "payload": {
                "endpoint": deleted.endpoint.model_dump(mode="json"),
                "custody_retirements": [
                    item.model_dump(mode="json") for item in retirements
                ],
            },
        }

    def attach_proxy_target(self, endpoint_id: str, remote_endpoint_id: str) -> dict:
        if self._remote_endpoint_service is None:
            raise RemoteEndpointServiceUnavailableError(
                "Remote endpoint service is not configured"
            )
        try:
            remote_endpoint = self._remote_endpoint_service.get_remote_endpoint(
                remote_endpoint_id
            )
        except KeyError as error:
            raise RemoteEndpointNotFoundError(remote_endpoint_id) from error
        current = self._endpoint_service.get_endpoint(endpoint_id).endpoint
        updated = self._endpoint_service.attach_proxy_target(
            endpoint_id, remote_endpoint
        )
        self._supersede_validation_if_needed(
            endpoint_id=endpoint_id,
            previous_configuration_hash=current.configuration_hash,
            updated=updated,
        )
        return {
            "updated": updated,
            "payload": {
                "endpoint": updated.endpoint.model_dump(mode="json"),
                "snapshot": (
                    updated.snapshot.model_dump(mode="json")
                    if updated.snapshot is not None
                    else None
                ),
            },
        }

    def detach_proxy_target(self, endpoint_id: str) -> dict:
        current = self._endpoint_service.get_endpoint(endpoint_id).endpoint
        updated = self._endpoint_service.detach_proxy_target(endpoint_id)
        self._supersede_validation_if_needed(
            endpoint_id=endpoint_id,
            previous_configuration_hash=current.configuration_hash,
            updated=updated,
        )
        return {
            "updated": updated,
            "payload": {
                "endpoint": updated.endpoint.model_dump(mode="json"),
                "snapshot": (
                    updated.snapshot.model_dump(mode="json")
                    if updated.snapshot is not None
                    else None
                ),
            },
        }

    def _supersede_validation_if_needed(
        self,
        *,
        endpoint_id: str,
        previous_configuration_hash: str,
        updated,
    ) -> None:
        if (
            self._validation_service is None
            or updated.snapshot is None
            or previous_configuration_hash == updated.endpoint.configuration_hash
        ):
            return
        self._validation_service.supersede_configuration(
            endpoint_id=endpoint_id,
            previous_configuration_hash=previous_configuration_hash,
            replacement_configuration_hash=updated.endpoint.configuration_hash,
            superseded_at=updated.snapshot.created_at,
        )
