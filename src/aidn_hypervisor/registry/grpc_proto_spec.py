"""gRPC Proto Specification for Registry Replication Protocol (M9-S4).

This module documents the proto definitions that would be generated
by ``grpcio-tools`` in production. In MVP, we use the
``GrpcProtoRegistryMessage`` model directly.

Proto file: ``registry_replication.proto``
"""

from __future__ import annotations

PROTO_SPEC = """\
syntax = "proto3";

package aidn.registry.v1;

import "google/protobuf/timestamp.proto";

// ---------------------------------------------------------------------------
// Registry replication message
// ---------------------------------------------------------------------------

message RegistryMessage {
    string message_id = 1;
    string message_type = 2;
    string source_node_id = 3;
    string destination_node_id = 4;
    uint64 sequence_number = 5;
    bytes payload = 6;
    uint64 created_at = 7;
    uint32 hop_limit = 8;
    string correlation_id = 9;
}

// ---------------------------------------------------------------------------
// Health check
// ---------------------------------------------------------------------------

message HealthRequest {
    string node_id = 1;
}

message HealthResponse {
    bool healthy = 1;
    int64 object_count = 2;
    int64 latest_epoch = 3;
    string status = 4;
}

// ---------------------------------------------------------------------------
// Sync status
// ---------------------------------------------------------------------------

message SyncStatusRequest {
    string node_id = 1;
    string peer_id = 2;
}

message SyncStatusResponse {
    string sync_mode = 1;
    int64 current_epoch = 2;
    int64 target_epoch = 3;
    double progress = 4;
    int64 objects_synced = 5;
    int64 bytes_synced = 6;
    bool completed = 7;
}

// ---------------------------------------------------------------------------
// Inventory exchange
// ---------------------------------------------------------------------------

message InventoryRequest {
    string request_id = 1;
    repeated string object_types = 2;
    int64 epoch_start = 3;
    int64 epoch_end = 4;
    bool include_bloom = 5;
}

message InventoryResponse {
    string request_id = 1;
    int64 object_count = 2;
    map<string, int64> object_types = 3;
    int64 earliest_epoch = 4;
    int64 latest_epoch = 5;
    bytes bloom_filter = 6;
    string inventory_root_hash = 7;
}

// ---------------------------------------------------------------------------
// Object transfer
// ---------------------------------------------------------------------------

message ObjectFetchRequest {
    repeated string object_ids = 1;
    bool include_payload = 2;
}

message ObjectFetchResponse {
    repeated bytes objects = 1;
    repeated string missing_ids = 2;
    int64 total_requested = 3;
    int64 total_delivered = 4;
}

// ---------------------------------------------------------------------------
// Registry replication service
// ---------------------------------------------------------------------------

service RegistryReplication {
    // Bidirectional streaming for registry messages
    rpc StreamMessages (stream RegistryMessage)
        returns (stream RegistryMessage);

    // Health check
    rpc HealthCheck (HealthRequest) returns (HealthResponse);

    // Sync status query
    rpc SyncStatus (SyncStatusRequest) returns (SyncStatusResponse);

    // Inventory exchange
    rpc ExchangeInventory (InventoryRequest) returns (InventoryResponse);

    // Object fetch
    rpc FetchObjects (ObjectFetchRequest) returns (ObjectFetchResponse);

    // Announcement push
    rpc PushAnnouncement (RegistryMessage) returns (AckResponse);
}

// ---------------------------------------------------------------------------
// Acknowledgment
// ---------------------------------------------------------------------------

message AckResponse {
    string message_id = 1;
    bool acknowledged = 2;
    string error = 3;
}
"""

__all__ = ["PROTO_SPEC"]
