from aidn_hypervisor.domain.models import TaskRequest
from aidn_hypervisor.queue import InMemoryTaskQueue


def test_queue_orders_by_priority_then_fifo() -> None:
    queue = InMemoryTaskQueue()
    low = queue.enqueue(
        TaskRequest(task_type="llm_text.generate", payload={"prompt": "a"}, priority=10)
    )
    high = queue.enqueue(
        TaskRequest(task_type="llm_text.generate", payload={"prompt": "b"}, priority=90)
    )

    next_task = queue.peek_next()

    assert next_task.task_id == high.task_id
    assert next_task.task_id != low.task_id


def test_queue_can_transition_task_status_after_enqueue() -> None:
    queue = InMemoryTaskQueue()
    task = queue.enqueue(
        TaskRequest(task_type="llm_text.generate", payload={"prompt": "a"}, priority=10)
    )

    updated = queue.transition_status(task.task_id, "admitted")

    assert updated.status == "admitted"


def test_queue_keeps_fifo_order_for_same_priority() -> None:
    queue = InMemoryTaskQueue()
    first = queue.enqueue(
        TaskRequest(task_type="llm_text.generate", payload={"prompt": "a"}, priority=50)
    )
    second = queue.enqueue(
        TaskRequest(task_type="llm_text.generate", payload={"prompt": "b"}, priority=50)
    )

    next_task = queue.peek_next()

    assert next_task.task_id == first.task_id
    assert next_task.task_id != second.task_id


def test_transition_status_raises_for_unknown_task_id() -> None:
    queue = InMemoryTaskQueue()

    try:
        queue.transition_status("missing-task", "admitted")
    except KeyError as exc:
        assert exc.args == ("missing-task",)
    else:
        raise AssertionError("Expected KeyError for unknown task_id")


def test_peek_next_skips_tasks_no_longer_queued() -> None:
    queue = InMemoryTaskQueue()
    first = queue.enqueue(
        TaskRequest(task_type="llm_text.generate", payload={"prompt": "a"}, priority=50)
    )
    second = queue.enqueue(
        TaskRequest(task_type="llm_text.generate", payload={"prompt": "b"}, priority=40)
    )

    queue.transition_status(first.task_id, "admitted")
    next_task = queue.peek_next()

    assert next_task.task_id == second.task_id
    assert next_task.task_id != first.task_id


def test_transition_status_rejects_invalid_status() -> None:
    queue = InMemoryTaskQueue()
    task = queue.enqueue(
        TaskRequest(task_type="llm_text.generate", payload={"prompt": "a"}, priority=50)
    )

    try:
        queue.transition_status(task.task_id, "bogus")
    except ValueError as exc:
        assert "bogus" in str(exc)
    else:
        raise AssertionError("Expected ValueError for invalid status")


def test_enqueued_task_uses_snapshot_of_request() -> None:
    queue = InMemoryTaskQueue()
    request = TaskRequest(
        task_type="llm_text.generate",
        payload={"prompt": "a"},
        priority=50,
        constraints={"region": "us-east"},
    )

    task = queue.enqueue(request)
    request.payload["prompt"] = "mutated"
    request.constraints["region"] = "eu-west"

    assert task.request.payload["prompt"] == "a"
    assert task.request.constraints["region"] == "us-east"
