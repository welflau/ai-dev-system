"""
开发代理（DevAgent）
负责代码生成、项目初始化、功能开发

LLM 模式：使用大模型智能生成代码
降级模式：使用模板引擎生成基础代码
"""
import os
import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from models.enums import AgentType, TaskType

logger = logging.getLogger(__name__)

# LLM 代码生成系统提示词
DEV_SYSTEM_PROMPT = """你是一位资深 Python 全栈开发工程师。
你的职责是根据任务描述生成高质量、可直接运行的代码。

技术栈：Python 3.10+, FastAPI, Pydantic, SQLAlchemy, SQLite

代码规范：
1. 包含完整的 docstring 和类型注解
2. 遵循 PEP 8 规范
3. 代码可直接运行，不需要额外修改
4. 包含必要的错误处理
5. 使用中文注释

你必须返回严格的 JSON 格式（不要包含 markdown 代码块标记），结构如下：
{
  "files": [
    {
      "path": "相对文件路径（如 src/api/user.py）",
      "content": "完整的文件内容"
    }
  ],
  "summary": "一句话描述做了什么"
}"""


class DevAgent:
    """开发代理 - LLM 智能生成 + 模板降级"""

    def __init__(self, work_dir: str = "projects", llm_client=None):
        self.agent_type = AgentType.DEV
        self.work_dir = work_dir
        self.llm_client = llm_client

    @property
    def _llm_available(self) -> bool:
        return self.llm_client is not None and self.llm_client.enabled

    def get_capabilities(self) -> List[str]:
        return [
            "项目初始化和脚手架生成",
            "API 端点代码生成",
            "数据模型代码生成",
            "前端页面代码生成",
            "数据库迁移脚本生成",
            "项目文档生成",
        ]

    def get_supported_tasks(self) -> List[str]:
        return [TaskType.DEVELOPMENT.value]

    def execute(self, task_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行开发任务

        Args:
            task_name: 任务名称
            context: 包含 project_id, requirement, tech_stack 等

        Returns:
            包含 success, files_created, output 的结果
        """
        project_id = context.get("project_id", "unknown")
        requirement = context.get("requirement", "")
        project_dir = os.path.join(self.work_dir, project_id)

        # 根据任务名匹配执行器
        task_handlers = {
            "项目初始化和环境搭建": self._init_project,
            "核心功能开发": self._generate_core_code,
            "辅助功能开发": self._generate_helper_code,
            "实现API端点": self._generate_api_code,
            "实现数据模型": self._generate_model_code,
            "编写数据库迁移脚本": self._generate_migration,
            "实现前端页面": self._generate_frontend,
            "实现前端交互逻辑": self._generate_frontend_js,
            "实现用户认证": self._generate_auth_code,
            "实现权限管理": self._generate_permission_code,
            "实现登录功能": self._generate_login_code,
            "实现注册功能": self._generate_register_code,
            "编写项目文档": self._generate_docs,
            "编写API文档": self._generate_api_docs,
        }

        handler = None
        for key, func in task_handlers.items():
            if key in task_name:
                handler = func
                break

        if not handler:
            # 没有匹配的模板 handler → 先尝试 LLM 生成
            llm_result = self._llm_generate_code(task_name, project_dir, requirement, context)
            if llm_result:
                return {
                    "success": True,
                    "agent": self.agent_type.value,
                    "task": task_name,
                    **llm_result,
                }
            # LLM 也不可用 → 通用模板兜底
            handler = self._generate_generic_code

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

    # ------------------------------------------------------------------
    #  LLM 智能代码生成
    # ------------------------------------------------------------------

    def _llm_generate_code(
        self,
        task_name: str,
        project_dir: str,
        requirement: str,
        context: Dict,
    ) -> Optional[Dict[str, Any]]:
        """
        使用 LLM 智能生成代码

        利用上下文传递的架构设计和已有文件信息，让代码生成与设计保持一致。

        Returns:
            成功返回 {files_created, output, mode}，失败返回 None
        """
        if not self._llm_available:
            return None

        project_name = context.get("project_name", "项目")
        tech_stack = context.get("tech_stack") or {}
        design_outputs = context.get("design_outputs", [])
        existing_files = context.get("existing_files", [])

        # 构建架构上下文（来自 ArchitectAgent 的输出）
        design_section = ""
        if design_outputs:
            design_items = []
            for d in design_outputs:
                design_items.append(
                    f"- [{d.get('task', '')}] {d.get('output', '')}"
                )
            design_section = f"""
架构设计参考（由架构 Agent 生成，请严格遵循）：
{chr(10).join(design_items[:10])}"""

        # 构建已有文件列表（避免重复生成）
        files_section = ""
        if existing_files:
            files_section = f"""
项目已有文件（不要重复生成这些文件，除非需要修改）：
{chr(10).join(f'- {f}' for f in existing_files[:30])}"""

        prompt = f"""请为以下开发任务生成代码：

项目名称：{project_name}
任务名称：{task_name}
需求描述：{requirement}
技术栈：{json.dumps(tech_stack, ensure_ascii=False) if tech_stack else 'Python / FastAPI / SQLite'}
{design_section}
{files_section}

请生成所有需要的文件，返回 JSON 格式。"""

        try:
            response = self.llm_client.chat(
                messages=[{"role": "user", "content": prompt}],
                system=DEV_SYSTEM_PROMPT,
                temperature=0.3,
                max_tokens=8192,
            )

            if not response or response == "[LLM_UNAVAILABLE]":
                return None

            # 解析 LLM 返回的 JSON
            return self._parse_llm_code_response(response, project_dir)

        except Exception as e:
            logger.warning(f"LLM 代码生成失败: {e}")
            return None

    def _parse_llm_code_response(
        self, response: str, project_dir: str
    ) -> Optional[Dict[str, Any]]:
        """解析 LLM 返回的代码 JSON 并写入文件"""
        text = response.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"LLM 代码响应 JSON 解析失败: {text[:200]}")
            return None

        files = data.get("files", [])
        if not files:
            return None

        files_created = []
        for f in files:
            path = f.get("path", "")
            content = f.get("content", "")
            if path and content:
                full_path = os.path.join(project_dir, path)
                files_created.append(self._write_file(full_path, content))

        if not files_created:
            return None

        return {
            "files_created": files_created,
            "output": data.get("summary", f"LLM 生成了 {len(files_created)} 个文件"),
            "mode": "llm",
        }

    def _ensure_dir(self, path: str) -> None:
        """确保目录存在"""
        os.makedirs(path, exist_ok=True)

    def _write_file(self, filepath: str, content: str) -> str:
        """写入文件并返回路径"""
        self._ensure_dir(os.path.dirname(filepath))
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return filepath

    # ==================== 项目初始化 ====================

    def _init_project(
        self, project_dir: str, requirement: str, context: Dict
    ) -> Dict[str, Any]:
        """初始化项目结构"""
        files_created = []
        project_name = context.get("project_name", "my-project")

        # 目录结构
        dirs = [
            f"{project_dir}/src",
            f"{project_dir}/src/api",
            f"{project_dir}/src/models",
            f"{project_dir}/src/services",
            f"{project_dir}/src/utils",
            f"{project_dir}/tests",
            f"{project_dir}/docs",
            f"{project_dir}/config",
        ]
        for d in dirs:
            self._ensure_dir(d)

        # requirements.txt
        files_created.append(self._write_file(
            f"{project_dir}/requirements.txt",
            f"""# {project_name} 依赖
fastapi>=0.100.0
uvicorn>=0.23.0
pydantic>=2.0.0
sqlalchemy>=2.0.0
python-dotenv>=1.0.0
pytest>=7.0.0
httpx>=0.24.0
"""
        ))

        # main.py
        files_created.append(self._write_file(
            f"{project_dir}/src/main.py",
            f'''"""
{project_name} - 主应用入口
自动生成于 {datetime.now().strftime("%Y-%m-%d %H:%M")}
需求: {requirement[:200]}
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="{project_name}",
    description="由 AI 自动开发系统生成",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {{"message": "{project_name} 运行中", "version": "0.1.0"}}


@app.get("/health")
async def health():
    return {{"status": "healthy"}}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)
