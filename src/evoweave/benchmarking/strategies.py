"""Benchmark-only Agent strategy controls using the same role-free TaskSpec protocol."""

from evoweave.application.adaptive_task_planner import (
    AdaptiveTaskPlan,
    AdaptiveTaskPlanner,
    TaskPlanner,
)
from evoweave.application.configuration import EvoWeaveConfig
from evoweave.benchmarking.models import AgentStrategy, ModelStrategy
from evoweave.domain.enums import InputModality, ModelTier, TaskDifficulty
from evoweave.domain.identifiers import SpecId, TaskId
from evoweave.domain.model_routing import (
    ModelProfile,
    ModelRequirement,
    ModelRoutingDecision,
)
from evoweave.domain.ports import ModelRouter
from evoweave.domain.repository_models import RepositoryProfile
from evoweave.domain.run_models import RunManifest
from evoweave.domain.task_spec import TaskSpec
from evoweave.infrastructure.models.rule_router import RuleBasedModelRouter


class FixedProfileModelRouter:
    """Keep capability constraints but remove adaptive difficulty-tier selection."""

    def __init__(self, strategy: ModelStrategy) -> None:
        if strategy is ModelStrategy.ADAPTIVE:
            raise ValueError("动态模型策略必须使用正式规则路由器")
        self._strategy = strategy
        self._delegate = RuleBasedModelRouter()

    def route(
        self,
        requirement: ModelRequirement,
        profiles: tuple[ModelProfile, ...],
    ) -> ModelRoutingDecision:
        fixed_requirement = requirement.model_copy(update={"difficulty": TaskDifficulty.LOW})
        decision = self._delegate.route(fixed_requirement, profiles)
        return decision.model_copy(
            update={
                "reason": (
                    f"benchmark {self._strategy.value} 对照固定使用单一模型；"
                    "输入模态、上下文、工具和结构化输出硬约束仍然生效"
                )
            }
        )


class SingleAgentTaskPlanner:
    def __init__(self, config: EvoWeaveConfig) -> None:
        self._delegate = AdaptiveTaskPlanner(config.model_copy(update={"max_dynamic_tasks": 1}))

    def plan(
        self,
        manifest: RunManifest,
        profile: RepositoryProfile,
    ) -> AdaptiveTaskPlan:
        base = self._delegate.plan(manifest, profile)
        return AdaptiveTaskPlan(
            task_specs=base.task_specs,
            rationale="单 Agent 对照：所有允许写范围合并为一个通用执行实例",
        )


class FixedMultiTaskPlanner:
    """Four-step fixed baseline; task functions are data, not product role classes."""

    def __init__(self, config: EvoWeaveConfig) -> None:
        self._single = SingleAgentTaskPlanner(config)

    def plan(
        self,
        manifest: RunManifest,
        profile: RepositoryProfile,
    ) -> AdaptiveTaskPlan:
        implementation_source = self._single.plan(manifest, profile).task_specs[0]
        exploration = _derived_task(
            implementation_source,
            goal="固定流水线步骤 1/4：读取仓库并总结需求相关证据，不修改文件",
            write_scope=(),
            depends_on=(),
            keep_input_modalities=True,
        )
        implementation = _derived_task(
            implementation_source,
            goal=(
                "固定流水线步骤 2/4：根据用户目标修改全部授权写范围；"
                f"原目标：{manifest.change_spec.objective}"
            ),
            write_scope=implementation_source.write_scope,
            depends_on=(exploration.task_id,),
            keep_input_modalities=True,
        )
        review = _derived_task(
            implementation_source,
            goal="固定流水线步骤 3/4：只读审查修改范围和验收条件，不修改文件",
            write_scope=(),
            depends_on=(implementation.task_id,),
            keep_input_modalities=False,
        )
        validation = _derived_task(
            implementation_source,
            goal="固定流水线步骤 4/4：只读检查测试与风险信息，不修改文件",
            write_scope=(),
            depends_on=(review.task_id,),
            keep_input_modalities=False,
        )
        return AdaptiveTaskPlan(
            task_specs=(exploration, implementation, review, validation),
            rationale="固定多 Agent 对照：始终创建四个串行通用实例",
        )


def planner_for_strategy(
    strategy: AgentStrategy,
    config: EvoWeaveConfig,
) -> TaskPlanner:
    if strategy is AgentStrategy.SINGLE:
        return SingleAgentTaskPlanner(config)
    if strategy is AgentStrategy.FIXED_MULTI:
        return FixedMultiTaskPlanner(config)
    return AdaptiveTaskPlanner(config)


def profiles_for_strategy(
    strategy: ModelStrategy,
    profiles: tuple[ModelProfile, ...],
) -> tuple[ModelProfile, ...]:
    if strategy is ModelStrategy.ADAPTIVE:
        return profiles
    target_tier = ModelTier.LOW if strategy is ModelStrategy.FIXED_LOW else ModelTier.HIGH
    candidates = tuple(
        sorted(
            (profile for profile in profiles if profile.tier is target_tier),
            key=lambda item: (
                InputModality.IMAGE not in item.input_modalities,
                item.stable_priority,
                item.key,
            ),
        )
    )
    return candidates[:1]


def router_for_strategy(strategy: ModelStrategy) -> ModelRouter:
    if strategy is ModelStrategy.ADAPTIVE:
        return RuleBasedModelRouter()
    return FixedProfileModelRouter(strategy)


def _derived_task(
    source: TaskSpec,
    *,
    goal: str,
    write_scope: tuple[str, ...],
    depends_on: tuple[TaskId, ...],
    keep_input_modalities: bool,
) -> TaskSpec:
    task_id = TaskId.new()
    modalities = source.required_modalities if keep_input_modalities else (InputModality.TEXT,)
    input_artifact_ids = source.input_artifact_ids if keep_input_modalities else ()
    requirement = ModelRequirement.model_validate(
        {
            **source.model_requirement.model_dump(),
            "requirement_id": SpecId.new(),
            "task_id": task_id,
            "required_modalities": modalities,
        }
    )
    return TaskSpec(
        spec_id=SpecId.new(),
        task_id=task_id,
        change_spec_id=source.change_spec_id,
        goal=goal,
        base_commit=source.base_commit,
        acceptance_criteria=source.acceptance_criteria,
        depends_on=depends_on,
        input_artifact_ids=input_artifact_ids,
        context_artifact_ids=source.context_artifact_ids,
        read_scope=source.read_scope,
        write_scope=write_scope,
        required_modalities=modalities,
        difficulty=source.difficulty,
        model_requirement=requirement,
        risk_level=source.risk_level,
    )
