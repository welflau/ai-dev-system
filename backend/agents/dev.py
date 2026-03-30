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
        existing_files = context.get("existing_files", [])
        existing_code = context.get("existing_code", {})
        sibling_tickets = context.get("sibling_tickets", [])

        # 构建已有代码上下文
        existing_section = ""
        if existing_files:
            file_list_str = "\n".join(f"  - {f}" for f in existing_files if not f.startswith(("docs/", "tests/", ".git")))
            existing_section += f"\n## 项目已有文件\n{file_list_str}\n"

        if existing_code:
            existing_section += "\n## 现有代码（重要：在此基础上修改，不要从零重写）\n"
            for fp, code in existing_code.items():
                existing_section += f"\n### {fp}\n```\n{code}\n```\n"

        if sibling_tickets:
            siblings_str = "\n".join(f"  - [{t['status']}] {t['title']}" for t in sibling_tickets)
            existing_section += f"\n## 同需求其他工单\n{siblings_str}\n"

        prompt = f"""你是一位资深软件开发工程师。请根据架构设计，在现有代码基础上实现以下功能。

## 任务
标题: {ticket_title}
描述: {ticket_description}
模块: {module}

## 架构设计
{json.dumps(architecture, ensure_ascii=False, indent=2)}
{existing_section}
## 请返回 JSON 格式：
{{
  "files": {{
    "index.html": "完整的文件内容...",
    "src/example.js": "完整的文件内容..."
  }},
  "key_implementations": ["关键实现点"],
  "estimated_hours": 实际用时估算,
  "notes": "开发备注"
}}

关键要求：
1. files 字典的 key 是文件路径，value 是该文件的**完整内容**
2. **增量开发**：如果 index.html 或其他文件已存在，在现有代码基础上添加/修改功能，保留已有功能
3. **不要创建孤立文件**：所有新文件必须被入口文件引用或导入
4. 前端项目：代码尽量内联到 index.html（CSS 用 <style>，JS 用 <script>），保持可直接浏览器打开
5. 后端项目：在 main.py 基础上扩展
6. 只输出**需要新建或修改**的文件，未改动的文件不要输出
7. 文件名和路径必须全部使用英文
8. 生成完整可运行的代码，不要用省略号或注释代替实际逻辑
"""

        result = await llm_client.chat_json(
            [{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=8192,
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