'''
        ))

        # __init__.py 文件
        for subdir in ["api", "models", "services", "utils"]:
            files_created.append(self._write_file(
                f"{project_dir}/src/{subdir}/__init__.py", ""
            ))

        # .env.example
        files_created.append(self._write_file(
            f"{project_dir}/config/.env.example",
            """# 应用配置
APP_ENV=development
APP_PORT=8080
DATABASE_URL=sqlite:///./app.db
SECRET_KEY=change-me-in-production
"""
        ))

        # README
        files_created.append(self._write_file(
            f"{project_dir}/README.md",
            f"""# {project_name}

> 由 AI 自动开发系统生成

## 需求描述
{requirement[:500]}

## 快速开始

```bash
pip install -r requirements.txt
cd src && python main.py
```

## 项目结构
```
src/
  ├── main.py          # 应用入口
  ├── api/             # API 路由
  ├── models/          # 数据模型
  ├── services/        # 业务逻辑
  └── utils/           # 工具函数
tests/                 # 测试用例
docs/                  # 文档
config/                # 配置文件
```
"""
        ))

        return {
            "files_created": files_created,
            "output": f"项目 {project_name} 初始化完成，创建了 {len(files_created)} 个文件",
            "structure": dirs,
        }

    # ==================== API 代码生成 ====================

    def _generate_api_code(
        self, project_dir: str, requirement: str, context: Dict
    ) -> Dict[str, Any]:
        """生成 API 端点代码"""
        files_created = []
        req_lower = requirement.lower()

        # 分析需要的资源类型
        resources = []
        if any(kw in req_lower for kw in ["用户", "user", "登录", "注册"]):
            resources.append(("user", "用户"))
        if any(kw in req_lower for kw in ["商品", "product", "商店"]):
            resources.append(("product", "商品"))
        if any(kw in req_lower for kw in ["订单", "order", "购买"]):
            resources.append(("order", "订单"))
        if not resources:
            resources.append(("item", "数据项"))

        for resource_name, resource_label in resources:
            files_created.append(self._write_file(
                f"{project_dir}/src/api/{resource_name}.py",
                f'''"""
{resource_label}管理 API
"""
from fastapi import APIRouter, HTTPException
from typing import List, Dict, Any, Optional
from pydantic import BaseModel

