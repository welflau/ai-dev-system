"""
产品代理(ProductAgent)
负责需求分析、PRD生成、用户故事创建
"""
from typing import Dict, Any, List
from models.schemas import Task, ExecutionResult, AgentContext, Requirement
from models.enums import TaskType, AgentType
from .base import BaseAgent


class ProductAgent(BaseAgent):
    """产品代理"""
    
    def __init__(self, llm_client, tool_registry):
        super().__init__(AgentType.PRODUCT, llm_client, tool_registry)
    
    async def execute(self, task: Task, context: AgentContext) -> ExecutionResult:
        """执行产品任务"""
        task_type = task.type
        
        if task_type == TaskType.REQUIREMENT:
            return await self._analyze_requirements(task, context)
        else:
            return ExecutionResult(
                success=False,
                error_message=f"不支持的任务类型: {task_type}"
            )
    
    def get_capabilities(self) -> List[str]:
        return [
            "需求分析",
            "PRD文档生成",
            "用户故事创建",
            "功能优先级规划",
            "需求澄清"
        ]
    
    def get_supported_tasks(self) -> List[str]:
        return [
            TaskType.REQUIREMENT.value
        ]
    
    async def _analyze_requirements(
        self,
        task: Task,
        context: AgentContext
    ) -> ExecutionResult:
        """
        分析需求并生成PRD
        
        Args:
            task: 任务
            context: 上下文
        
        Returns:
            执行结果
        """
        # 1. 理解用户需求
        user_input = task.input_data.get("description", "")
        
        # 2. 识别核心功能点
        features = await self._extract_features(user_input)
        
        # 3. 识别技术约束
        constraints = await self._identify_constraints(user_input)
        
        # 4. 生成项目名称
        project_name = self._extract_project_name(user_input)
        
        # 5. 构建需求对象
        requirement = Requirement(
            id=task.id,
            description=user_input,
            project_name=project_name,
            core_features=features,
            constraints=constraints,
            tech_stack=context.global_context.get("tech_stack")
        )
        
        # 6. 生成PRD文档
        prd_content = await self._generate_prd_content(requirement)
        
        # 7. 创建PRD文件
        prd_file = await self._create_prd_file(
            context.project_id,
            prd_content
        )
        
        # 8. 创建用户故事
        user_stories = await self._create_user_stories(
            requirement,
            context.project_id
        )
        
        return ExecutionResult(
            success=True,
            output={
                "requirement": requirement.dict(),
                "prd_file": prd_file,
                "user_stories": user_stories
            },
            artifacts=[
                {
                    "type": "requirement_doc",
                    "data": requirement.dict()
                },
                {
                    "type": "prd_file",
                    "path": prd_file
                }
            ]
        )
    
    async def _extract_features(self, user_input: str) -> List[str]:
        """提取核心功能点"""
        prompt = f"""
分析以下用户需求,提取核心功能点:

{user_input}

请列出所有功能点,每个功能点用一句话描述。
返回格式为JSON数组:
["功能点1", "功能点2", ...]
"""
        
        response = await self.llm_client.generate(prompt)
        
        # 简化版解析,实际需要更健壮的解析
        try:
            import json
            features = json.loads(response)
            return features
        except:
            # 如果解析失败,简单按行分割
            return [
                line.strip()
                for line in response.split('\n')
                if line.strip() and not line.startswith('#')
            ]
    
    async def _identify_constraints(self, user_input: str) -> List[str]:
        """识别技术约束"""
        prompt = f"""
分析以下用户需求,识别技术约束和限制条件:

{user_input}

包括:
- 性能要求
- 安全要求
- 兼容性要求
- 其他技术限制

返回格式为JSON数组:
["约束1", "约束2", ...]
"""
        
        response = await self.llm_client.generate(prompt)
        
        # 简化版解析
        try:
            import json
            constraints = json.loads(response)
            return constraints
        except:
            return [
                line.strip()
                for line in response.split('\n')
                if line.strip() and not line.startswith('#')
            ]
    
    def _extract_project_name(self, user_input: str) -> str:
        """提取项目名称"""
        # 简化版:使用第一个非空行作为项目名
        lines = user_input.strip().split('\n')
        for line in lines:
            if line.strip():
                return line.strip()[:50]  # 限制长度
        
        return "Unnamed Project"
    
    async def _generate_prd_content(self, requirement: Requirement) -> str:
        """生成PRD文档内容"""
        prompt = f"""
基于以下需求,生成完整的PRD(产品需求文档):

项目名称: {requirement.project_name}
需求描述: {requirement.description}
核心功能: {', '.join(requirement.core_features)}
技术约束: {', '.join(requirement.constraints)}

PRD应包含以下部分:
1. 项目概述
2. 目标用户
3. 核心功能描述
4. 用户故事
5. 非功能性需求
6. 技术架构建议

请使用Markdown格式。
"""
        
        prd_content = await self.llm_client.generate(prompt)
        return prd_content
    
    async def _create_prd_file(
        self,
        project_id: str,
        content: str
    ) -> str:
        """创建PRD文件"""
        file_path = f"projects/{project_id}/docs/PRD.md"
        
        result = await self.tool_registry.execute_tool(
            "file_writer",
            file_path=file_path,
            content=content,
            create_dirs=True
        )
        
        if not result.get("success"):
            raise Exception(f"创建PRD文件失败: {result.get('error')}")
        
        return file_path
    
    async def _create_user_stories(
        self,
        requirement: Requirement,
        project_id: str
    ) -> List[Dict[str, Any]]:
        """创建用户故事"""
        prompt = f"""
基于以下需求,为每个核心功能创建用户故事:

核心功能: {', '.join(requirement.core_features)}

用户故事格式:
作为[角色],我想要[功能],以便[价值]

为每个功能创建1-2个用户故事。

返回格式为JSON数组:
[
  {
    "id": "story-1",
    "feature": "功能名",
    "role": "角色",
    "want": "想要的功能",
    "so_that": "价值/目标"
  },
  ...
]
"""
        
        response = await self.llm_client.generate(prompt)
        
        # 解析用户故事
        try:
            import json
            stories = json.loads(response)
        except:
            # 如果解析失败,返回空列表
            stories = []
        
        # 保存用户故事到文件
        if stories:
            stories_file = f"projects/{project_id}/docs/user_stories.json"
            await self.tool_registry.execute_tool(
                "file_writer",
                file_path=stories_file,
                content=json.dumps(stories, indent=2, ensure_ascii=False),
                create_dirs=True
            )
        
        return stories
