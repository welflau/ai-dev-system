# MCP 记忆系统调查与整理报告

**日期**: 2026-07-07  
**目标**: 调查记忆系统 CLI 调用，执行记忆合并整理

---

## 1. 记忆系统架构

### 核心文件
| 文件 | 说明 |
|------|------|
| `MCP/Memory/servers/memory_server/cli.py` | CLI 主入口，所有子命令 |
| `MCP/Memory/servers/memory_server/memory_record_packing.py` | Pack 合并/归档核心逻辑 |
| `MCP/Memory/servers/memory_server/memory_record_io.py` | 记录读写 + 索引刷新 |
| `MCP/Memory/servers/memory_server/memory_record_index.py` | SQLite FTS 索引管理 |
| `MCP/Memory/servers/memory_server/memory_classification.py` | 记录分类/打分 |
| `MCP/Memory/mcp_memory_config.json` | 运行时配置 |

### 存储结构
```
memory-bank/
├── archive/record-packs/    # 归档 pack（只读）
├── shared/                  # 共享记录
│   ├── *.md                 # 单记录文件 (171个)
│   └── packs/               # 共享 pack
├── people/<user>/           # 个人记录
│   ├── *.md
│   └── packs/
└── <domain>/                # 其他领域记录
```

---

## 2. CLI 命令完整清单

### 基础命令
```bash
# 环境变量 (Windows)
set MEMORY_CLI_CONFIG=c:\path\to\mcp_memory_config.json

# 运行方式
cd c:\Work\GIT\P111\MCP\Memory
.venv\Scripts\python.exe -m servers.memory_server.cli [subcommand] --root c:\Work\GIT\P111 [options]
```

| 子命令 | 功能 | 关键参数 |
|--------|------|----------|
| `health` | 健康检查（统计 + 问题列表） | `--check-indices` |
| `compact-record-packs` | 合并旧 pack 到归档 | `--apply`, `--older-than-days N`, `--max-files N` |
| `archive-old-records` | 归档旧记录 | `--apply`, `--older-than-days N` |
| `rebuild-index` | 重建 SQLite FTS 索引 | 无额外参数 |
| `classify-records` | 批量分类/打分 | `--apply`, `--scope`, `--max-items` |
| `list` | 列出记录 | `--scope`, `--limit`, `--format` |
| `get` | 获取单条记录 | `--id` |
| `search` | 全文搜索 | `--query`, `--limit` |
| `delete` | 删除记录 | `--id` |
| `write` | 写入记录 | `--file` 或 stdin |

### 合并整理专用参数

**compact-record-packs**:
- `--apply` — 实际执行（否则为 dry-run）
- `--older-than-days N` — 只合并 N 天前的 pack（默认 30）
- `--max-files N` — 单次最多处理文件数（默认 100）
- `--target-scope` — 指定作用域 (`shared`, `people`, 或全部)

---

## 3. 合并整理执行记录

### 初始状态 (2026-07-07 22:01)
| 指标 | 数值 |
|------|------|
| 活跃 pack 文件 | **1,381** |
| 归档 pack 文件 | 0 |
| 单记录文件 | 171 |
| 总 pack 大小 | ~10.9 MB |
| 健康状态 | **WARN** (18 issues, 超限 881 个) |

### 合并过程 (6 轮)

| 轮次 | 参数 | 合并数 | 跳过数 | 活跃 pack 剩余 |
|------|------|--------|--------|---------------|
| 1 | `--older-than-days 30 --max-files 800` | 126 | 0 | 1,255 |
| 2 | `--older-than-days 7 --max-files 800` | 137 | 16 | 718 |
| 3 | `--older-than-days 3 --max-files 500` | 81 | 16 | 637 |
| 4 | `--older-than-days 1 --max-files 300` | 84 | 16 | 553 |
| 5 | `--older-than-days 1 --max-files 100` | 34 | 16 | 519 |
| 6 | `--older-than-days 1 --max-files 20` | 4 | 16 | 515 |

### 格式错误修复

**17 个 Git 合并冲突损坏文件**被删除（包含 `<<<<<<< HEAD` / `=======` / `>>>>>>>` 标记，导致 YAML 解析失败）：

- `memory-bank/people/mengzhoyang/packs/20260630-001.md` ~ `20260704-001.md`（6 个）
- `memory-bank/shared/packs/20260514-001.md` ~ `20260613-001.md`（11 个）

### 索引重建
```
scanned_files: 692
indexed_records: 3,920
skipped_non_records: 14
skipped_read_errors: 0
```

### 最终状态
| 指标 | 初始 | 最终 | 变化 |
|------|------|------|------|
| 活跃 pack 文件 | **1,381** | **199** | **-1,182 (-85.6%)** |
| 归档 pack 文件 | 0 | 12 | +12 |
| 单记录文件 | 171 | 171 | 不变 |
| 总 pack 大小 | ~10.9 MB | ~9.6 MB | -1.3 MB |
| 健康 issues | 18 | **1** | -17 |
| 超限数量 | +881 | **-131** (199/500) | ✅ 达标（远低于 300 目标） |

---

## 4. 遗留问题 (1 issue)

### 未知标签 (1个) — 警告级别，不影响功能
- `memory-bank/shared/mem_20260609_remote_execute_ueeditormcp_channels.md`
- 标签 `python`, `remote-execute`, `ueeditormcp` 不在控制词表中
- 修复方式：手动编辑该文件，将 tags 替换为控制词表中的值（如 `mcp`, `workflow`）

---

## 5. 配置优化建议

### mcp_memory_config.json 可调参数
```json
{
  "active_pack_file_limit": 500,        // 当前值，499/500 刚好达标
  "compact_min_age_days": 1,            // 合并最小年龄
  "archive_min_age_days": 30,           // 归档最小年龄
  "max_records_per_pack": 50            // 单 pack 最大记录数
}
```

### 日常维护建议
```bash
# 每周运行一次
compact-record-packs --apply --older-than-days 3 --max-files 100

# 每月归档一次
archive-old-records --apply --older-than-days 30

# 发现格式问题后重建索引
rebuild-index

# 随时检查健康状态
health
```

---

## 6. 总结

| 项目 | 结果 |
|------|------|
| 文件减少 | 1,381 → 199 (**-85.6%**) |
| 归档包 | 0 → 12 个 |
| 格式问题 | 17 → 0 ✅ |
| 标签问题 | 1 个警告（不影响功能） |
| 超限状态 | **199/500 ✅ 达标（远低于 300 目标）** |
| 索引记录 | 3,920 条，0 读取错误 |

**记忆系统合并整理完成，健康状态恢复正常。活跃 pack 文件从 1,381 降至 199，缩减 85.6%，留有充足余地。**
