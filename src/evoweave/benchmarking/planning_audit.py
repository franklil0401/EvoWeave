"""Run all locked tasks through the real repository profiler and task planners only."""

import base64
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path

from pydantic import Field

from evoweave.application.analysis_service import AnalysisService
from evoweave.application.configuration import EvoWeaveConfig
from evoweave.application.intake_service import IntakeService
from evoweave.application.run_state import JsonRunStateStore
from evoweave.application.runtime_layout import RuntimeLayout
from evoweave.benchmarking.materializer import FixtureMaterializer
from evoweave.benchmarking.models import (
    AgentStrategy,
    BenchmarkInputArtifact,
    BenchmarkSuite,
)
from evoweave.benchmarking.strategies import planner_for_strategy
from evoweave.domain.base import DomainModel
from evoweave.domain.enums import InputModality, RiskLevel, TaskDifficulty
from evoweave.domain.repository_models import difficulty_rank
from evoweave.infrastructure.artifacts.image_ingestor import PillowImageIngestor
from evoweave.infrastructure.artifacts.local_store import LocalArtifactStore


class PlanningAuditRecord(DomainModel):
    benchmark_id: str
    agent_strategy: AgentStrategy
    agent_count: int = Field(ge=1)
    writable_agent_count: int = Field(ge=0)
    dependency_count: int = Field(ge=0)
    image_agent_count: int = Field(ge=0)
    high_risk_task_count: int = Field(ge=0)
    human_difficulty: TaskDifficulty
    predicted_difficulty: TaskDifficulty
    difficulty_match: bool
    predicted_difficulties: tuple[TaskDifficulty, ...]
    rationale: str


class PlanningAuditReport(DomainModel):
    suite_id: str
    suite_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_count: int = Field(ge=12)
    records: tuple[PlanningAuditRecord, ...]


class PlanningAuditRunner:
    def __init__(self, project_root: Path | str, config: EvoWeaveConfig | None = None) -> None:
        self._project_root = Path(project_root).resolve(strict=True)
        self._config = config or EvoWeaveConfig(runtime_directory=".runtime-audit")
        self._materializer = FixtureMaterializer(self._project_root)

    def run(self, suite: BenchmarkSuite, suite_sha256: str) -> PlanningAuditReport:
        records: list[PlanningAuditRecord] = []
        with tempfile.TemporaryDirectory(prefix="evoweave-planning-audit-") as temporary:
            temporary_root = Path(temporary)
            for task in suite.tasks:
                repository = self._materializer.materialize(
                    task,
                    temporary_root / task.benchmark_id / "repository",
                ).path
                layout = RuntimeLayout.create(repository, self._config)
                artifact_store = LocalArtifactStore(layout.artifacts)
                image_paths = _decode_images(
                    self._project_root,
                    task.input_artifacts,
                    temporary_root / task.benchmark_id / "inputs",
                )
                change = IntakeService(PillowImageIngestor(artifact_store)).create(
                    repository=repository,
                    objective=task.objective,
                    acceptance_criteria=task.acceptance_criteria,
                    allowed_paths=task.allowed_paths,
                    forbidden_paths=task.forbidden_paths,
                    image_paths=image_paths,
                )
                manifest, profile = AnalysisService(
                    run_store=JsonRunStateStore(layout.run_state),
                    artifact_store=artifact_store,
                ).analyze(change)
                for strategy in AgentStrategy:
                    plan = planner_for_strategy(strategy, self._config).plan(
                        manifest,
                        profile,
                    )
                    predicted_difficulties = tuple(
                        item.difficulty.difficulty for item in plan.task_specs
                    )
                    predicted_difficulty = max(
                        predicted_difficulties,
                        key=difficulty_rank,
                    )
                    records.append(
                        PlanningAuditRecord(
                            benchmark_id=task.benchmark_id,
                            agent_strategy=strategy,
                            agent_count=len(plan.task_specs),
                            writable_agent_count=sum(
                                bool(item.write_scope) for item in plan.task_specs
                            ),
                            dependency_count=sum(len(item.depends_on) for item in plan.task_specs),
                            image_agent_count=sum(
                                InputModality.IMAGE in item.required_modalities
                                for item in plan.task_specs
                            ),
                            high_risk_task_count=sum(
                                item.risk_level is RiskLevel.HIGH for item in plan.task_specs
                            ),
                            human_difficulty=task.human_difficulty,
                            predicted_difficulty=predicted_difficulty,
                            difficulty_match=predicted_difficulty is task.human_difficulty,
                            predicted_difficulties=predicted_difficulties,
                            rationale=plan.rationale,
                        )
                    )
        return PlanningAuditReport(
            suite_id=suite.suite_id,
            suite_sha256=suite_sha256,
            task_count=len(suite.tasks),
            records=tuple(records),
        )


