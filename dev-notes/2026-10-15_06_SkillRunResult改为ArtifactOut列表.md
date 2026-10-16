# SkillRunResult.outputs 改为 List[ArtifactOut]（2026-10-15）

2026-10-15

方案文档：`docs/20261015_01_能力自描述与动态组装框架方案.md`（§3.7）
前置：`2026-10-15_05_ArtifactStore与injector.md`

## 一、这是计划里唯一的破坏性改动

```python
# 改前
outputs: Dict[str, str]          # {相对路径: 全文内容}
# 改后
outputs: List[ArtifactOut]       # 只有元信息，内容留在磁盘
```

`_collect_outputs`（runner.py:301）原来对每个命中文件做：

```python
result[rel] = p.read_text(encoding="utf-8", errors="replace")
```

对 PNG / MP3 / MP4 是灾难——二进制被逐字节替换成 U+FFFD 塞进内存，既没法用又白占 token。skill 链接入生图后**每一轮都会踩**。

`ArtifactOut` 带 `rel_path / abs_path / kind / mime / size / is_binary`，内容由需要的人自己读 `abs_path`。

## 二、调用点比预期少：只有 2 处，各改 1 行

事前 grep 以为有 3 处，实际核对：

| 文件 | 用法 | 改动 |
|---|---|---|
| `agents/architect.py:197` | `len(result.outputs)` | 不用改（list 也支持 len） |
| `agents/architect.py:200` | `set(result.outputs.keys())` | → `set(result.output_paths)` |
| `agents/skill_agent.py:86` | `list(result.outputs.keys())` | → `result.output_paths` |
| `agents/dev.py` | **不消费 outputs** | 零改动 |

`dev.py` 的 OpenSpec Apply 走的是 `run_ctx["_skill_written_files"]`（WriteFileAction 自己维护的 tracker），和 `_collect_outputs` 是两条独立路径。方案里把它列为「需要兼容属性兜住的调用点」是误判。

**前端零依赖**：grep `frontend/app.js` 的 `outputs` —— 0 结果。

## 三、`text_outputs` 兼容属性：留了但没人用

原计划用它让 architect.py 零改动。实际 architect 只要**文件名集合**判四件套齐不齐，用 `output_paths` 更直接也更便宜（不读盘）。

保留它是因为 OpenSpec Apply 那类场景后续可能要回读内容做校验。docstring 写明了当前无调用者 + 为什么新代码不该用它（二进制静默跳过、每次访问重新读盘）。

**没有为了「用上兼容层」而硬塞**——那会让 architect 每次都读 4 个文件的全文只为拿一组文件名。

## 四、顺手修了一个隐藏 bug：glob 重叠不去重

原实现对每个 glob 独立 `glob()` 后直接写进 dict——`{路径: 内容}` 天然按 key 去重。改成 list 后同一文件会被登记多次。

这不只是整洁问题：`expected_output_count` 的 partial 判定看 `len(outputs)`。声明 `["draft.md", "*.md"]` 两个 glob、实际只产出 1 个文件，不去重会报「2 个产出，齐了」——**虚假的成功**。

加了 `seen` 按 `resolve()` 去重，首个匹配的 glob 定 kind。

## 五、kind 反查：一个 glob 对一个 kind

```python
kind_by_glob = {p["glob"]: p["kind"] for p in sop_config["_produces"]}
```

`sop_config` 由 orchestrator 注入（orchestrator.py:1833），`_produces` 来自 x-workflow 声明。

**一个 glob 命中多文件时它们共享同一 kind** —— 这是刻意的。`images/*.png` 一次产出 N 张图不该要求声明 N 条 produces。写成了测试 `test_collect_one_glob_many_files_share_kind`。

老 skill（openspec-*）没有 x-workflow，`kind` 为空串，不报错。

## 六、端到端验证：openspec-propose 的真实回收路径

不调 LLM，只验「回收 + architect 消费」这段。造出四件套里的三件（模拟 LLM 漏写 design.md）：

```
skill loaded: openspec-propose | globs: ['proposal.md','specs.md','design.md','tasks.md']
out_root: .../openspec/changes/add-foo
3/4 partial=True
  proposal.md OK
  specs.md    OK
  design.md   MISS      ← 正确识别缺失
  tasks.md    OK
```

`expected_output_count` 的 partial 判定和 `_mark()` 的逐件标记都和改造前一致。

## 七、变异测试（3 注入全抓）

| 注入 | 变红 |
|---|---|
| A. `is_binary` 恒 False | 2（`does_not_read_binary` + `text_outputs_skips_binary`） |
| B. 去掉去重 | 1（`dedups_files_matched_by_multiple_globs`） |
| C. kind 反查关闭 | 3（三条 kind 用例） |

## 八、新增测试（16 个）

`backend/tests/skills/test_runner_outputs.py`

| 组 | 锁什么 |
|---|---|
| ArtifactOut | `name` 属性、`_TEXT_EXTS` 覆盖常见格式 |
| 回收基本行为 | 返回 list 不是 dict、元信息填充、缺 root 不抛、跳目录、多 glob、**去重** |
| 二进制（核心） | PNG 字节完好、`text_outputs` 跳过它、文件被删不崩 |
| kind 反查 | glob→kind、一 glob 多文件共享 kind、无声明为空、坏条目容错 |
| partial 判定 | `len(outputs)` 语义不变 |

## 九、改动清单

```
backend/skills/runner.py       +109 -12   （ArtifactOut / text_outputs / _collect_outputs 重写）
backend/agents/architect.py    +2 -1      （outputs.keys() → output_paths）
backend/agents/skill_agent.py  +1 -1      （同上）
backend/tests/skills/test_runner_outputs.py  新增 16 用例
```

实际逻辑改动很小，大头是 `ArtifactOut` 和 `text_outputs` 的 docstring——把「为什么不再读内容」「为什么兼容属性不该被新代码用」写在代码旁边。

测试总数 115 → 131。

## 十、验证

```bash
cd backend && python -m pytest tests/ -q     # 131 passed in 45s
python -c "import main; from agents.architect import ArchitectAgent; ..."  # 三个 Agent 导入正常
```

## 十一、遗留

**没有跑真实 LLM 的 openspec-propose。** 端到端验证只覆盖了「文件已落盘 → 回收 → architect 消费」这段，没验 SkillRunner 的 REACT 循环本身。那段没改动（`execute` 只有最后一行 `_collect_outputs` 的返回类型变了），但真实跑一次仍是更强的证据。等 demo skill 链落地时会连带覆盖。

## 十二、下一步

任务 #9：`discover_workflow_skills` + `WorkflowSkill` 解析（`skills/executable_loader.py` 新增函数）。

现有 `load_executable_skill` 只能按 id 加载，没有发现机制 —— 组装器要扫 skill 必须先有它。