router = APIRouter(prefix="/{resource_name}s", tags=["{resource_label}管理"])


# ===== 数据模型 =====

class {resource_name.capitalize()}Create(BaseModel):
    """创建{resource_label}请求"""
    name: str
    description: Optional[str] = None


class {resource_name.capitalize()}Update(BaseModel):
    """更新{resource_label}请求"""
    name: Optional[str] = None
    description: Optional[str] = None


class {resource_name.capitalize()}Response(BaseModel):
    """{ resource_label}响应"""
    id: str
    name: str
    description: Optional[str] = None
    created_at: str


# ===== 内存存储（后续替换为数据库） =====
_storage: Dict[str, Dict[str, Any]] = {{}}
_counter = 0


def _next_id() -> str:
    global _counter
    _counter += 1
    return f"{resource_name}-{{_counter}}"


# ===== CRUD 端点 =====

@router.get("/", response_model=List[{resource_name.capitalize()}Response])
async def list_{resource_name}s():
    """{resource_label}列表"""
    return list(_storage.values())


@router.post("/", response_model={resource_name.capitalize()}Response, status_code=201)
async def create_{resource_name}(data: {resource_name.capitalize()}Create):
    """创建{resource_label}"""
    from datetime import datetime
    item_id = _next_id()
    item = {{
        "id": item_id,
        "name": data.name,
        "description": data.description,
        "created_at": datetime.now().isoformat(),
    }}
    _storage[item_id] = item
    return item


@router.get("/{{item_id}}", response_model={resource_name.capitalize()}Response)
async def get_{resource_name}(item_id: str):
    """获取{resource_label}详情"""
    if item_id not in _storage:
        raise HTTPException(status_code=404, detail="{resource_label}不存在")
    return _storage[item_id]


