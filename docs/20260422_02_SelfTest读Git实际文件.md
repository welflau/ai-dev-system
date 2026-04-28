# DevAgent SelfTest 读 Git 实际文件 — 实现方案（盲审修复 P1）

> 日期: 2026-04-22 | TODO.md 盲审修复栏 P1 最后一项

---

## 一、背景

### 1.1 问题

DevAgent 开发完成后跑 SelfTest。历史实现（`backend/actions/self_test.py`）的 5 项检查**全部只读内存 `context["_files"]` dict**：
- check 1 文件产出：数 dict 条目
- check 2 入口文件：内存优先，磁盘只作"找不到时 fallback"
- check 3 代码非空：检查内存 values 长度
- check 4 语法检查：compile 内存字符串
- check 5 文件名规范：看内存 keys

**什么时候才写盘？** SelfTest 跑完返回后，orchestrator 的 `_handle_git_files` 才 `write_and_commit`。

**盲点**：SelfTest 跑完时磁盘上可能还什么都没有。如果 orchestrator 后续写盘失败（权限拒绝、磁盘满、subprocess 崩），SelfTest 已经报了 `6/6 通过 ✅`，ticket 会错误地进入 review/acceptance，下游 Agent 读空文件就各种奇怪。

唯一的 flush（`_flush_files_to_repo`，line 176）只在**截图阶段**才调，并且只在"有入口文件 + 前端项目"条件下触发。纯后端/API 项目根本不会预落盘。

### 1.2 TODO.md 登记

```
| P1 | DevAgent SelfTest | 不读 Git 仓库实际文件 | 检查仓库中文件而非只看内存 files |
```

### 1.3 目标

- SelfTest 开始时**无条件**把所有产出文件预落盘（所有项目类型）
- 入口文件检查改为"磁盘为准"
- 新增 check 6 "磁盘落地"：逐文件验证磁盘存在 + 大小合理
- SOP config `verify_disk_files: true` 默认开启，可关闭回到老行为

---

## 二、方案设计

### 2.1 新数据流

```
旧:
DevAgent._do_develop
  ├─ code_gen (WriteCode / PlanCodeChange)
  ├─ SelfTest (全内存检查)
  └─ return
  ↓
orchestrator._handle_agent_result
  └─ _handle_git_files → write_and_commit（此时才真落盘）

新:
DevAgent._do_develop
  ├─ code_gen
  ├─ SelfTest:
  │   ├─ Phase 0: _flush_files_to_repo（无条件、所有文件）
  │   ├─ check 1 文件产出
  │   ├─ check 2 入口文件（磁盘为准）
  │   ├─ check 3 代码非空（仍读内存，等价刚写盘内容）
  │   ├─ check 4 语法检查
  │   ├─ check 5 文件名规范
  │   ├─ check 6 磁盘落地验证（新增）
  │   └─ check 7 截图（条件同前，不再重复 flush）
  └─ return
  ↓
orchestrator._handle_agent_result
  └─ _handle_git_files → git add + commit（文件已在磁盘，commit 必定成功）
```

**为什么能兼容 orchestrator 的 write_and_commit？**
- `git_manager.write_file` 只写磁盘，不调 git add/commit
- orchestrator 后续 `write_and_commit` 会读内存 files dict 再 git add + commit —— 等价于对磁盘上相同内容再写一次（no-op）+ git add + commit

### 2.2 新 check `_verify_disk_files`

```python
async def _verify_disk_files(self, project_id: str, files: Dict[str, str]) -> Dict:
    from git_manager import git_manager
    repo = git_manager._repo_path(project_id)
    if not repo.exists():
        return {"ok": False, "detail": "仓库目录不存在"}

    problems = []
    checked = 0
    for fp, expected_content in files.items():
        p = repo / fp
        if not p.exists():
            problems.append(f"{fp}: 未落盘")
            continue
        try:
            actual = p.stat().st_size
        except Exception as e:
            problems.append(f"{fp}: stat 失败 ({e})")
            continue
        exp = len((expected_content or "").encode("utf-8"))
        # 预期非空但磁盘接近空
        if exp > 50 and actual < exp * 0.5:
            problems.append(f"{fp}: 磁盘 {actual}B 远小于预期 {exp}B")
            continue
        checked += 1

    if problems:
        return {"ok": False, "detail": "; ".join(problems[:3])}
    return {"ok": True, "detail": f"{checked} 个文件已落盘"}
```

**容差选择**：
- 预期 size ≤ 50 字节的小文件（如空 `__init__.py`）：跳过大小检查，只要磁盘存在就过
- 预期 >50 字节：磁盘 size 必须 ≥ 预期的 50%（留 50% 容差给 CRLF/BOM/trailing newline 差异）
- 接入后再根据实测微调

