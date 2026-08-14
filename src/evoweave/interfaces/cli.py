"""EvoWeave command-line entry point with Chinese human and JSON output."""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from evoweave.application.analysis_service import AnalysisService
from evoweave.application.configuration import EvoWeaveConfig, load_config
from evoweave.application.intake_service import IntakeService
from evoweave.application.reporting_service import ReportingService
from evoweave.application.run_state import JsonRunStateStore
from evoweave.application.runtime_layout import RuntimeLayout
from evoweave.application.update_workflow import (
    SingleTaskUpdateWorkflow,
    UpdateWorkflowOutcome,
    ValidationRunnerFactory,
    prepare_task_plan,
)
from evoweave.domain.enums import ModelAvailability
from evoweave.domain.errors import DomainError, ErrorCode
from evoweave.domain.identifiers import RunId
from evoweave.domain.repository_models import RepositoryProfile
from evoweave.domain.run_models import RunManifest
from evoweave.infrastructure.artifacts.image_ingestor import PillowImageIngestor
from evoweave.infrastructure.artifacts.local_store import LocalArtifactStore
from evoweave.infrastructure.models.doctor import ModelDoctor
from evoweave.infrastructure.models.openai_compatible import (
    OpenAICompatibleModelGateway,
    default_provider_configs,
)
from evoweave.infrastructure.persistence.graph_repository import SQLiteOrchestrationStore
from evoweave.infrastructure.persistence.sqlite import SQLiteDatabase
from evoweave.interfaces.schemas import CliEnvelope, CliError
from evoweave.orchestration.checkpointing import CheckpointManager
from evoweave.repository.git_inspector import GitInspector
from evoweave.repository.profile_cache import calculate_profile_digest
from evoweave.workspaces.command_policy import LocalWorkspaceCommandRunner
from evoweave.workspaces.docker_workspace import (
    DockerSandboxConfig,
    DockerWorkspaceCommandRunner,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="evoweave",
        description="面向已有 Python 仓库的动态多 Agent 软件更新系统",
    )
    parser.add_argument("--config", type=Path, help="JSON 兼容 YAML 配置文件")
    subparsers = parser.add_subparsers(dest="command", required=True)

    initialize = subparsers.add_parser("init", help="初始化仓库本地运行目录")
    _repository_argument(initialize)
    _json_argument(initialize)

    analyze = subparsers.add_parser("analyze", help="读取固定 commit 并生成仓库画像")
    _change_arguments(analyze)

    run = subparsers.add_parser("run", help="创建运行；不带 --execute 时只完成安全预检")
    _change_arguments(run)
    run.add_argument("--execute", action="store_true", help="允许调用模型并执行更新流水线")
    run.add_argument("--provider", help="覆盖默认模型供应商")
    run.add_argument("--model", help="覆盖默认模型 ID")
    run.add_argument(
        "--trusted-host-validation",
        action="store_true",
        help="仅对可信仓库显式允许宿主机验证；默认要求 Docker 沙箱",
    )
    run.add_argument(
        "--approve-high-risk",
        action="store_true",
        help="显式批准已审查的高风险任务范围",
    )

    status = subparsers.add_parser("status", help="查看一个或全部运行状态")
    _repository_argument(status)
    status.add_argument("--run-id")
    _json_argument(status)

    resume = subparsers.add_parser("resume", help="读取可恢复运行状态")
    _repository_argument(resume)
    resume.add_argument("run_id")
    resume.add_argument("--execute", action="store_true", help="继续执行 analyzed 运行")
    resume.add_argument("--provider", help="覆盖默认模型供应商")
    resume.add_argument("--model", help="覆盖默认模型 ID")
    resume.add_argument("--trusted-host-validation", action="store_true")
    resume.add_argument("--approve-high-risk", action="store_true")
    _json_argument(resume)

    export = subparsers.add_parser("export", help="导出中文 Markdown 与机器 JSON 报告")
    _repository_argument(export)
    export.add_argument("run_id")
    export.add_argument("--output", type=Path)
    _json_argument(export)

    models = subparsers.add_parser("models", help="模型配置与可用性诊断")
    model_subparsers = models.add_subparsers(dest="models_command", required=True)
    doctor = model_subparsers.add_parser("doctor", help="检查三个供应商配置")
    doctor.add_argument("--network", action="store_true", help="显式调用只读模型列表接口")
    _json_argument(doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    as_json = bool(getattr(arguments, "json", False))
    try:
        config = load_config(arguments.config)
        data, human = _dispatch(arguments, config)
    except DomainError as exc:
        _emit_error(exc.code.value, exc.message, as_json)
        return 2
    except (OSError, ValueError) as exc:
        _emit_error("invalid_input", str(exc), as_json)
        return 2
    if as_json:
        print(CliEnvelope(ok=True, data=data).model_dump_json(indent=2))
    else:
        print(human)
    return 0


def _dispatch(
    arguments: argparse.Namespace,
    config: EvoWeaveConfig,
) -> tuple[dict[str, Any], str]:
    if arguments.command == "models":
        return _models_doctor(arguments, config)
    repository = GitInspector(arguments.repository).repository_root
    layout = RuntimeLayout.create(repository, config)
    run_store = JsonRunStateStore(layout.run_state)
    artifact_store = LocalArtifactStore(layout.artifacts)
    if arguments.command == "init":
        init_data = {"repository": str(repository), "runtime_directory": str(layout.root)}
        return init_data, f"EvoWeave 运行目录已初始化：{layout.root}"
    if arguments.command in {"analyze", "run"}:
        manifest, profile = _analyze(arguments, run_store, artifact_store)
        analysis_data: dict[str, Any] = {
            "run_id": str(manifest.run_id),
            "status": manifest.status.value,
            "base_commit": manifest.change_spec.base_commit,
            "profile_artifact_id": str(manifest.repository_profile_artifact_id),
            "files": len(profile.files),
            "python_symbols": len(profile.symbols),
        }
        if arguments.command == "run" and arguments.execute:
            outcome = _execute_update(
                arguments,
                config,
                layout,
                run_store,
                artifact_store,
                manifest,
                profile,
            )
            analysis_data.update(
                {
                    "status": outcome.manifest.status.value,
                    "final_patch_artifact_id": str(outcome.final_patch.ref.artifact_id),
                    "validation_report_artifact_id": str(
                        outcome.validation_report.report_ref.artifact_id
                        if outcome.validation_report.report_ref is not None
                        else ""
                    ),
                    "validation_accepted": outcome.validation_report.accepted,
                    "agent_count": outcome.agent_count,
                }
            )
            return (
                analysis_data,
                f"运行 {manifest.run_id} 已结束：{outcome.manifest.status.value}",
            )
        human = (
            f"运行 {manifest.run_id} 已完成仓库分析："
            f"{len(profile.files)} 个文件，{len(profile.symbols)} 个 Python 符号。"
        )
        return analysis_data, human
    if arguments.command == "status":
        manifests = (
            (run_store.get(RunId(arguments.run_id)),) if arguments.run_id else run_store.list_all()
        )
        status_data: dict[str, Any] = {
            "runs": [
                {
                    "run_id": str(item.run_id),
                    "status": item.status.value,
                    "message": item.message,
                    "base_commit": item.change_spec.base_commit,
                }
                for item in manifests
            ]
        }
        human = (
            "\n".join(f"{item.run_id}  {item.status.value}  {item.message}" for item in manifests)
            or "当前没有运行记录。"
        )
        return status_data, human
    if arguments.command == "resume":
        manifest = run_store.get(RunId(arguments.run_id))
        if arguments.execute:
            profile = _load_profile(manifest, artifact_store)
            outcome = _execute_update(
                arguments,
                config,
                layout,
                run_store,
                artifact_store,
                manifest,
                profile,
            )
            resume_data = outcome.manifest.model_dump(mode="json")
            return resume_data, f"运行已继续并结束：{outcome.manifest.status.value}"
        resume_data = manifest.model_dump(mode="json")
        return resume_data, f"已恢复运行状态：{manifest.run_id} / {manifest.status.value}"
    if arguments.command == "export":
        manifest = run_store.get(RunId(arguments.run_id))
        output = arguments.output or layout.reports
        checkpoint = CheckpointManager(
            SQLiteOrchestrationStore(SQLiteDatabase(layout.orchestration_database))
        ).load(manifest.run_id)
        markdown_path, json_path = ReportingService().export(
            manifest,
            output,
            checkpoint=checkpoint,
        )
        export_data = {"markdown": str(markdown_path), "json": str(json_path)}
        return export_data, f"报告已导出：\n{markdown_path}\n{json_path}"
    raise ValueError(f"未知命令：{arguments.command}")


def _analyze(
    arguments: argparse.Namespace,
    run_store: JsonRunStateStore,
    artifact_store: LocalArtifactStore,
) -> tuple[RunManifest, RepositoryProfile]:
    image_paths = tuple(Path(item).resolve(strict=True) for item in arguments.image)
    change_spec = IntakeService(PillowImageIngestor(artifact_store)).create(
        repository=arguments.repository,
        objective=arguments.request,
        acceptance_criteria=tuple(arguments.acceptance),
        allowed_paths=tuple(arguments.path),
        forbidden_paths=tuple(arguments.forbid),
        image_paths=image_paths,
    )
    return AnalysisService(run_store=run_store, artifact_store=artifact_store).analyze(change_spec)


def _models_doctor(
    arguments: argparse.Namespace,
    config: EvoWeaveConfig,
) -> tuple[dict[str, Any], str]:
    providers = default_provider_configs(qianwen_base_url=config.qianwen_base_url)
    gateway = OpenAICompatibleModelGateway(providers)
    results = ModelDoctor(providers, gateway).inspect(network=arguments.network)
    data = {"providers": [item.model_dump(mode="json") for item in results]}
    human = "\n".join(
        (
            f"{item.provider}: Key={'已设置' if item.key_present else '未设置'}，"
            f"网络={'成功' if item.reachable else '失败' if item.reachable is False else '未检查'}"
        )
        for item in results
    )
    return data, human


def _execute_update(
    arguments: argparse.Namespace,
    config: EvoWeaveConfig,
    layout: RuntimeLayout,
    run_store: JsonRunStateStore,
    artifact_store: LocalArtifactStore,
    manifest: RunManifest,
    profile: RepositoryProfile,
) -> UpdateWorkflowOutcome:
    prepare_task_plan(
        config=config,
        run_store=run_store,
        manifest=manifest,
        profile=profile,
        approve_high_risk=arguments.approve_high_risk,
    )
    provider_name = arguments.provider or config.default_provider
    model_id = arguments.model or config.default_model_id
    runner_factory = _validation_runner_factory(arguments, config)
    providers = default_provider_configs(qianwen_base_url=config.qianwen_base_url)
    gateway = OpenAICompatibleModelGateway(providers)
    discovered_profiles = gateway.available_profiles(provider_name)
    selected = next((item for item in discovered_profiles if item.model_id == model_id), None)
    if selected is None or selected.availability is not ModelAvailability.AVAILABLE:
        raise DomainError(
            ErrorCode.MODEL_UNAVAILABLE,
            f"当前 Key 未发现可用模型 {provider_name}:{model_id}",
        )
    profiles = tuple(
        item.model_copy(update={"stable_priority": 0 if item.model_id == model_id else 100})
        for item in discovered_profiles
        if item.availability is ModelAvailability.AVAILABLE
    )
    return SingleTaskUpdateWorkflow(
        config=config,
        layout=layout,
        run_store=run_store,
        artifact_store=artifact_store,
        model_gateway=gateway,
        model_profiles=profiles,
        validation_runner_factory=runner_factory,
        approve_high_risk=arguments.approve_high_risk,
    ).execute(manifest, profile)


def _validation_runner_factory(
    arguments: argparse.Namespace,
    config: EvoWeaveConfig,
) -> ValidationRunnerFactory:
    if arguments.trusted_host_validation:
        return lambda lease: LocalWorkspaceCommandRunner(
            lease=lease,
            allowed_commands=("python",),
            allow_host_execution=True,
        )
    _assert_docker_ready(config.sandbox_image)
    docker_config = DockerSandboxConfig(image=config.sandbox_image)
    return lambda lease: DockerWorkspaceCommandRunner(
        lease=lease,
        allowed_commands=("python",),
        config=docker_config,
    )


def _load_profile(
    manifest: RunManifest,
    artifact_store: LocalArtifactStore,
) -> RepositoryProfile:
    artifact_id = manifest.repository_profile_artifact_id
    if artifact_id is None:
        raise ValueError("运行没有仓库画像产物")
    profile = RepositoryProfile.model_validate_json(artifact_store.get_bytes(artifact_id))
    if calculate_profile_digest(profile) != profile.profile_digest:
        raise ValueError("仓库画像摘要校验失败")
    return profile


def _assert_docker_ready(image: str) -> None:
    executable = shutil.which("docker")
    if executable is None:
        raise DomainError(ErrorCode.SANDBOX_UNAVAILABLE, "未找到 Docker CLI")
    try:
        completed = subprocess.run(
            (executable, "image", "inspect", image),
            check=False,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DomainError(ErrorCode.SANDBOX_UNAVAILABLE, "Docker 环境检查失败") from exc
    if completed.returncode != 0:
        raise DomainError(
            ErrorCode.SANDBOX_UNAVAILABLE,
            f"本地不存在锁定沙箱镜像：{image}",
        )


def _repository_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("repository", nargs="?", default=".", help="目标 Git 仓库")


def _json_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")


def _change_arguments(parser: argparse.ArgumentParser) -> None:
    _repository_argument(parser)
    parser.add_argument("--request", required=True, help="软件更新需求")
    parser.add_argument(
        "--acceptance",
        action="append",
        default=["满足用户需求并通过确定性验证"],
        help="验收条件，可重复",
    )
    parser.add_argument("--path", action="append", default=[], help="允许修改路径，可重复")
    parser.add_argument("--forbid", action="append", default=[], help="禁止路径，可重复")
    parser.add_argument("--image", action="append", default=[], help="图片输入，可重复")
    _json_argument(parser)


def _emit_error(code: str, message: str, as_json: bool) -> None:
    if as_json:
        print(
            CliEnvelope(
                ok=False,
                error=CliError(code=code, message=message),
            ).model_dump_json(indent=2)
        )
    else:
        print(f"错误 [{code}]：{message}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
