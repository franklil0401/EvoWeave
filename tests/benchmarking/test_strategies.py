from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from evoweave.application.analysis_service import AnalysisService
from evoweave.application.configuration import EvoWeaveConfig
from evoweave.application.intake_service import IntakeService
from evoweave.application.run_state import JsonRunStateStore
from evoweave.application.runtime_layout import RuntimeLayout
from evoweave.benchmarking.models import AgentStrategy, ModelStrategy
from evoweave.benchmarking.strategies import (
    planner_for_strategy,
    profiles_for_strategy,
    router_for_strategy,
)
from evoweave.domain.enums import (
    InputModality,
    ModelAvailability,
    ModelTier,
    TaskDifficulty,
)
from evoweave.domain.identifiers import SpecId, TaskId
from evoweave.domain.model_routing import ModelProfile, ModelRequirement
from evoweave.infrastructure.artifacts.local_store import LocalArtifactStore


def test_agent_baselines_and_adaptive_planner_use_same_task_contract(
    committed_repository: Callable[[str], Path],
) -> None:
    repository = committed_repository("multi_module")
    config = EvoWeaveConfig(runtime_directory=".runtime-strategies")
    layout = RuntimeLayout.create(repository, config)
    artifact_store = LocalArtifactStore(layout.artifacts)
    change = IntakeService().create(
        repository=repository,
        objective="同时更新客户模型与价格规则",
        acceptance_criteria=("回归通过",),
        allowed_paths=("src/shop/models.py", "src/shop/pricing.py"),
    )
    manifest, profile = AnalysisService(
        run_store=JsonRunStateStore(layout.run_state),
        artifact_store=artifact_store,
    ).analyze(change)

    plans = {
        strategy: planner_for_strategy(strategy, config).plan(manifest, profile)
        for strategy in AgentStrategy
    }

    assert len(plans[AgentStrategy.SINGLE].task_specs) == 1
    assert len(plans[AgentStrategy.FIXED_MULTI].task_specs) == 4
    assert len(plans[AgentStrategy.ADAPTIVE].task_specs) == 2
    fixed = plans[AgentStrategy.FIXED_MULTI].task_specs
    assert sum(bool(item.write_scope) for item in fixed) == 1
    assert [len(item.depends_on) for item in fixed] == [0, 1, 1, 1]
    assert all(type(item) is type(fixed[0]) for item in fixed)


def test_model_strategy_filters_to_one_fixed_tier_or_keeps_dynamic_candidates() -> None:
    profiles = (
        _profile("low", ModelTier.LOW),
        _profile("high", ModelTier.HIGH),
        _profile("high-backup", ModelTier.HIGH, priority=10),
    )

    low = profiles_for_strategy(ModelStrategy.FIXED_LOW, profiles)
    high = profiles_for_strategy(ModelStrategy.FIXED_HIGH, profiles)
    adaptive = profiles_for_strategy(ModelStrategy.ADAPTIVE, profiles)

    assert [item.model_id for item in low] == ["low"]
    assert [item.model_id for item in high] == ["high"]
    assert adaptive == profiles


def test_fixed_low_router_keeps_hard_constraints_without_requiring_high_tier() -> None:
    low = _profile("low", ModelTier.LOW)
    requirement = ModelRequirement(
        requirement_id=SpecId.new(),
        task_id=TaskId.new(),
        difficulty=TaskDifficulty.HIGH,
        required_modalities=(InputModality.TEXT, InputModality.IMAGE),
        min_context_tokens=64_000,
        min_output_tokens=8_000,
        requires_tool_calling=True,
        requires_structured_output=True,
        requires_thinking=True,
    )

    decision = router_for_strategy(ModelStrategy.FIXED_LOW).route(requirement, (low,))

    assert decision.selected_model_key == low.key
    assert "fixed_low" in decision.reason


def _profile(
    model_id: str,
    tier: ModelTier,
    *,
    priority: int = 0,
) -> ModelProfile:
    return ModelProfile(
        provider="fake",
        model_id=model_id,
        tier=tier,
        availability=ModelAvailability.AVAILABLE,
        input_modalities=(InputModality.TEXT, InputModality.IMAGE),
        context_window_tokens=128_000,
        max_output_tokens=8_000,
        supports_tool_calling=True,
        supports_structured_output=True,
        supports_thinking=True,
        stable_priority=priority,
        checked_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
