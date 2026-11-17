"""验收/审查类 CLI 调用必须用真实仓库 cwd（治验收幻觉根因）

背景（TK-20261110-48b6af）：acceptance_review 是纯文本评审调用，历史上被
丢进隔离空目录 ads_cli_pure_gen。codebuddy CLI 自带文件工具，一查工作目录
「0 个文件」就幻觉判定「产出文件全部缺失 / 全目录树 0 个文件」，判 1 分
打回 → rework 重写代码 → tsc 失败 → blocked → 无限循环。

修复：验收/审查类调用 cwd 指向项目真实仓库；prompt 同时声明「注入证据是
唯一事实，禁止用工作目录文件树判断交付物缺失」。
"""
from llm_client import cli_needs_repo_cwd
from actions.acceptance_review import AcceptanceReviewAction


def test_review_calls_get_repo_cwd():
    """验收/代码审查必须拿真实仓库 cwd，否则被丢进隔离空目录幻觉"""
    assert cli_needs_repo_cwd("ProductAgent", "acceptance_review", False) is True
    assert cli_needs_repo_cwd("ReviewAgent", "code_review", False) is True


def test_pure_generation_still_isolated():
    """纯生成类仍走隔离空目录，避免 CLI 自主跑 git/Bash 空转"""
    for agent, action in [
        ("DevAgent", "develop"),
        ("DevAgent", "fix_issues"),
        ("PlannerAgent", "write_prd"),
        ("ArchitectAgent", "design_architecture"),
    ]:
        assert cli_needs_repo_cwd(agent, action, False) is False, (agent, action)


def test_chat_and_skill_io_get_repo_cwd():
    """聊天 / SkillRunner 一直用仓库 cwd，行为不变"""
    assert cli_needs_repo_cwd("ChatAssistant", "chat", False) is True
    assert cli_needs_repo_cwd("DevAgent", "develop", True) is True


def test_preview_not_matched_as_review():
    """"preview" 含 "review" 子串，不能被误判为审查类"""
    assert cli_needs_repo_cwd("TestAgent", "preview_scan", False) is False
    assert cli_needs_repo_cwd("DeployAgent", "gen_preview", False) is False


def test_acceptance_prompt_forbids_cwd_filetree_judgment():
    """验收 prompt 必须声明「注入证据是唯一事实、禁止用工作目录文件数判断」"""
    import inspect
    src = inspect.getsource(AcceptanceReviewAction.run)
    # 关键约束文案必须存在（防止后续被改回去）
    assert "事实来源" in src
    assert "严禁列出" in src or "严禁用工作目录" in src
    assert "唯一事实" in src or "唯一依据" in src
