"""
架构师代理（ArchitectAgent）
负责技术架构设计、数据库结构设计、系统方案输出

LLM 模式：使用大模型生成专业架构方案
降级模式：使用模板引擎生成基础方案
"""
import os
import logging
from typing import Dict, Any, List
from datetime import datetime
from models.enums import AgentType, TaskType

logger = logging.getLogger(__name__)

# LLM 架构设计系统提示词
ARCHITECT_SYSTEM_PROMPT = """你是一位资深软件架构师。你的职责是根据需求生成专业的技术方案文档。

输出要求：
1. 使用 Markdown 格式
2. 内容专业、结构清晰
3. 包含具体的技术选型理由
4. 包含架构图（用 ASCII/文本描述）
5. 适合中小型团队落地执行

你直接输出 Markdown 文档内容，不要包含 ```markdown 代码块标记。"""


class ArchitectAgent:
    """架构师代理 - LLM 智能设计 + 模板降级"""

    def __init__(self, work_dir: str = "projects", llm_client=None):
        self.agent_type = AgentType.ARCHITECT
        self.work_dir = work_dir
        self.llm_client = llm_client

    def get_capabilities(self) -> List[str]:
        return [
            "系统架构设计",
            "数据库结构设计",
            "API 接口设计",
            "技术选型建议",
            "模块划分",
        ]

    def get_supported_tasks(self) -> List[str]:
        return [TaskType.DESIGN.value]

    @property
    def _llm_available(self) -> bool:
        return self.llm_client is not None and self.llm_client.enabled

    def execute(self, task_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行架构设计任务

        Args:
            task_name: 任务名称
            context: 包含 project_id, requirement 等

        Returns:
            包含 success, files_created, output 的结果
        """
        project_id = context.get("project_id", "unknown")
        requirement = context.get("requirement", "")
        project_dir = os.path.join(self.work_dir, project_id)

        task_handlers = {
            "技术架构设计": self._design_architecture,
            "设计数据库结构": self._design_database,
            "设计API接口": self._design_api,
            "功能模块设计": self._design_modules,
            "设计UI界面": self._design_ui,
            "设计用户系统": self._design_user_system,
        }

        handler = None
        for key, func in task_handlers.items():
            if key in task_name:
                handler = func
                break

        if not handler:
            handler = self._design_generic

        try:
            result = handler(project_dir, requirement, context)
            return {
                "success": True,
                "agent": self.agent_type.value,
                "task": task_name,
                **result,
            }
        except Exception as e:
            return {
                "success": False,
                "agent": self.agent_type.value,
                "task": task_name,
                "error": str(e),
            }

    def _ensure_dir(self, path: str) -> None:
        os.makedirs(path, exist_ok=True)

    def _write_file(self, filepath: str, content: str) -> str:
        self._ensure_dir(os.path.dirname(filepath))
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return filepath

    # ------------------------------------------------------------------
    #  LLM 辅助方法
    # ------------------------------------------------------------------

    def _llm_generate_doc(
        self,
        task_type: str,
        requirement: str,
        context: Dict,
        extra_instructions: str = "",
    ) -> str:
        """使用 LLM 生成设计文档，失败返回空字符串"""
        if not self._llm_available:
            return ""

        project_name = context.get("project_name", "系统")
        tech_stack = context.get("tech_stack") or {}

        prompt = f"""请为以下项目生成{task_type}文档：

项目名称：{project_name}
需求描述：{requirement}
技术栈偏好：{tech_stack if tech_stack else '未指定，请给出推荐'}

{extra_instructions}"""

        try:
            response = self.llm_client.chat(
                messages=[{"role": "user", "content": prompt}],
                system=ARCHITECT_SYSTEM_PROMPT,
                temperature=0.4,
                max_tokens=4096,
            )
            if response and response != "[LLM_UNAVAILABLE]":
                logger.info(f"LLM 生成{task_type}文档成功")
                return response
        except Exception as e:
            logger.warning(f"LLM 生成{task_type}文档失败: {e}")

        return ""

    # ==================== 系统架构设计 ====================

    def _design_architecture(
        self, project_dir: str, requirement: str, context: Dict
    ) -> Dict[str, Any]:
        """生成系统架构设计文档"""
        files_created = []
        project_name = context.get("project_name", "系统")

        # 尝试 LLM 生成
        llm_content = self._llm_generate_doc(
            "系统架构设计",
            requirement,
            context,
            extra_instructions="""文档必须包含：
1. 架构概览（架构模式选择及理由）
2. 系统分层（用 ASCII 图展示）
3. 模块划分（表格：模块名、职责、依赖）
4. 技术选型（表格：层级、技术、说明）
5. 数据流（用文本流程描述）
6. 安全设计
7. 部署架构""",
        )

        if llm_content:
            files_created.append(self._write_file(
                f"{project_dir}/docs/architecture.md",
                llm_content,
            ))
            return {
                "files_created": files_created,
                "output": f"架构设计完成（LLM 生成）",
                "mode": "llm",
            }

        # 降级：模板生成
        return self._template_design_architecture(project_dir, requirement, context)

    def _template_design_architecture(
        self, project_dir: str, requirement: str, context: Dict
    ) -> Dict[str, Any]:
        """模板生成系统架构设计文档（降级方案）"""
        files_created = []
        project_name = context.get("project_name", "系统")
        req_lower = requirement.lower()

        features = []
        if any(kw in req_lower for kw in ["api", "接口", "端点"]):
            features.append("RESTful API")
        if any(kw in req_lower for kw in ["数据库", "存储", "数据"]):
            features.append("数据持久化")
        if any(kw in req_lower for kw in ["前端", "界面", "页面", "ui"]):
            features.append("Web 前端")
        if any(kw in req_lower for kw in ["用户", "登录", "注册", "认证"]):
            features.append("用户认证")
        if not features:
            features = ["核心业务逻辑"]

        tech_stack_section = self._recommend_tech_stack(features)
        architecture_pattern = "前后端分离 + MVC" if "Web 前端" in features else "后端微服务"

        files_created.append(self._write_file(
            f"{project_dir}/docs/architecture.md",
            f"""# {project_name} - 系统架构设计

> 生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M")}
> 需求摘要: {requirement[:300]}

## 1. 架构概览

### 1.1 架构模式
**{architecture_pattern}**

### 1.2 识别到的功能模块
{chr(10).join(f'- {f}' for f in features)}

## 2. 系统分层

```
┌─────────────────────────────────────────┐
│              表示层 (Presentation)        │
│         HTML/CSS/JS / API Gateway        │
├─────────────────────────────────────────┤
│              业务层 (Business)            │
│        Services / Business Logic         │
├─────────────────────────────────────────┤
│              数据层 (Data Access)         │
│        Models / ORM / Repository         │
├─────────────────────────────────────────┤
│              基础设施 (Infrastructure)     │
│        Database / Cache / MQ             │
└─────────────────────────────────────────┘
```

## 3. 模块划分

| 模块 | 职责 | 依赖 |
|------|------|------|
| `api/` | HTTP 路由和请求处理 | services |
| `services/` | 核心业务逻辑 | models |
| `models/` | 数据模型定义 | database |
| `utils/` | 通用工具函数 | 无 |
| `config/` | 配置管理 | 无 |
{('| `auth/` | 认证授权 | services, models |' + chr(10)) if '用户认证' in features else ''}

## 4. 技术选型

{tech_stack_section}

## 5. 数据流

```
用户请求 → API 路由 → 业务服务 → 数据模型 → 数据库
                ↓
           响应返回 ← 数据序列化 ← 查询结果
```

## 6. 安全设计

- API 认证: {"JWT Token" if "用户认证" in features else "API Key"}
- 数据验证: Pydantic Schema 校验
- CORS: 白名单机制
- 密码: {"bcrypt 哈希存储" if "用户认证" in features else "N/A"}

## 7. 部署架构

- 开发环境: 本地 SQLite + uvicorn
- 生产环境: PostgreSQL + gunicorn + Nginx
- 容器化: Docker + Docker Compose
"""
        ))

        return {
            "files_created": files_created,
            "output": f"架构设计完成（模板生成）：{architecture_pattern}，识别 {len(features)} 个核心模块",
            "features": features,
            "pattern": architecture_pattern,
            "mode": "template",
        }

    def _recommend_tech_stack(self, features: List[str]) -> str:
        """推荐技术栈"""
        stack = [
            "| 层级 | 技术 | 说明 |",
            "|------|------|------|",
            "| 语言 | Python 3.10+ | 主开发语言 |",
            "| 框架 | FastAPI | 高性能异步 Web 框架 |",
            "| 数据校验 | Pydantic | 数据模型和校验 |",
        ]

        if "数据持久化" in features:
            stack.append("| ORM | SQLAlchemy 2.0 | 数据库 ORM |")
            stack.append("| 数据库 | SQLite / PostgreSQL | 开发/生产 |")

        if "Web 前端" in features:
            stack.append("| 前端 | HTML + CSS + JS | 原生实现 |")

        if "用户认证" in features:
            stack.append("| 认证 | JWT + bcrypt | Token 认证 |")

        stack.extend([
            "| 测试 | pytest + httpx | 单元/集成测试 |",
            "| 部署 | Docker + Nginx | 容器化部署 |",
        ])

        return "\n".join(stack)

    # ==================== 数据库设计 ====================

    def _design_database(
        self, project_dir: str, requirement: str, context: Dict
    ) -> Dict[str, Any]:
        """生成数据库结构设计"""
        # 尝试 LLM 生成
        llm_content = self._llm_generate_doc(
            "数据库设计",
            requirement,
            context,
            extra_instructions="""文档必须包含：
1. ER 模型（每张表的字段、类型、说明用表格展示）
2. 表之间的关联关系
3. 索引策略
4. 数据库选型建议""",
        )

        if llm_content:
            files_created = [self._write_file(
                f"{project_dir}/docs/database_design.md",
                llm_content,
            )]
            return {
                "files_created": files_created,
                "output": "数据库设计完成（LLM 生成）",
                "mode": "llm",
            }

        # 降级：模板生成
        return self._template_design_database(project_dir, requirement, context)

    def _template_design_database(
        self, project_dir: str, requirement: str, context: Dict
    ) -> Dict[str, Any]:
        """模板生成数据库设计（降级方案）"""
        files_created = []
        req_lower = requirement.lower()

        tables = []
        if any(kw in req_lower for kw in ["用户", "user", "登录"]):
            tables.append({
                "name": "users",
                "label": "用户",
                "columns": [
                    ("id", "TEXT PK", "用户ID"),
                    ("username", "VARCHAR(50) UNIQUE NOT NULL", "用户名"),
                    ("email", "VARCHAR(100) UNIQUE NOT NULL", "邮箱"),
                    ("hashed_password", "VARCHAR(128) NOT NULL", "密码哈希"),
                    ("is_active", "BOOLEAN DEFAULT TRUE", "是否启用"),
                    ("created_at", "TIMESTAMP DEFAULT NOW()", "创建时间"),
                    ("updated_at", "TIMESTAMP DEFAULT NOW()", "更新时间"),
                ],
            })

        if any(kw in req_lower for kw in ["商品", "product"]):
            tables.append({
                "name": "products",
                "label": "商品",
                "columns": [
                    ("id", "TEXT PK", "商品ID"),
                    ("name", "VARCHAR(100) NOT NULL", "商品名"),
                    ("description", "TEXT", "描述"),
                    ("price", "DECIMAL(10,2) NOT NULL", "价格"),
                    ("stock", "INTEGER DEFAULT 0", "库存"),
                    ("created_at", "TIMESTAMP DEFAULT NOW()", "创建时间"),
                ],
            })

        if not tables:
            tables.append({
                "name": "items",
                "label": "数据项",
                "columns": [
                    ("id", "TEXT PK", "ID"),
                    ("name", "VARCHAR(100) NOT NULL", "名称"),
                    ("data", "JSON", "数据内容"),
                    ("created_at", "TIMESTAMP DEFAULT NOW()", "创建时间"),
                ],
            })

        table_docs = []
        for t in tables:
            cols = "\n".join(
                f"| {c[0]} | {c[1]} | {c[2]} |" for c in t["columns"]
            )
            table_docs.append(f"""### {t['label']}表 (`{t['name']}`)

| 字段 | 类型 | 说明 |
|------|------|------|
{cols}
""")

        files_created.append(self._write_file(
            f"{project_dir}/docs/database_design.md",
            f"""# 数据库设计文档

> 生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M")}

## ER 模型

{chr(10).join(table_docs)}

## 索引策略
- 主键: 自动索引
- 唯一约束字段: 自动索引
- 查询频繁字段: 建议添加 B-Tree 索引

## 数据库选型
- **开发环境**: SQLite（零配置）
- **生产环境**: PostgreSQL（推荐）
"""
        ))

        return {
            "files_created": files_created,
            "output": f"数据库设计完成（模板生成），包含 {len(tables)} 张表",
            "tables": [t["name"] for t in tables],
            "mode": "template",
        }

    # ==================== API 接口设计 ====================

    def _design_api(
        self, project_dir: str, requirement: str, context: Dict
    ) -> Dict[str, Any]:
        """生成 API 接口设计文档"""
        llm_content = self._llm_generate_doc(
            "API 接口设计",
            requirement,
            context,
            extra_instructions="""文档必须包含：
1. 基本约定（Base URL、数据格式、认证方式、分页）
2. 端点列表（表格：方法、路径、说明）
3. 统一响应格式（成功/错误的 JSON 示例）
4. 关键接口的请求/响应示例
5. HTTP 状态码说明""",
        )

        if llm_content:
            files_created = [self._write_file(
                f"{project_dir}/docs/api_design.md",
                llm_content,
            )]
            return {
                "files_created": files_created,
                "output": "API 接口设计完成（LLM 生成）",
                "mode": "llm",
            }

        # 降级：模板生成
        return self._template_design_api(project_dir, requirement, context)

    def _template_design_api(
        self, project_dir: str, requirement: str, context: Dict
    ) -> Dict[str, Any]:
        """模板生成 API 设计（降级方案）"""
        files_created = []
        req_lower = requirement.lower()

        endpoints = []
        if any(kw in req_lower for kw in ["用户", "user", "登录"]):
            endpoints.extend([
                ("POST", "/api/auth/register", "用户注册"),
                ("POST", "/api/auth/login", "用户登录"),
                ("POST", "/api/auth/logout", "用户登出"),
                ("GET", "/api/users", "用户列表"),
                ("GET", "/api/users/{id}", "用户详情"),
                ("PUT", "/api/users/{id}", "更新用户"),
                ("DELETE", "/api/users/{id}", "删除用户"),
            ])

        if any(kw in req_lower for kw in ["api", "接口"]):
            endpoints.extend([
                ("GET", "/api/items", "资源列表"),
                ("POST", "/api/items", "创建资源"),
                ("GET", "/api/items/{id}", "资源详情"),
                ("PUT", "/api/items/{id}", "更新资源"),
                ("DELETE", "/api/items/{id}", "删除资源"),
            ])

        if not endpoints:
            endpoints = [
                ("GET", "/api/data", "获取数据"),
                ("POST", "/api/data", "提交数据"),
            ]

        ep_table = "\n".join(
            f"| `{e[0]}` | `{e[1]}` | {e[2]} |" for e in endpoints
        )

        files_created.append(self._write_file(
            f"{project_dir}/docs/api_design.md",
            f"""# API 接口设计

> 生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M")}

## 基本约定
- Base URL: `http://localhost:8080`
- 数据格式: JSON
- 认证方式: Bearer Token（Header: `Authorization: Bearer <token>`）
- 分页: `?page=1&size=20`

## 端点列表

| 方法 | 路径 | 说明 |
|------|------|------|
{ep_table}
| `GET` | `/health` | 健康检查 |

## 统一响应格式

### 成功
```json
{{
    "data": {{}},
    "message": "操作成功"
}}
```

### 错误
```json
{{
    "detail": "错误描述",
    "status_code": 400
}}
```

## HTTP 状态码
| 状态码 | 说明 |
|--------|------|
| 200 | 成功 |
| 201 | 创建成功 |
| 400 | 请求参数错误 |
| 401 | 未认证 |
| 403 | 无权限 |
| 404 | 资源不存在 |
| 500 | 服务器内部错误 |
"""
        ))

        return {
            "files_created": files_created,
            "output": f"API 接口设计完成（模板生成），共 {len(endpoints)} 个端点",
            "endpoints_count": len(endpoints),
            "mode": "template",
        }

    # ==================== 其他设计 ====================

    def _design_modules(
        self, project_dir: str, requirement: str, context: Dict
    ) -> Dict[str, Any]:
        """功能模块设计"""
        return self._design_architecture(project_dir, requirement, context)

    def _design_ui(
        self, project_dir: str, requirement: str, context: Dict
    ) -> Dict[str, Any]:
        """UI 界面设计"""
        llm_content = self._llm_generate_doc(
            "UI 界面设计",
            requirement,
            context,
            extra_instructions="""文档必须包含：
1. 设计原则
2. 页面结构和导航
3. 色彩方案
4. 布局方案
5. 关键页面线框描述""",
        )

        if llm_content:
            files_created = [self._write_file(
                f"{project_dir}/docs/ui_design.md",
                llm_content,
            )]
            return {
                "files_created": files_created,
                "output": "UI 界面设计完成（LLM 生成）",
                "mode": "llm",
            }

        # 降级
        files_created = []
        project_name = context.get("project_name", "应用")

        files_created.append(self._write_file(
            f"{project_dir}/docs/ui_design.md",
            f"""# {project_name} - UI 设计方案

## 设计原则
- 简洁易用
- 响应式布局
- 一致的视觉风格

## 页面结构
1. **首页** - 系统概览和快捷入口
2. **列表页** - 数据展示（表格/卡片）
3. **详情页** - 单条数据详细信息
4. **表单页** - 数据创建和编辑

## 色彩方案
- 主色: `#1890ff`（蓝色）
- 成功: `#52c41a`（绿色）
- 警告: `#faad14`（橙色）
- 错误: `#f5222d`（红色）
- 背景: `#f0f2f5`

## 布局
- 侧边栏导航（240px 固定宽度）
- 顶部面包屑
- 主内容区自适应
- 底部状态栏

## 组件库
使用原生 HTML/CSS/JS，参考 Ant Design 设计语言。
"""
        ))

        return {
            "files_created": files_created,
            "output": "UI 界面设计方案完成（模板生成）",
            "mode": "template",
        }

    def _design_user_system(
        self, project_dir: str, requirement: str, context: Dict
    ) -> Dict[str, Any]:
        """用户系统设计"""
        llm_content = self._llm_generate_doc(
            "用户系统设计",
            requirement,
            context,
            extra_instructions="""文档必须包含：
1. 认证流程（注册、登录、鉴权）
2. 角色权限设计
3. 安全措施
4. Token 管理策略""",
        )

        if llm_content:
            files_created = [self._write_file(
                f"{project_dir}/docs/user_system_design.md",
                llm_content,
            )]
            return {
                "files_created": files_created,
                "output": "用户系统设计完成（LLM 生成）",
                "mode": "llm",
            }

        # 降级
        files_created = []
        files_created.append(self._write_file(
            f"{project_dir}/docs/user_system_design.md",
            f"""# 用户系统设计

## 认证流程

```
注册: 用户信息 → 参数校验 → 密码哈希 → 存入数据库 → 返回用户信息
登录: 用户名+密码 → 校验 → 生成 Token → 返回 Token
鉴权: 请求 + Token → 解析 Token → 校验有效期 → 放行/拒绝
```

## 角色权限

| 角色 | 权限 | 说明 |
|------|------|------|
| admin | read, write, delete, manage_users | 管理员 |
| editor | read, write | 编辑者 |
| viewer | read | 浏览者 |

## 安全措施
- 密码: SHA-256 哈希（生产用 bcrypt）
- Token: 随机 hex 字符串，24h 过期
- 传输: HTTPS（生产环境必须）
- 防注入: ORM 参数化查询
"""
        ))

        return {
            "files_created": files_created,
            "output": "用户系统设计完成（模板生成）",
            "mode": "template",
        }

    def _design_generic(
        self, project_dir: str, requirement: str, context: Dict
    ) -> Dict[str, Any]:
        """通用设计"""
        return self._design_architecture(project_dir, requirement, context)
