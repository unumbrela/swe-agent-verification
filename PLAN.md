# 项目总结：在 mini-swe-agent 上研究"让代码 Agent 检查自己的修复"

> 状态：**已收束（2026-10-28）**。逐题分析见 `notes/experiments.md`（第 6 节为离线验证者基准与候选选择）。

## 1. 一句话

基于 [mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent)（约 100 行核心循环的 SWE-bench Agent），用 DeepSeek-v4-pro 在 SWE-bench Verified 50 题分层子集上：先建立**无泄漏**的基线，再实现并评估两种"提交前验证"机制。结论是两种机制**都没有带来收益**，并且用证据讲清了原因。
随后把所有运行的补丁整理成带标签的离线验证集（156 个补丁），发现"驳回重做"不如"从多次运行中挑选"：listwise 对比选择在 8 道可改进题上从 4.0 提到 5.3（p=0.08，方向正面但未显著）。

## 2. 结果总表

| 配置 | Resolve | 平均步数 | Prompt tok/题 | 说明 |
|---|---|---|---|---|
| 基线（容器联网） | ~~41/50 = 82%~~ | 44.9 | 1.55M | **作废**：Agent 联网抄上游修复 |
| **基线（断网）** | **39/50 = 78%** | 50.6 | 1.93M | 正式基线 |
| B：提交前自检 | 39/50 = 78% | 58.2 | 2.51M | 自检只改了 3/50 题补丁，且结果都没变 |
| B2：独立审查者 | 42/50 = 84% | 53.5 + 审查 25.1 | 2.62M | 首次提交的反事实分数同为 42/50 → 审查贡献 0 |
| C：3 次断网运行 + 随机挑一个 | 40.0/50 | — | — | 期望 pass@1 |
| C：3 次断网运行 + pointwise 打分挑选 | 39.5/50 | — | — | 不如随机 |
| **C：3 次断网运行 + listwise 对比挑选** | **41.3/50** | — | 仅 8/50 题需调用 | 上限 oracle pass@3 = 44/50 |

噪声：同一配置重跑，约 8% 的题会翻转，因此 50 题上 ±2 题以内都不可信。

## 3. 主要发现（面试要讲的）

1. **评测泄漏**：SWE-bench 容器默认有网。50 题中 16 题 Agent 主动联网（pip 下载新版本、curl GitHub、用 GitHub API 搜到别人的解答）。断网后丢掉的 4 题**全部**来自这 16 题。→ 所有实验统一 `--network none`。
2. **失败原因不是"找不到代码"**：9 个失败题中定位错误为 0，主因是**理解偏差**（5/9）。还有一个反复出现的模式：模型自己的输出已经暴露了问题，它却以"保持最小改动"为由放过。
3. **自检是橡皮图章**（B）：同一个模型带着同一段上下文自检时，会把"预期值"写成和现有实现一致。django-15957 中，模型在自检时甚至想到了正确做法（Window + RowNumber），随后又放弃了。
4. **上下文独立 ≠ 判断独立**（B2）：换成全新上下文、只看 issue + diff 的审查者后，仍然只抓到 2/8 个错误补丁，误报 3 次，9/50 题没给出结论。同一个模型当审查者，会和生成者犯相关的错误（django-12273 两者都只验证了字面例子）。正面的一点是：误报**没有**把任何正确补丁改坏。
5. **方法：不重跑也能剥离噪声**。把被驳回题的"首次提交"也拿去评测，就得到同一次运行中"有/无该机制"的反事实对比。这样确认了 84% 与 78% 的差距来自随机性。
6. **验证者的全局 AUROC 会骗人**（C）：pointwise judge 的 AUROC 为 0.735，但把每个补丁的分数换成"所在题目的平均分"（完全不看补丁）也有 0.740；同一题内对 vs 错补丁的排序 AUROC 只有 0.424，低于随机。也就是说 judge 只学会了判断"题难不难"，不会区分候选。用于选择的验证者必须报告题内指标。
7. **对比比打分有效**（C）：把候选放在一起比较（listwise），模型能找到候选之间的行为差异再对照 issue 判断。django-15957 中它 3/3 选中正确补丁，理由正是主 Agent 当初合理化掉的那个矛盾（每类各取 N 条 vs 全局 LIMIT）；pointwise 却给这个正确补丁打了三者中最低分。

## 4. 代码结构（我加的部分）

```
src/minisweagent/agents/self_check.py          # B：拦下首次提交，注入自检提示（~40 行）
src/minisweagent/agents/independent_review.py  # B2：首次提交交给新上下文的审查 Agent；审查后恢复工作区（~70 行）
src/minisweagent/agents/__init__.py            # 注册 self_check / independent_review
src/minisweagent/run/benchmarks/swebench.py    # 支持 YAML 里的 agent_class（默认行为不变）
tests/agents/test_self_check.py                # 4 个单测
tests/agents/test_independent_review.py        # 2 个单测（含"审查者乱改文件→恢复"）
configs/deepseek.yaml / no_network.yaml        # 模型叠加配置 / 容器断网
configs/self_check.yaml / independent_review.yaml  # 两种机制的提示词
configs/subset_verified_50.txt                 # 50 题分层子集（每仓库 ≥1，按比例，seed=42）
scripts/make_subset.py   scripts/stats.py      # 抽子集 / 统计（含审查者 token）
scripts/run_exp.sh       scripts/drop_failed.py  # 一键实验：等中转站→跑→剔除故障题补跑→评测→统计
scripts/smoke_test.py                          # 本地冒烟测试
scripts/verifier_data.py                       # C：汇总所有运行的补丁 → 去重带标签数据集（156 个补丁）
scripts/judge.py   configs/judge.yaml          # C：pointwise 打分 / listwise 对比 judge（流式 + 重试，结果可续跑）
scripts/eval_verifiers.py                      # C：验证者分类指标（含题内 AUROC）+ 各选择方法 + 显著性
notes/experiments.md                           # 逐题分析
runs/                                          # 轨迹、评测报告、日志（gitignore）
```

