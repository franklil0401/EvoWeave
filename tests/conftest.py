"""Shared deterministic fixtures for stage 0 contracts."""

from datetime import UTC, datetime

import pytest

from evoweave.domain.enums import (
    InputModality,
    ModelAvailability,
    ModelTier,
    TaskDifficulty,
)
from evoweave.domain.identifiers import TaskId
from evoweave.domain.model_routing import (
    DifficultyAssessment,
    ModelProfile,
    ModelRequirement,
)


@pytest.fixture
def task_id() -> TaskId:
    return TaskId.new()


@pytest.fixture
def low_difficulty() -> DifficultyAssessment:
    return DifficultyAssessment(difficulty=TaskDifficulty.LOW, rationale="单文件确定性修改")


@pytest.fixture
def text_requirement(task_id: TaskId) -> ModelRequirement:
    return ModelRequirement(
        requirement_id="spec_requirement1",
        task_id=task_id,
        difficulty=TaskDifficulty.LOW,
        min_context_tokens=8_000,
        min_output_tokens=1_000,
    )


@pytest.fixture
def text_profile() -> ModelProfile:
    return ModelProfile(
        provider="fake",
        model_id="text-small",
        tier=ModelTier.LOW,
        availability=ModelAvailability.AVAILABLE,
        input_modalities=(InputModality.TEXT,),
        context_window_tokens=32_000,
        max_output_tokens=4_000,
        supports_structured_output=True,
        checked_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
