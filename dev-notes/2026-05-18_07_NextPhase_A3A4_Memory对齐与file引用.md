# NextPhase A-3/A-4：Memory 對齊 + @file 引用展開

> 系列：NextPhase  
> 日期：2026-05-18  
> 提交：`4403a4f`（A-3）、`577ab22`（A-4）

---

## A-3：Memory 4 類型對齊（對標 Claude Code）

### 類型映射

| 新類型（Claude Code 對齊）| 舊類型（自動映射）| 表情 | 說明 |
|---|---|---|---|
| `user_profile` | `user` | 👤 | 用戶角色、偏好、知識背景 |
| `behavior_feedback` | `insight` | 💬 | 行為反饋（正向確認或糾正）|
| `project_context` | `project`、`technical`、`decision` | 📁 | 項目決策、里程碑、技術方案 |
| `external_ref` | — | 🔗 | 外部資源指針（Linear/文檔鏈接）|

### MEMORY.md 索引樣式注入

**之前**：
```
## 項目歷史記憶（最近 3 條）
  [decision] 選擇 Phaser 3 框架（2026-05-14）
```

**現在**（MEMORY.md 樣式）：
```
## 項目記憶（MEMORY）

- [📁 項目] **選擇 Phaser 3 框架**（2026-05-14）
  考慮了 Godot/Unity 後選擇 Phaser 3，因為輕量且前端友好
- [👤 用戶] **用戶偏好：代碼注釋用中文**（2026-05-15）
- [💬 反饋] **不要 mock 數據庫**（2026-05-16）
  之前測試通過但 prod 失敗，必須真實 DB

如需完整記憶請調用 get_memory 工具。
```

### 改動

- `actions/chat/memory_write.py`：枚舉擴充到 4 類，舊值自動映射
- `agents/base.py`：`_MEMORY_TYPE_LABELS` + `get_memory_prompt()` 更新為 MEMORY.md 格式，limit 3→5
- `agents/chat_assistant.py`：Memory 注入改為調用 `BaseAgent.get_memory_prompt`

---

## A-4：@file 引用展開（對標 Claude Code `@include`）

**用法**：在消息中輸入文件路徑，前面加 `@`：
```
幫我分析這個崩潰日誌 @G:/A_Works/OG2/BUG/2026-05-14_Crash/修复方案.md
對比這兩個文件：@./src/main.py 和 @./src/utils.py
```

**工作原理**：
```
用戶消息（含 @file）
  ↓ api/chat.py _expand_file_refs()
  ├─ 識別所有 @/path 語法
  ├─ 讀取文件（限 100KB）
  ├─ 注入為 markdown 附件塊
  └─ 失敗的引用顯示警告
  ↓ 展開後的消息 → LLM
```

**安全限制**：
- 文件大小上限：100KB
- 禁止：`.pem`、`.key`、`.pfx`、`.p12` 密鑰文件

**前端**：輸入 `@` 後顯示 3 秒提示氣泡告知用法。
