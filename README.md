# 演进织网（EvoWeave）

演进织网是一个面向已有软件仓库的无固定业务角色、自适应任务图多智能体软件更新系统。

## 项目标识

| 项目项 | 正式名称 |
|---|---|
| 中文名称 | 演进织网 |
| 英文名称 | EvoWeave |
| GitHub 仓库 | [franklil0401/EvoWeave](https://github.com/franklil0401/EvoWeave) |
| Python 包名 | `evoweave` |

`Evo` 表示既有软件的持续演进，`Weave` 表示总调度 Agent 根据任务和仓库证据，把临时 Agent、任务依赖、上下文和补丁动态编织成可执行任务图。

## 一句话定位

> 一个由总调度 Agent 动态生成任务图，并按任务实时装配无固定业务角色 Agent，在隔离工作区中为已有仓库生成可验证补丁的软件演进系统。

## 当前状态

阶段 3 已完成：工程骨架、动态能力、通用 `WorkerRuntime`、固定 commit 仓库画像，以及独立 Git worktree 隔离写入已经落地。

每个写任务现在绑定唯一租约、临时分支和 worktree；路径、符号链接、读写范围和 diff 会被程序校验，最终补丁绑定 base commit、任务、Agent、执行规格、工作区和命令/测试产物。当前准备进入阶段 4，实现唯一总调度 Agent 与动态任务图。Docker 无网执行适配器已实现并通过命令构造测试，但当前开发机未安装 Docker CLI，因此尚未运行真实容器。

## 本地验证

```powershell
uv sync --group dev --frozen --no-editable
./scripts/运行全部检查.ps1
```

当前阶段门禁为 Ruff、mypy 严格模式和 139 项完全离线的 pytest 测试，不需要 API Key。

Windows 工作区路径包含中文时，当前统一使用非 editable 安装，避免 Python 3.12 在读取 `.pth` 路径时受系统编码影响；这不改变源码布局和打包结果。

## 文档入口

- [任务文档](任务文档.md)
- [项目结构文档](项目结构文档.md)
- [模型接口与环境变量说明](docs/开发指南/模型接口与环境变量说明.md)
- [当前可调用模型与价格清单](docs/开发指南/当前可调用模型与价格清单.md)
- [历史方案与调研](docs/研究归档/)
