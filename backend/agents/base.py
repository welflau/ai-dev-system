"""
Agent基类
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, List
from models.schemas import Task, ExecutionResult, AgentContext
from models.enums import AgentType


class BaseAgent(ABC):
    """Agent基类"""
    
    def __init__(
        self,
        agent_type: AgentType,
        llm_client: Any,
        tool_registry: Any
    ):
        self.agent_type = agent_type
        self.llm_client = llm_client
        self.tool_registry = tool_registry
        self.execution_history: List[Dict] = []
    
    @abstractmethod
    async def execute(self, task: Task, context: AgentContext) -> ExecutionResult:
        """
        执行任务
        
        Args:
            task: 要执行的任务
            context: Agent上下文
        
        Returns:
            执行结果
        """
        pass
    
    @abstractmethod
    def get_capabilities(self) -> List[str]:
        """
        获取Agent能力列表
        
        Returns:
            能力列表
        """
        pass
    
    @abstractmethod
    def get_supported_tasks(self) -> List[str]:
        """
        获取支持的任务类型
        
        Returns:
            任务类型列表
        """
        pass
    
    async def think(
        self,
        context: AgentContext,
        task: Task
    ) -> List[Dict[str, Any]]:
        """
        思考并生成行动计划
        
        Args:
            context: Agent上下文
            task: 当前任务
        
        Returns:
            行动计划列表
        """
        # 构建思考提示词
        prompt = self._build_thinking_prompt(context, task)
        
        # 调用LLM生成行动计划
        response = await self.llm_client.generate(prompt)
        
        # 解析响应
        actions = self._parse_actions(response)
        
        return actions
    
    async def act(
        self,
        actions: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        执行动作
        
        Args:
            actions: 动作列表
        
        Returns:
            执行结果列表
        """
        results = []
        
        for action in actions:
            tool_name = action.get("tool")
            parameters = action.get("parameters", {})
            
            try:
                # 调用工具
                tool_result = await self.tool_registry.execute_tool(
                    tool_name,
                    **parameters
                )
                
                results.append({
                    "action": action,
                    "success": tool_result.get("success", False),
                    "result": tool_result
                })
                
            except Exception as e:
                results.append({
                    "action": action,
                    "success": False,
                    "error": str(e)
                })
        
        return results
    
    async def reflect(
        self,
        context: AgentContext,
        task: Task,
        actions: List[Dict],
        results: List[Dict]
    ) -> Dict[str, Any]:
        """
        反思执行结果
        
        Args:
            context: Agent上下文
            task: 任务
            actions: 执行的动作
            results: 执行结果
        
        Returns:
            反思结果
        """
        success_count = sum(1 for r in results if r.get("success", False))
        total_count = len(results)
        
        if success_count == total_count:
            return {
                "status": "success",
                "message": "所有操作成功完成",
                "success_rate": 1.0
            }
        else:
            # 分析失败原因
            failures = [r for r in results if not r.get("success", False)]
            return await self._analyze_failures(
                context,
                task,
                failures
            )
    
    def _build_thinking_prompt(
        self,
        context: AgentContext,
        task: Task
    ) -> str:
        """构建思考提示词"""
        return f"""
你是{self.agent_type.value} Agent,负责执行以下任务:

任务描述: {task.description}
任务类型: {task.type.value}
优先级: {task.priority.value}

项目上下文:
- 项目ID: {context.project_id}
- 需求: {context.requirements.description if context.requirements else 'N/A'}

可用的工具:
{self._format_available_tools()}

请分析任务并生成一个行动计划。
行动计划应该包含一系列步骤,每个步骤指定要使用的工具和参数。

返回格式:
1. [工具名称] - [工具用途]
   参数: [参数列表]

示例:
1. file_writer - 创建需求文档
   参数: file_path="requirements.md", content="..."

2. git_commit - 提交文档
   参数: message="feat: 添加需求文档"
"""
    
    def _format_available_tools(self) -> str:
        """格式化可用工具列表"""
        tools = self.tool_registry.list_tools()
        if not tools:
            return "无可用工具"
        
        formatted = []
        for tool_name in tools:
            tool = self.tool_registry.get(tool_name)
            if tool:
                formatted.append(f"- {tool_name}: {tool.get_description()[:100]}...")
        
        return "\n".join(formatted)
    
    def _parse_actions(self, response: str) -> List[Dict[str, Any]]:
        """解析LLM响应为动作列表"""
        # 简化版解析,实际需要更复杂的解析逻辑
        actions = []
        
        lines = response.strip().split('\n')
        for line in lines:
            if line.strip() and not line.startswith('#'):
                # 简单解析逻辑,实际需要改进
                if '[' in line and ']' in line:
                    tool_name = line[line.find('[')+1:line.find(']')]
                    actions.append({
                        "tool": tool_name,
                        "description": line
                    })
        
        return actions
    
    async def _analyze_failures(
        self,
        context: AgentContext,
        task: Task,
        failures: List[Dict]
    ) -> Dict[str, Any]:
        """分析失败原因"""
        # 构建分析提示词
        failures_desc = "\n".join([
            f"- {f.get('action', {}).get('tool')}: {f.get('error', 'Unknown error')}"
            for f in failures
        ])
        
        prompt = f"""
以下操作失败了:
{failures_desc}

请分析失败原因并提供改进建议。
"""
        
        response = await self.llm_client.generate(prompt)
        
        return {
            "status": "partial_failure",
            "message": "部分操作失败",
            "failures": failures,
            "analysis": response,
            "success_rate": (len(failures) - len(failures)) / (len(failures) or 1)
        }
    
    def record_execution(
        self,
        task_id: str,
        actions: List[Dict],
        results: List[Dict],
        reflection: Dict
    ):
        """记录执行历史"""
        self.execution_history.append({
            "task_id": task_id,
            "timestamp": None,  # 需要添加时间戳
            "actions": actions,
            "results": results,
            "reflection": reflection
        })
