from datetime import UTC, datetime
from uuid import uuid4

from aidn_hypervisor.endpoint_publications.models import (
    PublishedEndpointConfiguration,
    canonical_configuration_payload,
    configuration_hash_for_publication,
)
from aidn_hypervisor.endpoint_publications.signing import (
    public_key_for_private_key,
    sign_publication_payload,
)


class EndpointPublicationReadinessError(ValueError):
    def __init__(self, readiness: dict) -> None:
        self.readiness = readiness
        blocker_codes = ", ".join(
            blocker["code"] for blocker in readiness.get("blockers", [])
        )
        super().__init__(f"Endpoint publication is blocked: {blocker_codes}")


class EndpointPublicationService:
    def __init__(self, *, store, endpoint_service, operation_recorder=None) -> None:
        self.store = store
        self.endpoint_service = endpoint_service
        self.operation_recorder = operation_recorder

    def publish_configuration(
        self,
        *,
        endpoint_id: str,
        owner_wallet: str,
        owner_public_key: str | None = None,
        node_id: str,
        wallet_private_key: str,
    ) -> PublishedEndpointConfiguration:
        record = self.prepare_configuration(
            endpoint_id=endpoint_id,
            owner_wallet=owner_wallet,
            owner_public_key=owner_public_key,
            node_id=node_id,
            wallet_private_key=wallet_private_key,
        )
        return self.commit_prepared_configuration(record)

    def prepare_configuration(
        self,
        *,
        endpoint_id: str,
        owner_wallet: str,
        owner_public_key: str | None = None,
        node_id: str,
        wallet_private_key: str,
    ) -> PublishedEndpointConfiguration:
        """Build a signed publication without mutating the local read model.

        Validator-mode callers submit this exact record through consensus and
        commit it locally only after finality. Non-validator callers can use
        ``publish_configuration`` for the legacy immediate local path.
        """
        manifest = self.endpoint_service.get_endpoint(endpoint_id).endpoint
        readiness = self.publication_readiness(
            endpoint_id=endpoint_id,
            owner_wallet=owner_wallet,
            owner_public_key=owner_public_key,
            node_id=node_id,
            wallet_private_key=wallet_private_key,
        )
        if not readiness["ready"]:
            raise EndpointPublicationReadinessError(readiness)
        records = self.store.list_records()
        previous = self._current_publication_from_records(records, endpoint_id)
        execution_payload = self._execution_payload(manifest)
        payload = canonical_configuration_payload(
            bundle_hash=manifest.bundle_hash,
            model_class=manifest.model_class,
            capabilities=manifest.capabilities,
            runtime=manifest.runtime.model_dump(mode="json"),
            publication=manifest.publication.model_dump(mode="json"),
            pricing=manifest.pricing.model_dump(mode="json"),
            session=manifest.session.model_dump(mode="json"),
            execution=execution_payload,
            profile=manifest.profile.model_dump(mode="json"),
        )
        configuration_hash = configuration_hash_for_publication(payload)
        sequence = 1 if previous is None else previous.sequence + 1
        if (
            previous is not None
            and previous.configuration_hash == configuration_hash
            and owner_public_key is not None
        ):
            return previous
        record = PublishedEndpointConfiguration(
            publication_id=f"pub-{uuid4().hex[:12]}",
            endpoint_id=endpoint_id,
            owner_wallet=owner_wallet,
            owner_public_key=owner_public_key,
            node_id=node_id,
            configuration_hash=configuration_hash,
            previous_configuration_hash=(
                previous.configuration_hash if previous is not None else None
            ),
            bundle_id=manifest.bundle_id,
            bundle_hash=manifest.bundle_hash,
            model_class=manifest.model_class,
            capabilities=list(manifest.capabilities),
            profile=manifest.profile.model_dump(mode="json"),
            runtime=manifest.runtime.model_dump(mode="json"),
            publication=manifest.publication.model_dump(mode="json"),
            pricing=manifest.pricing.model_dump(mode="json"),
            session=manifest.session.model_dump(mode="json"),
            execution=execution_payload,
            validation_requirement=manifest.validation.model_dump(mode="json"),
            published_at=datetime.now(UTC).isoformat(),
            sequence=sequence,
            status="published",
            wallet_signature="",
        )
        if owner_public_key is not None:
            record.wallet_signature = sign_publication_payload(
                private_key=wallet_private_key,
                payload=record.signed_payload(),
            )
        else:
            # Legacy local callers remain readable, but their records are not
            # cryptographically publishable outside this Hypervisor.
            record.wallet_signature = f"legacy-unverified:{configuration_hash[:16]}"
        return record

    def commit_prepared_configuration(
        self,
        record: PublishedEndpointConfiguration,
        *,
        record_operations: bool | None = None,
    ) -> PublishedEndpointConfiguration:
        """Commit one prepared publication to the local projection.

        ``record_operations=False`` is used after a canonical
        ``ENDPOINT_PUBLISH`` finality proof. The consensus operation is then
        the only economic/publication authority; the local store is merely its
        read model.
        """
        records = self.store.list_records()
        existing_by_id = next(
            (
                existing
                for existing in records
                if existing.publication_id == record.publication_id
            ),
            None,
        )
        if existing_by_id is not None:
            if existing_by_id.model_dump(mode="json") != record.model_dump(mode="json"):
                raise ValueError("publication id is already bound to another record")
            return existing_by_id
        previous = self._current_publication_from_records(records, record.endpoint_id)
        if previous is None:
            if record.sequence != 1 or record.previous_configuration_hash is not None:
                raise ValueError("publication sequence does not start at one")
        else:
            if record.sequence != previous.sequence + 1:
                raise ValueError("publication sequence is not next after current record")
            if record.previous_configuration_hash != previous.configuration_hash:
                raise ValueError("publication previous configuration hash conflicts")
        if record_operations is None:
            record_operations = self.operation_recorder is not None
        if record_operations:
            self._record_advertisement_publish(
                record,
                previous_publication_id=(
                    previous.publication_id if previous is not None else None
                ),
            )
            self._record_offer_publish(record)
        if previous is None:
            self.store.append(record)
            return record

        updated_records = [
            existing.model_copy(update={"status": "superseded"})
            if existing.publication_id == previous.publication_id
            else existing
            for existing in records
        ]
        updated_records.append(record)
        self.store.replace_records(updated_records)
        return record

    def reconcile_canonical_publications(self, operations: list[dict]) -> list[str]:
        """Restore publication read models from applied Ledger operations.

        The publication store is a local projection. A snapshot write must not
        make a finalized ``ENDPOINT_PUBLISH`` disappear, so rebuild missing
        records from the canonical operation log without emitting a new
        operation.
        """
        reconciled: list[str] = []
        for operation in operations:
            if operation.get("operation_type") != "ENDPOINT_PUBLISH":
                continue
            result = operation.get("result")
            if not isinstance(result, dict) or result.get("status") != "applied":
                continue
            payload = operation.get("payload")
            publication_payload = payload.get("publication") if isinstance(payload, dict) else None
            if not isinstance(publication_payload, dict):
                continue
            record = PublishedEndpointConfiguration.model_validate(publication_payload)
            current = self.current_publication(record.endpoint_id)
            if current is not None and current.publication_id == record.publication_id:
                continue
            self.commit_prepared_configuration(record, record_operations=False)
            reconciled.append(record.publication_id)
        return reconciled

    def publication_readiness(
        self,
        *,
        endpoint_id: str,
        owner_wallet: str | None = None,
        owner_public_key: str | None = None,
        node_id: str | None = None,
        wallet_private_key: str | None = None,
    ) -> dict:
        manifest = self.endpoint_service.get_endpoint(endpoint_id).endpoint
        blockers: list[dict] = []
        warnings: list[dict] = []

        def block(code: str, message: str) -> None:
            blockers.append({"code": code, "message": message})

        def warn(code: str, message: str) -> None:
            warnings.append({"code": code, "message": message})

        external_access = (
            manifest.publication.accepts_external_requests
            or manifest.publication.visibility == "public"
        )
        pricing_configured = any(
            value is not None
            for value in (
                manifest.pricing.fixed_price,
                manifest.pricing.input_price,
                manifest.pricing.output_price,
                manifest.pricing.audio_input_second_price,
            )
        )
        paid_pricing = any(
            (value or 0) > 0
            for value in (
                manifest.pricing.fixed_price,
                manifest.pricing.input_price,
                manifest.pricing.output_price,
                manifest.pricing.audio_input_second_price,
            )
        )
        validation_requested = manifest.publication.validation == "enabled"
        validation_supported = (
            manifest.validation.enabled
            and manifest.validation.model_class_supported
            and manifest.validation.verification_status != "unsupported"
        )

        if not manifest.owner_wallet.strip():
            block(
                "ENDPOINT_OWNER_WALLET_REQUIRED",
                "Endpoint must declare an owner wallet before publication.",
            )
        if owner_wallet is not None and owner_wallet != manifest.owner_wallet:
            block(
                "ENDPOINT_PUBLICATION_OWNER_MISMATCH",
                "Publishing wallet must match the Endpoint owner wallet.",
            )
        if node_id is not None and not node_id.strip():
            block(
                "ENDPOINT_PUBLICATION_NODE_ID_REQUIRED",
                "A node identity is required for signed endpoint publication.",
            )
        if wallet_private_key is not None and not wallet_private_key.strip():
            block(
                "ENDPOINT_PUBLICATION_SIGNATURE_REQUIRED",
                "A wallet signing key is required for endpoint publication.",
            )
        if owner_public_key is not None and wallet_private_key is not None:
            try:
                derived_public_key = public_key_for_private_key(wallet_private_key)
            except ValueError as error:
                block("ENDPOINT_PUBLICATION_SIGNATURE_INVALID", str(error))
            else:
                if owner_public_key != derived_public_key:
                    block(
                        "ENDPOINT_PUBLICATION_SIGNER_MISMATCH",
                        "The signing key does not belong to the Endpoint owner wallet.",
                    )
        if manifest.publication.visibility == "private" and manifest.publication.accepts_external_requests:
            block(
                "ENDPOINT_PUBLICATION_POLICY_CONFLICT",
                "Private endpoints cannot accept external requests.",
            )
        if manifest.execution_strategy == "proxy" and manifest.proxy_target is None:
            block(
                "ENDPOINT_PROXY_TARGET_REQUIRED",
                "Proxy endpoints require a bound remote target before publication.",
            )
        if validation_requested and not validation_supported:
            block(
                "ENDPOINT_VALIDATION_POLICY_UNSUPPORTED",
                "Validation is enabled but the Endpoint validation profile is not ready.",
            )
        if external_access and not pricing_configured:
            warn(
                "ENDPOINT_PRICING_NOT_CONFIGURED",
                "External Endpoint publication has no explicit price; "
                "it will be treated as free until pricing is configured.",
            )
        if paid_pricing and manifest.session.minimum_deposit <= 0:
            warn(
                "ENDPOINT_MINIMUM_DEPOSIT_NOT_CONFIGURED",
                "Paid Endpoint publication has no minimum Session deposit policy.",
            )
        if manifest.publication.visibility == "public" and not manifest.publication.discoverable:
            warn(
                "ENDPOINT_PUBLIC_NOT_DISCOVERABLE",
                "Public Endpoint is signed but excluded from discovery.",
            )

        return {
            "endpoint_id": manifest.endpoint_id,
            "ready": not blockers,
            "blockers": blockers,
            "warnings": warnings,
            "dimensions": {
                "owner": {
                    "endpoint_owner_wallet": manifest.owner_wallet,
                    "publishing_wallet": owner_wallet,
                    "matches": owner_wallet is None or owner_wallet == manifest.owner_wallet,
                },
                "signature": {
                    "node_id_present": node_id is None or bool(node_id.strip()),
                    "signing_key_present": (
                        wallet_private_key is None or bool(wallet_private_key.strip())
                    ),
                    "owner_public_key": owner_public_key,
                    "cryptographic_signature": owner_public_key is not None,
                },
                "publication": {
                    "visibility": manifest.publication.visibility,
                    "discoverable": manifest.publication.discoverable,
                    "accepts_external_requests": manifest.publication.accepts_external_requests,
                    "external_access": external_access,
                },
                "pricing": {
                    "configured": pricing_configured,
                    "paid": paid_pricing,
                    "billing_unit": manifest.pricing.billing_unit,
                },
                "session": {
                    "minimum_deposit": manifest.session.minimum_deposit,
                    "maximum_session_duration_seconds": (
                        manifest.session.maximum_session_duration_seconds
                    ),
                    "max_concurrent_sessions": manifest.session.max_concurrent_sessions,
                    "queue_policy": manifest.session.queue_policy,
                },
                "validation": {
                    "requested": validation_requested,
                    "supported": validation_supported,
                    "verification_status": manifest.validation.verification_status,
                },
                "execution": {
                    "strategy": manifest.execution_strategy,
                    "proxy_target_bound": manifest.proxy_target is not None,
                },
            },
        }

    def current_publication(
        self, endpoint_id: str
    ) -> PublishedEndpointConfiguration | None:
        return self._current_publication_from_records(
            self.store.list_records(),
            endpoint_id,
        )

    def list_publications(
        self,
        *,
        endpoint_id: str | None = None,
    ) -> list[PublishedEndpointConfiguration]:
        records = self.store.list_records()
        if endpoint_id is None:
            return records
        return [record for record in records if record.endpoint_id == endpoint_id]

    def revoke_publication(
        self,
        endpoint_id: str,
    ) -> PublishedEndpointConfiguration:
        records = self.store.list_records()
        current = self._current_publication_from_records(records, endpoint_id)
        if current is None:
            raise ValueError(
                f"No active published configuration for endpoint: {endpoint_id}"
            )
        updated_records = [
            existing.model_copy(update={"status": "revoked"})
            if existing.publication_id == current.publication_id
            else existing
            for existing in records
        ]
        self.store.replace_records(updated_records)
        revoked = current.model_copy(update={"status": "revoked"})
        self._record_advertisement_withdraw(revoked)
        return revoked

    def _current_publication_from_records(
        self,
        records: list[PublishedEndpointConfiguration],
        endpoint_id: str,
    ) -> PublishedEndpointConfiguration | None:
        for record in reversed(records):
            if record.endpoint_id == endpoint_id and record.status == "published":
                return record
        return None

    def _execution_payload(self, manifest) -> dict:
        runtime_binding = {"runtime_binding_id": manifest.runtime_binding_id}
        if manifest.execution_strategy != "proxy" or manifest.proxy_target is None:
            return {"strategy": manifest.execution_strategy, **runtime_binding}
        fingerprint = configuration_hash_for_publication(
            {
                "remote_endpoint_id": manifest.proxy_target.remote_endpoint_id,
                "source_publication_id": manifest.proxy_target.source_publication_id,
                "source_configuration_hash": manifest.proxy_target.source_configuration_hash,
            }
        )
        return {
            "strategy": manifest.execution_strategy,
            "target_fingerprint": fingerprint,
            **runtime_binding,
        }

    def _record_advertisement_publish(
        self,
        record: PublishedEndpointConfiguration,
        *,
        previous_publication_id: str | None = None,
    ) -> None:
        if self.operation_recorder is None:
            return
        self.operation_recorder(
            operation_type="ENDPOINT_ADVERTISEMENT_PUBLISH",
            origin_type="wallet",
            fee_class="standard",
            initiator_id=record.owner_wallet,
            sender_wallet=record.owner_wallet,
            fee_payer=record.owner_wallet,
            payload={
                "advertisement_id": record.publication_id,
                "resource_type": "endpoint_configuration",
                "resource_id": record.endpoint_id,
                "owner_wallet": record.owner_wallet,
                "visibility": record.publication.get("visibility", "private"),
                "advertisement_version": record.sequence,
                "previous_advertisement_id": previous_publication_id,
                "content_hash": record.configuration_hash,
                "status": record.status,
            },
            created_at=record.published_at,
            emitted_events=["AdvertisementPublished"],
        )

    def _record_offer_publish(
        self,
        record: PublishedEndpointConfiguration,
    ) -> None:
        if self.operation_recorder is None:
            return
        self.operation_recorder(
            operation_type="ENDPOINT_OFFER_PUBLISH",
            origin_type="wallet",
            fee_class="standard",
            initiator_id=record.owner_wallet,
            sender_wallet=record.owner_wallet,
            fee_payer=record.owner_wallet,
            payload={
                "offer_id": f"offer-{record.publication_id}",
                "endpoint_id": record.endpoint_id,
                "advertisement_id": record.publication_id,
                "access_scope": record.publication.get("visibility", "private"),
                "configuration_hash": record.configuration_hash,
                "status": "active",
            },
            created_at=record.published_at,
            emitted_events=["EndpointOfferPublished"],
        )

    def _record_advertisement_withdraw(
        self,
        record: PublishedEndpointConfiguration,
    ) -> None:
        if self.operation_recorder is None:
            return
        self.operation_recorder(
            operation_type="ENDPOINT_ADVERTISEMENT_WITHDRAW",
            origin_type="wallet",
            fee_class="standard",
            initiator_id=record.owner_wallet,
            sender_wallet=record.owner_wallet,
            fee_payer=record.owner_wallet,
            payload={
                "advertisement_id": record.publication_id,
                "resource_type": "endpoint_configuration",
                "resource_id": record.endpoint_id,
                "owner_wallet": record.owner_wallet,
                "status": record.status,
            },
            created_at=datetime.now(UTC).isoformat(),
            emitted_events=["AdvertisementWithdrawn"],
        )