设计原则：改进全部做成 `DefaultAgent` 子类 + YAML 配置，上游核心循环不动。

## 5. 复现

```bash
uv venv .venv -p 3.12 && uv pip install -p .venv -e . mcp pytest        # Agent 环境
uv venv .venv-eval -p 3.12 && uv pip install -p .venv-eval swebench    # 评测环境（隔离依赖）
# API：~/.config/mini-swe-agent/.env 里写 OPENAI_API_KEY / OPENAI_API_BASE（不进仓库）
scripts/run_exp.sh baseline_nonet configs/no_network.yaml
scripts/run_exp.sh self_check     configs/no_network.yaml configs/self_check.yaml
scripts/run_exp.sh review         configs/no_network.yaml configs/independent_review.yaml
# C：离线验证者与候选选择（只需 API，不需要 Docker）
.venv/bin/python scripts/verifier_data.py
.venv/bin/python scripts/judge.py pointwise --samples 1 --reasoning-effort low
.venv/bin/python scripts/judge.py listwise --samples 3
.venv/bin/python scripts/eval_verifiers.py
```

## 6. 踩坑记录

- litellm 1.106 缺 `mcp` 依赖；`config/default.yaml` 是文本格式提示词，tool-call 模型要用 `mini.yaml` / `swebench.yaml`。
- swebench 5.x 评测要用 `SWE-bench/SWE-bench_Verified`（旧名 `princeton-nlp/...` 缺 `image` 字段）。
- WSL 下 Docker daemon 不继承终端代理 → 已写 `/etc/systemd/system/docker.service.d/proxy.conf`（172.29.160.1:7897，Windows 重启后 IP 可能变）。
- 中转站会整组不可用（两次）→ `run_exp.sh` 可续跑，故障题不会被算成模型失败。中转站无价格信息，成本用 token 衡量。
- 单次 judge 调用在难题上推理可达约 4.8 万 token（>10 分钟）：非流式请求会被中转站断开；超时后整条重试会无限循环。→ judge 用流式 + tenacity 重试 + 1h 超时，pointwise 用 `reasoning_effort=low`（默认强度跑完的 57 个结果另存为 `pointwise_default_effort.jsonl`，结论一致）。

## 7. 局限与可能的后续

- 50 题样本小，基线已近 80%，准确率改进很难显著。若继续，可换更难或更大的评测集（全量 500 题 / SWE-bench Pro）。
- C 的瓶颈是"有对有错的题"只有 8 道（p=0.08）。要显著，需要更多候选不一致的题：更大/更难的题集，或每题更多次运行（N=5）。
- 审查者 / judge 换成**不同的模型**，可能打破"相关错误"（需另一家 API）。离线数据集已就绪，换模型只需 `--model`。
- listwise 可以再加"执行证据"：让 judge 先写区分候选的测试并在容器里运行（agentic listwise），预计对 seaborn/pylint 这类纯读 diff 难判断的题有帮助。
- 效率方向未做：每题 2M+ prompt token，其中约 96% 命中缓存；压缩历史可能破坏前缀缓存，需同时报告总 token 和未缓存 token。

## 8. 简历写法（参考）

> **代码修复 Agent 的自我验证研究**（基于 mini-swe-agent，SWE-bench Verified）
> - 发现并修复评测泄漏：容器联网导致 Agent 抄袭上游修复（16/50 题联网），断网后基线由 82% 校正为 78%。
> - 失败归因显示瓶颈在需求理解而非代码定位；据此实现"提交前自检"和"独立审查 Agent"（含工作区隔离与恢复、单测覆盖）。
> - 用"首次提交反事实评测"在不重跑的前提下剥离噪声，证明两种机制均无收益，并定位原因：同一模型的审查者与生成者错误相关。
> - 构建 156 个带标签补丁的离线验证集，发现 LLM judge 的全局 AUROC（0.74）完全来自题目难度、题内排序低于随机；改用 listwise 对比选择，在可改进题上把解出数从 4.0 提到 5.3（总体 40.0 → 41.3 / 50）。

## 9. 进度日志

| 日期 | 进展 |
|---|---|
| 10-25 | clone 上游 v2.4.6，读代码，写规划 |
| 10-26 | 接入 DeepSeek（中转站）；单题端到端跑通；配好 Docker 代理；50 题基线 82% |
| 10-26 | 失败分析：理解偏差为主、定位 0；**发现联网泄漏** → 断网基线 78% |
| 10-26 | 改进 B（自检）：78%，负结果；中途中转站故障 → 实验脚本改为可续跑 |
| 10-27 | 改进 B2（独立审查）：84%，但反事实同为 84% → 贡献 0 |
| 10-28 | C：离线验证集（156 补丁）；pointwise judge 题内 AUROC 0.42（只认难度）；listwise 选择 40.0 → 41.3（p=0.08）；**项目收束** |
