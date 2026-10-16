# artifact kind 注册表（2026-10-15）

2026-10-15

方案文档：`docs/20261015_01_能力自描述与动态组装框架方案.md`（§3.2）
前置：`2026-10-15_02_base_stages可裁剪.md`

## 一、做了什么

新建 `backend/artifacts/` 包（kind 词表 + 后续的 ArtifactStore / injector）：

```
backend/artifacts/kinds.yaml   词表（19 个 kind）
backend/artifacts/kinds.py     加载 / 校验 / lint
backend/artifacts/__init__.py  对外接口
backend/tests/artifacts/test_kinds.py  26 个用例
```

三道闸：

| 闸 | 实现 | 行为 |
|---|---|---|
| 1 扫描期 | `lint_kind_refs(skill_id, consumes, produces)` | errors 非空 → skill 出局 + **ERROR** |
| 2 写入期 | `validate_kind(kind)` | 未注册直接 raise |
| 3 CI 期 | 待 x-workflow 落地后建 | 扫 SKILL.md 断言 kind 全在表内 |

## 二、先查了线上真实数据，没有凭空设计

`data/ai_dev_system.db` 的 `artifacts` 表 2246 条：

```
  1436  deploy_config      186  code         184  code_review
   163  ux_design          108  prd           88  architecture
    71  art_design          10  report
--- path 非空: 10 / content 非空: 2246
```

加上代码里 `db.insert("artifacts")` 写入但库中暂无数据的 6 个（asset_manifest / document / html_prototype / screenshot / test / ue_content），**14 个老 type 全部登记进词表**。

关键观察：**2246 条里只有 10 条 path 非空，content 全部非空。** 老产物是纯 inline 形态，新框架是纯 file 形态——这不是「要不要统一」的问题，是两套并存的既成事实。

## 三、`storage` 字段：把两套形态显式写进词表

与其假装只有一种存储，不如承认现状并让它可被校验：

```yaml
storage: file     # 落盘 + artifacts 表存 path 索引（新框架，二进制必须）
storage: inline   # 内容塞 artifacts.content 列（老 Agent 路径）
```

由此推出一条 lint 硬规则（**E2**）：

> **inline kind 不得出现在 skill 的 produces 里。**

因为 ArtifactStore 只写文件，而老读取方（`actions/write_ux_design.py:58` 的 `WHERE type='prd'` 取 content 列）会读到 NULL。表面上「产出成功」，实际下游什么都拿不到——典型的静默断链。

反向是允许的：新 skill `consumes: [prd]` 合理（内容 skill 参考 PRD），injector 会从 content 列读。

这条规则靠一条不变式支撑，已写成测试：**legacy ⟹ inline**。

## 四、lint 的 4 条 error + 1 条 warning

| 码 | 规则 | 不拦的后果 |
|---|---|---|
| E1 | 未注册 kind | 下游找不到 producer → skill 静默出局，流水线少跑一步无报错 |
| E2 | produces inline kind | 见 §三 |
| E3 | produces builtin kind | 天然源被覆盖 → 拓扑图源头出现歧义 |
| E4 | 同一 kind 既 consumes 又 produces | 自环 → 拓扑检出环 → **整条链**不组装，一个笔误拖垮全链 |
| W1 | produces 为空 | 合法（参考 openspec-validate 这类只读 skill），仅提示它是叶子节点 |

E4 单独报是有意的：方案定的降级策略是「成环 → 整条 skill 链不组装」，不在 lint 阶段指名道姓，排查时只会看到「链怎么空了」。

## 五、词表自身也要校验（解析期 raise，不降级）

`_parse_kinds` 强制：

- 命名 `^[a-z][a-z0-9_]*$`——拒绝 `Content-Outline` / `contentOutline` / `content.outline`
- `storage ∈ {file, inline}`
- `builtin` 与 `legacy` 互斥（框架自动产出 vs 老 Agent 产出，语义冲突）
- **一次报全部问题**，不要改一个发现一个

为什么 raise 而不是跳过坏条目：词表坏了意味着所有 kind 校验都不可信，继续跑等于关掉三道闸里的两道。

## 六、变异测试（4 注入全抓）

| 注入 | 变红 |
|---|---|
| A. E2 从 error 降级成 warning | `test_lint_e2_cannot_produce_inline_kind` |
| B. `validate_kind` 未注册时返回默认 spec | `test_validate_kind_raises_on_unknown` + `_error_lists_known_kinds` |
| C. 自环检测关闭 | `test_lint_e4_self_loop` |
| D. 词表混入 `Content-Outline` | 5 个（命名校验让整个词表加载失败，连锁影响） |

注入 A 是最该防的退化形态——「看起来还在校验，实际只是记了条日志」。`trait_taxonomy.yaml` 就是这么漂的。

## 七、踩到的坑：`.gitignore` 把新包整个忽略了

`backend/artifacts/` 建好后 `git status` 看不到。查出来是：

```gitignore
# Artifacts
artifacts/          # ← 不带路径前缀，匹配任意层级的 artifacts 目录
```

这条规则本意是忽略产物输出目录（`<repo>/artifacts/` 由 ArtifactStore 落盘），但 `backend/artifacts/` 是 Python 包，同名纯属巧合。

加了例外 + 注释说明为什么需要它：

```gitignore
artifacts/
# 例外：backend/artifacts/ 是 Python 包，不是产物目录
!backend/artifacts/
```

**没改包名。** `artifacts` 是这个概念最准确的名字，为了绕开一条 gitignore 规则去起 `artifact_bus` 之类的名字是本末倒置。顺带确认了没有任何代码往 `backend/artifacts/` 写运行时文件。

## 八、一个刻意的断言：`test_exactly_one_builtin_source`

```python
assert builtin_kinds() == {"ticket_brief"}
```

多个 builtin 不是错误，但「拓扑图有几个源头」是关键结构性质。新增 builtin 应当是一个有意识的决定，而不是顺手加一个字段。这条测试会强制那次决定被看见。

## 九、改动清单

```
backend/artifacts/kinds.yaml           新增（19 kind）
backend/artifacts/kinds.py             新增（~250 行）
backend/artifacts/__init__.py          新增
backend/tests/artifacts/test_kinds.py  新增（26 用例）
.gitignore                             +3（例外 + 注释）
```

测试总数 48 → 74。

## 十、验证

```bash
cd backend && python -m pytest tests/ -q    # 74 passed
python -c "import main"                      # 导入无副作用
git check-ignore backend/artifacts/kinds.py  # exit 1（未被忽略）
```

## 十一、下一步

任务 #6：`artifacts` 表加 4 列（kind / mime / size_bytes / produced_by），走 `database.py:51` 的 `_auto_migrate`。

注意第 §二 节发现的事实——老数据 2246 条的 `kind` 列会全是 NULL，读取侧需要 `COALESCE(kind, type)`。
