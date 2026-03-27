"""
Agent 配置 API — 返回所有 Agent 的提示词和参数配置
"""
from fastapi import APIRouter

router = APIRouter(prefix="/api/agents", tags=["agents"])


# Agent 注册表：定义所有 Agent 的元信息和提示词
AGENT_REGISTRY = [
    {
        "name": "ProductAgent",
        "icon": "📝",
        "description": "需求分析 → PRD 文档生成",
        "role": "资深产品经理和项目经理",
        "enabled": True,
        "temperature": 0.3,
        "max_tokens": 4096,
        "prompts": [
            {
                "action": "analyze_and_decompose",
                "label": "需求分析 & 拆单",
                "template": """你是一位资深产品经理和项目经理。请分析以下需求，生成 PRD 要点，并将其拆分为可执行的任务单。

## 需求标题
{title}

## 需求描述
{description}

## 优先级
{priority}

## 请按 JSON 格式返回，结构如下：

{
  "prd_summary": "PRD 核心要点摘要（200字以内）",
  "tickets": [
    {
      "title": "任务标题",
      "description": "任务详细描述",
      "type": "feature|bugfix|refactor|test|deploy|doc",
      "module": "frontend|backend|database|api|testing|deploy|design|other",
      "priority": "1-5（1最高）",
      "estimated_hours": "预估工时（小时）",
      "subtasks": [
        {"title": "子任务标题", "description": "子任务描述"}
      ],
      "dependencies": []
    }
  ]
}

请确保：
1. 任务拆分粒度适中，每个任务 2-8 小时工作量
2. 按模块分类（前端、后端、数据库、API、测试、部署）
3. 标注任务间的依赖关系
4. 每个任务下列出具体的子任务""",
            },
            {
                "action": "acceptance_review",
                "label": "产品验收",
                "template": """你是一位产品经理，正在验收开发交付物。

## 原始需求
{requirement_description}

## 工单标题
{ticket_title}

## 开发交付结果
{dev_result}

## 请判断：
1. 交付物是否满足需求？
2. 是否有遗漏的功能点？
3. 是否需要修改？

请以 JSON 格式返回：
{
  "passed": true/false,
  "score": 1-10,
  "feedback": "验收意见",
  "issues": ["问题1", "问题2"]
}""",
            },
        ],
    },
    {
        "name": "ArchitectAgent",
        "icon": "🏗️",
        "description": "架构设计 → 技术方案",
        "role": "资深软件架构师",
        "enabled": True,
        "temperature": 0.3,
        "max_tokens": 4096,
        "prompts": [
            {
                "action": "design_architecture",
                "label": "架构设计",
                "template": """你是一位资深软件架构师。请为以下任务设计技术架构方案。

## 需求背景
{requirement_description}

## 当前任务
标题: {ticket_title}
描述: {ticket_description}
模块: {module}

## 请返回 JSON 格式：
{
  "architecture_type": "架构模式（如 MVC、微服务、分层等）",
  "tech_stack": {
    "language": "编程语言",
    "framework": "框架",
    "database": "数据库",
    "others": ["其他技术"]
  },
  "module_design": [
    {
      "name": "模块名",
      "responsibility": "职责描述",
      "interfaces": ["接口描述"]
    }
  ],
  "data_flow": "数据流描述",
  "estimated_hours": "预估开发工时（小时）",
  "risks": ["风险点"],
  "decisions": ["关键技术决策"]
}""",
            },
        ],
    },
    {
        "name": "DevAgent",
        "icon": "💻",
        "description": "代码生成 → 源代码文件",
        "role": "资深软件开发工程师",
        "enabled": True,
        "temperature": 0.3,
        "max_tokens": 4096,
        "prompts": [
            {
                "action": "develop",
                "label": "代码开发",
                "template": """你是一位资深软件开发工程师。请根据架构设计实现以下功能。

## 任务
标题: {ticket_title}
描述: {ticket_description}
模块: {module}

## 架构设计
{architecture}

## 请返回 JSON 格式（注意 files 字段包含真正的文件内容）：
{
  "files": {
    "src/services/example.py": "# 文件的完整代码内容\\nimport ...\\n...",
    "src/models/example.py": "# 模型代码\\n..."
  },
  "key_implementations": ["关键实现点"],
  "api_endpoints": [
    {"method": "GET/POST/PUT/DELETE", "path": "/api/xxx", "description": "接口描述"}
  ],
  "dependencies_added": ["新增依赖"],
  "estimated_hours": "实际用时估算",
  "notes": "开发备注"
}

关键要求：
1. files 字典的 key 是相对于项目根目录的文件路径，value 是文件的完整代码内容
2. 根据模块类型放到对应目录：src/api/、src/models/、src/services/、src/utils/
3. 生成完整可运行的代码，不要用省略号或注释代替""",
            },
            {
                "action": "rework",
                "label": "返工修改",
                "template": "（复用 develop 提示词，附加返工原因）",
            },
            {
                "action": "fix_issues",
                "label": "修复问题",
                "template": "（复用 develop 提示词，附加测试问题列表）",
            },
        ],
    },
    {
        "name": "TestAgent",
        "icon": "🧪",
        "description": "测试生成 → 测试用例 + 报告",
        "role": "代码审查专家",
        "enabled": True,
        "temperature": 0.3,
        "max_tokens": 4096,
        "prompts": [
            {
                "action": "code_review",
                "label": "代码审查",
                "template": """你是一位代码审查专家。请审查以下开发交付物。

## 开发结果
{dev_result}

请检查以下方面并返回 JSON：
{
  "passed": true/false,
  "score": 1-10,
  "issues": ["问题描述"],
  "suggestions": ["改进建议"],
  "security_issues": ["安全问题"],
  "performance_issues": ["性能问题"]
}""",
            },
            {
                "action": "smoke_test",
                "label": "冒烟测试",
                "template": "（规则引擎，不调用 LLM）",
            },
            {
                "action": "unit_test",
                "label": "单元测试",
                "template": "（规则引擎，不调用 LLM）",
            },
        ],
    },
    {
        "name": "ReviewAgent",
        "icon": "🔍",
        "description": "代码审查 → 审查报告",
        "role": "代码审查专家",
        "enabled": True,
        "temperature": 0.3,
        "max_tokens": 4096,
        "prompts": [
            {
                "action": "llm_review",
                "label": "智能代码审查",
                "template": """作为代码审查专家，请审查以下代码交付物：
{dev_result}

请返回 JSON：
{
  "quality_score": 1-10,
  "issues": ["问题描述"],
  "positive_points": ["优点"],
  "recommendations": ["建议"]
}""",
            },
        ],
        "static_rules": [
            "naming_convention (命名规范)",
            "function_length (函数长度)",
            "complexity (圈复杂度)",
            "error_handling (错误处理)",
            "security_check (安全检查)",
            "sql_injection (SQL 注入)",
            "xss_check (XSS 检查)",
            "hardcoded_secrets (硬编码密钥)",
            "code_duplication (代码重复)",
            "documentation (文档完整性)",
        ],
    },
    {
        "name": "DeployAgent",
        "icon": "🚀",
        "description": "部署配置 → Dockerfile + CI/CD",
        "role": "DevOps 工程师",
        "enabled": True,
        "temperature": 0.3,
        "max_tokens": 4096,
        "prompts": [
            {
                "action": "deploy",
                "label": "部署配置生成",
                "template": """你是一位 DevOps 工程师。请为以下项目生成部署配置文件。

## 任务
{ticket_title}

## 开发交付物
{dev_result}

## 测试结果
{test_result}

## 请返回 JSON 格式（files 字段包含真正的文件内容）：
{
  "files": {
    "build/Dockerfile": "FROM python:3.10-slim\\n...",
    "build/docker-compose.yml": "version: '3'\\n...",
    "build/.github/workflows/ci.yml": "name: CI\\n...",
    "docs/deploy.md": "# 部署文档\\n..."
  },
  "deploy_steps": ["部署步骤"],
  "environment": {
    "runtime": "运行环境",
    "ports": ["端口"],
    "env_vars": ["环境变量"]
  },
  "health_check": {
    "endpoint": "健康检查地址",
    "expected_status": 200
  }
}

关键要求：files 字典的 value 是文件的完整内容""",
            },
        ],
    },
]


@router.get("")
async def list_agents():
    """获取所有 Agent 配置列表（含提示词）"""
    return {"agents": AGENT_REGISTRY}


@router.get("/status")
async def get_agents_status():
    """获取所有 Agent 实时运行状态"""
    from orchestrator import orchestrator
    return orchestrator.get_agent_status()


@router.get("/{agent_name}")
async def get_agent(agent_name: str):
    """获取单个 Agent 配置详情"""
    for agent in AGENT_REGISTRY:
        if agent["name"] == agent_name:
            return agent
    return {"error": f"Agent '{agent_name}' not found"}
