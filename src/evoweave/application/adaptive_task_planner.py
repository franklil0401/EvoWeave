"""Evidence-backed task count, modality, and dependency planning without fixed roles."""

from dataclasses import dataclass
from typing import Protocol

from evoweave.application.configuration import EvoWeaveConfig
from evoweave.domain.enums import InputModality, RiskLevel, TaskDifficulty
from evoweave.domain.identifiers import SpecId, TaskId
from evoweave.domain.repository_models import (
    RepositoryFile,
    RepositoryProfile,
    RepositoryTaskAssessment,
    difficulty_rank,
)
from evoweave.domain.run_models import RunManifest
from evoweave.domain.task_spec import TaskSpec
from evoweave.domain.validation import path_is_within_scopes
from evoweave.repository.git_inspector import GitInspector
from evoweave.repository.impact_analysis import (
    RepositoryDifficultyAssessor,
    RepositoryImpactAnalyzer,
)

_VISUAL_PATH_MARKERS = (
    "frontend",
    "template",
    "style",
    "view",
    "web",
    "ui",
)
_VISUAL_SUFFIXES = (".css", ".html", ".jsx", ".scss", ".svelte", ".tsx", ".vue")
_VISUAL_OBJECTIVE_TERMS = ("ui", "原型", "图片", "图像", "截图", "架构图", "界面", "视觉")
_IMAGE_NEGATIVE_TERMS = ("与任务无关", "不需要读图", "忽略图片", "无需图片", "无关图片")
_HIGH_COMPLEXITY_TERMS = (
    "架构",
    "数据流",
    "冲突",
    "迁移",
    "并发",
    "权限",
    "安全",
    "支付",
    "已有失败",
)


@dataclass(frozen=True, slots=True)
class AdaptiveTaskPlan:
    task_specs: tuple[TaskSpec, ...]
    rationale: str

    @property
    def agent_count(self) -> int:
        return len(self.task_specs)


class TaskPlanner(Protocol):
    def plan(
        self,
        manifest: RunManifest,
        profile: RepositoryProfile,
    ) -> AdaptiveTaskPlan: ...


class AdaptiveTaskPlanner:
    def __init__(self, config: EvoWeaveConfig) -> None:
        self._config = config

    def plan(
        self,
        manifest: RunManifest,
        profile: RepositoryProfile,
    ) -> AdaptiveTaskPlan:
        change = manifest.change_spec
        groups = _write_groups(
            change.allowed_paths,
            profile.files,
            max_tasks=self._config.max_dynamic_tasks,
            split_directory_lines=self._config.split_directory_lines,
        )
        task_ids = tuple(TaskId.new() for _ in groups)
        visual_groups = _visual_group_indexes(
            groups,
            bool(change.input_artifacts),
            change.objective,
        )
        difficulty_floor, floor_reasons = _task_structure_difficulty_floor(
            objective=change.objective,
            acceptance_criteria=change.acceptance_criteria,
            allowed_paths=change.allowed_paths,
            groups=groups,
            files=profile.files,
        )
        readable_paths = tuple(item.path for item in profile.files if item.line_count > 0)
        context_artifacts = (
            (manifest.repository_profile_artifact_id,)
            if manifest.repository_profile_artifact_id is not None
            else ()
        )
        inspector = GitInspector(change.repository, change.base_commit)
        specs: list[TaskSpec] = []
        for index, (task_id, write_scope) in enumerate(zip(task_ids, groups, strict=True)):
            goal = (
                f"{change.objective}\n"
                f"本任务只负责写范围：{', '.join(write_scope)}；"
                "可以读取授权仓库证据，但不得修改其他路径。"
            )
            modalities = (
                (InputModality.TEXT, InputModality.IMAGE)
                if index in visual_groups
                else (InputModality.TEXT,)
            )
            impact = RepositoryImpactAnalyzer().analyze(
                inspector=inspector,
                profile=profile,
                objective=goal,
                acceptance_criteria=change.acceptance_criteria,
            )
            assessment = RepositoryDifficultyAssessor().assess(
                task_id=task_id,
                impact=impact,
                required_modalities=modalities,
            )
            assessment = _apply_difficulty_floor(
                assessment,
                minimum=difficulty_floor,
                reasons=floor_reasons,
            )
            read_scope = tuple(dict.fromkeys((*readable_paths, *write_scope)))
            specs.append(
                TaskSpec(
                    spec_id=SpecId.new(),
                    task_id=task_id,
                    change_spec_id=change.spec_id,
                    goal=goal,
                    base_commit=change.base_commit,
                    acceptance_criteria=change.acceptance_criteria,
                    input_artifact_ids=(
                        tuple(item.artifact_id for item in change.input_artifacts)
                        if InputModality.IMAGE in modalities
                        else ()
                    ),
                    context_artifact_ids=context_artifacts,
                    read_scope=read_scope,
                    write_scope=write_scope,
                    required_modalities=modalities,
                    difficulty=assessment.difficulty,
                    model_requirement=assessment.model_requirement,
                    risk_level=_risk_level(
                        assessment.difficulty.difficulty,
                        assessment.impact.risk_signals,
                    ),
                )
            )

        dependencies = _task_dependencies(groups, task_ids, profile)
        planned = tuple(
            spec.model_copy(update={"depends_on": dependencies[index]})
            for index, spec in enumerate(specs)
        )
        relation_count = sum(len(item.depends_on) for item in planned)
        rationale = (
            f"按 {len(change.allowed_paths)} 个用户写范围、固定 commit 文件规模和模块依赖，"
            f"生成 {len(planned)} 个临时任务、{relation_count} 条依赖；"
            f"其中 {len(visual_groups)} 个任务接收图片。"
        )
        return AdaptiveTaskPlan(task_specs=planned, rationale=rationale)


