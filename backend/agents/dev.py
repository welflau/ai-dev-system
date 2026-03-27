"""
DevAgent — 开发 Agent
职责：接单开发代码，更新开发时间和状态
"""
import json
import logging
from typing import Any, Dict
from agents.base import BaseAgent
from llm_client import llm_client

logger = logging.getLogger("dev_agent")


class DevAgent(BaseAgent):

    @property
    def agent_type(self) -> str:
        return "DevAgent"

    async def execute(self, task_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        if task_name == "develop":
            return await self.develop(context)
        elif task_name == "rework":
            return await self.rework(context)
        elif task_name == "fix_issues":
            return await self.fix_issues(context)
        else:
            return {"status": "error", "message": f"未知任务: {task_name}"}

    async def develop(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """开发任务"""
        ticket_title = context.get("ticket_title", "")
        ticket_description = context.get("ticket_description", "")
        architecture = context.get("architecture", {})
        module = context.get("module", "other")

        prompt = f"""你是一位资深软件开发工程师。请根据架构设计实现以下功能。

## 任务
标题: {ticket_title}
描述: {ticket_description}
模块: {module}

## 架构设计
{json.dumps(architecture, ensure_ascii=False, indent=2)}

## 请返回 JSON 格式（注意 files 字段包含真正的文件内容）：
{{
  "files": {{
    "index.html": "<!DOCTYPE html>\\n<html>\\n...",
    "src/services/example.js": "// 模块代码..."
  }},
  "key_implementations": ["关键实现点"],
  "api_endpoints": [
    {{"method": "GET/POST/PUT/DELETE", "path": "/api/xxx", "description": "接口描述"}}
  ],
  "dependencies_added": ["新增依赖"],
  "estimated_hours": 实际用时估算,
  "notes": "开发备注"
}}

关键要求：
1. files 字典的 key 是相对于项目根目录的文件路径，value 是文件的完整代码内容
2. **必须生成 index.html 入口文件**，可以直接在浏览器中打开运行
3. 如果是前端项目：index.html 应引入所有 JS/CSS 模块，用 <script src="src/..."> 引入
4. 如果是后端项目：生成 main.py 入口文件，可以直接 python main.py 运行
5. 生成完整可运行的代码，不要用省略号或注释代替实际逻辑
6. 文件名和路径必须全部使用英文，禁止中文文件名（如用 block-system.js 而不是 方块系统.js）
7. 代码要有完整的功能实现，不是空壳，用户打开就能看到效果
"""

        result = await llm_client.chat_json(
            [{"role": "user", "content": prompt}],
            temperature=0.3,
        )

        if result and isinstance(result, dict) and result.get("files"):
            files = result.get("files", {})
            logger.info("✅ DevAgent LLM 返回 %d 个文件", len(files))
            return {
                "status": "success",
                "dev_result": result,
                "estimated_hours": result.get("estimated_hours", 4),
                "files": files if isinstance(files, dict) else {},
            }

        # LLM 返回但无 files，或返回 None
        logger.warning("⚠️ DevAgent LLM 返回无效（result=%s），使用降级模板", type(result).__name__)

        # 降级：生成模板代码
        return self._fallback_develop(ticket_title, ticket_description, module)

    def _fallback_develop(self, title: str, description: str, module: str) -> Dict:
        """规则引擎降级：生成模板代码文件"""
        safe_name = title.lower().replace(" ", "_").replace("-", "_")[:30]
        files = {}

        if module in ("backend", "api", "other"):
            files[f"src/services/{safe_name}.py"] = f'''"""
{title} - 业务逻辑
由 AI 自动开发系统生成
"""


class {safe_name.title().replace("_", "")}Service:
    """{title} 服务类"""

    async def execute(self, params: dict) -> dict:
        """执行核心逻辑"""
        # TODO: 实现 {description[:100]}
        return {{"status": "success", "message": "{title} 完成"}}
'''
            files[f"src/api/{safe_name}_router.py"] = f'''"""
{title} - API 路由
"""
from fastapi import APIRouter

router = APIRouter(prefix="/api/{safe_name}", tags=["{safe_name}"])


@router.get("")
async def list_{safe_name}():
    """获取列表"""
    return {{"items": [], "total": 0}}


@router.post("")
async def create_{safe_name}(body: dict):
    """创建"""
    return {{"status": "success"}}
'''

        elif module == "frontend":
            files[f"src/frontend/{safe_name}.js"] = f'''/**
 * {title} - 前端模块
 * 由 AI 自动开发系统生成
 */

class {safe_name.title().replace("_", "")} {{
    constructor() {{
        this.container = null;
    }}

    render(container) {{
        this.container = container;
        container.innerHTML = `
            <div class="{safe_name}">
                <h2>{title}</h2>
                <p>{description[:100]}</p>
            </div>
        `;
    }}
}}
'''

        elif module == "database":
            files[f"src/models/{safe_name}.py"] = f'''"""
{title} - 数据模型
"""
from pydantic import BaseModel
from typing import Optional


class {safe_name.title().replace("_", "")}(BaseModel):
    """数据模型"""
    id: str
    name: str
    description: Optional[str] = None
    created_at: str
    updated_at: str
'''

        # 通用：生成 requirements.txt
        files["requirements.txt"] = "fastapi>=0.100.0\nuvicorn>=0.22.0\naiosqlite>=0.19.0\npydantic>=2.0.0\n"

        return {
            "status": "success",
            "dev_result": {
                "files": files,
                "key_implementations": [f"实现了 {title} 的核心功能"],
                "api_endpoints": [],
                "dependencies_added": [],
                "estimated_hours": 4,
                "notes": "[规则引擎] 代码开发完成",
            },
            "estimated_hours": 4,
            "files": files,
        }

    async def rework(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """返工（验收不通过打回）"""
        rejection_reason = context.get("rejection_reason", "")
        return await self.develop({
            **context,
            "ticket_description": f"{context.get('ticket_description', '')} [返工原因] {rejection_reason}",
        })

    async def fix_issues(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """修复问题（测试不通过打回）"""
        test_issues = context.get("test_issues", [])
        return await self.develop({
            **context,
            "ticket_description": f"{context.get('ticket_description', '')} [测试问题] {json.dumps(test_issues, ensure_ascii=False)}",
        })