@router.put("/{{item_id}}", response_model={resource_name.capitalize()}Response)
async def update_{resource_name}(item_id: str, data: {resource_name.capitalize()}Update):
    """更新{resource_label}"""
    if item_id not in _storage:
        raise HTTPException(status_code=404, detail="{resource_label}不存在")
    item = _storage[item_id]
    if data.name is not None:
        item["name"] = data.name
    if data.description is not None:
        item["description"] = data.description
    return item


@router.delete("/{{item_id}}")
async def delete_{resource_name}(item_id: str):
    """删除{resource_label}"""
    if item_id not in _storage:
        raise HTTPException(status_code=404, detail="{resource_label}不存在")
    del _storage[item_id]
    return {{"message": "{resource_label}已删除"}}
'''
            ))

        # 生成路由注册文件
        router_imports = "\n".join(
            f"from api.{r[0]} import router as {r[0]}_router"
            for r in resources
        )
        router_includes = "\n".join(
            f'    app.include_router({r[0]}_router, prefix="/api")'
            for r in resources
        )
        files_created.append(self._write_file(
            f"{project_dir}/src/api/router.py",
            f'''"""
API 路由注册
"""
{router_imports}


def register_routes(app):
    """注册所有 API 路由"""
{router_includes}
'''
        ))

        return {
            "files_created": files_created,
            "output": f"生成了 {len(resources)} 个资源的 CRUD API ({', '.join(r[1] for r in resources)})",
            "resources": [r[0] for r in resources],
        }

    # ==================== 数据模型生成 ====================

    def _generate_model_code(
        self, project_dir: str, requirement: str, context: Dict
    ) -> Dict[str, Any]:
        """生成 SQLAlchemy 数据模型"""
        files_created = []

        # 数据库基础配置
        files_created.append(self._write_file(
            f"{project_dir}/src/models/database.py",
            '''"""
数据库配置
"""
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

DATABASE_URL = "sqlite:///./app.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """获取数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """初始化数据库表"""
    Base.metadata.create_all(bind=engine)
'''
        ))

        # 用户模型
        req_lower = requirement.lower()
        if any(kw in req_lower for kw in ["用户", "user", "登录"]):
            files_created.append(self._write_file(
                f"{project_dir}/src/models/user.py",
                '''"""
用户数据模型
"""
from sqlalchemy import Column, String, Boolean, DateTime
from sqlalchemy.sql import func
from .database import Base


class User(Base):
    """用户表"""
    __tablename__ = "users"

    id = Column(String, primary_key=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(100), unique=True, nullable=False, index=True)
    hashed_password = Column(String(128), nullable=False)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<User {self.username}>"
'''
            ))

        return {
            "files_created": files_created,
            "output": f"生成了 {len(files_created)} 个数据模型文件",
        }

    # ==================== 认证相关 ====================

    def _generate_auth_code(
        self, project_dir: str, requirement: str, context: Dict
    ) -> Dict[str, Any]:
        """生成认证模块"""
        files_created = []

        files_created.append(self._write_file(
            f"{project_dir}/src/services/auth.py",
            '''"""
认证服务
"""
import hashlib
import secrets
from typing import Optional, Dict, Any
from datetime import datetime, timedelta


