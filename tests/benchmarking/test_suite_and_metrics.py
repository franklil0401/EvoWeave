import json
from hashlib import sha256
from pathlib import Path

import pytest

from evoweave.benchmarking.materializer import FixtureMaterializer
from evoweave.benchmarking.metrics import aggregate_metrics
from evoweave.benchmarking.models import (
    AgentStrategy,
    BenchmarkRunRecord,
    BenchmarkRunStatus,
    EvidenceLevel,
    ModelStrategy,
)
from evoweave.benchmarking.planning_audit import PlanningAuditRunner
from evoweave.benchmarking.reporting import (
    BenchmarkReportWriter,
    GoNoGoStatus,
    assess_go_no_go,
)
from evoweave.benchmarking.suite_loader import (
    load_benchmark_suite,
    validate_benchmark_suite,
)

_PROJECT_ROOT = Path(__file__).parents[2]
_SUITE_PATH = _PROJECT_ROOT / "benchmarks/任务集/第一版任务集.json"
_SUITE_DIGEST = sha256(_SUITE_PATH.read_bytes()).hexdigest()


def test_fixed_suite_verifies_tasks_commits_and_image_hashes(tmp_path: Path) -> None:
    suite, suite_digest = load_benchmark_suite(_SUITE_PATH)

    report = validate_benchmark_suite(_PROJECT_ROOT, _SUITE_PATH)
    materialized = FixtureMaterializer(_PROJECT_ROOT).materialize(
        suite.tasks[0],
        tmp_path / "repository",
    )

    assert report.suite_sha256 == suite_digest
    assert report.task_count == 12
    assert report.fixture_count == 3
    assert report.image_task_count == 2
    assert report.image_negative_count == 1
    assert len(report.verified_asset_sha256s) == 3
    assert report.verified_hidden_acceptance_sha256 == suite.hidden_acceptance_sha256
    assert materialized.base_commit == suite.tasks[0].base_commit


def test_adaptive_planning_matches_locked_difficulty_labels() -> None:
    suite, suite_digest = load_benchmark_suite(_SUITE_PATH)

    report = PlanningAuditRunner(_PROJECT_ROOT).run(suite, suite_digest)
    adaptive = tuple(
        item for item in report.records if item.agent_strategy is AgentStrategy.ADAPTIVE
    )

    assert len(adaptive) == 12
    assert all(item.difficulty_match for item in adaptive)


def test_complete_strategy_matrix_can_reach_go_without_missing_data() -> None:
    suite, _suite_digest = load_benchmark_suite(_SUITE_PATH)
    records = tuple(
        _passing_record(task, agent_strategy, model_strategy)
        for agent_strategy in AgentStrategy
        for model_strategy in ModelStrategy
        for task in suite.tasks
    )

    metrics = aggregate_metrics(suite, records)
    assessment = assess_go_no_go(suite, records, metrics)

    assert len(metrics) == 9
    assert all(item.run_count == 12 for item in metrics)
    assert assessment.status is GoNoGoStatus.GO
    assert assessment.evidence_level is EvidenceLevel.OFFLINE_REPLAY


def test_report_marks_incomplete_evidence_pending_instead_of_filling_zeroes(
    tmp_path: Path,
) -> None:
    suite, suite_digest = load_benchmark_suite(_SUITE_PATH)
    records = (
        _passing_record(
            suite.tasks[0],
            AgentStrategy.ADAPTIVE,
            ModelStrategy.ADAPTIVE,
        ),
    )

    markdown, machine_json = BenchmarkReportWriter().write(
        suite=suite,
        suite_sha256=suite_digest,
        records=records,
        output_root=tmp_path,
    )

    assert "尚无任一真实性等级完成" in markdown.read_text(encoding="utf-8")
    payload = json.loads(machine_json.read_text(encoding="utf-8"))
    assert payload["record_count"] == 1
    assert payload["go_no_go"]["status"] == "pending"


def test_duplicate_strategy_record_is_rejected() -> None:
    suite, _suite_digest = load_benchmark_suite(_SUITE_PATH)
    record = _passing_record(
        suite.tasks[0],
        AgentStrategy.ADAPTIVE,
        ModelStrategy.ADAPTIVE,
    )

    with pytest.raises(ValueError, match="不能重复"):
        aggregate_metrics(suite, (record, record))


def test_hard_constraint_compliance_is_distinct_from_initial_execution_success() -> None:
    suite, _suite_digest = load_benchmark_suite(_SUITE_PATH)
    record = _passing_record(
        suite.tasks[0],
        AgentStrategy.ADAPTIVE,
        ModelStrategy.ADAPTIVE,
    ).model_copy(update={"initial_route_valid": False})

    metric = aggregate_metrics(suite, (record,))[0]

    assert metric.route_hard_constraint_compliance_rate == 1.0
    assert metric.initial_execution_success_rate == 0.0
    assert metric.initial_route_success_rate == 0.0


