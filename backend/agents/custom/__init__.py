# 自定义 Agent 放在此目录，系统启动时自动扫描加载
# 每个 .py 文件中继承 BaseAgent 的类会被自动注册
#
# 示例:
# from agents.base import BaseAgent
# class SecurityAgent(BaseAgent):
#     @property
#     def agent_type(self): return "SecurityAgent"
#     async def execute(self, task_name, context): ...
