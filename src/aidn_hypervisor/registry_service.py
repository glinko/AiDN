from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import time
from urllib import error as urllib_error, request as urllib_request

from aidn_hypervisor.registry_models import (
    RegistryConflictEvidence,
    RegistryCompletenessIssue,
    RegistryCompletenessIntegrity,
    RegistryCompletenessTotals,
    RegistryDiscoveryQuery,
    RegistryLocalCompletenessSummary,
    RegistryNodeAdvertisement,
    RegistryObjectQuery,
)


_REGISTRY_OBJECT_SNAPSHOT_SCHEMA_VERSION = "registry-object-store.v1"
_LOCAL_REGISTRY_COMPLETENESS_SUMMARY_VERSION = (
    "registry-local-completeness-summary.v1"
)
_REQUIRED_REGISTRY_OBJECT_FIELDS = (
    "object_id",
    "object_type",
    "object_version",
    "namespace",
    "payload_hash",
    "payload_encoding",
    "source_reference",
)


class RegistryService:
    def __init__(
        self,
        *,
        stale_grace_seconds: int = 30,
        snapshot_path: str | Path | None = None,
    ) -> None:
        self.stale_grace_seconds = stale_grace_seconds
        self._nodes: dict[str, dict] = {}
        self._registry_objects: dict[str, dict] = {}
        self._conflicts: dict[str, dict] = {}
        self._snapshot_path = Path(snapshot_path) if snapshot_path is not None else None
        self._load_registry_object_snapshot()

    def upsert_node(self, payload: RegistryNodeAdvertisement) -> dict:
        self._validate_wallet_identity_objects(
            payload.model_dump(mode="json").get("canonical_registry_objects", []),
            exclude_node_id=payload.node_id,
        )
        self._nodes[payload.node_id] = payload.model_dump(mode="json")
        return self.get_node(payload.node_id)

    def list_nodes(self) -> list[dict]:
        return [self.get_node(node_id) for node_id in sorted(self._nodes)]

    def list_conflicts(
        self,
        *,
        conflict_class: str | None = None,
        object_type: str | None = None,
        logical_key: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        items = []
        for conflict_id in sorted(self._conflicts):
            item = deepcopy(self._conflicts[conflict_id])
            if conflict_class is not None and item.get("conflict_class") != conflict_class:
                continue
            if object_type is not None and item.get("object_type") != object_type:
                continue
            if logical_key is not None and item.get("logical_key") != logical_key:
                continue
            items.append(item)
        return items[:limit]

    def list_wallet_identity_objects(self, *, limit: int = 500) -> list[dict]:
        return self.list_registry_objects(
            {
                "object_type": "wallet_identity",
                "namespace": "identity",
                "include_payload": True,
                "limit": limit,
            }
        )

    def export_wallet_identity_sync_state(self, *, limit: int = 500) -> dict:
        return {
            "objects": self.list_wallet_identity_objects(limit=limit),
            "conflicts": self.list_conflicts(
                conflict_class="wallet_identity_binding",
                object_type="wallet_identity",
                limit=limit,
            ),
        }

    def ingest_conflict_evidence(self, conflicts: list[dict]) -> list[dict]:
        accepted: list[dict] = []
        changed = False
        for item in conflicts:
            model = RegistryConflictEvidence.model_validate(item)
            if model.conflict_id in self._conflicts:
                continue
            self._conflicts[model.conflict_id] = model.model_dump(mode="json")
            accepted.append(deepcopy(self._conflicts[model.conflict_id]))
            changed = True
        if changed:
            self._persist_registry_object_snapshot()
        return accepted

    def import_wallet_identity_sync_state(
        self,
        *,
        objects: list[dict],
        conflicts: list[dict],
    ) -> dict:
        imported_objects = 0
        rejected_objects: list[dict] = []
        for item in objects:
            try:
                self.upsert_registry_object(item)
                imported_objects += 1
            except ValueError as error:
                rejected_objects.append(
                    {
                        "source_reference": item.get("source_reference"),
                        "object_id": item.get("object_id"),
                        "reason": str(error),
                    }
                )
        accepted_conflicts = self.ingest_conflict_evidence(conflicts)
        return {
            "imported_object_count": imported_objects,
            "rejected_objects": rejected_objects,
            "accepted_conflict_count": len(accepted_conflicts),
            "conflict_count": len(
                self.list_conflicts(
                    conflict_class="wallet_identity_binding",
                    object_type="wallet_identity",
                )
            ),
        }

    def sync_wallet_identity_from_peer(
        self,
        *,
        peer_base_url: str,
        limit: int = 500,
        timeout_seconds: int = 10,
    ) -> dict:
        normalized_base_url = peer_base_url.rstrip("/")
        request = urllib_request.Request(
            f"{normalized_base_url}/registry/wallet-identities/sync-state?limit={int(limit)}",
            method="GET",
        )
        try:
            with urllib_request.urlopen(request, timeout=timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib_error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise ValueError(
                f"Failed to sync wallet identities from peer {peer_base_url}"
            ) from error
        if not isinstance(payload, dict):
            raise ValueError(
                f"Peer wallet identity sync response from {peer_base_url} is invalid"
            )
        result = self.import_wallet_identity_sync_state(
            objects=list(payload.get("objects") or []),
            conflicts=list(payload.get("conflicts") or []),
        )
        result["peer_base_url"] = normalized_base_url
        return result

    def get_node(self, node_id: str) -> dict:
        record = deepcopy(self._nodes[node_id])
        if record.get("reputation") is None:
            record.pop("reputation", None)
        record["status"] = self._status_for(record)
        return record

    def upsert_registry_object(self, record: dict, *, persist: bool = True) -> dict:
        object_id = str(record["object_id"])
        normalized = deepcopy(record)
        self._validate_wallet_identity_objects([normalized])
        existing = self._registry_objects.get(object_id)
        if existing is not None and existing != normalized:
            raise ValueError(f"Conflicting registry object for {object_id}")
        self._registry_objects[object_id] = normalized
        if persist:
            try:
                self._persist_registry_object_snapshot()
            except Exception:
                if existing is None:
                    self._registry_objects.pop(object_id, None)
                else:
                    self._registry_objects[object_id] = existing
                raise
        return deepcopy(self._registry_objects[object_id])

    def ingest_registry_objects(self, records: list[dict]) -> list[dict]:
        previous_registry_objects = deepcopy(self._registry_objects)
        stored: list[dict] = []
        try:
            for record in records:
                stored.append(self.upsert_registry_object(record, persist=False))
            if stored:
                self._persist_registry_object_snapshot()
        except Exception:
            self._registry_objects = previous_registry_objects
            raise
        return stored

    def list_registry_objects(
        self, query: RegistryObjectQuery | dict | None = None
    ) -> list[dict]:
        if query is None:
            query_model = RegistryObjectQuery()
        elif isinstance(query, RegistryObjectQuery):
            query_model = query
        else:
            query_model = RegistryObjectQuery(**query)

        objects_by_id: dict[str, dict] = {}
        store_backed_object_ids: set[str] = set()
        node_backed_records: dict[str, dict] = {}
        for object_id in sorted(self._registry_objects):
            item = self._registry_objects[object_id]
            source = self._registry_object_source(item)
            if (
                query_model.node_id is not None
                and source.get("node_id") != query_model.node_id
            ):
                continue
            if (
                query_model.object_type is not None
                and item.get("object_type") != query_model.object_type
            ):
                continue
            if (
                query_model.namespace is not None
                and item.get("namespace") != query_model.namespace
            ):
                continue
            if (
                query_model.source_reference is not None
                and item.get("source_reference") != query_model.source_reference
            ):
                continue
            objects_by_id[object_id] = self._registry_object_row(
                item=item,
                include_payload=query_model.include_payload,
                source=source,
            )
            store_backed_object_ids.add(object_id)

        for node_id in self._nodes:
            node = self.get_node(node_id)
            if node["status"] == "offline":
                continue
            if node["status"] == "stale" and not query_model.include_stale:
                continue
            if query_model.node_id is not None and node["node_id"] != query_model.node_id:
                continue
            for item in node.get("canonical_registry_objects", []):
                if (
                    query_model.object_type is not None
                    and item.get("object_type") != query_model.object_type
                ):
                    continue
                if (
                    query_model.namespace is not None
                    and item.get("namespace") != query_model.namespace
                ):
                    continue
                if (
                    query_model.source_reference is not None
                    and item.get("source_reference") != query_model.source_reference
                ):
                    continue
                object_id = str(item["object_id"])
                if object_id in store_backed_object_ids:
                    if self._registry_object_records_conflict(
                        self._registry_objects[object_id],
                        item,
                    ):
                        raise ValueError(f"Conflicting registry object for {object_id}")
                    continue
                existing_item = node_backed_records.get(object_id)
                if existing_item is None:
                    node_backed_records[object_id] = deepcopy(item)
                elif self._registry_object_records_conflict(existing_item, item):
                    raise ValueError(f"Conflicting registry object for {object_id}")
                row = objects_by_id.get(object_id)
                source = {
                    "node_id": node["node_id"],
                    "operator_id": node["operator_id"],
                    "status": node["status"],
                }
                if row is None:
                    row = self._registry_object_row(
                        item=item,
                        include_payload=query_model.include_payload,
                        source=source,
                    )
                    objects_by_id[object_id] = row
                    continue
                if (
                    query_model.include_payload
                    and "payload" not in row
                    and item.get("payload") is not None
                ):
                    row["payload"] = deepcopy(item["payload"])
                if source not in row["sources"]:
                    row["sources"].append(source)
                    row["source_count"] = len(row["sources"])

        objects = sorted(
            objects_by_id.values(),
            key=lambda item: (
                item["object_type"],
                item["namespace"],
                item["source_reference"],
                item["object_id"],
            ),
        )
        return objects[: query_model.limit]

    def get_registry_object(self, object_id: str, *, include_payload: bool = False) -> dict:
        stored = self._registry_objects.get(object_id)
        item: dict | None = None
        if stored is not None:
            item = self._registry_object_row(
                item=stored,
                include_payload=include_payload,
                source=self._registry_object_source(stored),
            )
        else:
            for candidate in self.list_registry_objects(
                query={
                    "limit": RegistryObjectQuery.model_fields["limit"].default,
                    "include_payload": include_payload,
                }
            ):
                if candidate["object_id"] == object_id:
                    item = candidate
                    break
        if item is not None:
            if stored is None:
                return item

        # Scan node-backed compatibility objects directly so lookups are not limited by list pagination.
        for node_id in self._nodes:
            node = self.get_node(node_id)
            if node["status"] == "offline":
                continue
            if node["status"] == "stale":
                continue
            for candidate in node.get("canonical_registry_objects", []):
                if str(candidate["object_id"]) != object_id:
                    continue
                if stored is not None:
                    if self._registry_object_records_conflict(stored, candidate):
                        raise ValueError(f"Conflicting registry object for {object_id}")
                    continue
                source = {
                    "node_id": node["node_id"],
                    "operator_id": node["operator_id"],
                    "status": node["status"],
                }
                if item is None:
                    item = self._registry_object_row(
                        item=candidate,
                        include_payload=include_payload,
                        source=source,
                    )
                    continue
                if self._registry_object_records_conflict(
                    self._registry_object_record_from_row(item),
                    candidate,
                ):
                    raise ValueError(f"Conflicting registry object for {object_id}")
                if include_payload and "payload" not in item and candidate.get("payload") is not None:
                    item["payload"] = deepcopy(candidate["payload"])
                if source not in item["sources"]:
                    item["sources"].append(source)
                    item["source_count"] = len(item["sources"])
        if item is not None:
            return item
        raise KeyError(object_id)

    def resolve_wallet_identity(self, wallet_id: str) -> dict | None:
        matches = self._wallet_identity_matches(wallet_id)
        if not matches:
            return None
        unique_records = {
            (
                str(item["object_id"]),
                str(item["payload_hash"]),
            ): item
            for item in matches
        }
        if len(unique_records) > 1:
            raise ValueError(
                f"Conflicting wallet identity objects found for {wallet_id}"
            )
        record = next(iter(unique_records.values()))
        payload = record.get("payload")
        if not isinstance(payload, dict):
            raise ValueError(
                f"Canonical wallet identity object for {wallet_id} has no payload"
            )
        registry_sources: list[dict] = []
        for item in sorted(
            matches,
            key=lambda candidate: (
                str(candidate.get("_source", {}).get("node_id") or ""),
                str(candidate.get("_source", {}).get("operator_id") or ""),
            ),
        ):
            source = {
                "node_id": item.get("_source", {}).get("node_id"),
                "operator_id": item.get("_source", {}).get("operator_id"),
                "status": item.get("_source", {}).get("status") or "stored",
            }
            if source not in registry_sources:
                registry_sources.append(source)
        return {
            "wallet_id": str(payload["wallet_id"]),
            "public_key": str(payload["public_key"]),
            "registration_nonce": str(payload["registration_nonce"]),
            "registered_at": None,
            "identity_source": "registry_object",
            "registry_object_id": str(record["object_id"]),
            "registry_sources": registry_sources,
        }

    def discover(self, query: RegistryDiscoveryQuery) -> dict:
        matched_nodes: list[dict] = []
        canonical_candidates_by_node: dict[str, list[dict]] = {}
        use_legacy_filters = self._uses_legacy_filters(query)
        use_canonical_filters = self._uses_canonical_filters(query)
        for node_id in self._nodes:
            node = self.get_node(node_id)
            if node["status"] == "offline":
                continue
            if node["status"] == "stale" and not query.include_stale:
                continue
            if (
                query.can_host_custom_model is not None
                and node["can_host_custom_model"] != query.can_host_custom_model
            ):
                continue
            if query.min_rating is not None and self._node_rating_score(node) < query.min_rating:
                continue
            if (
                query.max_input_price_q_per_1kk is not None
                and node["pricing"]["input"] > query.max_input_price_q_per_1kk
            ):
                continue
            if (
                query.max_output_price_q_per_1kk is not None
                and node["pricing"]["output"] > query.max_output_price_q_per_1kk
            ):
                continue

            bundles = [
                bundle for bundle in node["bundles"] if self._bundle_matches(bundle, query)
            ]
            canonical_candidates = self._flatten_canonical_candidates_for_node(node)
            if use_canonical_filters:
                canonical_candidates = [
                    candidate
                    for candidate in canonical_candidates
                    if self._canonical_candidate_matches(candidate=candidate, query=query)
                ]

            has_legacy_matches = bool(bundles)
            has_canonical_matches = bool(canonical_candidates)
            if use_legacy_filters and use_canonical_filters:
                if not has_legacy_matches or not has_canonical_matches:
                    continue
            elif use_canonical_filters:
                if not has_canonical_matches:
                    continue
            elif not has_legacy_matches:
                continue
            node["bundles"] = bundles
            matched_nodes.append(node)
            canonical_candidates_by_node[node["node_id"]] = canonical_candidates

        matched_nodes.sort(
            key=lambda node: (
                {"ready": 0, "stale": 1, "offline": 2}[node["status"]],
                -self._node_rating_score(node),
                node["pricing"]["input"],
                node["pricing"]["output"],
                -datetime.fromisoformat(node["heartbeat_at"]).timestamp(),
            )
        )
        nodes = matched_nodes[: query.limit]
        canonical_candidates: list[dict] = []
        for node in nodes:
            canonical_candidates.extend(canonical_candidates_by_node.get(node["node_id"], []))
        canonical_candidates.sort(key=self._canonical_candidate_sort_key)
        return {
            "query": query.model_dump(mode="json"),
            "nodes": nodes,
            "candidates": self._flatten_candidates(nodes),
            "canonical_candidates": canonical_candidates,
        }

    def get_local_registry_completeness_summary(self) -> RegistryLocalCompletenessSummary:
        by_namespace: dict[str, int] = {}
        by_object_type: dict[str, int] = {}
        payload_object_count = 0
        payload_bytes_total = 0
        payload_hash_coverage_count = 0
        issues: list[RegistryCompletenessIssue] = []

        for object_id in sorted(self._registry_objects):
            record = self._registry_objects[object_id]
            if not isinstance(record, dict):
                raise ValueError(
                    f"Registry object store contains non-object record for {object_id}"
                )

            issues.extend(
                self._registry_object_summary_issues(object_id=object_id, record=record)
            )

            namespace = record.get("namespace")
            if isinstance(namespace, str) and namespace:
                by_namespace[namespace] = by_namespace.get(namespace, 0) + 1

            object_type = record.get("object_type")
            if isinstance(object_type, str) and object_type:
                by_object_type[object_type] = by_object_type.get(object_type, 0) + 1

            payload_hash = record.get("payload_hash")
            if isinstance(payload_hash, str) and payload_hash:
                payload_hash_coverage_count += 1

            if record.get("payload") is not None:
                payload_object_count += 1
                payload_bytes_total += self._payload_size_bytes(record["payload"])

        return RegistryLocalCompletenessSummary(
            summary_version=_LOCAL_REGISTRY_COMPLETENESS_SUMMARY_VERSION,
            generated_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            snapshot_schema_version=_REGISTRY_OBJECT_SNAPSHOT_SCHEMA_VERSION,
            store_totals=RegistryCompletenessTotals(
                total_object_count=len(self._registry_objects),
                payload_object_count=payload_object_count,
                payload_bytes_total=payload_bytes_total,
            ),
            by_namespace=by_namespace,
            by_object_type=by_object_type,
            integrity=RegistryCompletenessIntegrity(
                object_count_matches_store=True,
                all_object_ids_unique=True,
                all_required_fields_present=not any(
                    issue.code == "missing_required_field" for issue in issues
                ),
                payload_hash_coverage_count=payload_hash_coverage_count,
                issues=issues,
            ),
        )

    def _registry_object_summary_issues(
        self,
        *,
        object_id: str,
        record: dict,
    ) -> list[RegistryCompletenessIssue]:
        issues: list[RegistryCompletenessIssue] = []
        for field in _REQUIRED_REGISTRY_OBJECT_FIELDS:
            value = record.get(field)
            if value is None or (isinstance(value, str) and not value):
                issues.append(
                    RegistryCompletenessIssue(
                        code="missing_required_field",
                        object_id=object_id,
                        field=field,
                        detail=f"Stored record is missing required field {field}",
                    )
                )
        return issues

    def _payload_size_bytes(self, payload: object) -> int:
        return len(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        )

    def _flatten_candidates(self, nodes: list[dict]) -> list[dict]:
        candidates: list[dict] = []
        for node in nodes:
            for bundle in node["bundles"]:
                candidates.append(
                    {
                        "node_id": node["node_id"],
                        "operator_id": node["operator_id"],
                        "status": node["status"],
                        "base_url": node["base_url"],
                        "resources": node["resources"],
                        "can_host_custom_model": node["can_host_custom_model"],
                        "pricing": node["pricing"],
                        "rating": node["rating"],
                        "bundle_id": bundle["bundle_id"],
                        "plugin_id": bundle["plugin_id"],
                        "provider_type": bundle["provider_type"],
                        "model_id": bundle["model_id"],
                        "workload_type": bundle["workload_type"],
                        "endpoint": bundle["endpoint"],
                        "endpoint_ready": self._bundle_endpoint_ready(bundle),
                        "supports_allocation": bundle["supports_allocation"],
                        "supports_queue": bundle["supports_queue"],
                    }
                )
                if node.get("reputation") is not None:
                    candidates[-1]["reputation"] = node["reputation"]
        candidates.sort(key=self._candidate_sort_key)
        return candidates

    def _registry_object_row(self, *, item: dict, include_payload: bool, source: dict) -> dict:
        row = {
            "object_id": str(item["object_id"]),
            "object_type": item["object_type"],
            "object_version": item["object_version"],
            "namespace": item["namespace"],
            "payload_hash": item["payload_hash"],
            "payload_encoding": item["payload_encoding"],
            "source_reference": item["source_reference"],
            "source_count": 1,
            "sources": [deepcopy(source)],
        }
        if include_payload and item.get("payload") is not None:
            row["payload"] = deepcopy(item["payload"])
        return row

    def _registry_object_source(self, item: dict) -> dict:
        source = item.get("_source")
        if isinstance(source, dict):
            return {
                "node_id": source.get("node_id"),
                "operator_id": source.get("operator_id"),
                "status": source.get("status") or "stored",
            }
        return {"node_id": None, "operator_id": None, "status": "stored"}

    def _registry_object_record_from_row(self, row: dict) -> dict:
        record = {
            "object_id": row["object_id"],
            "object_type": row["object_type"],
            "object_version": row["object_version"],
            "namespace": row["namespace"],
            "payload_hash": row["payload_hash"],
            "payload_encoding": row["payload_encoding"],
            "source_reference": row["source_reference"],
        }
        if "payload" in row:
            record["payload"] = deepcopy(row["payload"])
        return record

    def _registry_object_records_conflict(self, left: dict, right: dict) -> bool:
        for field in (
            "object_type",
            "object_version",
            "namespace",
            "payload_hash",
            "payload_encoding",
            "source_reference",
        ):
            if left.get(field) != right.get(field):
                return True
        if "payload" in left and "payload" in right and left.get("payload") != right.get("payload"):
            return True
        return False

    def _record_conflict_evidence(
        self,
        *,
        conflict_class: str,
        object_type: str,
        namespace: str,
        logical_key: str,
        existing_record: dict,
        conflicting_record: dict,
    ) -> None:
        conflict_payload = {
            "conflict_class": conflict_class,
            "object_type": object_type,
            "namespace": namespace,
            "logical_key": logical_key,
            "existing_object_id": existing_record.get("object_id"),
            "existing_payload_hash": existing_record.get("payload_hash"),
            "conflicting_object_id": conflicting_record.get("object_id"),
            "conflicting_payload_hash": conflicting_record.get("payload_hash"),
        }
        encoded = json.dumps(
            conflict_payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        conflict_id = f"sha256:{hashlib.sha256(encoded).hexdigest()}"
        if conflict_id in self._conflicts:
            return
        self._conflicts[conflict_id] = RegistryConflictEvidence(
            conflict_id=conflict_id,
            conflict_class=conflict_class,
            object_type=object_type,
            namespace=namespace,
            logical_key=logical_key,
            existing_record=deepcopy(existing_record),
            conflicting_record=deepcopy(conflicting_record),
            observed_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        ).model_dump(mode="json")
        self._persist_registry_object_snapshot()

    def _wallet_identity_matches(self, wallet_id: str) -> list[dict]:
        matches: list[dict] = []
        for object_id in sorted(self._registry_objects):
            record = self._registry_objects[object_id]
            if self._wallet_identity_record_key(record) != wallet_id:
                continue
            matches.append(deepcopy(record))
        for node_id in sorted(self._nodes):
            node = self._nodes[node_id]
            for record in node.get("canonical_registry_objects", []):
                if self._wallet_identity_record_key(record) != wallet_id:
                    continue
                candidate = deepcopy(record)
                candidate["_source"] = {
                    "node_id": node.get("node_id"),
                    "operator_id": node.get("operator_id"),
                    "status": self._status_for(node),
                }
                matches.append(candidate)
        return matches

    def _wallet_identity_record_key(self, record: dict) -> str | None:
        if record.get("object_type") != "wallet_identity":
            return None
        if record.get("namespace") != "identity":
            return None
        source_reference = record.get("source_reference")
        if not isinstance(source_reference, str) or not source_reference:
            return None
        return source_reference

    def _validate_wallet_identity_objects(
        self,
        records: list[dict],
        *,
        exclude_node_id: str | None = None,
    ) -> None:
        seen_by_wallet: dict[str, dict] = {}
        for record in records:
            wallet_id = self._wallet_identity_record_key(record)
            if wallet_id is None:
                continue
            candidate = deepcopy(record)
            if exclude_node_id is not None:
                candidate["_source"] = {
                    "node_id": exclude_node_id,
                    "operator_id": None,
                    "status": "pending",
                }
            existing_seen = seen_by_wallet.get(wallet_id)
            if existing_seen is not None:
                if (
                    existing_seen.get("payload_hash") != candidate.get("payload_hash")
                    or existing_seen.get("object_id") != candidate.get("object_id")
                ):
                    self._record_conflict_evidence(
                        conflict_class="wallet_identity_binding",
                        object_type="wallet_identity",
                        namespace="identity",
                        logical_key=wallet_id,
                        existing_record=existing_seen,
                        conflicting_record=candidate,
                    )
                    raise ValueError(
                        f"Conflicting wallet identity objects found for {wallet_id}"
                    )
            else:
                seen_by_wallet[wallet_id] = candidate
            payload_hash = record.get("payload_hash")
            object_id = record.get("object_id")
            for existing in self._wallet_identity_matches(wallet_id):
                source_node_id = existing.get("_source", {}).get("node_id")
                if exclude_node_id is not None and source_node_id == exclude_node_id:
                    continue
                if (
                    existing.get("payload_hash") != payload_hash
                    or existing.get("object_id") != object_id
                ):
                    self._record_conflict_evidence(
                        conflict_class="wallet_identity_binding",
                        object_type="wallet_identity",
                        namespace="identity",
                        logical_key=wallet_id,
                        existing_record=existing,
                        conflicting_record=candidate,
                    )
                    raise ValueError(
                        f"Conflicting wallet identity objects found for {wallet_id}"
                    )

    def _load_registry_object_snapshot(self) -> None:
        if self._snapshot_path is None or not self._snapshot_path.exists():
            return
        try:
            snapshot = json.loads(self._snapshot_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Malformed registry object snapshot: {self._snapshot_path}"
            ) from exc
        if not isinstance(snapshot, dict):
            raise ValueError("Registry object snapshot must be a JSON object")

        schema_version = snapshot.get("schema_version")
        if schema_version != _REGISTRY_OBJECT_SNAPSHOT_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported registry object snapshot schema version: {schema_version}"
            )

        objects = snapshot.get("objects")
        if not isinstance(objects, list):
            raise ValueError("Registry object snapshot must contain an objects list")

        conflicts = snapshot.get("conflicts", [])
        if not isinstance(conflicts, list):
            raise ValueError("Registry object snapshot conflicts must be a list")

        for index, record in enumerate(objects):
            if not isinstance(record, dict):
                raise ValueError(
                    f"Registry object snapshot contains invalid object entry at index {index}"
                )
            try:
                self.upsert_registry_object(record, persist=False)
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(
                    f"Registry object snapshot contains invalid object entry at index {index}"
                ) from exc
        for index, conflict in enumerate(conflicts):
            if not isinstance(conflict, dict):
                raise ValueError(
                    f"Registry object snapshot contains invalid conflict entry at index {index}"
                )
            model = RegistryConflictEvidence.model_validate(conflict)
            self._conflicts[model.conflict_id] = model.model_dump(mode="json")

    def _persist_registry_object_snapshot(self) -> None:
        if self._snapshot_path is None:
            return
        self._snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot = {
            "schema_version": _REGISTRY_OBJECT_SNAPSHOT_SCHEMA_VERSION,
            "objects": [
                deepcopy(self._registry_objects[object_id])
                for object_id in sorted(self._registry_objects)
            ],
            "conflicts": [
                deepcopy(self._conflicts[conflict_id])
                for conflict_id in sorted(self._conflicts)
            ],
        }
        temp_path = self._snapshot_path.with_suffix(self._snapshot_path.suffix + ".tmp")
        temp_path.write_text(
            json.dumps(snapshot, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        temp_path.replace(self._snapshot_path)

    def _status_for(self, record: dict) -> str:
        heartbeat = datetime.fromisoformat(record["heartbeat_at"]).timestamp()
        ttl = int(record["heartbeat_ttl_seconds"])
        age = time.time() - heartbeat
        if age <= ttl:
            return "ready"
        if age <= ttl + self.stale_grace_seconds:
            return "stale"
        return "offline"

    def _bundle_matches(self, bundle: dict, query: RegistryDiscoveryQuery) -> bool:
        if query.workload_type is not None and bundle["workload_type"] != query.workload_type:
            return False
        if query.provider_type is not None and bundle["provider_type"] != query.provider_type:
            return False
        if query.bundle_id is not None and bundle["bundle_id"] != query.bundle_id:
            return False
        if query.model_id is not None and query.model_id.lower() not in bundle["model_id"].lower():
            return False
        if query.require_allocation_support and not bundle["supports_allocation"]:
            return False
        if query.require_queue_support and not bundle["supports_queue"]:
            return False
        if query.ready_endpoint_only and not self._bundle_endpoint_ready(bundle):
            return False
        return True

    def _uses_canonical_filters(self, query: RegistryDiscoveryQuery) -> bool:
        return any(
            value is not None
            for value in (
                query.capability_id,
                query.runtime_id,
                query.advertisement_resource_type,
                query.visibility,
                query.owner_wallet,
            )
        )

    def _uses_legacy_filters(self, query: RegistryDiscoveryQuery) -> bool:
        return any(
            value is not None
            for value in (
                query.workload_type,
                query.provider_type,
                query.model_id,
                query.bundle_id,
            )
        ) or query.require_allocation_support or query.require_queue_support or query.ready_endpoint_only

    def _bundle_endpoint_ready(self, bundle: dict) -> bool:
        return bool(bundle.get("enabled")) and bundle.get("status") == "ready" and bool(
            bundle.get("endpoint")
        )

    def _flatten_canonical_candidates_for_node(self, node: dict) -> list[dict]:
        candidates: list[dict] = []
        runtimes_by_id = {}
        runtimes_by_capability: dict[str, list[dict]] = {}
        for runtime in node.get("canonical_capability_runtimes", []):
            runtimes_by_id[runtime["runtime_id"]] = runtime
            runtimes_by_capability.setdefault(runtime["capability_id"], []).append(runtime)
        compatibility_by_capability: dict[str, list[dict]] = {}
        compatibility_by_runtime_id: dict[str, list[dict]] = {}
        for item in node.get("canonical_compute_compatibility", []):
            compatibility_by_capability.setdefault(item["canonical_capability_id"], []).append(item)
            compatibility_by_runtime_id.setdefault(item["canonical_runtime_id"], []).append(item)
        for advertisement in node.get("canonical_advertisements", []):
            service_id = self._service_id_for_advertisement(advertisement=advertisement)
            capability_id = advertisement.get("capability_id")
            runtime_rows = (
                runtimes_by_capability.get(capability_id, [])
                if capability_id is not None
                else []
            )
            emitted = False
            for runtime in runtime_rows:
                compatibility_rows = compatibility_by_runtime_id.get(runtime["runtime_id"]) or [None]
                for compatibility in compatibility_rows:
                    candidates.append(
                        self._canonical_candidate_row(
                            node=node,
                            advertisement=advertisement,
                            service_id=service_id,
                            capability_id=capability_id,
                            runtime=runtime,
                            compatibility=compatibility,
                        )
                    )
                emitted = True

            if emitted:
                continue

            compatibility_rows = (
                compatibility_by_capability.get(capability_id, [])
                if capability_id is not None
                else []
            )
            for compatibility in compatibility_rows:
                candidates.append(
                    self._canonical_candidate_row(
                        node=node,
                        advertisement=advertisement,
                        service_id=service_id,
                        capability_id=capability_id,
                        runtime=runtimes_by_id.get(compatibility.get("canonical_runtime_id"), {}),
                        compatibility=compatibility,
                    )
                )
                emitted = True

            if not emitted:
                candidates.append(
                    self._canonical_candidate_row(
                        node=node,
                        advertisement=advertisement,
                        service_id=service_id,
                        capability_id=capability_id,
                        runtime={},
                        compatibility=None,
                    )
                )
        return candidates

    def _canonical_candidate_row(
        self,
        *,
        node: dict,
        advertisement: dict,
        service_id: str,
        capability_id: str | None,
        runtime: dict,
        compatibility: dict | None,
    ) -> dict:
        runtime_id = runtime.get("runtime_id")
        if runtime_id is None and compatibility is not None:
            runtime_id = compatibility.get("canonical_runtime_id")
        row = {
            "node_id": node["node_id"],
            "operator_id": node["operator_id"],
            "base_url": node["base_url"],
            "status": node["status"],
            "service_id": service_id,
            "capability_id": capability_id,
            "capability_version": advertisement.get("capability_version"),
            "runtime_id": runtime_id,
            "advertisement_id": advertisement["advertisement_id"],
            "offer_id": advertisement.get("offer_id"),
            "capability_definition_hash": advertisement.get("capability_definition_hash"),
            "feature_profile_hash": advertisement.get("feature_profile_hash"),
            "limit_profile_hash": advertisement.get("limit_profile_hash"),
            "implementation_profile_hash": advertisement.get(
                "implementation_profile_hash"
            ),
            "resource_type": advertisement["resource_type"],
            "visibility": advertisement["visibility"],
            "owner_wallet": advertisement.get("owner_wallet"),
            "pricing": node["pricing"],
            "rating": node["rating"],
            "can_host_custom_model": node["can_host_custom_model"],
            "published_endpoint_count": len(node.get("published_endpoints", [])),
            "trust_summary": self._canonical_trust_summary(node),
            "legacy_bundle_id": (
                compatibility.get("legacy_bundle_id") if compatibility is not None else None
            ),
            "legacy_plugin_id": (
                compatibility.get("legacy_plugin_id") if compatibility is not None else None
            ),
            "legacy_provider_type": (
                compatibility.get("legacy_provider_type")
                if compatibility is not None
                else None
            ),
        }
        if node.get("reputation") is not None:
            row["reputation"] = node["reputation"]
        return row

    def _service_id_for_advertisement(self, *, advertisement: dict) -> str:
        resource_type = advertisement.get("resource_type")
        if resource_type == "registry_service":
            return "registry"
        if resource_type == "validation_service":
            return "validation"
        if resource_type == "consensus_service":
            return "consensus"
        return "compute"

    def _canonical_candidate_matches(
        self,
        *,
        candidate: dict,
        query: RegistryDiscoveryQuery,
    ) -> bool:
        if query.capability_id is not None and candidate.get("capability_id") != query.capability_id:
            return False
        if (
            query.advertisement_resource_type is not None
            and candidate.get("resource_type") != query.advertisement_resource_type
        ):
            return False
        if query.visibility is not None and candidate.get("visibility") != query.visibility:
            return False
        if (
            query.owner_wallet is not None
            and candidate.get("owner_wallet") != query.owner_wallet
        ):
            return False
        if query.runtime_id is not None and candidate.get("runtime_id") != query.runtime_id:
            return False
        return True

    def _canonical_trust_summary(self, node: dict) -> dict:
        published_endpoints = node.get("published_endpoints", [])
        validation_by_status: dict[str, int] = {}
        publication_by_status: dict[str, int] = {}
        certified_count = 0
        certified_with_issues_count = 0
        validated_count = 0
        pending_count = 0
        attention_count = 0
        in_sync_count = 0
        drift_count = 0

        for item in published_endpoints:
            validation_summary = item.get("published_validation_summary", {}) or {}
            certification_status = validation_summary.get("certification_status")
            validation_status = validation_summary.get("validation_status", "unknown")
            publication_status = item.get("publication_sync_status") or "unknown"
            validation_by_status[validation_status] = (
                validation_by_status.get(validation_status, 0) + 1
            )
            publication_by_status[publication_status] = (
                publication_by_status.get(publication_status, 0) + 1
            )

            if certification_status == "certified":
                certified_count += 1
            elif certification_status == "certified_with_issues":
                certified_with_issues_count += 1
            elif certification_status in {
                "pending_initial",
                "maintenance_in_progress",
                "maintenance_due",
                "uncertified",
            }:
                pending_count += 1
            elif certification_status not in {None, "superseded"}:
                attention_count += 1
            elif validation_status == "validated":
                validated_count += 1
            elif validation_status in {"pending_initial", "pending_maintenance", "unvalidated"}:
                pending_count += 1
            elif validation_status not in {"unknown"}:
                attention_count += 1

            if publication_status == "in_sync":
                in_sync_count += 1
            elif publication_status in {
                "local_changes_not_published",
                "published_configuration_not_served",
            }:
                drift_count += 1

        return {
            "total_endpoints": len(published_endpoints),
            "certified_count": certified_count,
            "certified_with_issues_count": certified_with_issues_count,
            "validated_count": certified_count + certified_with_issues_count + validated_count,
            "pending_count": pending_count,
            "attention_count": attention_count,
            "in_sync_count": in_sync_count,
            "drift_count": drift_count,
            "validation_by_status": validation_by_status,
            "publication_by_status": publication_by_status,
        }

    def _candidate_sort_key(self, candidate: dict) -> tuple:
        return (
            {"ready": 0, "stale": 1, "offline": 2}[candidate["status"]],
            0 if candidate["endpoint_ready"] else 1,
            0 if candidate["supports_allocation"] else 1,
            0 if candidate["supports_queue"] else 1,
            -self._node_rating_score(candidate),
            candidate["pricing"]["input"],
            candidate["pricing"]["output"],
            candidate["node_id"],
            candidate["bundle_id"],
        )

    def _canonical_candidate_sort_key(self, candidate: dict) -> tuple:
        return (
            {"ready": 0, "stale": 1, "offline": 2}[candidate["status"]],
            -self._node_rating_score(candidate),
            candidate["pricing"]["input"],
            candidate["pricing"]["output"],
            candidate["node_id"],
            candidate["advertisement_id"],
        )

    def _node_rating_score(self, item: dict) -> float:
        reputation = item.get("reputation") or {}
        if reputation.get("score") is not None:
            return float(reputation.get("score") or 0)
        rating = item.get("rating") or {}
        return float(rating.get("score") or 0)
