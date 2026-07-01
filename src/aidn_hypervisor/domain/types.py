from typing import Literal

TaskMode = Literal["manual", "auto"]
AllocationPolicy = Literal["reject", "wait"]
WarmPolicy = Literal["always", "auto", "never"]
LaunchMode = Literal["managed_process", "attached_service"]
TaskStatus = Literal[
    "queued",
    "admitted",
    "starting",
    "running",
    "completed",
    "failed",
    "cancelled",
]
