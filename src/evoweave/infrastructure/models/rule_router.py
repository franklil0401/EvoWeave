"""Deterministic model router driven by hard capabilities and task difficulty."""

from datetime import datetime

from pydantic import Field

from evoweave.domain.base import DomainModel
from evoweave.domain.enums import ModelAvailability, ModelTier, TaskDifficulty
from evoweave.domain.errors import DomainError, ErrorCode
from evoweave.domain.identifiers import SpecId
from evoweave.domain.model_routing import (
    ModelCandidateRejection,
    ModelProfile,
    ModelRequirement,
    ModelRoutingDecision,
)

_TIER_RANK = {ModelTier.LOW: 0, ModelTier.MEDIUM: 1, ModelTier.HIGH: 2}
_REQUIRED_TIER = {
    TaskDifficulty.LOW: ModelTier.LOW,
    TaskDifficulty.MEDIUM: ModelTier.MEDIUM,
    TaskDifficulty.HIGH: ModelTier.HIGH,
}


class RoutingPolicy(DomainModel):
    provider_priority: tuple[str, ...] = ()
    max_fallbacks: int = Field(default=3, ge=0, le=20)


class RuleBasedModelRouter:
    def __init__(self, policy: RoutingPolicy | None = None) -> None:
        self._policy = policy or RoutingPolicy()

    def route(
        self,
        requirement: ModelRequirement,
        profiles: tuple[ModelProfile, ...],
    ) -> ModelRoutingDecision:
        minimum_tier = _REQUIRED_TIER[requirement.difficulty]
        rejected: list[ModelCandidateRejection] = []
        hard_eligible: list[ModelProfile] = []
        for profile in sorted(profiles, key=lambda item: item.key):
            reasons = hard_constraint_violations(requirement, profile)
            if reasons:
                rejected.append(
                    ModelCandidateRejection(model_key=profile.key, reasons=tuple(reasons))
                )
            else:
                hard_eligible.append(profile)
        primary_eligible = [
            profile
            for profile in hard_eligible
            if _TIER_RANK[profile.tier] >= _TIER_RANK[minimum_tier]
        ]
        if not primary_eligible:
            raise DomainError(
                ErrorCode.MODEL_CAPABILITY_MISMATCH,
                "没有满足任务硬约束和难度档位的模型",
                details={"task_id": str(requirement.task_id)},
            )

        ordered = sorted(
            primary_eligible,
            key=lambda profile: self._sort_key(profile, minimum_tier),
        )
        selected, *remaining = ordered
        lower_tier = sorted(
            (
                profile
                for profile in hard_eligible
                if _TIER_RANK[profile.tier] < _TIER_RANK[minimum_tier]
            ),
            key=self._fallback_sort_key,
        )
        fallbacks = [*remaining, *lower_tier][: self._policy.max_fallbacks]
        snapshot_at = _latest_checked_at([selected, *fallbacks])
        downgrade_note = (
            "；故障回退可降档但不得放宽输入模态、上下文、工具和结构化输出硬约束"
            if lower_tier
            else ""
        )
        return ModelRoutingDecision(
            decision_id=SpecId.new(),
            requirement_id=requirement.requirement_id,
            requirement_version=requirement.version,
            selected_model_key=selected.key,
            selected_snapshot=selected.snapshot,
            reason=(
                f"任务难度为 {requirement.difficulty.value}，选择满足全部硬约束的"
                f" {selected.tier.value} 档最高优先级模型{downgrade_note}"
            ),
            fallback_model_keys=tuple(profile.key for profile in fallbacks),
            rejected_candidates=tuple(rejected),
            capability_snapshot_at=snapshot_at,
            version=1,
        )

    def _sort_key(
        self, profile: ModelProfile, minimum_tier: ModelTier
    ) -> tuple[int, int, int, str]:
        provider_order = {name: index for index, name in enumerate(self._policy.provider_priority)}
        tier_distance = _TIER_RANK[profile.tier] - _TIER_RANK[minimum_tier]
        provider_priority = provider_order.get(profile.provider, len(provider_order))
        return (tier_distance, profile.stable_priority, provider_priority, profile.key)

    def _fallback_sort_key(self, profile: ModelProfile) -> tuple[int, int, int, str]:
        provider_order = {name: index for index, name in enumerate(self._policy.provider_priority)}
        provider_priority = provider_order.get(profile.provider, len(provider_order))
        return (-_TIER_RANK[profile.tier], profile.stable_priority, provider_priority, profile.key)


def hard_constraint_violations(
    requirement: ModelRequirement,
    profile: ModelProfile,
) -> tuple[str, ...]:
    """Return deterministic capability violations without considering price or tier."""

    reasons: list[str] = []
    if profile.availability is not ModelAvailability.AVAILABLE:
        reasons.append("模型当前不可用")
    missing_modalities = set(requirement.required_modalities) - set(profile.input_modalities)
    if missing_modalities:
        missing = ",".join(sorted(item.value for item in missing_modalities))
        reasons.append(f"缺少输入模态：{missing}")
    if profile.context_window_tokens < requirement.min_context_tokens:
        reasons.append("上下文窗口不足")
    if profile.max_output_tokens < requirement.min_output_tokens:
        reasons.append("最大输出不足")
    if requirement.requires_tool_calling and not profile.supports_tool_calling:
        reasons.append("不支持工具调用")
    if requirement.requires_structured_output and not profile.supports_structured_output:
        reasons.append("不支持结构化输出")
    if requirement.requires_thinking and not profile.supports_thinking:
        reasons.append("不支持思考模式")
    return tuple(reasons)


def _latest_checked_at(profiles: list[ModelProfile]) -> datetime:
    checked = [profile.checked_at for profile in profiles if profile.checked_at is not None]
    if not checked:
        raise DomainError(ErrorCode.MODEL_UNAVAILABLE, "合格模型缺少可用性检查时间")
    return max(checked)
