"""Aggregate comparable metrics without inventing missing benchmark outcomes."""

from collections import defaultdict

from pydantic import Field

from evoweave.benchmarking.models import (
    AgentStrategy,
    BenchmarkRunRecord,
    BenchmarkRunStatus,
    BenchmarkSuite,
    BenchmarkTask,
    EvidenceLevel,
    ModelStrategy,
)
from evoweave.domain.base import DomainModel


class StrategyMetrics(DomainModel):
    agent_strategy: AgentStrategy
    model_strategy: ModelStrategy
    evidence_level: EvidenceLevel
    run_count: int = Field(ge=1)
    success_rate: float = Field(ge=0.0, le=1.0)
    localization_recall: float = Field(ge=0.0, le=1.0)
    patch_efficiency: float = Field(ge=0.0, le=1.0)
    regression_rate: float = Field(ge=0.0, le=1.0)
    average_tokens: float = Field(ge=0.0)
    average_duration_ms: float = Field(ge=0.0)
    average_agent_count: float = Field(ge=0.0)
    invalid_task_rate: float = Field(ge=0.0, le=1.0)
    conflict_rate: float = Field(ge=0.0, le=1.0)
    orchestrator_context_ratio: float = Field(ge=0.0)
    initial_route_success_rate: float = Field(ge=0.0, le=1.0)
    fallback_rate: float = Field(ge=0.0, le=1.0)
    difficulty_match_rate: float = Field(ge=0.0, le=1.0)
    image_success_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    original_image_exposure_rate: float | None = Field(default=None, ge=0.0, le=1.0)


def aggregate_metrics(
    suite: BenchmarkSuite,
    records: tuple[BenchmarkRunRecord, ...],
) -> tuple[StrategyMetrics, ...]:
    task_by_id = {task.benchmark_id: task for task in suite.tasks}
    unknown = {record.benchmark_id for record in records}.difference(task_by_id)
    if unknown:
        raise ValueError(f"benchmark 结果引用未知任务：{sorted(unknown)}")
    duplicate_keys = [
        (record.benchmark_id, record.agent_strategy, record.model_strategy, record.evidence_level)
        for record in records
    ]
    if len(set(duplicate_keys)) != len(duplicate_keys):
        raise ValueError("同一任务和策略组合不能重复记录")
    grouped: defaultdict[
        tuple[AgentStrategy, ModelStrategy, EvidenceLevel],
        list[BenchmarkRunRecord],
    ] = defaultdict(list)
    for record in records:
        if record.status is not BenchmarkRunStatus.SKIPPED:
            grouped[(record.agent_strategy, record.model_strategy, record.evidence_level)].append(
                record
            )
    return tuple(
        _aggregate_group(task_by_id, key, tuple(group))
        for key, group in sorted(
            grouped.items(),
            key=lambda item: tuple(value.value for value in item[0]),
        )
    )


def _aggregate_group(
    task_by_id: dict[str, BenchmarkTask],
    key: tuple[AgentStrategy, ModelStrategy, EvidenceLevel],
    records: tuple[BenchmarkRunRecord, ...],
) -> StrategyMetrics:
    count = len(records)
    generated = [record for record in records if record.patch_generated]
    target_passed = [record for record in records if record.target_tests_passed]
    total_tasks = sum(record.task_count for record in records)
    total_worker_context = sum(record.worker_context_chars for record in records)
    image_records = [
        record
        for record in records
        if "image_relevant" in task_by_id[record.benchmark_id].scenario_tags
    ]
    image_agents = sum(record.image_agent_count for record in image_records)
    image_total_agents = sum(record.agent_count for record in image_records)
    return StrategyMetrics(
        agent_strategy=key[0],
        model_strategy=key[1],
        evidence_level=key[2],
        run_count=count,
        success_rate=_ratio(
            sum(record.status is BenchmarkRunStatus.PASSED for record in records), count
        ),
        localization_recall=_average(
            [
                _ratio(
                    len(
                        set(record.localization_candidates)
                        & set(task_by_id[record.benchmark_id].gold_paths)
                    ),
                    len(task_by_id[record.benchmark_id].gold_paths),
                )
                for record in records
            ]
        ),
        patch_efficiency=_ratio(
            sum(record.patch_applied and record.patch_authorized for record in generated),
            len(generated),
        ),
        regression_rate=_ratio(
            sum(not record.full_regression_passed for record in target_passed),
            len(target_passed),
        ),
        average_tokens=_average([float(record.total_tokens) for record in records]),
        average_duration_ms=_average([float(record.duration_ms) for record in records]),
        average_agent_count=_average([float(record.agent_count) for record in records]),
        invalid_task_rate=_ratio(sum(record.invalid_task_count for record in records), total_tasks),
        conflict_rate=_ratio(sum(record.conflict_count > 0 for record in records), count),
        orchestrator_context_ratio=_ratio(
            sum(record.orchestrator_context_chars for record in records),
            total_worker_context,
        ),
        initial_route_success_rate=_ratio(
            sum(record.initial_route_valid for record in records), count
        ),
        fallback_rate=_ratio(sum(record.fallback_count > 0 for record in records), count),
        difficulty_match_rate=_ratio(
            sum(
                record.predicted_difficulty is task_by_id[record.benchmark_id].human_difficulty
                for record in records
            ),
            count,
        ),
        image_success_rate=(
            _ratio(
                sum(record.status is BenchmarkRunStatus.PASSED for record in image_records),
                len(image_records),
            )
            if image_records
            else None
        ),
        original_image_exposure_rate=(
            _ratio(image_agents, image_total_agents) if image_total_agents else None
        ),
    )


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def _average(values: list[float]) -> float:
    return round(sum(values) / len(values), 3) if values else 0.0