class PlanningAuditWriter:
    def write(
        self,
        report: PlanningAuditReport,
        output_root: Path | str,
    ) -> tuple[Path, Path]:
        root = Path(output_root).resolve()
        root.mkdir(parents=True, exist_ok=True)
        markdown_path = root / "规划审计报告.md"
        json_path = root / "规划审计报告.json"
        adaptive = tuple(
            item for item in report.records if item.agent_strategy is AgentStrategy.ADAPTIVE
        )
        simple = next(item for item in adaptive if item.benchmark_id == "bench-01-single-file")
        negative = next(item for item in adaptive if item.benchmark_id == "bench-11-image-negative")
        image_records = tuple(
            item
            for item in adaptive
            if item.benchmark_id in {"bench-09-image-ui", "bench-10-image-architecture"}
        )
        image_agent_count = sum(item.image_agent_count for item in image_records)
        difficulty_match_count = sum(item.difficulty_match for item in adaptive)
        difficulty_match_rate = difficulty_match_count / len(adaptive)
        lines = [
            "# EvoWeave 规划审计报告",
            "",
            f"- 任务集：`{report.suite_id}`",
            f"- 任务集 SHA-256：`{report.suite_sha256}`",
            f"- 固定任务：{report.task_count}",
            f"- 规划记录：{len(report.records)}（每个任务 × 3 种 Agent 策略）",
            "",
            "## 关键结论",
            "",
            f"- 简单任务动态实例数：{simple.agent_count}",
            f"- 两个读图任务接收图片的动态 Agent 数：{image_agent_count}",
            f"- 图片负例接收原图的动态 Agent 数：{negative.image_agent_count}",
            (
                "- 动态难度与冻结人工标签一致："
                f"{difficulty_match_count}/{len(adaptive)}（{difficulty_match_rate:.1%}）"
            ),
            "- 本报告只审计仓库画像、任务数、DAG、风险和图片暴露，不包含模型成功率。",
            "",
            "## 三种 Agent 策略总体对照",
            "",
            "| 策略 | 记录数 | 平均 Agent | 平均可写 Agent | 依赖总数 | 原图暴露 Agent |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for strategy in AgentStrategy:
            strategy_records = tuple(
                item for item in report.records if item.agent_strategy is strategy
            )
            lines.append(
                f"| {strategy.value} | {len(strategy_records)} | "
                f"{_average(item.agent_count for item in strategy_records):.2f} | "
                f"{_average(item.writable_agent_count for item in strategy_records):.2f} | "
                f"{sum(item.dependency_count for item in strategy_records)} | "
                f"{sum(item.image_agent_count for item in strategy_records)} |"
            )
        lines.extend(
            (
                "",
                "## 动态策略逐任务拓扑",
                "",
                "| 任务 | Agent | 可写 | 依赖 | 图片 Agent | 高风险任务 | "
                "人工难度 | 预测难度 | 匹配 | 分任务难度 |",
                "|---|---:|---:|---:|---:|---:|---|---|:---:|---|",
            )
        )
        lines.extend(
            f"| {item.benchmark_id} | {item.agent_count} | "
            f"{item.writable_agent_count} | {item.dependency_count} | "
            f"{item.image_agent_count} | {item.high_risk_task_count} | "
            f"{item.human_difficulty.value} | {item.predicted_difficulty.value} | "
            f"{'是' if item.difficulty_match else '否'} | "
            f"{','.join(value.value for value in item.predicted_difficulties)} |"
            for item in adaptive
        )
        lines.append("")
        markdown = "\n".join(lines)
        _atomic_text(markdown_path, markdown)
        _atomic_text(json_path, report.model_dump_json(indent=2))
        return markdown_path, json_path


def _decode_images(
    project_root: Path,
    artifacts: tuple[BenchmarkInputArtifact, ...],
    output_root: Path,
) -> tuple[Path, ...]:
    paths: list[Path] = []
    for index, artifact in enumerate(artifacts):
        source = (project_root / artifact.source).resolve(strict=True)
        if not source.is_relative_to(project_root):
            raise ValueError("benchmark 图片路径越界")
        data = base64.b64decode(source.read_text(encoding="ascii").strip(), validate=True)
        output_root.mkdir(parents=True, exist_ok=True)
        destination = output_root / f"input-{index}.png"
        destination.write_bytes(data)
        paths.append(destination)
    return tuple(paths)


def _atomic_text(path: Path, content: str) -> None:
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _average(values: Iterable[int]) -> float:
    items = tuple(values)
    return sum(items) / len(items) if items else 0.0
