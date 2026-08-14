from datetime import UTC, datetime
from pathlib import Path

import pytest

from evoweave.domain.enums import (
    InputModality,
    ModelAvailability,
    ModelTier,
    TaskDifficulty,
    TaskStatus,
)
from evoweave.domain.errors import DomainError, ErrorCode
from evoweave.domain.identifiers import RunId, SpecId, TaskId
from evoweave.domain.model_routing import DifficultyAssessment, ModelProfile, ModelRequirement
from evoweave.domain.policies import GraphPolicy
from evoweave.domain.task_spec import TaskSpec
from evoweave.infrastructure.models.rule_router import RuleBasedModelRouter
from evoweave.infrastructure.persistence.graph_repository import SQLiteOrchestrationStore
from evoweave.infrastructure.persistence.sqlite import SQLiteDatabase
from evoweave.orchestration.agent_factory import AgentFactory, CapabilityPlan
from evoweave.orchestration.checkpointing import CheckpointManager
from evoweave.orchestration.decisions import (
    OrchestratorDecision,
    SplitTaskAction,
    WaitAction,
)
from evoweave.orchestration.orchestrator import Orchestrator
from evoweave.orchestration.scheduler import Scheduler
from evoweave.orchestration.task_graph import TaskGraph


def test_no_progress_limit_rejects_decision_without_mutating_accepted_state(
    tmp_path: Path,
) -> None:
    orchestrator, run_id, _task_spec = _orchestrator(
        tmp_path,
        policy=GraphPolicy(max_no_progress_decisions=1),
    )
    for index in range(2):
        assert orchestrator.apply(_wait(run_id, orchestrator.graph.snapshot.version, str(index)))
    before = orchestrator.control_view()

    with pytest.raises(DomainError) as error:
        orchestrator.apply(_wait(run_id, orchestrator.graph.snapshot.version, "rejected"))

    assert error.value.code is ErrorCode.POLICY_REJECTED
    assert orchestrator.control_view() == before


def test_same_decision_id_cannot_be_reused_with_different_payload(tmp_path: Path) -> None:
    orchestrator, run_id, _task_spec = _orchestrator(tmp_path)
    decision = _wait(run_id, orchestrator.graph.snapshot.version, "first")
    orchestrator.apply(decision)

    with pytest.raises(DomainError) as error:
        orchestrator.apply(decision.model_copy(update={"rationale": "different payload"}))
    assert error.value.code is ErrorCode.ARTIFACT_INTEGRITY_ERROR


def test_failed_split_rolls_back_source_cancellation(tmp_path: Path) -> None:
    policy = GraphPolicy(max_nodes=1)
    orchestrator, run_id, source = _orchestrator(tmp_path, policy=policy)
    child_a = _task(change_spec_id=source.change_spec_id, goal="child a")
    child_b = _task(change_spec_id=source.change_spec_id, goal="child b")
    decision = OrchestratorDecision(
        decision_id=SpecId.new(),
        run_id=run_id,
        based_on_graph_version=orchestrator.graph.snapshot.version,
        action=SplitTaskAction(
            source_task_id=source.task_id,
            task_specs=(child_a, child_b),
            cancel_source=True,
        ),
        rationale="会超过节点上限",
    )

    with pytest.raises(DomainError) as error:
        orchestrator.apply(decision)
    assert error.value.code is ErrorCode.POLICY_REJECTED
    assert orchestrator.graph.node_for(source.task_id).status is TaskStatus.READY
    assert len(orchestrator.graph.snapshot.nodes) == 1


def test_model_mismatch_during_dispatch_leaves_task_ready_and_no_allocation_record(
    tmp_path: Path,
) -> None:
    high_task = _task(
        change_spec_id=SpecId.new(),
        goal="high task",
        difficulty=TaskDifficulty.HIGH,
    )
    run_id = RunId.new()
    policy = GraphPolicy()
    orchestrator = _build(tmp_path, run_id, high_task, policy)
    factory = AgentFactory(
        model_router=RuleBasedModelRouter(),
        model_profiles=(_low_profile(),),
    )

    with pytest.raises(DomainError) as error:
        orchestrator.dispatch(
            scheduler=Scheduler(policy),
            agent_factory=factory,
            capability_plan_for=lambda _task_id: CapabilityPlan(),
        )
    assert error.value.code is ErrorCode.MODEL_CAPABILITY_MISMATCH
    assert orchestrator.graph.node_for(high_task.task_id).status is TaskStatus.READY
    assert orchestrator.allocation_decisions == ()


def test_model_fallback_replaces_agent_and_execution_spec_version(tmp_path: Path) -> None:
    orchestrator, _run_id, task = _orchestrator(tmp_path)
    first = _low_profile().model_copy(update={"model_id": "first", "stable_priority": 0})
    second = _low_profile().model_copy(update={"model_id": "second", "stable_priority": 1})
    router = RuleBasedModelRouter()
    scheduler = Scheduler()
    original = orchestrator.dispatch(
        scheduler=scheduler,
        agent_factory=AgentFactory(model_router=router, model_profiles=(first, second)),
        capability_plan_for=lambda _task_id: CapabilityPlan(),
    )[0]

    unavailable_first = first.model_copy(
        update={"availability": ModelAvailability.UNAVAILABLE, "checked_at": None}
    )
    rerouting = router.route(task.model_requirement, (unavailable_first, second))
    revised = orchestrator.reroute_execution(
        original.spec_id,
        rerouting,
        scheduler=scheduler,
    )

    assert revised.spec_id != original.spec_id
    assert revised.agent_id != original.agent_id
    assert revised.version == original.version + 1
    assert revised.model_routing.version == original.model_routing.version + 1
    assert revised.model_routing.selected_model_key == second.key
    assert orchestrator.graph.node_for(task.task_id).status is TaskStatus.RUNNING
    assert orchestrator.active_leases[0].execution_spec_id == revised.spec_id


