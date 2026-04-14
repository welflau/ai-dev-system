"""
ActionNode — 结构化输出节点
移植自 MetaGPT ActionNode，适配本系统的 LLM Client

核心功能：
1. 编译 prompt（自动加入 JSON Schema 约束）
2. 调用 LLM
3. 解析输出为 Pydantic 模型（类型安全）
4. 解析失败时宽松降级（不崩溃）
"""
import json
import logging
from typing import Type, Optional, Any
from pydantic import BaseModel

logger = logging.getLogger("action_node")


class ActionNode:
    """结构化输出节点"""

    def __init__(
        self,
        key: str,
        expected_type: Type[BaseModel],
        instruction: str,
        schema: str = "json",
    ):
        self.key = key
        self.expected_type = expected_type
        self.instruction = instruction
        self.schema = schema
        self.instruct_content: Optional[BaseModel] = None
        self.raw_content: str = ""

    async def fill(self, req: str, llm, max_tokens: int = 16000, temperature: float = 0.3) -> "ActionNode":
        """调用 LLM → 解析 → 验证 → 存储

        Args:
            req: 上下文/需求描述
            llm: LLM client 实例（需有 chat_json 方法）
            max_tokens: 最大输出 token
            temperature: 温度

        Returns:
            self（instruct_content 已填充）
        """
        # 1. 编译 prompt（加入 Schema 约束）
        prompt = self._compile(req)

        # 2. 调用 LLM
        response = await llm.chat_json(
            [{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=temperature,
        )

        # 3. 解析并验证
        if response and isinstance(response, dict):
            try:
                self.instruct_content = self.expected_type(**response)
                self.raw_content = json.dumps(response, ensure_ascii=False)
                logger.info("✅ ActionNode[%s] 解析成功 (%s)", self.key, self.expected_type.__name__)
                return self
            except Exception as e:
                logger.warning("ActionNode[%s] Schema 验证失败: %s, 尝试宽松解析", self.key, e)
                # 宽松解析：过滤无效字段
                self.instruct_content = self._lenient_parse(response)
                self.raw_content = json.dumps(response, ensure_ascii=False)
                return self

        # 4. LLM 返回无效 → 降级为空模型
        logger.warning("ActionNode[%s] LLM 返回无效 (type=%s)", self.key, type(response).__name__)
        self.instruct_content = self.expected_type.model_construct()
        return self

    def _compile(self, context: str) -> str:
        """编译 prompt = 指令 + 上下文 + JSON Schema 约束"""
        schema = self.expected_type.model_json_schema()
        properties = schema.get("properties", {})

        # 生成简洁的字段说明
        fields_desc = []
        for name, prop in properties.items():
            type_str = prop.get("type", "string")
            default = prop.get("default", "")
            desc = f'  "{name}": {type_str}'
            if default:
                desc += f'  // 默认: {json.dumps(default, ensure_ascii=False)}'
            fields_desc.append(desc)

        schema_hint = "{\n" + ",\n".join(fields_desc) + "\n}"

        return f"""{self.instruction}

{context}

请返回以下 JSON 格式（严格遵循字段名）:
{schema_hint}"""

    def _lenient_parse(self, data: dict) -> BaseModel:
        """宽松解析：忽略无效字段，缺失字段用默认值"""
        try:
            # 只保留 Schema 中定义的字段
            valid_fields = set(self.expected_type.model_fields.keys())
            filtered = {k: v for k, v in data.items() if k in valid_fields}
            return self.expected_type.model_construct(**filtered)
        except Exception:
            return self.expected_type.model_construct()

    @property
    def is_filled(self) -> bool:
        return self.instruct_content is not None

    def __repr__(self):
        filled = "filled" if self.is_filled else "empty"
        return f"<ActionNode:{self.key} ({filled})>"
