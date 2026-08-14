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

阶段 6 已完成，阶段 7 正在进行：工程骨架、动态能力、固定 commit 仓库画像、动态任务图、隔离补丁集成、确定性验证和可运行 CLI 已经连成闭环；12 个冻结任务、三种 Agent 策略、三种模型策略和规划审计已经落地。

系统会根据用户允许路径、固定版本代码规模和 Python 模块依赖生成任务数与 DAG，而不是套用预设角色。互不冲突的就绪任务可并发运行，每个 Agent 的模型、工具、读写范围和运行上限独立生成；图片只发送给需要视觉输入的任务。首选模型失败时会创建新 Agent 和新路由版本，高风险任务则在任何模型调用前等待显式批准。

所有写入发生在独立 worktree。多个 `PatchArtifact` 通过内容哈希、base commit、实际路径、写范围、敏感文件和冲突守卫后，才会进入集成 worktree；局部、影响、全量 Pytest 与 Ruff 门禁以真实命令记录判定。最终结果是可审查补丁，不会修改或推送用户主分支。

当前规划审计显示：简单任务只创建一个动态 Agent，两个图片相关任务共向两个必要 Agent 提供原图，图片负例不暴露原图，冻结人工难度匹配 12/12。第三版任务集已有 12 项任务级隐藏验收，并通过“基线必失败、正确实现必通过”的自洽测试；真实运行器会把结果同时绑定任务集摘要和系统 Git commit。两轮探索性真实调用分别发现隐藏验收和系统级验收漏洞，原始记录与证据均完整归档、不进入正式效果比较；模型回退场景现在会确定性注入一次首选模型故障，并要求新 Agent/新路由实际出现。

提交 `10385091b453b4753f1a84a9b56388fb26a049ca` 上已经完成七组共 84 条正式 `live_model` 运行，单 Agent和动态 Agent的三种模型策略，以及固定多 Agent + 固定高档模型均已覆盖。当前成功数依次为：单 Agent + 动态模型 7/12、动态 Agent + 动态模型 6/12、单 Agent + 固定高档 6/12、动态 Agent + 固定高档 4/12、动态 Agent + 固定低档 1/12、单 Agent + 固定低档 0/12、固定多 Agent + 固定高档 0/12。固定四步组平均使用 2.67 个执行实例和 75,095.3 Token，7 个任务因 Worker 决策协议无效而失败，说明无条件增加调用链路会放大结构化输出风险。现有证据支持动态选模的价值，但尚未支持动态或固定任务拆分；弱模型也无法靠增加 Agent稳定补偿。主要失败边界是结构化输出和工具循环不稳定、高风险修改引入回归，以及当前视觉模型服务不可用。完整矩阵进度为 84/108，Go/No-Go 仍保持 `PENDING`。Docker 无网执行适配器已通过离线构造测试，但本开发机未安装 Docker CLI，因此真实容器实测仍是环境待办。

## 评测与规划审计

```powershell
uv run --no-editable evoweave benchmark validate `
  --suite benchmarks/任务集/第一版任务集.json --project-root .

uv run --no-editable evoweave benchmark audit `
  --suite benchmarks/任务集/第一版任务集.json `
  --project-root . --output benchmarks/结果

uv run --no-editable evoweave benchmark summarize `
  --suite benchmarks/任务集/第一版任务集.json `
  --results benchmarks/结果/真实模型结果.json --output benchmarks/结果

# 真实 API：默认运行动态 Agent + 动态模型；可用 --task 只选部分任务
uv run --no-editable evoweave benchmark run `
  --suite benchmarks/任务集/第一版任务集.json `
  --project-root . --results benchmarks/结果/真实模型结果.json
```

汇总器不会为缺失实验补零；没有完整的 12 × 3 × 3 同等级运行记录时，效果结论保持 `PENDING`。

## 快速开始

```powershell
uv sync --group dev --frozen --no-editable
$env:PYTHONPATH="src"
uv run --no-editable evoweave models doctor

# 默认只分析，不调用模型、不修改仓库
uv run --no-editable evoweave run C:\path\to\repo `
  --request "让客户类型匹配不区分大小写" `
  --path src/pricing.py

# 对可信本地仓库显式执行；生产使用时应准备默认 Docker 沙箱
uv run --no-editable evoweave run C:\path\to\repo `
  --request "让客户类型匹配不区分大小写" `
  --path src/pricing.py `
  --execute --trusted-host-validation
```

涉及支付、权限、安全、迁移等高风险信号时，首次执行会进入 `waiting_for_input`；审查范围后使用 `resume ... --execute --approve-high-risk` 继续。

## 本地验证

```powershell
uv sync --group dev --frozen --no-editable
./scripts/运行全部检查.ps1
```

当前阶段门禁为 Ruff、mypy 严格模式和 217 项完全离线的 pytest 测试，不需要 API Key。端到端测试覆盖单 Agent 更新、两个独立 Agent 真并发、依赖任务排序、模型回退次数上限、高风险暂停、真实 Git 补丁集成和宿主机可信 fixture 的真实 Pytest/Ruff 验证；基准测试还覆盖 12 项隐藏验收自洽性、故障注入、系统级验收、证据持久化和版本混用拒绝。

Windows 工作区路径包含中文时，当前统一使用非 editable 安装，避免 Python 3.12 在读取 `.pth` 路径时受系统编码影响；这不改变源码布局和打包结果。

## 文档入口

- [任务文档](任务文档.md)
- [项目结构文档](项目结构文档.md)
- [模型接口与环境变量说明](docs/开发指南/模型接口与环境变量说明.md)
- [当前可调用模型与价格清单](docs/开发指南/当前可调用模型与价格清单.md)
- [安装与配置](docs/使用指南/安装与配置.md)
- [命令行使用](docs/使用指南/命令行使用.md)
- [运行结果解读](docs/使用指南/运行结果解读.md)
- [运行时拓扑与任务图](docs/架构设计/运行时拓扑与任务图.md)
- [基准评测说明](benchmarks/评测说明.md)
- [规划审计报告](benchmarks/结果/规划审计报告.md)
- [正式评测汇总报告](benchmarks/结果/评测汇总报告.md)
- [秋招演示与答辩指南](docs/演示指南/秋招演示与答辩指南.md)
- [历史方案与调研](docs/研究归档/)