def _task_structure_difficulty_floor(
    *,
    objective: str,
    acceptance_criteria: tuple[str, ...],
    allowed_paths: tuple[str, ...],
    groups: tuple[tuple[str, ...], ...],
    files: tuple[RepositoryFile, ...],
) -> tuple[TaskDifficulty, tuple[str, ...]]:
    reasons: list[str] = []
    minimum = TaskDifficulty.LOW
    if len(groups) >= 2:
        minimum = TaskDifficulty.MEDIUM
        reasons.append("任务需要协调多个独立写范围")
    broad_scopes = tuple(scope for scope in allowed_paths if _is_broad_scope(scope, files))
    if broad_scopes:
        minimum = TaskDifficulty.HIGH
        reasons.append("用户授权的是目录或宽泛范围：" + "、".join(broad_scopes))
    text = "\n".join((objective, *acceptance_criteria)).casefold()
    matched_terms = tuple(term for term in _HIGH_COMPLEXITY_TERMS if term in text)
    if matched_terms:
        minimum = TaskDifficulty.HIGH
        reasons.append("需求包含高复杂度语义：" + "、".join(matched_terms))
    return minimum, tuple(reasons)


def _is_broad_scope(scope: str, files: tuple[RepositoryFile, ...]) -> bool:
    if any(item.path == scope for item in files):
        return False
    descendants = tuple(item for item in files if path_is_within_scopes(item.path, (scope,)))
    leaf = scope.rsplit("/", 1)[-1]
    return len(descendants) >= 2 or "." not in leaf


def _apply_difficulty_floor(
    assessment: RepositoryTaskAssessment,
    *,
    minimum: TaskDifficulty,
    reasons: tuple[str, ...],
) -> RepositoryTaskAssessment:
    current = assessment.difficulty.difficulty
    if difficulty_rank(current) >= difficulty_rank(minimum):
        return assessment
    context_tokens = {
        TaskDifficulty.LOW: 8_000,
        TaskDifficulty.MEDIUM: 32_000,
        TaskDifficulty.HIGH: 64_000,
    }[minimum]
    output_tokens = {
        TaskDifficulty.LOW: 2_000,
        TaskDifficulty.MEDIUM: 4_000,
        TaskDifficulty.HIGH: 8_000,
    }[minimum]
    rationale = assessment.difficulty.rationale + "；结构性难度下限：" + "；".join(reasons)
    difficulty = assessment.difficulty.model_copy(
        update={"difficulty": minimum, "rationale": rationale}
    )
    requirement = assessment.model_requirement.model_copy(
        update={
            "difficulty": minimum,
            "min_context_tokens": context_tokens,
            "min_output_tokens": output_tokens,
            "requires_thinking": minimum is TaskDifficulty.HIGH,
        }
    )
    return assessment.model_copy(
        update={"difficulty": difficulty, "model_requirement": requirement}
    )


