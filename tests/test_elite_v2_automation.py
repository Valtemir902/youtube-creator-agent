from __future__ import annotations

import pytest

from elite_v2_automation import AutomationState, SupervisedAutomationQueue


def test_queue_requires_provenance_and_never_writes_on_approval() -> None:
    queue = SupervisedAutomationQueue()
    with pytest.raises(ValueError):
        queue.enqueue(intent="propose_metadata", provider="local", proposal={"title": "Novo"}, facts=[])

    item = queue.enqueue(
        intent="propose_metadata",
        provider="local",
        proposal={"title": "Novo"},
        facts=[{"source": "youtube_data_api", "name": "title", "value": "Atual"}],
        target_kind="video",
        target_id="VID1",
    )
    assert item.state is AutomationState.AWAITING_APPROVAL
    with pytest.raises(PermissionError):
        queue.approve(item.item_id, user_confirmed=False)
    approved = queue.approve(item.item_id, user_confirmed=True)
    assert approved.state is AutomationState.APPROVED
    assert all(event["youtube_write_performed"] is False for event in queue.audit)


def test_handoff_is_separate_from_write_gateway_and_needs_confirmation() -> None:
    queue = SupervisedAutomationQueue()
    item = queue.enqueue(
        intent="propose_playlist",
        provider="internal",
        proposal={"title": "Nova playlist"},
        facts=[{"source": "local_context", "name": "topic", "value": "roça"}],
    )
    queue.approve(item.item_id, user_confirmed=True)
    with pytest.raises(PermissionError):
        queue.hand_to_write_gateway(item.item_id, user_confirmed=False)
    handed = queue.hand_to_write_gateway(item.item_id, user_confirmed=True)
    assert handed.state is AutomationState.HANDED_TO_WRITE_GATEWAY
    assert all(event["youtube_write_performed"] is False for event in queue.audit)


def test_cancelled_item_cannot_be_handed_to_write_gateway() -> None:
    queue = SupervisedAutomationQueue()
    item = queue.enqueue(
        intent="read_analyze",
        provider="internal",
        proposal={"analysis_only": True},
        facts=[{"source": "youtube_analytics_api", "name": "views", "value": 10}],
    )
    queue.cancel(item.item_id)
    assert item.state is AutomationState.CANCELLED
    with pytest.raises(RuntimeError):
        queue.hand_to_write_gateway(item.item_id, user_confirmed=True)