def test_metrics_report_cross_trial_variance() -> None:
    suite, _suite_digest = load_benchmark_suite(_SUITE_PATH)
    first_trial = tuple(
        _passing_record(
            task,
            AgentStrategy.ADAPTIVE,
            ModelStrategy.ADAPTIVE,
        )
        for task in suite.tasks
    )
    second_trial = tuple(
        item.model_copy(
            update={
                "run_id": f"{item.run_id}-trial-2",
                "trial_index": 2,
                "status": BenchmarkRunStatus.FAILED,
            }
        )
        for item in first_trial
    )

    metric = aggregate_metrics(suite, (*first_trial, *second_trial))[0]

    assert metric.run_count == 24
    assert metric.trial_count == 2
    assert metric.success_rate == 0.5
    assert metric.success_rate_stddev == 0.5
    assert metric.average_tokens_stddev == 0.0


def test_incomplete_additional_trial_keeps_assessment_pending() -> None:
    suite, _suite_digest = load_benchmark_suite(_SUITE_PATH)
    first_trial = tuple(
        _passing_record(task, agent_strategy, model_strategy)
        for agent_strategy in AgentStrategy
        for model_strategy in ModelStrategy
        for task in suite.tasks
    )
    incomplete_second = _passing_record(
        suite.tasks[0],
        AgentStrategy.ADAPTIVE,
        ModelStrategy.ADAPTIVE,
    ).model_copy(update={"run_id": "incomplete-trial-2", "trial_index": 2})

    metrics = aggregate_metrics(suite, (*first_trial, incomplete_second))
    assessment = assess_go_no_go(suite, (*first_trial, incomplete_second), metrics)

    assert assessment.status is GoNoGoStatus.PENDING


def test_v1_record_without_trial_or_hard_constraint_fields_remains_loadable() -> None:
    suite, _suite_digest = load_benchmark_suite(_SUITE_PATH)
    record = _passing_record(
        suite.tasks[0],
        AgentStrategy.ADAPTIVE,
        ModelStrategy.ADAPTIVE,
    )
    payload = record.model_dump(exclude={"trial_index", "route_hard_constraints_satisfied"})

    restored = BenchmarkRunRecord.model_validate(payload)

    assert restored.trial_index == 1
    assert restored.route_hard_constraints_satisfied is None


def test_report_rejects_mixed_system_commits(tmp_path: Path) -> None:
    suite, suite_digest = load_benchmark_suite(_SUITE_PATH)
    first = _passing_record(
        suite.tasks[0],
        AgentStrategy.ADAPTIVE,
        ModelStrategy.ADAPTIVE,
    )
    second = _passing_record(
        suite.tasks[1],
        AgentStrategy.ADAPTIVE,
        ModelStrategy.ADAPTIVE,
    ).model_copy(update={"system_commit": "b" * 40})

    with pytest.raises(ValueError, match="多个系统 Git 提交"):
        BenchmarkReportWriter().write(
            suite=suite,
            suite_sha256=suite_digest,
            records=(first, second),
            output_root=tmp_path,
        )


def _passing_record(task, agent_strategy, model_strategy) -> BenchmarkRunRecord:
    adaptive = agent_strategy is AgentStrategy.ADAPTIVE and model_strategy is ModelStrategy.ADAPTIVE
    image_relevant = "image_relevant" in task.scenario_tags
    return BenchmarkRunRecord(
        benchmark_id=task.benchmark_id,
        run_id=f"run-{agent_strategy.value}-{model_strategy.value}-{task.benchmark_id}",
        suite_sha256=_SUITE_DIGEST,
        system_commit="a" * 40,
        agent_strategy=agent_strategy,
        model_strategy=model_strategy,
        evidence_level=EvidenceLevel.OFFLINE_REPLAY,
        status=BenchmarkRunStatus.PASSED,
        target_tests_passed=True,
        full_regression_passed=True,
        localization_candidates=task.gold_paths,
        patch_generated=True,
        patch_applied=True,
        patch_authorized=True,
        input_tokens=40 if adaptive else 80,
        output_tokens=10 if adaptive else 20,
        reasoning_tokens=0,
        duration_ms=50 if adaptive else 100,
        agent_count=(1 if adaptive else 4 if agent_strategy is AgentStrategy.FIXED_MULTI else 1),
        task_count=1,
        invalid_task_count=0,
        conflict_count=0,
        orchestrator_context_chars=100 if adaptive else 500,
        worker_context_chars=1_000,
        initial_route_valid=True,
        route_hard_constraints_satisfied=True,
        fallback_count=0,
        predicted_difficulty=task.human_difficulty,
        image_agent_count=1 if image_relevant else 0,
    )