def test_expired_lease_is_persisted_and_restored_without_active_agent(tmp_path: Path) -> None:
    orchestrator, run_id, task = _orchestrator(tmp_path)
    store = SQLiteOrchestrationStore(SQLiteDatabase(tmp_path / f"{run_id}.db"))
    checkpoint_manager = CheckpointManager(store)
    scheduler = Scheduler()
    execution = orchestrator.dispatch(
        scheduler=scheduler,
        agent_factory=AgentFactory(
            model_router=RuleBasedModelRouter(),
            model_profiles=(_low_profile(),),
        ),
        capability_plan_for=lambda _task_id: CapabilityPlan(),
    )[0]
    active = orchestrator.active_leases[0]

    expired = orchestrator.expire_leases(scheduler=scheduler, now=active.expires_at)

    assert expired[0].execution_spec_id == execution.spec_id
    assert orchestrator.active_leases == ()
    assert orchestrator.graph.node_for(task.task_id).status is TaskStatus.FAILED
    checkpoint = checkpoint_manager.load(run_id)
    assert checkpoint is not None
    restored = Orchestrator.restore(
        checkpoint,
        graph_store=store,
        decision_ledger=store,
        checkpoint_manager=checkpoint_manager,
    )
    assert restored.active_leases == ()
    assert restored.graph.node_for(task.task_id).status is TaskStatus.FAILED


def test_split_that_cancels_source_creates_ready_superseding_tasks(tmp_path: Path) -> None:
    orchestrator, run_id, source = _orchestrator(tmp_path)
    first = _task(change_spec_id=source.change_spec_id, goal="replacement a")
    second = _task(change_spec_id=source.change_spec_id, goal="replacement b")
    decision = OrchestratorDecision(
        decision_id=SpecId.new(),
        run_id=run_id,
        based_on_graph_version=orchestrator.graph.snapshot.version,
        action=SplitTaskAction(
            source_task_id=source.task_id,
            task_specs=(first, second),
            cancel_source=True,
        ),
        rationale="用两个独立任务替代原任务",
    )

    orchestrator.apply(decision)

    assert orchestrator.graph.node_for(source.task_id).status is TaskStatus.CANCELLED
    assert orchestrator.graph.node_for(first.task_id).status is TaskStatus.READY
    assert orchestrator.graph.node_for(second.task_id).status is TaskStatus.READY


def _orchestrator(
    tmp_path: Path,
    *,
    policy: GraphPolicy | None = None,
) -> tuple[Orchestrator, RunId, TaskSpec]:
    run_id = RunId.new()
    task = _task(change_spec_id=SpecId.new(), goal="root")
    return _build(tmp_path, run_id, task, policy or GraphPolicy()), run_id, task


def _build(
    tmp_path: Path,
    run_id: RunId,
    task: TaskSpec,
    policy: GraphPolicy,
) -> Orchestrator:
    store = SQLiteOrchestrationStore(SQLiteDatabase(tmp_path / f"{run_id}.db"))
    return Orchestrator(
        graph=TaskGraph.create(run_id=run_id, task_specs=(task,), policy=policy),
        graph_store=store,
        decision_ledger=store,
        checkpoint_manager=CheckpointManager(store),
        policy=policy,
    )


def _wait(run_id: RunId, graph_version: int, label: str) -> OrchestratorDecision:
    return OrchestratorDecision(
        decision_id=SpecId.new(),
        run_id=run_id,
        based_on_graph_version=graph_version,
        action=WaitAction(reason=f"wait {label}"),
        rationale=f"wait {label}",
    )


def _task(
    *,
    change_spec_id: SpecId,
    goal: str,
    difficulty: TaskDifficulty = TaskDifficulty.LOW,
) -> TaskSpec:
    task_id = TaskId.new()
    return TaskSpec(
        spec_id=SpecId.new(),
        task_id=task_id,
        change_spec_id=change_spec_id,
        goal=goal,
        base_commit="a" * 40,
        acceptance_criteria=("完成",),
        read_scope=("src",),
        difficulty=DifficultyAssessment(difficulty=difficulty, rationale="测试"),
        model_requirement=ModelRequirement(
            requirement_id=SpecId.new(),
            task_id=task_id,
            difficulty=difficulty,
            min_context_tokens=1_000,
            min_output_tokens=500,
        ),
    )


def _low_profile() -> ModelProfile:
    return ModelProfile(
        provider="fake",
        model_id="low",
        tier=ModelTier.LOW,
        availability=ModelAvailability.AVAILABLE,
        input_modalities=(InputModality.TEXT,),
        context_window_tokens=8_000,
        max_output_tokens=2_000,
        checked_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
