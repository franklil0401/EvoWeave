"""Controlled in-memory image ingestion backed by Pillow decoding."""

import warnings
from io import BytesIO
from pathlib import PurePath

from PIL import Image, UnidentifiedImageError

from evoweave.domain.artifacts import ImageIngestionPolicy, InputArtifactRef
from evoweave.domain.enums import (
    ArtifactKind,
    ArtifactSecurityStatus,
    ArtifactSource,
)
from evoweave.domain.errors import DomainError, ErrorCode
from evoweave.domain.ports import ArtifactStore, ImageInput


class PillowImageIngestor:
    def __init__(self, artifact_store: ArtifactStore) -> None:
        self._artifact_store = artifact_store

    def ingest_image(
        self,
        image: ImageInput,
        *,
        policy: ImageIngestionPolicy,
    ) -> InputArtifactRef:
        if not image.data:
            raise DomainError(ErrorCode.IMAGE_REJECTED, "图片内容不能为空")
        if len(image.data) > policy.max_size_bytes:
            raise DomainError(ErrorCode.IMAGE_REJECTED, "图片字节大小超过摄取上限")
        declared_media_type = image.declared_media_type.lower().strip()
        if declared_media_type not in policy.allowed_media_types:
            raise DomainError(ErrorCode.IMAGE_REJECTED, "声明的图片 MIME 不在允许列表")
        if image.original_name and PurePath(image.original_name).name != image.original_name:
            raise DomainError(ErrorCode.IMAGE_REJECTED, "图片原始名称不能包含路径")

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(image.data)) as candidate:
                    detected_media_type = candidate.get_format_mimetype()
                    width, height = candidate.size
                    frame_count = getattr(candidate, "n_frames", 1)
                    candidate.verify()
                with Image.open(BytesIO(image.data)) as decoded:
                    decoded.load()
        except (
            UnidentifiedImageError,
            OSError,
            SyntaxError,
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
        ) as exc:
            raise DomainError(ErrorCode.IMAGE_REJECTED, "图片无法安全解码") from exc

        if detected_media_type is None or detected_media_type not in policy.allowed_media_types:
            raise DomainError(ErrorCode.IMAGE_REJECTED, "实际图片格式不在允许列表")
        if detected_media_type != declared_media_type:
            raise DomainError(ErrorCode.IMAGE_REJECTED, "声明 MIME 与实际图片格式不一致")
        if width * height > policy.max_pixels:
            raise DomainError(ErrorCode.IMAGE_REJECTED, "图片像素数量超过摄取上限")
        if width < policy.min_width_px or height < policy.min_height_px:
            raise DomainError(
                ErrorCode.IMAGE_REJECTED,
                "图片宽高低于模型兼容下限",
                details={
                    "width_px": width,
                    "height_px": height,
                    "min_width_px": policy.min_width_px,
                    "min_height_px": policy.min_height_px,
                },
            )
        if frame_count != 1:
            raise DomainError(ErrorCode.IMAGE_REJECTED, "第一版不接受多帧或动画图片")

        base_ref = self._artifact_store.put_bytes(
            image.data,
            media_type=detected_media_type,
            kind=ArtifactKind.INPUT_IMAGE,
        )
        input_ref = InputArtifactRef(
            **base_ref.model_dump(),
            source=ArtifactSource.CONTROLLED_INGESTION,
            security_status=ArtifactSecurityStatus.ACCEPTED,
            original_name=image.original_name,
            width_px=width,
            height_px=height,
        )
        self._artifact_store.update_ref(input_ref)
        return input_ref
