"""Contract and rejection tests for controlled Pillow image ingestion."""

from io import BytesIO

import pytest
from PIL import Image

from evoweave.domain.artifacts import ImageIngestionPolicy, InputArtifactRef
from evoweave.domain.enums import ArtifactSecurityStatus
from evoweave.domain.errors import DomainError, ErrorCode
from evoweave.domain.ports import ImageInput, InputArtifactIngestor
from evoweave.infrastructure.artifacts.image_ingestor import PillowImageIngestor
from evoweave.infrastructure.artifacts.memory import InMemoryArtifactStore


def _image_bytes(
    *,
    image_format: str = "PNG",
    size: tuple[int, int] = (4, 3),
    frames: int = 1,
) -> bytes:
    buffer = BytesIO()
    images = [Image.new("RGB", size, color=(index, 20, 30)) for index in range(frames)]
    images[0].save(
        buffer,
        format=image_format,
        save_all=frames > 1,
        append_images=images[1:],
    )
    return buffer.getvalue()


def test_valid_png_is_decoded_hashed_and_persisted() -> None:
    store = InMemoryArtifactStore()
    ingestor = PillowImageIngestor(store)
    assert isinstance(ingestor, InputArtifactIngestor)
    data = _image_bytes()
    ref = ingestor.ingest_image(
        ImageInput(data=data, declared_media_type="image/png", original_name="ui.png"),
        policy=ImageIngestionPolicy(),
    )
    assert isinstance(store.get_ref(ref.artifact_id), InputArtifactRef)
    assert ref.security_status is ArtifactSecurityStatus.ACCEPTED
    assert (ref.width_px, ref.height_px) == (4, 3)
    assert store.get_bytes(ref.artifact_id) == data


def test_declared_mime_must_match_detected_content() -> None:
    with pytest.raises(DomainError) as error:
        PillowImageIngestor(InMemoryArtifactStore()).ingest_image(
            ImageInput(data=_image_bytes(), declared_media_type="image/jpeg"),
            policy=ImageIngestionPolicy(),
        )
    assert error.value.code is ErrorCode.IMAGE_REJECTED


def test_invalid_image_bytes_are_rejected() -> None:
    with pytest.raises(DomainError) as error:
        PillowImageIngestor(InMemoryArtifactStore()).ingest_image(
            ImageInput(data=b"not an image", declared_media_type="image/png"),
            policy=ImageIngestionPolicy(),
        )
    assert error.value.code is ErrorCode.IMAGE_REJECTED


def test_image_byte_limit_is_checked_before_decode() -> None:
    data = _image_bytes()
    with pytest.raises(DomainError, match="字节大小"):
        PillowImageIngestor(InMemoryArtifactStore()).ingest_image(
            ImageInput(data=data, declared_media_type="image/png"),
            policy=ImageIngestionPolicy(max_size_bytes=len(data) - 1),
        )


def test_image_pixel_limit_is_enforced() -> None:
    with pytest.raises(DomainError, match="像素"):
        PillowImageIngestor(InMemoryArtifactStore()).ingest_image(
            ImageInput(data=_image_bytes(size=(10, 10)), declared_media_type="image/png"),
            policy=ImageIngestionPolicy(max_pixels=99),
        )


def test_animated_image_is_rejected() -> None:
    with pytest.raises(DomainError, match="多帧"):
        PillowImageIngestor(InMemoryArtifactStore()).ingest_image(
            ImageInput(
                data=_image_bytes(image_format="GIF", frames=2),
                declared_media_type="image/gif",
            ),
            policy=ImageIngestionPolicy(allowed_media_types=("image/gif",)),
        )


def test_original_name_cannot_contain_path() -> None:
    with pytest.raises(DomainError, match="路径"):
        PillowImageIngestor(InMemoryArtifactStore()).ingest_image(
            ImageInput(
                data=_image_bytes(),
                declared_media_type="image/png",
                original_name="folder/ui.png",
            ),
            policy=ImageIngestionPolicy(),
        )
