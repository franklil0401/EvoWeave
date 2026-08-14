"""Tests for explainable difficulty and deterministic model routing."""

from datetime import UTC, datetime

import pytest

from evoweave.agent_runtime.difficulty import RuleBasedDifficultyAssessor, TaskSignals
from evoweave.agent_runtime.fallback import revise_execution_spec_for_routing
from evoweave.domain.agent_execution_spec import AgentExecutionSpec
from evoweave.domain.enums import (
    InputModality,
    ModelAvailability,
    ModelTier,
    RiskLevel,
    TaskDifficulty,
)
from evoweave.domain.errors import DomainError, ErrorCode
from evoweave.domain.identifiers import AgentId, RunId, SpecId, TaskId
from evoweave.domain.model_routing import ModelProfile, ModelRequirement
from evoweave.infrastructure.models.rule_router import RoutingPolicy, RuleBasedModelRouter

CHECKED_AT = datetime(2026, 8, 14, tzinfo=UTC)


def _profile(
    model_id: str,
    tier: ModelTier,
    *,
    modalities: tuple[InputModality, ...] = (InputModality.TEXT,),
    availability: ModelAvailability = ModelAvailability.AVAILABLE,
    priority: int = 100,
    provider: str = "fake",
) -> ModelProfile:
    return ModelProfile(
        provider=provider,
        model_id=model_id,
        tier=tier,
        availability=availability,
        input_modalities=modalities,
        context_window_tokens=100_000,
        max_output_tokens=8_000,
        supports_tool_calling=True,
        supports_structured_output=True,
        checked_at=CHECKED_AT if availability is ModelAvailability.AVAILABLE else None,
        stable_priority=priority,
    )


def _requirement(
    difficulty: TaskDifficulty,
    modalities: tuple[InputModality, ...] = (InputModality.TEXT,),
) -> ModelRequirement:
    return ModelRequirement(
        requirement_id=SpecId.new(),
        task_id=TaskId.new(),
        difficulty=difficulty,
        required_modalities=modalities,
        min_context_tokens=1_000,
        min_output_tokens=500,
        requires_tool_calling=True,
        requires_structured_output=True,
    )


def test_difficulty_assessor_keeps_small_local_change_low() -> None:
    assessment = RuleBasedDifficultyAssessor().assess(
        TaskSignals(affected_files=1, affected_symbols=2)
    )
    assert assessment.difficulty is TaskDifficulty.LOW
    assert "规则评分" in assessment.rationale


def test_difficulty_assessor_marks_unknown_high_risk_change_high() -> None:
    assessment = RuleBasedDifficultyAssessor().assess(
        TaskSignals(
            affected_files=4,
            dependency_depth=4,
            crosses_modules=True,
            scope_is_unknown=True,
            risk_level=RiskLevel.HIGH,
        )
    )
    assert assessment.difficulty is TaskDifficulty.HIGH
    assert "影响范围未知" in assessment.rationale


@pytest.mark.parametrize(
    ("difficulty", "expected"),
    [
        (TaskDifficulty.LOW, "fake:low"),
        (TaskDifficulty.MEDIUM, "fake:medium"),
        (TaskDifficulty.HIGH, "fake:high"),
    ],
)
def test_router_chooses_matching_difficulty_tier(
    difficulty: TaskDifficulty,
    expected: str,
) -> None:
    profiles = (
        _profile("high", ModelTier.HIGH),
        _profile("low", ModelTier.LOW),
        _profile("medium", ModelTier.MEDIUM),
    )
    decision = RuleBasedModelRouter().route(_requirement(difficulty), profiles)
    assert decision.selected_model_key == expected


def test_high_difficulty_still_selects_one_agent_model() -> None:
    high = _profile("high", ModelTier.HIGH)
    decision = RuleBasedModelRouter().route(_requirement(TaskDifficulty.HIGH), (high,))
    assert decision.selected_model_key == high.key
    assert not hasattr(decision, "agent_count")


def test_image_requirement_excludes_text_only_candidates() -> None:
    text = _profile("text", ModelTier.MEDIUM)
    vision = _profile(
        "vision",
        ModelTier.MEDIUM,
        modalities=(InputModality.TEXT, InputModality.IMAGE),
    )
    requirement = _requirement(
        TaskDifficulty.MEDIUM,
        (InputModality.TEXT, InputModality.IMAGE),
    )
    decision = RuleBasedModelRouter().route(requirement, (text, vision))
    assert decision.selected_model_key == vision.key
    assert decision.rejected_candidates[0].model_key == text.key


def test_unavailable_first_choice_falls_back_explicitly() -> None:
    offline = _profile(
        "offline",
        ModelTier.LOW,
        availability=ModelAvailability.UNAVAILABLE,
        priority=0,
    )
    online = _profile("online", ModelTier.LOW, priority=10)
    decision = RuleBasedModelRouter().route(
        _requirement(TaskDifficulty.LOW),
        (offline, online),
    )
    assert decision.selected_model_key == online.key
    assert decision.rejected_candidates[0].model_key == offline.key


def test_router_fails_instead_of_dropping_image_requirement() -> None:
    with pytest.raises(DomainError) as error:
        RuleBasedModelRouter().route(
            _requirement(
                TaskDifficulty.LOW,
                (InputModality.TEXT, InputModality.IMAGE),
            ),
            (_profile("text", ModelTier.LOW),),
        )
    assert error.value.code is ErrorCode.MODEL_CAPABILITY_MISMATCH


def test_router_semantics_are_deterministic() -> None:
    profiles = (
        _profile("a", ModelTier.LOW, provider="first"),
        _profile("b", ModelTier.LOW, provider="second"),
    )
    router = RuleBasedModelRouter(
        RoutingPolicy(provider_priority=("second", "first"), max_fallbacks=1)
    )
    requirement = _requirement(TaskDifficulty.LOW)
    decisions = [router.route(requirement, tuple(reversed(profiles))) for _ in range(2)]
    assert [item.selected_model_key for item in decisions] == ["second:b", "second:b"]
    assert [item.fallback_model_keys for item in decisions] == [
        ("first:a",),
        ("first:a",),
    ]
    assert all(item.capability_snapshot_at == CHECKED_AT for item in decisions)


def test_failed_model_reroute_creates_new_execution_spec_version() -> None:
    task_id = TaskId.new()
    requirement = ModelRequirement(
        requirement_id=SpecId.new(),
        task_id=task_id,
        difficulty=TaskDifficulty.LOW,
    )
    first = _profile("first", ModelTier.LOW, priority=0)
    second = _profile("second", ModelTier.LOW, priority=1)
    router = RuleBasedModelRouter()
    initial_decision = router.route(requirement, (first, second))
    original = AgentExecutionSpec(
        spec_id=SpecId.new(),
        run_id=RunId.new(),
        agent_id=AgentId.new(),
        task_id=task_id,
        task_spec_id=SpecId.new(),
        task_spec_version=1,
        base_commit="a" * 40,
        goal="执行简单任务",
        acceptance_criteria=("完成",),
        model_routing=initial_decision,
        read_scope=("src",),
    )
    unavailable_first = first.model_copy(
        update={"availability": ModelAvailability.UNAVAILABLE, "checked_at": None}
    )
    rerouted = router.route(requirement, (unavailable_first, second))
    revised = revise_execution_spec_for_routing(original, rerouted)
    assert original.version == 1
    assert original.model_routing.selected_model_key == first.key
    assert revised.version == 2
    assert revised.spec_id != original.spec_id
    assert revised.model_routing.version == 2
    assert revised.model_routing.decision_id != original.model_routing.decision_id
    assert revised.model_routing.selected_model_key == second.key
