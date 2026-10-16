# ArtifactStore + consumes injector（2026-10-15）

2026-10-15

方案文档：`docs/20261015_01_能力自描述与动态组装框架方案.md`（§3.6）
前置：`2026-10-15_04_artifacts表加4列.md`

## 一、做了什么

产物总线的两端：

```
backend/artifacts/store.py      388 行  写入 / 查询 / ticket_brief
backend/artifacts/injector.py   186 行  consumes 注入 + prompt 渲染
backend/tests/artifacts/test_store.py  648 行（33 用例）
```

落盘约定（与 `orchestrator.py:3770` 的 `docs_prefix` 同构）：

```
<repo>/artifacts/{req_id[-6:]}/{ticket_id[-6:]}/{kind}/{filename}
```

`x-runner.outputs.root` 渲染成同一位置 → SkillRunner 写出来就在位，`put` 只登记不搬运（已用 `test_put_from_src_path_already_in_place_no_copy` 锁住）。

## 二、测试抓到一个真 bug

写完 store 跑测试，**16 个用例同时红**：

```python
if bool(src_path) == (content is None):
    raise ArtifactStoreError("src_path 与 content 必须且只能提供一个")
```

这个条件恰好把两种**合法**情形判成错误：

| src_path | content | `bool(src)` | `content is None` | 判定 |
|---|---|---|---|---|
| 给了 | 没给 | True | True | ❌ 误报 |
| 没给 | 给了 | False | False | ❌ 误报 |

正确写法是 `bool(src_path) == (content is not None)`。

这类「两者恰好二选一」的异或判断写反是高频错误，而且**不写测试根本发现不了**——因为两条正常路径全被挡住，任何调用都会 raise，但 raise 的消息看起来还挺合理。代码里留了注释说明初版错在哪。

## 三、COALESCE(kind, type) 是核心正确性来源

存量 2246 条的 `kind` 全是 NULL（上一轮刻意不回填）。`list(kinds=[...])` 如果只查 `kind` 列，老产物**一条都查不到**。

```sql
WHERE COALESCE(kind, type) IN (?, ?)
```

这直接决定了「新 skill 能否 consumes 老产物」——lint 的 E2 规则明确允许这个方向（内容 skill 读 PRD 是合理需求）。注入「去掉 COALESCE」验证：2 个测试红。

正因为这类 SQL 语义是核心，测试用**真实 SQLite** 而非 mock。mock 掉等于不测。

## 四、又一个假绿：binary 检查

注入「删掉 `spec.binary` 判断」，测试**全绿**。

原因：测试用的 PNG 魔数 `\x89PNG` 不是合法 UTF-8，所以即便少了声明检查，也会被下面的 `UnicodeDecodeError` 兜底捕获而返回空串。两条路径产出相同结果，测试不可区分。

补了 `test_read_text_respects_binary_kind_even_if_decodable`，内容用 `b"GIF89a" + b"pretend-image-bytes"`——**合法 UTF-8 的字节串**。少了声明检查就会被当文本返回，二进制内容进 prompt。真实场景：小尺寸 GIF、某些 WAV 头部恰好落在 ASCII 区间。

再注入立刻变红。

**这是第三次踩同一类坑**（T9b 的 yaml cache、T11c 的 trigger_on、这次的 binary）。规律已经很清楚：

> 当测试要验证「某个判断必须生效」时，先问：**现有输入下，去掉这个判断会不会产生相同结果？** 会，就说明测试测的是别的东西。

必须构造一个让「有判断」和「无判断」产生**可观测差异**的输入。

## 五、injector 的三个设计决定

### a) 路径为主，不内联内容

system prompt 只给路径 + 大小，让 LLM 用 `read_file` 自取。理由：

- 二进制产物根本塞不进 prompt
- 大文件挤爆 token，而 skill 往往只需要其中一部分
- LLM 按需截取比我们猜它要哪段准

`mode=text` 是例外（小文件且必读），上限 8000 字符。

**关键细节**：不内联时**必须显式告诉 LLM 用 read_file**，否则它会凭空编造内容。写成了测试断言。

### b) required 与可选的缺失分开报

```python
"_artifacts_missing": [...]           # 全部缺失
"_artifacts_missing_required": [...]  # 其中必需的
```

前者是正常降级（可选产物本就可能没有），后者是异常信号。prompt 里对必需缺失额外加一句「不要编造内容，在 done 的 summary 里说明」。

### c) 工单级查不到 → 回退需求级

跨工单共享的产物（如 `style_guide`）挂在需求上。只查工单会漏。

### d) 不因缺失而 abort

组装期的「缺源」检查已剔除无 producer 的 skill。运行期还缺通常意味着上游 skipped 或失败——此时让 LLM 看到「缺什么」比直接中断更有用。

## 六、`put_ticket_brief`：天然源必须有人产出

`ticket_brief` 在 kinds.yaml 标了 `builtin: true`，组装器视为已就绪。但**它不会凭空存在**——没有它，所有 `consumes: [ticket_brief]` 的 skill 都会因缺源被剔除，整条链直接空掉。

所以 store 提供 `put_ticket_brief`，SkillAgent 跑第一个 skill 前调。

做成**幂等**（已存在直接返回）：返工重跑时需求快照不应变化，也不该堆出一串重复行。注入「去掉幂等检查」验证：对应测试红。

## 七、变异测试（5 注入，4 抓 1 补）

| 注入 | 结果 |
|---|---|
| A. 去掉 COALESCE | 2 红 ✓ |
| B. 不双写 type | 1 红 ✓ |
| C. filename 不清洗（路径穿越） | 1 红 ✓ |
| D. 去掉 binary 检查 | **全绿 → 补测试后 1 红** |
| E. ticket_brief 不幂等 | 1 红 ✓ |

注入 C 验证的是安全边界：`filename` 来自 LLM（produces glob 命中的文件名），`../../../etc/passwd` 必须被削成 `passwd` 落在目标目录内。

## 八、改动清单

```
backend/artifacts/store.py                388 行（新增）
backend/artifacts/injector.py             186 行（新增）
backend/artifacts/__init__.py             +26（导出 store/injector）
backend/tests/artifacts/test_store.py     648 行（33 用例，新增）
```

测试总数 82 → 115。

## 九、验证

```bash
cd backend && python -m pytest tests/ -q    # 115 passed in 46s
python -c "import main"                      # 导入无副作用
```

测试耗时从 12s 涨到 46s——每个 store 测试都建一个真实 SQLite 并跑完整 `init_tables`。可接受，但如果继续增长要考虑把 schema 初始化提成 session 级 fixture。

## 十、遗留

1. **无产物版本语义**。返工重跑覆盖同路径文件，表里插第二条。`latest_per_kind` 取新的没问题，旧文件物理覆盖不可回溯（git 历史兜底）。已在方案 §五-5 记录。
2. **`_env` 替换全局 `database.db`**。ArtifactStore 内部 `from database import db` 取模块级单例，测试只能替换它。同进程跑完所有文件时必须还原，已用 try/finally 保证。更干净的做法是给 store 的方法加 `db` 参数注入，但那会污染 10 个调用点的签名。

## 十一、下一步

任务 #8：`SkillRunResult.outputs` 从 `Dict[str,str]` 改成 `List[ArtifactOut]`。

这是整个计划里**唯一的破坏性改动**。`text_outputs` 兼容属性能让 `architect.py` / `dev.py` 两个 OpenSpec 调用点零改动，只需改 `skill_agent.py:86`。改完要跑一次真实的 openspec-propose 确认不回归。
