# ouroborosagent — Ouroboros 渗透 Agent 独立包

从 Ouroboros 工作台抽取的**纯 Agent 部分**：Go 后端核心 + 驱动脚本 + 知识库。
不含桌面 GUI / 前端 / 工作台业务层。

## 结构

```
ouroborosagent/
├── cmd/ouro/            # Go 入口（serve <workspace> --port 8090）
├── internal/            # Go 核心（22 万行）
│   ├── api/             # L5 编排层：chat/ACTION 协议/子循环/MBEE/BENCH 传送带
│   │   ├── subloop.go       # 12 轮脉冲子循环 + 证伪收据 + Clean Fork
│   │   ├── conveyor.go      # BENCH 平台五操作（含 flag 证据守卫+熔断器）
│   │   ├── mbee_intent.go   # MBEE 意图信封（结构化父决策）
│   │   ├── inspect_scalpel.go # INSPECT 观测手术刀（按需切片 ≤1.5KB）
│   │   ├── tce_gate.go      # 远端因果纪元 + 请求指纹去重
│   │   ├── sisyphus_gate.go # 观测积压熔断
│   │   └── hypergraph.go    # 1889 节点配方超图匹配
│   ├── app/             # provider 层（GLM/DeepSeek 适配 + 认知分层路由）
│   └── nativetools/     # 零判定观测原语（ObserveHTTP 等）
├── kb/                  # 知识库（79 SKILL.md → 超图索引）
├── benchmark/           # Python 驱动
│   ├── drive_orchestrated.py # 硬流水线（TSec 类平台）★主力
│   ├── drive_single.py       # 单题模式（CTFy GAUNTLET 类）
│   ├── drive_parent.py       # 对话编排模式
│   └── parallel_entry.py     # OURO_DRIVE_MODE 入口分发
├── Dockerfile           # 容器构建（适配本包路径）
├── AGENTS.md            # 工程约定
└── docs/architecture-review.md  # 架构剖析
```

## 快速开始

### 构建
```bash
go build -o ouro ./cmd/ouro          # 本机
GOOS=linux GOARCH=amd64 go build -o docker-build/ouro-linux ./cmd/ouro  # 容器用
```

### 容器部署（TSec 类平台）
```bash
docker build -t ouro-agent .
docker run -d --name ouro-tsec \
  -e BENCHMARK_TOKEN=<token> \
  -e BENCHMARK_BASE_URL=<url> \
  -e OURO_PROVIDER_MODEL=glm-5.3-flash \
  -e OURO_PROVIDER_BASE_URL=<provider-url> \
  -e OURO_PROVIDER_API_KEY=<key> \
  -e OURO_DRIVE_MODE=orchestrated \
  -e OURO_MAX_SUB_LOOPS=3 \
  ouro-agent
```

### 原生部署（VPN 靶场，Windows 宿主）
参考 run-native.ps1 模式：OURO_AGENT_BIN/OURO_LOG_PATH/OURO_KB_SOURCE 参数化，
OURO_DRIVE_MODE=single + OURO_MISSION_FILE。

## 核心机制（v28.5）

- **观察-推理循环**：工具零判定，模型下全部结论
- **12 轮脉冲子循环**：证伪收据落黑板 → Clean Fork（销毁污染上下文）→ 2 sterile 休眠
- **MBEE 意图信封**：330 字思考槽 + 结构化 directive（GLM 需非流式 + tier-1 + 2048 帽）
- **三层提交防线**：flag 证据守卫（观测原文逐字匹配）→ 平台拒旗熔断 → 教学铁律
- **sapper 教义栈**：易题先行 / 同族迁移 / 将军攻坚（20min tier=2）/ 停车纪律（35min）/ 末段清账
- **证据总线**：INSPECT 手术刀 / TCE 因果去重 / Sisyphus 积压熔断 / READ journal 封禁

## 环境变量

| 变量 | 作用 | 默认 |
|---|---|---|
| OURO_DRIVE_MODE | orchestrated/single/parent | orchestrated |
| OURO_PROVIDER_MODEL | 主力模型 | glm-5.3-flash |
| OURO_TACTIC_MODEL | 战术层（tier-1） | 同主力 |
| OURO_MAX_SUB_LOOPS | 子循环并发上限 | 2 |
| BENCHMARK_TOKEN/BASE_URL | 平台凭据 | - |
