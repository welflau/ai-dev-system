# ManualMode Phase1 — 基础设施：P4管理器 + VCS检测 + 手动挡开关

> 日期：2026-06-16
> 系列：ManualMode
> 关联文档：`docs/20260616_02_手动挡模式与多路径项目设计方案.md`

---

## 背景

现有系统只有「自动挡」：工单流转 + 自动 git commit。  
Phase 1 搭建手动挡所需的基础设施，为后续阶段（快速打开目录、多路径感知、P4 写前 checkout）打基础。

---

## 新增文件

### `backend/p4_manager.py`

P4 操作管理器（全局单例 `p4_manager`）。

| 方法 | 说明 |
|---|---|
| `p4_info(cwd)` | 执行 `p4 info`，返回解析 dict，失败返回 None |
| `detect_p4_root(path)` | 检测路径是否在 P4 workspace 下，返回 client root |
| `p4_where(file_path)` | 确认文件是否在 P4 depot 映射中 |
| `p4_edit(file_path)` | `p4 edit` checkout 文件，返回 (success, message) |
| `p4_add(file_path)` | `p4 add` 新文件加入 P4 管理 |
| `p4_revert(file_path)` | `p4 revert` 撤销 checkout |
| `is_p4_managed(file_path)` | 快速判断文件是否在 P4 管理下 |
| `is_checked_out(file_path)` | 判断文件是否已 opened |

所有方法异步，超时保护（10-15s），失败只返回 False/None，不抛异常。  
P4 未安装时优雅降级。

### `backend/vcs_detector.py`

VCS 类型检测器 + 写前检查。

**`detect_vcs(path) → VCSType`**  
优先级：git > p4 > none
1. 向上查找 `.git/` → git
2. 向上查找 `.p4config`（或 `$P4CONFIG`）→ p4
3. `p4 where` 确认 → p4
4. 兜底 → none

结果缓存到 `_vcs_cache`，`clear_vcs_cache()` 可清空。

**`ensure_writable(file_path, readonly_paths) → dict`**  
写文件前调用，返回 `{ok, action, message, vcs}`：

| action | 含义 |
|---|---|
| `direct` | git 路径或无管理，直接可写 |
| `p4_edit` | 已执行 `p4 edit` checkout |
| `p4_already` | 文件已在 P4 opened 状态 |
| `readonly` | 只读路径，需调用方弹确认 |
| `error` | P4 操作失败 |

**`scan_project_paths(root_path) → list[dict]`**  
扫描项目目录，识别子目录 VCS 类型，用于「打开目录」自动填充多路径配置。

---

## 改动文件

### `backend/database.py`

migrations 列表新增两个字段（`IF NOT EXISTS` 方式，向后兼容）：

```python
("projects", "mode",        "TEXT NOT NULL DEFAULT 'auto'"),   # auto | manual
("projects", "extra_paths", "TEXT NOT NULL DEFAULT '[]'"),      # JSON 多路径配置
```

`mode` 字段：
- `auto`：自动挡（现有行为，工单流转 + 自动 git commit）
- `manual`：手动挡（纯对话 + 只写文件不 commit）

`extra_paths` 字段（JSON 数组）：
```json
[
  {"path": "F:/MyGame/Source", "vcs": "git", "auto_detected": false, "writable": true},
  {"path": "F:/MyGame/Content", "vcs": "p4", "auto_detected": false, "writable": true},
  {"path": "F:/UE5/Engine", "vcs": "git", "auto_detected": true, "writable": false}
]
```

### `backend/git_manager.py`

新增 `write_files_only(project_id, files) → dict`：  
只写文件，不 commit、不 push，返回 `{"manual_mode": True, ...}`。

### `backend/orchestrator.py`

`_handle_git_files()` 中读取项目 `mode` 字段：

```python
project_mode = project.get("mode", "auto")
if project_mode == "manual":
    git_result = await git_manager.write_files_only(project_id, files)
else:
    git_result = await git_manager.write_and_commit(...)
```

媒体文件（截图）同样在手动挡下只写不 commit。

---

## 验证

重启服务后：
1. 将某项目 `mode` 改为 `manual`（直接改 DB 或 API）
2. 触发工单执行 → 日志出现 `🔧 手动挡：跳过 git commit`
3. 检查项目目录 → 文件已写入，`git log` 无新 commit
4. `p4_manager.p4_info()` 在有 P4 环境的机器上返回连接信息