class AuthService:
    """认证服务（简化版，生产环境应使用 JWT + bcrypt）"""

    def __init__(self):
        self._users: Dict[str, Dict[str, Any]] = {}
        self._sessions: Dict[str, Dict[str, Any]] = {}

    def register(self, username: str, email: str, password: str) -> Dict[str, Any]:
        """用户注册"""
        if username in self._users:
            raise ValueError(f"用户名 {username} 已存在")

        user_id = f"user-{len(self._users) + 1}"
        hashed = hashlib.sha256(password.encode()).hexdigest()

        user = {
            "id": user_id,
            "username": username,
            "email": email,
            "hashed_password": hashed,
            "is_active": True,
            "created_at": datetime.now().isoformat(),
        }
        self._users[username] = user
        return {k: v for k, v in user.items() if k != "hashed_password"}

    def login(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        """用户登录"""
        user = self._users.get(username)
        if not user:
            return None

        hashed = hashlib.sha256(password.encode()).hexdigest()
        if user["hashed_password"] != hashed:
            return None

        # 生成会话 token
        token = secrets.token_hex(32)
        self._sessions[token] = {
            "user_id": user["id"],
            "username": username,
            "expires_at": (datetime.now() + timedelta(hours=24)).isoformat(),
        }

        return {"token": token, "user": {k: v for k, v in user.items() if k != "hashed_password"}}

    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """验证 token"""
        session = self._sessions.get(token)
        if not session:
            return None
        if datetime.fromisoformat(session["expires_at"]) < datetime.now():
            del self._sessions[token]
            return None
        return session

    def logout(self, token: str) -> bool:
        """登出"""
        if token in self._sessions:
            del self._sessions[token]
            return True
        return False
'''
        ))

        return {
            "files_created": files_created,
            "output": "生成了认证服务模块（注册、登录、Token 验证、登出）",
        }

    def _generate_login_code(
        self, project_dir: str, requirement: str, context: Dict
    ) -> Dict[str, Any]:
        """生成登录 API"""
        files_created = []

        files_created.append(self._write_file(
            f"{project_dir}/src/api/auth.py",
            '''"""
认证 API 端点
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from services.auth import AuthService

router = APIRouter(prefix="/auth", tags=["认证"])
auth_service = AuthService()


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str


@router.post("/login")
async def login(req: LoginRequest):
    """用户登录"""
    result = auth_service.login(req.username, req.password)
    if not result:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return result


@router.post("/register")
async def register(req: RegisterRequest):
    """用户注册"""
    try:
        user = auth_service.register(req.username, req.email, req.password)
        return {"message": "注册成功", "user": user}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/logout")
async def logout(token: str):
    """用户登出"""
    auth_service.logout(token)
    return {"message": "已登出"}
'''
        ))

        return {
            "files_created": files_created,
            "output": "生成了登录/注册/登出 API 端点",
        }

    def _generate_register_code(
        self, project_dir: str, requirement: str, context: Dict
    ) -> Dict[str, Any]:
        """注册功能（与登录共用，标记为已完成）"""
        return {
            "files_created": [],
            "output": "注册功能已包含在登录模块中（/auth/register）",
        }

    def _generate_permission_code(
        self, project_dir: str, requirement: str, context: Dict
    ) -> Dict[str, Any]:
        """生成权限管理"""
        files_created = []

        files_created.append(self._write_file(
            f"{project_dir}/src/services/permissions.py",
            '''"""
权限管理服务
"""
from typing import Dict, List, Optional, Set


class PermissionService:
    """基于角色的权限管理"""

    # 预定义角色
    ROLES = {
        "admin": {"read", "write", "delete", "manage_users"},
        "editor": {"read", "write"},
        "viewer": {"read"},
    }

    def __init__(self):
        self._user_roles: Dict[str, str] = {}  # user_id -> role

    def assign_role(self, user_id: str, role: str) -> bool:
        """分配角色"""
        if role not in self.ROLES:
            return False
        self._user_roles[user_id] = role
        return True

    def get_role(self, user_id: str) -> Optional[str]:
        """获取用户角色"""
        return self._user_roles.get(user_id, "viewer")

    def get_permissions(self, user_id: str) -> Set[str]:
        """获取用户权限集"""
        role = self.get_role(user_id)
        return self.ROLES.get(role, set())

    def has_permission(self, user_id: str, permission: str) -> bool:
        """检查权限"""
        return permission in self.get_permissions(user_id)

    def check_permission(self, user_id: str, permission: str) -> None:
        """检查权限，无权限则抛异常"""
        if not self.has_permission(user_id, permission):
            raise PermissionError(
                f"用户 {user_id} 没有 {permission} 权限"
            )
'''
        ))

        return {
            "files_created": files_created,
            "output": "生成了基于角色的权限管理服务（admin/editor/viewer）",
        }

    # ==================== 前端生成 ====================

    def _generate_frontend(
        self, project_dir: str, requirement: str, context: Dict
    ) -> Dict[str, Any]:
        """生成前端页面"""
        files_created = []
        project_name = context.get("project_name", "应用")

        files_created.append(self._write_file(
            f"{project_dir}/frontend/index.html",
            f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{project_name}</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #f5f5f5; }}
        .header {{ background: #1890ff; color: white; padding: 16px 24px; }}
        .header h1 {{ font-size: 20px; }}
        .container {{ max-width: 1200px; margin: 24px auto; padding: 0 24px; }}
        .card {{ background: white; border-radius: 8px; padding: 24px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
        .btn {{ padding: 8px 16px; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; }}
        .btn-primary {{ background: #1890ff; color: white; }}
        .btn-primary:hover {{ background: #40a9ff; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>{project_name}</h1>
    </div>
    <div class="container">
        <div class="card">
            <h2>欢迎使用 {project_name}</h2>
            <p style="margin-top:12px;color:#666">由 AI 自动开发系统生成</p>
        </div>
        <div class="card" id="content">
            <p>加载中...</p>
        </div>
    </div>
    <script src="app.js"></script>
</body>
</html>
'''
        ))

        return {
            "files_created": files_created,
            "output": "生成了前端主页面",
        }

    def _generate_frontend_js(
        self, project_dir: str, requirement: str, context: Dict
    ) -> Dict[str, Any]:
        """生成前端交互逻辑"""
        files_created = []

        files_created.append(self._write_file(
            f"{project_dir}/frontend/app.js",
            '''/**
 * 前端应用逻辑
 */
const API_BASE = window.location.origin;

async function fetchAPI(path, options = {}) {
    try {
        const response = await fetch(API_BASE + path, {
            headers: { "Content-Type": "application/json" },
            ...options,
        });
        return await response.json();
    } catch (err) {
        console.error("API Error:", err);
        return { error: err.message };
    }
}

async function init() {
    const content = document.getElementById("content");
    const health = await fetchAPI("/health");
    if (health.status === "healthy") {
        content.innerHTML = "<p style=\\"color:#52c41a\\">✅ 后端服务运行正常</p>";
    } else {
        content.innerHTML = "<p style=\\"color:#ff4d4f\\">❌ 无法连接后端服务</p>";
    }
}

document.addEventListener("DOMContentLoaded", init);
'''
        ))

        return {
            "files_created": files_created,
            "output": "生成了前端 JavaScript 交互逻辑",
        }

    # ==================== 数据库迁移 ====================

    def _generate_migration(
        self, project_dir: str, requirement: str, context: Dict
    ) -> Dict[str, Any]:
        """生成数据库迁移脚本"""
        files_created = []

        files_created.append(self._write_file(
            f"{project_dir}/migrations/001_init.py",
            '''"""
数据库迁移脚本 001 - 初始化
"""


def upgrade(db):
    """升级"""
    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            hashed_password TEXT NOT NULL,
            is_active BOOLEAN DEFAULT TRUE,
            is_admin BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    print("Migration 001: users 表已创建")


def downgrade(db):
    """回滚"""
    db.execute("DROP TABLE IF EXISTS users")
    print("Migration 001: users 表已删除")
'''
        ))

        return {
            "files_created": files_created,
            "output": "生成了数据库迁移脚本（001_init）",
        }

    # ==================== 文档生成 ====================

    def _generate_docs(
        self, project_dir: str, requirement: str, context: Dict
    ) -> Dict[str, Any]:
        """生成项目文档"""
        files_created = []
        project_name = context.get("project_name", "项目")

        files_created.append(self._write_file(
            f"{project_dir}/docs/DEVELOPMENT.md",
            f"""# {project_name} 开发文档

## 技术栈
- 后端: Python / FastAPI
- 数据库: SQLite (开发) / PostgreSQL (生产)
- 前端: HTML / CSS / JavaScript

## 本地开发

```bash
# 安装依赖
pip install -r requirements.txt

# 启动服务
cd src && python main.py

# 运行测试
pytest tests/ -v
```

## API 接口
启动后访问 http://localhost:8080/docs 查看自动生成的 Swagger 文档。

## 项目约定
- 所有 API 端点遵循 RESTful 规范
- 数据模型使用 Pydantic 定义
- 所有时间字段使用 ISO 8601 格式
"""
        ))

        return {
            "files_created": files_created,
            "output": "生成了开发文档",
        }

    def _generate_api_docs(
        self, project_dir: str, requirement: str, context: Dict
    ) -> Dict[str, Any]:
        """生成 API 文档"""
        files_created = []

        files_created.append(self._write_file(
            f"{project_dir}/docs/API.md",
            """# API 文档

## 基础信息
- Base URL: `http://localhost:8080`
- 数据格式: JSON

## 通用响应格式
```json
{
    "message": "操作描述",
    "data": {}
}
```

## 端点列表

### GET /health
健康检查

### GET /api/{resource}s
获取资源列表

### POST /api/{resource}s
创建新资源

### GET /api/{resource}s/{id}
获取资源详情

### PUT /api/{resource}s/{id}
更新资源

### DELETE /api/{resource}s/{id}
删除资源

---
完整交互文档请访问: http://localhost:8080/docs
"""
        ))

        return {
            "files_created": files_created,
            "output": "生成了 API 文档",
        }

    # ==================== 通用代码生成 ====================

    def _generate_core_code(
        self, project_dir: str, requirement: str, context: Dict
    ) -> Dict[str, Any]:
        """生成核心功能代码"""
        # 组合调用 API + 模型生成
        results = []
        r1 = self._generate_api_code(project_dir, requirement, context)
        results.extend(r1.get("files_created", []))
        r2 = self._generate_model_code(project_dir, requirement, context)
        results.extend(r2.get("files_created", []))

        return {
            "files_created": results,
            "output": f"核心功能代码生成完成，共 {len(results)} 个文件",
        }

    def _generate_helper_code(
        self, project_dir: str, requirement: str, context: Dict
    ) -> Dict[str, Any]:
        """生成辅助功能代码"""
        files_created = []

        files_created.append(self._write_file(
            f"{project_dir}/src/utils/helpers.py",
            '''"""
工具函数
"""
import uuid
from datetime import datetime


def generate_id(prefix: str = "") -> str:
    """生成唯一 ID"""
    short_uuid = uuid.uuid4().hex[:8]
    return f"{prefix}-{short_uuid}" if prefix else short_uuid


def now_iso() -> str:
    """当前时间 ISO 格式"""
    return datetime.now().isoformat()


def paginate(items: list, page: int = 1, size: int = 20) -> dict:
    """分页工具"""
    total = len(items)
    start = (page - 1) * size
    end = start + size
    return {
        "items": items[start:end],
        "total": total,
        "page": page,
        "size": size,
        "pages": (total + size - 1) // size,
    }
'''
        ))

        files_created.append(self._write_file(
            f"{project_dir}/src/utils/validators.py",
            '''"""
数据验证工具
"""
import re


def validate_email(email: str) -> bool:
    """验证邮箱格式"""
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, email))


def validate_password(password: str) -> tuple:
    """
    验证密码强度
    返回 (is_valid, message)
    """
    if len(password) < 6:
        return False, "密码长度至少 6 位"
    if not re.search(r"[a-zA-Z]", password):
        return False, "密码需包含字母"
    if not re.search(r"[0-9]", password):
        return False, "密码需包含数字"
    return True, "密码强度合格"
'''
        ))

        return {
            "files_created": files_created,
            "output": "生成了辅助工具函数（ID生成、分页、邮箱验证、密码验证）",
        }

    def _generate_generic_code(
        self, project_dir: str, requirement: str, context: Dict
    ) -> Dict[str, Any]:
        """通用代码生成（无匹配时的兜底）"""
        files_created = []

        files_created.append(self._write_file(
            f"{project_dir}/src/services/core.py",
            f'''"""
核心业务逻辑
基于需求: {requirement[:200]}
"""
from typing import Dict, Any, List


class CoreService:
    """核心服务"""

    def __init__(self):
        self._data: Dict[str, Dict[str, Any]] = {{}}

    def process(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """处理输入数据"""
        return {{
            "status": "processed",
            "input": input_data,
            "message": "处理完成",
        }}
'''
        ))

        return {
            "files_created": files_created,
            "output": "生成了通用业务逻辑框架",
        }
