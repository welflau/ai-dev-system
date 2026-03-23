"""
工具注册表
"""
from typing import Dict, Optional
from abc import ABC, abstractmethod


class BaseTool(ABC):
    """工具基类"""
    
    def __init__(self, name: str):
        self.name = name
    
    @abstractmethod
    async def execute(self, **kwargs) -> any:
        """执行工具"""
        pass
    
    @abstractmethod
    def get_description(self) -> str:
        """获取工具描述"""
        pass
    
    def get_schema(self) -> Dict:
        """获取工具参数schema"""
        return {
            "name": self.name,
            "description": self.get_description(),
            "parameters": self._get_parameters()
        }
    
    def _get_parameters(self) -> Dict:
        """获取参数定义"""
        return {}


class ToolRegistry:
    """工具注册表"""
    
    def __init__(self):
        self.tools: Dict[str, BaseTool] = {}
    
    def register(self, tool: BaseTool):
        """注册工具"""
        self.tools[tool.name] = tool
        print(f"✓ 工具已注册: {tool.name}")
    
    def get(self, name: str) -> Optional[BaseTool]:
        """获取工具"""
        return self.tools.get(name)
    
    def get_all(self) -> Dict[str, BaseTool]:
        """获取所有工具"""
        return self.tools.copy()
    
    def list_tools(self) -> list:
        """列出所有工具名称"""
        return list(self.tools.keys())
    
    def get_schemas(self) -> Dict[str, Dict]:
        """获取所有工具的schema"""
        return {
            name: tool.get_schema()
            for name, tool in self.tools.items()
        }
    
    def execute_tool(self, name: str, **kwargs) -> any:
        """执行工具"""
        tool = self.get(name)
        if tool is None:
            raise ValueError(f"工具不存在: {name}")
        return tool.execute(**kwargs)
