import subprocess
from collections.abc import Callable
from pathlib import Path

from evoweave.domain.enums import InputModality, TaskDifficulty
from evoweave.domain.identifiers import TaskId
from evoweave.repository.baseline_runner import (
    BaselineExecution,
    BaselineRunner,
    ScriptedBaselineExecutor,
    existing_failure_ids,
)
from evoweave.repository.git_inspector import GitInspector
from evoweave.repository.impact_analysis import (
    RepositoryDifficultyAssessor,
    RepositoryImpactAnalyzer,
)
from evoweave.repository.profile_builder import RepositoryProfiler


def test_baseline_records_preexisting_failure_without_patch_attribution(
    committed_repository: Callable[[str], Path],
) -> None:
    repository = committed_repository("baseline_failure")
    executor = ScriptedBaselineExecutor(
        {"pytest": BaselineExecution(exit_code=1, stdout="1 failed")}
    )
    profile = RepositoryProfiler(baseline_runner=BaselineRunner(executor)).build(
        GitInspector(repository)
    )

    assert existing_failure_ids(profile.baseline_results) == frozenset({"pytest"})
    assert profile.baseline_results[0].passed is False
    assert executor.calls == [(profile.base_commit, "pytest")]


def test_impact_contains_human_marked_change_point_and_dependency_neighbor(
    committed_repository: Callable[[str], Path],
) -> None:
    inspector = GitInspector(committed_repository("multi_module"))
    profile = RepositoryProfiler().build(inspector)
    impact = RepositoryImpactAnalyzer().analyze(
        inspector=inspector,
        profile=profile,
        objective="修复 calculate_discount 的 VIP 折扣并检查 checkout_total",
    )

    paths = {candidate.path for candidate in impact.candidates}
    assert "src/shop/pricing.py" in paths
    assert "src/shop/service.py" in paths
    assert all(candidate.evidence_ids for candidate in impact.candidates)
    assert impact.search_hits


def test_difficulty_is_stable_and_not_driven_by_total_repository_size(
    committed_repository: Callable[[str], Path],
) -> None:
    repository = committed_repository("multi_module")
    irrelevant = repository / "src" / "irrelevant"
    irrelevant.mkdir()
    for index in range(120):
        (irrelevant / f"module_{index}.py").write_text(
            f"VALUE_{index} = {index}\n", encoding="utf-8"
        )
    _commit(repository, "add irrelevant modules")
    inspector = GitInspector(repository)
    profile = RepositoryProfiler().build(inspector)
    impact = RepositoryImpactAnalyzer().analyze(
        inspector=inspector,
        profile=profile,
        objective="只修改 src/shop/pricing.py 中 calculate_discount 的一个分支判断",
    )
    assessor = RepositoryDifficultyAssessor()
    first = assessor.assess(task_id=TaskId.new(), impact=impact)
    second = assessor.assess(
        task_id=first.model_requirement.task_id,
        impact=impact,
        previous_requirement=first.model_requirement,
    )

    assert len(profile.files) > 120
    assert first.difficulty.difficulty is TaskDifficulty.LOW
    assert second.difficulty.difficulty is TaskDifficulty.LOW
    assert second.model_requirement == first.model_requirement


def test_new_image_requirement_creates_new_model_requirement_version(
    committed_repository: Callable[[str], Path],
) -> None:
    inspector = GitInspector(committed_repository("single_module"))
    profile = RepositoryProfiler().build(inspector)
    impact = RepositoryImpactAnalyzer().analyze(
        inspector=inspector,
        profile=profile,
        objective="修改 calculator.py 的 calculate_discount",
    )
    assessor = RepositoryDifficultyAssessor()
    task_id = TaskId.new()
    text_only = assessor.assess(task_id=task_id, impact=impact)
    visual = assessor.assess(
        task_id=task_id,
        impact=impact,
        required_modalities=(InputModality.TEXT, InputModality.IMAGE),
        previous_requirement=text_only.model_requirement,
    )

    assert visual.model_requirement.requirement_id == text_only.model_requirement.requirement_id
    assert visual.model_requirement.version == text_only.model_requirement.version + 1
    assert visual.model_requirement.required_modalities == (
        InputModality.TEXT,
        InputModality.IMAGE,
    )


def test_unknown_scope_is_assessed_as_high_difficulty(
    committed_repository: Callable[[str], Path],
) -> None:
    inspector = GitInspector(committed_repository("single_module"))
    profile = RepositoryProfiler().build(inspector)
    impact = RepositoryImpactAnalyzer().analyze(
        inspector=inspector,
        profile=profile,
        objective="彻底重做",
    )
    assessment = RepositoryDifficultyAssessor().assess(
        task_id=TaskId.new(),
        impact=impact,
    )

    assert impact.candidates == ()
    assert assessment.difficulty.difficulty is TaskDifficulty.HIGH


def _commit(repository: Path, message: str) -> None:
    subprocess.run(
        ("git", "-C", str(repository), "add", "-A"),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ("git", "-C", str(repository), "commit", "-m", message),
        check=True,
        capture_output=True,
    )
