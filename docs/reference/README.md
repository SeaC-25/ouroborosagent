# 参考资料导读（竞品 sapper-v2 研究）

来源：腾讯智能攻防线上赛季军（80.18/100 · 634 队 · 8h 无人值守 · 1B tokens 完胜 4.5B）。
开源仓库 N1nEmAn/sapper-v2（本目录为其核心文档的本地研究存档）。

## 文件

| 文件 | 内容 |
|---|---|
| `BATTLE-REPORT.md` | 8 小时战役七阶段复盘 + 十条可迁移经验（同族迁移/分层用脑/收官清账） |
| `commander-SKILL.md` | 426 行指挥官教义原版（调度循环/升级阶梯/槽位管理/自我管理） |
| `commander-SPEC.md` | 架构契约（worker.sh/watchdog.sh/SKILL 三单元 + 已知陷阱清单） |
| `SKILL.md` | sapper 事实图 CLI 设计（typed facts / intent DAG / flag ledger） |
| `README.zh.md` | 女娲测试哲学（Create/Language/History 三能力） |

## 与 Ouroboros 的对照

| 维度 | sapper-v2 | Ouroboros |
|---|---|---|
| 编排 | Claude TUI 指挥官（全量旗舰烧 token） | driver 硬流水线 + 零 LLM spawn 管路 |
| 决策 | 教义规则表（20/30/45 分钟阶梯） | 模型指挥官看全态势 + 60min 兜底 |
| 记忆 | 事实图（一节点一文件+flock） | 黑板 jsonl（含证据回链/证伪/族打法） |
| 子循环 | tmux pane 工人（watchdog 保活） | Go goroutine 微任务（6 轮原子链） |
| 提交 | flag ledger（recorded≠submitted） | 三层防线（证据守卫/熔断/满分拦截） |

**已吸收**：同族迁移、易题先行、双角度（w1/w2）、末段清账、工具链前置。
**有意不吸收**：硬编码时间阶梯（教条 vs 模型判断）、Claude TUI 依赖。
