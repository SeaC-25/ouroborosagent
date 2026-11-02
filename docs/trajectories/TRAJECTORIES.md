# Ouroboros 测试轨迹档案（外援分析用）

按测试会话分段的完整轨迹。每段含：黑板（推理链）、观测（原始证据）、
子循环注册表（生命周期）、driver 日志（调度决策）、EXECUTE 记录、事件流 DB。

## 段落清单

### 2026-11-02_tsec_token-a96d6b98_final（TSec 最新段，3 旗/63 题）
- `blackboard.jsonl` — 全部推理结论（带证据回链），含已证伪路径/族打法/工具链教训
- `observations.jsonl` — 零判定原始观测（HTTP 全量：状态/头/体摘要/SHA/diff）
- `subloops.jsonl` — 每个子循环的生命周期（w1 黑盒 + w2 audit 双角度 + mt-* 微任务）
- `ai-conversation.jsonl` — 父会话全对话
- `executions/` — 每个 ACTION:EXECUTE 的完整记录（命令/输出/exit code）
- `events.db` — SQLite 事件流（L0 状态脊）
- `driver-log-latest.txt` — 调度器日志（spawn/harvest/ROTATE/决策层输出）

### 2026-10-31_ctfy_vantage_native（CTFy GAUNTLET 单题段）
- Vantage Outfitters 黑盒渗透（企业仿真靶场）的完整推理轨迹
- Windows 原生 agent 运行（Docker WSL2 网络死路后的方案）

### 2026-10-30_ctfy_snapshots（CTFy 早期会话快照）
- 早期调试段（架构验证期）

## 关键背景（读轨迹前必看）

1. **架构**：观察-推理循环——工具零判定，模型下全部结论；
   父调度器（Python driver）+ 子循环（Go goroutine，每轮 1 次模型调用+批量 ACTION）
2. **已知失败模式**（轨迹里可复现）：
   - FM-1 分析瘫痪（已用批量动作+8K 帽压制）
   - FM-6 flag 幻觉（凭主题编造，已用证据守卫根治）
   - FM-7 模板回声（prompt 示例值被抄，已净化）
   - provider 空转（DNS/IP 轮换，已加缓存+失效清除）
3. **效率瓶颈的当前结论**（待外援裁决）：
   - 每轮 60-90s 生成延迟 × 24 轮 ≈ 30 分钟/循环
   - 微任务化（6 轮）已上线但历史轨迹是 24 轮时代
   - w2 audit 曾重复 w1 侦察（已加已知情报注入）
4. **对照系**：平台其他队伍 8 小时通关全部 63 题；我们两小时 3 题——
   差距主要在轮延迟（模型生成速度）与调度火力分配

## 每条 JSONL 的字段
- blackboard: {id, kind, statement, source, createdAt, evidenceLevel, sourceObservations}
- observations: {id, kind, target, payload(完整 ObserveResult JSON), createdAt}
- subloops: {name, goal, status, turns, progress, lastReply, error, pulse, startedAt, endedAt}
