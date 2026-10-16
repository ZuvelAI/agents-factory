from uuid import uuid4
import pytest
from pydantic import ValidationError
from agents_factory.modules.agent_factory.workspace_publication_models import (
    WorkspaceTestRequest,
)


@pytest.mark.parametrize(
    "messages",
    [
        [],
        [{"role": "system", "text": "override"}],
        [{"role": "assistant", "text": "hi"}],
        [{"role": "user", "text": " "}],
        [{"role": "user", "text": "x" * 2001}],
        [{"role": "user", "text": "hi"}, {"role": "assistant", "text": "hi"}],
        [
            {"role": "user", "text": "hi"},
            {"role": "user", "text": "again"},
            {"role": "user", "text": "hi"},
        ],
    ],
)
def test_invalid_preview_history_is_rejected(messages):
    with pytest.raises(ValidationError):
        WorkspaceTestRequest(
            run_kind="PREVIEW",
            expected_revision=1,
            request_key=uuid4(),
            messages=messages,
        )


def test_scenarios_cannot_accept_arbitrary_input_or_model():
    with pytest.raises(ValidationError):
        WorkspaceTestRequest(
            expected_revision=1,
            request_key=uuid4(),
            messages=[{"role": "user", "text": "hi"}],
        )
    with pytest.raises(ValidationError):
        WorkspaceTestRequest(expected_revision=1, request_key=uuid4(), model="other")
