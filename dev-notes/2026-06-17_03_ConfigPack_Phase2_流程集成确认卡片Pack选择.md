# ConfigPack 库 — Phase 2：流程集成

**日期**：2026-06-17  
**阶段**：Phase 2 完成

---

## 实现内容

### 修改文件

| 文件 | 变更 |
|---|---|
| `backend/actions/chat/create_project.py` | 新增 `_auto_install_packs()` + 调用 |
| `backend/actions/chat/confirm_project.py` | 两处 run() 返回值加 `recommended_packs`；新增 `_get_recommended_packs()` 辅助函数；删除重复 class 定义 |
| `backend/api/chat.py` | `ConfirmCreateProjectRequest` 新增 `selected_packs` 字段 |
| `backend/models.py` | `ProjectCreate` 新增 `selected_packs` 字段 |
| `frontend/app.js` | 确认卡片新增 Pack 选择区 + `doConfirmProject` 传 `selected_packs` |

---

## 数据流

```
用户发起新建项目意图
    ↓
ConfirmProjectAction.run()
    → traits → _get_recommended_packs() → recommended_packs[]
    → 返回 confirm_project action_data（含 recommended_packs）
    ↓
前端渲染确认卡片
    → 展示推荐 Pack（默认勾选）
    → 用户可反选
    ↓
用户点击「确认创建」
    → doConfirmProject() 读取勾选的 Pack
    → POST /chat/confirm-create-project { ...原有字段, selected_packs: [...] }
    ↓
CreateProjectAction.run()
    → asyncio.create_task(_auto_install_packs(..., selected_packs))
    ↓
_auto_install_packs()
    → selected_packs 不为 None：直接安装用户选择的 Pack
    → selected_packs 为 None：按 traits 推荐安装
    → install_packs() → copy/append/merge 到项目目录
    → 写 project_packs 表 + 更新 projects.installed_packs
```

---

## 前端 Pack 选择区

在 `_renderConfirmProjectCard` 末尾、模式选择器之后插入 Pack 区块：

```html
⚙️ ConfigPack（CLI 配置，可取消勾选）
☑ UE5 开发套件    UE5 项目全套 CLI 配置   [rules] [agents] [commands]
☑ Git 工作流      Git 日常操作命令        [commands]
```

- 默认勾选推荐 Pack（`selected: true`）
- 用户可反选任意 Pack
- 无推荐时不显示该区块（不干扰原有流程）

---

## confirm_project.py 重复类清理

文件原来有两个 `ConfirmProjectAction` 类定义（历史遗留）。  
本次删除了第二个（只支持新建项目的旧版本），保留第一个（支持 local_path 手动挡的完整版本）。  
两个版本的 run() 返回值都已加上 `recommended_packs` 字段。

---

## Phase 3 待办

- 项目详情页展示已安装 Pack 列表（从 `project_packs` 表读取）
- 手动"重新安装"某个 Pack 的接口和按钮
- 支持用户自定义 Pack（`~/.ads/config_packs/`）
