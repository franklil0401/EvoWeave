"""Build minimal worker context and gate raw image attachment exposure."""

from dataclasses import dataclass

from pydantic import Field

from evoweave.domain.agent_execution_spec import AgentExecutionSpec
from evoweave.domain.artifacts import InputArtifactRef
from evoweave.domain.base import DomainModel
from evoweave.domain.enums import (
    ArtifactKind,
    ArtifactSecurityStatus,
    InputModality,
)
from evoweave.domain.errors import DomainError, ErrorCode
from evoweave.domain.identifiers import ArtifactId
from evoweave.domain.ports import ArtifactStore, ModelAttachment


class ContextPolicy(DomainModel):
    max_text_chars: int = Field(default=100_000, ge=1)
    max_artifact_bytes: int = Field(default=10 * 1024 * 1024, ge=1)
    max_image_attachments: int = Field(default=4, ge=0, le=20)


@dataclass(frozen=True, slots=True)
class ContextBundle:
    text: str
    attachments: tuple[ModelAttachment, ...]
    included_artifact_ids: tuple[ArtifactId, ...]
    excluded_image_artifact_ids: tuple[ArtifactId, ...]


class ContextBuilder:
    def __init__(
        self,
        artifact_store: ArtifactStore,
        policy: ContextPolicy | None = None,
    ) -> None:
        self._artifact_store = artifact_store
        self._policy = policy or ContextPolicy()

    def build(self, spec: AgentExecutionSpec) -> ContextBundle:
        sections = [
            f"任务目标：{spec.goal}",
            "验收条件：\n- " + "\n- ".join(spec.acceptance_criteria),
            "已授权能力：" + ", ".join(spec.tool_names),
        ]
        attachments: list[ModelAttachment] = []
        included: list[ArtifactId] = []
        excluded_images: list[ArtifactId] = []
        total_artifact_bytes = 0
        artifact_ids = spec.context_artifact_ids + spec.input_artifact_ids
        for artifact_id in artifact_ids:
            ref = self._artifact_store.get_ref(artifact_id)
            data = self._artifact_store.get_bytes(artifact_id)
            total_artifact_bytes += len(data)
            if total_artifact_bytes > self._policy.max_artifact_bytes:
                raise DomainError(
                    ErrorCode.CONTEXT_LIMIT_EXCEEDED,
                    "上下文产物字节数超过上限",
                )
            if ref.kind is ArtifactKind.INPUT_IMAGE:
                self._validate_input_image(ref)
                if InputModality.IMAGE in spec.required_modalities:
                    attachments.append(
                        ModelAttachment(
                            artifact_id=artifact_id,
                            media_type=ref.media_type,
                            data=data,
                        )
                    )
                    included.append(artifact_id)
                else:
                    excluded_images.append(artifact_id)
                continue
            if ref.media_type.startswith("text/") or ref.media_type == "application/json":
                try:
                    content = data.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise DomainError(
                        ErrorCode.CONTEXT_LIMIT_EXCEEDED,
                        f"文本产物不是有效 UTF-8：{artifact_id}",
                    ) from exc
                sections.append(f"产物 {artifact_id}：\n{content}")
                included.append(artifact_id)
            else:
                sections.append(
                    f"二进制产物引用：{artifact_id}，MIME={ref.media_type}，SHA256={ref.sha256}"
                )
                included.append(artifact_id)

        if len(attachments) > self._policy.max_image_attachments:
            raise DomainError(ErrorCode.CONTEXT_LIMIT_EXCEEDED, "图片附件数量超过上限")
        text = "\n\n".join(sections)
        if len(text) > self._policy.max_text_chars:
            raise DomainError(ErrorCode.CONTEXT_LIMIT_EXCEEDED, "文本上下文字符数超过上限")
        return ContextBundle(
            text=text,
            attachments=tuple(attachments),
            included_artifact_ids=tuple(included),
            excluded_image_artifact_ids=tuple(excluded_images),
        )

    @staticmethod
    def _validate_input_image(ref: object) -> None:
        if not isinstance(ref, InputArtifactRef):
            raise DomainError(ErrorCode.IMAGE_REJECTED, "图片缺少受控摄取元数据")
        if ref.security_status is not ArtifactSecurityStatus.ACCEPTED:
            raise DomainError(ErrorCode.IMAGE_REJECTED, "图片没有通过安全摄取")