def _write_groups(
    allowed_paths: tuple[str, ...],
    files: tuple[RepositoryFile, ...],
    *,
    max_tasks: int,
    split_directory_lines: int,
) -> tuple[tuple[str, ...], ...]:
    collapsed = tuple(
        scope
        for scope in allowed_paths
        if not any(
            scope != other and path_is_within_scopes(scope, (other,)) for other in allowed_paths
        )
    )
    expanded: list[str] = []
    for scope in collapsed:
        exact = next((item for item in files if item.path == scope), None)
        candidates = tuple(
            item
            for item in files
            if item.line_count > 0 and path_is_within_scopes(item.path, (scope,))
        )
        if (
            exact is None
            and len(candidates) >= 2
            and sum(item.line_count for item in candidates) >= split_directory_lines
        ):
            expanded.extend(item.path for item in candidates)
        else:
            expanded.append(scope)
    scopes = tuple(dict.fromkeys(expanded))
    if len(scopes) <= max_tasks:
        return tuple((scope,) for scope in scopes)

    line_counts = {item.path: item.line_count for item in files}
    buckets: list[list[str]] = [[] for _ in range(max_tasks)]
    weights = [0] * max_tasks
    for scope in sorted(scopes, key=lambda item: (-line_counts.get(item, 1), item)):
        target = min(range(max_tasks), key=lambda index: (weights[index], index))
        buckets[target].append(scope)
        weights[target] += line_counts.get(scope, 1)
    return tuple(tuple(sorted(bucket)) for bucket in buckets if bucket)


def _visual_group_indexes(
    groups: tuple[tuple[str, ...], ...],
    has_images: bool,
    objective: str,
) -> frozenset[int]:
    if not has_images:
        return frozenset()
    folded_objective = objective.casefold()
    if any(term in folded_objective for term in _IMAGE_NEGATIVE_TERMS):
        return frozenset()
    matched = {
        index
        for index, scopes in enumerate(groups)
        if any(_is_visual_path(scope) for scope in scopes)
    }
    if matched:
        return frozenset(matched)
    if any(term in folded_objective for term in _VISUAL_OBJECTIVE_TERMS):
        return frozenset({0})
    return frozenset()


def _is_visual_path(path: str) -> bool:
    folded = path.casefold()
    parts = folded.replace(".", "/").split("/")
    return folded.endswith(_VISUAL_SUFFIXES) or any(
        marker in parts for marker in _VISUAL_PATH_MARKERS
    )


def _risk_level(
    difficulty: TaskDifficulty,
    risk_signals: tuple[str, ...],
) -> RiskLevel:
    if risk_signals:
        return RiskLevel.HIGH
    if difficulty is TaskDifficulty.HIGH:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def _task_dependencies(
    groups: tuple[tuple[str, ...], ...],
    task_ids: tuple[TaskId, ...],
    profile: RepositoryProfile,
) -> tuple[tuple[TaskId, ...], ...]:
    module_to_group: dict[str, int] = {}
    for file in profile.files:
        if file.module_name is None:
            continue
        group_index = next(
            (
                index
                for index, scopes in enumerate(groups)
                if path_is_within_scopes(file.path, scopes)
            ),
            None,
        )
        if group_index is not None:
            module_to_group[file.module_name] = group_index

    candidates = {
        (module_to_group[edge.imported_module], module_to_group[edge.importer_module])
        for edge in profile.dependencies
        if edge.imported_module in module_to_group
        and edge.importer_module in module_to_group
        and module_to_group[edge.imported_module] != module_to_group[edge.importer_module]
    }
    accepted: set[tuple[int, int]] = set()
    for source, target in sorted(candidates, key=lambda item: (groups[item[0]], groups[item[1]])):
        if not _would_create_cycle(accepted, source, target):
            accepted.add((source, target))
    return tuple(
        tuple(task_ids[source] for source, target in sorted(accepted) if target == index)
        for index in range(len(groups))
    )


def _would_create_cycle(
    edges: set[tuple[int, int]],
    source: int,
    target: int,
) -> bool:
    frontier = [target]
    visited: set[int] = set()
    while frontier:
        current = frontier.pop()
        if current == source:
            return True
        if current in visited:
            continue
        visited.add(current)
        frontier.extend(edge_target for edge_source, edge_target in edges if edge_source == current)
    return False
