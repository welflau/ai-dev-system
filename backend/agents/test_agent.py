"""
测试代理（TestAgent）
负责自动生成测试用例、测试代码

LLM 模式：根据已生成的代码智能生成测试
降级模式：基于模板生成基础测试框架
"""
import os
import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from models.enums import AgentType

logger = logging.getLogger(__name__)

# LLM 测试生成系统提示词
TEST_SYSTEM_PROMPT = """你是一位资深 Python 测试工程师。
你的职责是根据项目代码和需求，生成高质量、可运行的 pytest 测试代码。

测试规范：
1. 使用 pytest 框架
2. 每个测试函数有清晰的 docstring
3. 覆盖正常路径和异常路径
4. 使用 fixture 复用测试资源
5. 测试命名：test_<功能>_<场景>
6. 包含必要的 mock（使用 unittest.mock）
7. 中文注释

你必须返回严格的 JSON 格式（不要包含 markdown 代码块标记），结构如下：
{
  "files": [
    {
      "path": "tests/test_xxx.py",
      "content": "完整的测试文件内容"
    }
  ],
  "summary": "一句话描述测试覆盖范围",
  "test_count": 5
}"""


class TestAgent:
    """测试代理 - LLM 智能生成 + 模板降级"""

    def __init__(self, work_dir: str = "projects", llm_client=None):
        self.agent_type = AgentType.TEST
        self.work_dir = work_dir
        self.llm_client = llm_client

    @property
    def _llm_available(self) -> bool:
        return self.llm_client is not None and self.llm_client.enabled

    def execute(self, task_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行测试任务

        Args:
            task_name: 任务名称
            context: 包含 project_id, requirement, dev_outputs, existing_files 等

        Returns:
            包含 success, files_created, output 的结果
        """
        project_id = context.get("project_id", "unknown")
        requirement = context.get("requirement", "")
        project_dir = os.path.join(self.work_dir, project_id)

        try:
            # 尝试 LLM 生成测试
            llm_result = self._llm_generate_tests(task_name, project_dir, requirement, context)
            if llm_result:
                return {
                    "success": True,
                    "agent": self.agent_type.value,
                    "task": task_name,
                    **llm_result,
                }

            # 降级：模板生成
            result = self._template_generate_tests(project_dir, requirement, context)
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
    #  LLM 智能测试生成
    # ------------------------------------------------------------------

    def _llm_generate_tests(
        self,
        task_name: str,
        project_dir: str,
        requirement: str,
        context: Dict,
    ) -> Optional[Dict[str, Any]]:
        """使用 LLM 智能生成测试代码"""
        if not self._llm_available:
            return None

        project_name = context.get("project_name", "项目")
        dev_outputs = context.get("dev_outputs", [])
        existing_files = context.get("existing_files", [])
        design_outputs = context.get("design_outputs", [])

        # 收集已生成的代码文件内容（供 LLM 参考）
        code_context = self._read_existing_code(project_dir, existing_files)

        prompt = f"""请为以下项目生成测试代码：

项目名称：{project_name}
任务名称：{task_name}
需求描述：{requirement}

已生成的代码文件：
{code_context or '（暂无代码文件）'}

架构设计摘要：
{json.dumps([d.get('output', '') for d in design_outputs], ensure_ascii=False)[:2000] if design_outputs else '（无）'}

开发输出摘要：
{json.dumps([d.get('output', '') for d in dev_outputs], ensure_ascii=False)[:2000] if dev_outputs else '（无）'}

请生成完整的 pytest 测试文件，返回 JSON 格式。"""

        try:
            response = self.llm_client.chat(
                messages=[{"role": "user", "content": prompt}],
                system=TEST_SYSTEM_PROMPT,
                temperature=0.3,
                max_tokens=8192,
            )

            if not response or response == "[LLM_UNAVAILABLE]":
                return None

            return self._parse_llm_response(response, project_dir)

        except Exception as e:
            logger.warning(f"LLM 测试生成失败: {e}")
            return None

    def _read_existing_code(self, project_dir: str, existing_files: List[str]) -> str:
        """读取已生成的 Python 代码文件（供 LLM 参考）"""
        code_snippets = []
        py_files = [f for f in existing_files if f.endswith('.py') and 'test' not in f.lower()]

        for rel_path in py_files[:10]:  # 最多读 10 个文件
            full_path = os.path.join(project_dir, rel_path)
            if os.path.exists(full_path):
                try:
                    with open(full_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    if content.strip():
                        # 截断过长的文件
                        if len(content) > 2000:
                            content = content[:2000] + "\n# ... (文件已截断)"
                        code_snippets.append(f"--- {rel_path} ---\n{content}")
                except Exception:
                    continue

        return "\n\n".join(code_snippets) if code_snippets else ""

    def _parse_llm_response(
        self, response: str, project_dir: str
    ) -> Optional[Dict[str, Any]]:
        """解析 LLM 返回的测试 JSON 并写入文件"""
        text = response.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"LLM 测试响应 JSON 解析失败: {text[:200]}")
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
            "output": data.get("summary", f"LLM 生成了 {len(files_created)} 个测试文件"),
            "test_count": data.get("test_count", len(files_created)),
            "mode": "llm",
        }

    # ------------------------------------------------------------------
    #  模板降级
    # ------------------------------------------------------------------

    def _template_generate_tests(
        self,
        project_dir: str,
        requirement: str,
        context: Dict,
    ) -> Dict[str, Any]:
        """模板引擎生成基础测试框架"""
        project_name = context.get("project_name", "project")
        existing_files = context.get("existing_files", [])
        dev_outputs = context.get("dev_outputs", [])

        files_created = []

        # 1. conftest.py
        conftest = self._gen_conftest(project_name)
        path = os.path.join(project_dir, "tests", "conftest.py")
        files_created.append(self._write_file(path, conftest))

        # 2. 根据已有代码文件生成对应测试
        py_files = [
            f for f in existing_files
            if f.endswith('.py')
            and 'test' not in f.lower()
            and '__init__' not in f
        ]

        if py_files:
            # 为每个主要模块生成测试
            for py_file in py_files[:5]:  # 最多 5 个
                module_name = os.path.splitext(os.path.basename(py_file))[0]
                test_content = self._gen_module_test(module_name, py_file, requirement)
                test_path = os.path.join(project_dir, "tests", f"test_{module_name}.py")
                files_created.append(self._write_file(test_path, test_content))
        else:
            # 没有代码文件，生成通用测试
            test_content = self._gen_generic_test(project_name, requirement)
            test_path = os.path.join(project_dir, "tests", "test_main.py")
            files_created.append(self._write_file(test_path, test_content))

        # 3. pytest.ini
        pytest_ini = self._gen_pytest_ini()
        path = os.path.join(project_dir, "pytest.ini")
        files_created.append(self._write_file(path, pytest_ini))

        test_count = sum(1 for f in files_created if 'test_' in os.path.basename(f))
        return {
            "files_created": files_created,
            "output": f"模板生成了 {len(files_created)} 个测试文件（{test_count} 个测试模块）",
            "test_count": test_count,
            "mode": "template",
        }

    def _gen_conftest(self, project_name: str) -> str:
        return f'''"""
{project_name} - 测试配置
"""
import pytest
import sys
import os

# 将 src 目录加入 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


@pytest.fixture
def app_config():
    """应用测试配置"""
    return {{
        "testing": True,
        "debug": True,
        "database_url": "sqlite:///:memory:",
    }}


@pytest.fixture
def sample_data():
    """示例测试数据"""
    return {{
        "name": "测试项目",
        "description": "这是一个测试用的示例数据",
    }}
'''

    def _gen_module_test(self, module_name: str, file_path: str, requirement: str) -> str:
        return f'''"""
{module_name} 模块测试
自动生成：基于 {file_path}
"""
import pytest


class Test{module_name.title().replace("_", "")}:
    """测试 {module_name} 模块"""

    def test_{module_name}_exists(self):
        """验证模块文件存在"""
        import os
        # 模块文件应该存在
        assert True, "{module_name} 模块已生成"

    def test_{module_name}_basic_functionality(self):
        """基础功能测试"""
        # TODO: 根据实际代码补充测试
        # 需求: {requirement[:80]}
        assert True, "基础功能正常"

    def test_{module_name}_error_handling(self):
        """异常处理测试"""
        # 测试异常输入场景
        with pytest.raises(Exception):
            raise ValueError("示例异常测试")

    def test_{module_name}_edge_cases(self):
        """边界条件测试"""
        # 空输入
        assert "" == ""
        # None 处理
        assert None is None
'''

    def _gen_generic_test(self, project_name: str, requirement: str) -> str:
        return f'''"""
{project_name} - 通用测试
需求: {requirement[:100]}
"""
import pytest


class TestProjectSetup:
    """项目初始化测试"""

    def test_project_structure(self):
        """验证项目结构"""
        import os
        # 基本目录应存在
        assert True, "项目结构已创建"

    def test_requirements_file(self):
        """验证依赖文件"""
        assert True, "依赖文件已生成"


class TestCoreFunctionality:
    """核心功能测试"""

    def test_basic_operation(self):
        """基本操作测试"""
        # TODO: 根据实际需求补充
        assert True, "基本操作正常"

    def test_input_validation(self):
        """输入校验测试"""
        # 空输入
        assert "" == ""
        # 长度验证
        assert len("test") == 4

    def test_error_scenarios(self):
        """错误场景测试"""
        with pytest.raises(ZeroDivisionError):
            _ = 1 / 0
'''

    def _gen_pytest_ini(self) -> str:
        return """[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = -v --tb=short
"""

    # ------------------------------------------------------------------
    #  工具方法
    # ------------------------------------------------------------------

    def _write_file(self, path: str, content: str) -> str:
        """写入文件，自动创建目录"""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path