### 2.3 `_flush_files_to_repo` 改动

扩大范围：原来 skip `.md/.txt`（只写代码文件），现在**连文档都写**（dev-notes.md / PRD.md 等）。

这样 `_verify_disk_files` 能统一验证所有产出（不用区分代码 vs 文档），同时文档也能在 SelfTest 阶段真的落地（供后续 Agent 读取 dev-notes.md 引导后续步骤）。

### 2.4 入口文件检查改"磁盘为准"

```python
# 旧:
has_entry = any(f in files for f in ENTRY)  # 内存
if not has_entry and project_id:
    has_entry = any((repo / f).exists() for f in ENTRY)  # fallback

# 新:
if project_id:
    try:
        has_entry = any((repo / f).exists() for f in ENTRY)  # 直接磁盘
    except Exception:
        has_entry = any(f in files for f in ENTRY)  # 异常时降级内存
else:
    has_entry = any(f in files for f in ENTRY)
```

现在磁盘是权威：如果内存有但磁盘没落下，check 2 会红——比老行为更诚实。

### 2.5 SOP config opt-out

```yaml
- id: development
  config:
    self_test: true
    verify_disk_files: true    # 默认开；false 则跳过 check 6
    ...
```

`sop_config.verify_disk_files=false` 时只跑 check 1-5（老行为）+ check 7 截图；不做磁盘落地验证。

---

## 三、改动清单

### 修改

| 文件 | 改动 |
|---|---|
| `backend/actions/self_test.py` | run() 开头 Phase 0 `_flush_files_to_repo`；check 2 改磁盘优先；新增 `_verify_disk_files` + check 6；screenshot 阶段去除重复 flush；_flush_files_to_repo 不再 skip .md/.txt |
| `backend/sop/default_sop.yaml` | development.config 加 `verify_disk_files: true` |
| `docs/TODO.md` | 盲审修复栏 P1 DevAgent SelfTest 标记 ✅ 完成 |

### 新增

| 文件 | 说明 |
|---|---|
| `backend/_test_self_test_disk_verify.py` | 5 用例单测 |
| `docs/20260422_02_SelfTest读Git实际文件.md` | 本文档 |

---

## 四、测试

### 单测 `_test_self_test_disk_verify.py`（5/5 通过）

```
✅ Test 1 flush + verify 全过
✅ Test 2 文件缺失 verify 失败
✅ Test 3 空文件 verify 失败
✅ Test 4 无 project_id 跳过磁盘 check
✅ Test 5 SOP opt-out
```

### 回归（9 套 47 用例全绿）

```
_test_skills.py              ✅ 8/8
_test_reflection.py          ✅ 5/5
_test_failure_library.py     ✅ 6/6
_test_session_logger.py      ✅ 5/5
_test_mcp_client.py          ✅ 5/5
_test_vision_action_node.py  ✅ 4/4
_test_blind_review_fixes.py  ✅ 4/4
_test_self_consistency.py    ✅ 5/5
_test_self_test_disk_verify  ✅ 5/5（新增）
```

### 端到端手工

1. `POST /api/sop/reload` 让新 SOP 配置生效
2. 创建一个新需求
3. DevAgent 完成后查 ticket_logs：`self_test.summary` 应变为 "7/7 通过 ✅"（多出一条"磁盘落地"）
4. 查 `self_test.checks`，对应一条：
   ```
   {"name": "磁盘落地", "passed": true, "detail": "3 个文件已落盘"}
   ```

---

## 五、风险与降级

| 风险 | 缓解 |
|---|---|
| 预写盘 + orchestrator write_and_commit 重复写 | write_file 只写磁盘不 commit；后续 git add 吸收即可 |
| 文件大小容差过严/过宽 | 50% 下限 + 50 字节 small-file 跳过；实测后微调 |
| 第三方文件（如 .env）误过检 | SelfTest 只关心 dev_result.files 产出的文件，不扫整个仓库 |
| 某项目 verify 误报致所有工单 rework | SOP `verify_disk_files: false` opt-out 一键回滚 |
| flush 失败被静默吞掉 | flush 用 try/except 但 verify 会抓出文件缺失 → check 6 红 → SelfTest 失败 → 走 rework 路径 |

---

## 六、一句话总结

> DevAgent 自测历史只看内存 `_files` dict，能产生"自测通过但文件未落盘"的假阳性。现在 SelfTest 开头就把所有文件预写磁盘，新增 check 6 "磁盘落地"逐文件验证存在且大小合理。默认开启，SOP `verify_disk_files: false` 可关。盲审修复 P1 完成，盲审栏 2/5 → 3/5。
