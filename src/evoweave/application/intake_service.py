"""Convert CLI inputs and controlled images into one immutable ChangeSpec."""

import mimetypes
from pathlib import Path

from evoweave.domain.artifacts import ImageIngestionPolicy
from evoweave.domain.change_spec import ChangeSpec
from evoweave.domain.identifiers import RunId, SpecId
from evoweave.domain.ports import ImageInput, InputArtifactIngestor
from evoweave.repository.git_inspector import GitInspector


class IntakeService:
    def __init__(self, image_ingestor: InputArtifactIngestor | None = None) -> None:
        self._image_ingestor = image_ingestor

    def create(
        self,
        *,
        repository: Path | str,
        objective: str,
        acceptance_criteria: tuple[str, ...],
        allowed_paths: tuple[str, ...] = (),
        forbidden_paths: tuple[str, ...] = (),
        image_paths: tuple[Path, ...] = (),
    ) -> ChangeSpec:
        inspector = GitInspector(repository)
        artifacts = []
        if image_paths and self._image_ingestor is None:
            raise ValueError("提供图片时必须配置受控图片摄取器")
        for path in image_paths:
            media_type, _encoding = mimetypes.guess_type(path.name)
            if media_type is None:
                raise ValueError(f"无法识别图片 MIME：{path.name}")
            assert self._image_ingestor is not None
            artifacts.append(
                self._image_ingestor.ingest_image(
                    ImageInput(
                        data=path.read_bytes(),
                        declared_media_type=media_type,
                        original_name=path.name,
                    ),
                    policy=ImageIngestionPolicy(),
                )
            )
        run_id = RunId.new()
        return ChangeSpec(
            spec_id=SpecId.new(),
            run_id=run_id,
            objective=objective,
            repository=str(inspector.repository_root),
            base_commit=inspector.base_commit,
            acceptance_criteria=acceptance_criteria,
            allowed_paths=allowed_paths,
            forbidden_paths=forbidden_paths,
            input_artifacts=tuple(artifacts),
        )
