"""视频/内容项目不能挂「在线试玩」，也不能产出网页 Dockerfile。"""
from agents.deploy import DeployAgent, preview_skip_kind


def test_video_traits_skip_playtest():
    assert preview_skip_kind(["category:video", "pipeline:video"]) == "video"
    assert preview_skip_kind(["pipeline:video", "platform:web"]) == "video"


def test_content_traits_skip_playtest():
    assert preview_skip_kind(["pipeline:content"]) == "content"


def test_web_traits_still_playtest():
    assert preview_skip_kind(["platform:web"]) is None
    assert preview_skip_kind(["category:app"]) is None


def test_video_deploy_files_have_no_docker_or_playtest():
    agent = DeployAgent.__new__(DeployAgent)
    files = agent._generate_deploy_files(
        "第一集视频简报", "docs/", preview_url="http://localhost:8000/preview/dev/index.html",
        kind="video",
    )
    assert "build/Dockerfile" not in files
    assert "build/docker-compose.yml" not in files
    text = files["docs/deploy.md"]
    assert "在线试玩" in text
    assert "docker" not in text.lower()


def test_web_deploy_files_still_have_docker():
    agent = DeployAgent.__new__(DeployAgent)
    files = agent._generate_deploy_files("网页 MVP", "docs/", kind="web")
    assert "build/Dockerfile" in files
    assert "uvicorn" in files["build/Dockerfile"]
