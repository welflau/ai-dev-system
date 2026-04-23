"""
ProjectTypeDetectorAction — 扫 repo 根目录文件特征，推断项目 traits candidates

v0.17 Phase D：导入现有项目时不让用户手填 trait，自动扫仓库文件给出**带证据的**
候选 traits 列表，用户在确认卡片上选择性采纳。

规则设计：
- 硬证据（>=0.90）：`*.uproject` / `project.godot` / `ProjectVersion.txt` 等明确的引擎工程文件
- 中等证据（0.70-0.85）：`package.json` 依赖分析、`requirements.txt` 含特定框架
- 弱证据（0.50-0.70）：扩展名统计、README 关键词

规则冲突时：
- 同一 trait 多条规则命中 → 取最高 confidence
- 不同维度 trait 间：按 `trait_taxonomy.yaml` 里的约束校验（例 category=game + engine=ue5）

返回：`{candidates, suggested_preset, warnings}`。preset 匹配跟 PresetMatcher 不同 ——
那个是 user_text 评分，这个是从 traits 集合反查 preset（全集匹配度最高的 preset 名）。
"""
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from actions.base import ActionBase, ActionResult

logger = logging.getLogger("actions.chat.detect_project_type")


# ==================== 规则集 ====================
# 每条规则格式：
#   {
#     "file": str | [str, ...]      # 相对路径或 glob；glob 至少命中一个就算
#     "exists_in": Optional[str]    # 必须位于子目录（未用时 None）
#     "contents_has": Optional[List[str]]  # 文件内容含任一子串才算命中
#     "contents_any_key": Optional[List[str]]  # JSON 文件里任一 key 存在
#     "dep_any_of": Optional[List[str]]  # package.json/requirements 依赖含任一
#     "emit": List[str]              # 命中后产出的 traits
#     "confidence": float            # 0..1
#     "evidence": str                # 人类可读的证据描述（{file} 会被替换）
#   }

RULES = [
    # ============= 引擎类（高置信） =============
    {
        "glob": ["*.uproject"],
        "emit": ["engine:ue5", "category:game", "platform:desktop", "lang:cpp"],
        "confidence": 0.98,
        "evidence": "找到 {file}（UE5 工程文件）",
    },
    {
        "glob": ["project.godot"],
        "emit": ["engine:godot4", "category:game", "platform:desktop"],
        "confidence": 0.98,
        "evidence": "找到 {file}（Godot 工程文件）",
    },
    {
        "glob": ["ProjectSettings/ProjectVersion.txt"],
        "emit": ["engine:unity", "category:game", "platform:desktop", "lang:csharp"],
        "confidence": 0.95,
        "evidence": "找到 Unity ProjectVersion.txt",
    },
    {
        "glob": ["*.unity"],    # 场景文件
        "emit": ["engine:unity", "category:game"],
        "confidence": 0.80,
        "evidence": "找到 Unity 场景文件 {file}",
    },
    {
        "glob": ["*.uasset"],
        "emit": ["engine:ue5"],
        "confidence": 0.75,
        "evidence": "发现 UE asset 文件",
    },
    # ============= 小程序 =============
    {
        "glob": ["miniprogram/app.json", "app.json"],
        "exists_also": ["app.wxss", "miniprogram/app.wxss"],
        "emit": ["platform:wechat", "platform:web", "category:app", "lang:javascript"],
        "confidence": 0.95,
        "evidence": "找到微信小程序配置（app.json + app.wxss）",
    },
    # ============= Node / 前端 =============
    {
        "glob": ["package.json"],
        "dep_any_of": ["react", "react-dom"],
        "emit": ["framework:react", "platform:web", "lang:javascript"],
        "confidence": 0.92,
        "evidence": "package.json 依赖 react",
    },
    {
        "glob": ["package.json"],
        "dep_any_of": ["vue"],
        "emit": ["framework:vue", "platform:web", "lang:javascript"],
        "confidence": 0.92,
        "evidence": "package.json 依赖 vue",
    },
    {
        "glob": ["package.json"],
        "dep_any_of": ["@angular/core"],
        "emit": ["framework:angular", "platform:web", "lang:typescript"],
        "confidence": 0.92,
        "evidence": "package.json 依赖 @angular/core",
    },
    {
        "glob": ["package.json"],
        "dep_any_of": ["svelte"],
        "emit": ["framework:svelte", "platform:web", "lang:javascript"],
        "confidence": 0.92,
        "evidence": "package.json 依赖 svelte",
    },
    {
        "glob": ["package.json"],
        "dep_any_of": ["express", "koa", "fastify"],
        "emit": ["framework:express", "category:service", "platform:server", "lang:javascript"],
        "confidence": 0.88,
        "evidence": "package.json 依赖 Node 后端框架 (express/koa/fastify)",
    },
    {
        "glob": ["package.json"],
        "dep_any_of": ["react-native"],
        "emit": ["platform:mobile", "framework:react", "lang:javascript"],
        "confidence": 0.90,
        "evidence": "package.json 依赖 react-native",
    },
    {
        "glob": ["package.json"],
        "emit": ["lang:javascript"],
        "confidence": 0.60,
        "evidence": "找到 package.json（至少是 Node.js 项目）",
    },
    {
        "glob": ["tsconfig.json"],
        "emit": ["lang:typescript"],
        "confidence": 0.85,
        "evidence": "找到 tsconfig.json",
    },
    # ============= Python =============
    {
        "glob": ["requirements.txt", "pyproject.toml", "setup.py"],
        "dep_any_of": ["fastapi"],
        "emit": ["framework:fastapi", "category:service", "platform:server", "lang:python"],
        "confidence": 0.90,
        "evidence": "依赖声明含 fastapi",
    },
    {
        "glob": ["requirements.txt", "pyproject.toml"],
        "dep_any_of": ["django"],
        "emit": ["framework:django", "category:service", "platform:server", "lang:python"],
        "confidence": 0.90,
        "evidence": "依赖声明含 django",
    },
    {
        "glob": ["requirements.txt", "pyproject.toml"],
        "dep_any_of": ["flask"],
        "emit": ["framework:flask", "category:service", "platform:server", "lang:python"],
        "confidence": 0.88,
        "evidence": "依赖声明含 flask",
    },
    {
        "glob": ["requirements.txt", "pyproject.toml", "setup.py"],
        "emit": ["lang:python"],
        "confidence": 0.70,
        "evidence": "Python 依赖文件存在",
    },
    # ============= 其他语言 =============
    {
        "glob": ["Cargo.toml"],
        "emit": ["lang:rust"],
        "confidence": 0.95,
        "evidence": "找到 Cargo.toml（Rust 项目）",
    },
    {
        "glob": ["go.mod"],
        "emit": ["lang:go"],
        "confidence": 0.95,
        "evidence": "找到 go.mod",
    },
    {
        "glob": ["pom.xml", "build.gradle", "build.gradle.kts"],
        "emit": ["lang:java"],
        "confidence": 0.88,
        "evidence": "找到 Java 构建文件 {file}",
    },
    # ============= HTML5 纯前端/游戏 =============
    {
        "glob": ["index.html"],
        "contents_has": ["<canvas", "requestAnimationFrame"],
        "emit": ["category:game", "platform:web", "engine:none"],
        "confidence": 0.65,
        "evidence": "index.html 含 <canvas> + 动画循环特征，可能是纯 JS 网页游戏",
    },
    # ============= VCS =============
    {
        "glob": [".git/HEAD", ".git/config"],
        "emit": ["vcs:git"],
        "confidence": 0.99,
        "evidence": "找到 .git 目录",
    },
    {
        "glob": [".p4config", ".p4ignore"],
        "emit": ["vcs:p4"],
        "confidence": 0.95,
        "evidence": "找到 Perforce 配置文件",
    },
]


class ProjectTypeDetectorAction(ActionBase):
    """扫描仓库根目录文件特征，推断 traits candidates"""

    @property
    def name(self) -> str:
        return "detect_project_type"

    @property
    def description(self) -> str:
        return "扫描仓库根目录，按文件特征规则推断项目 traits + 建议的 preset"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        # 不对 LLM 暴露，程序化调用
        return {
            "name": self.name,
            "description": "（内部用）扫描仓库推断 traits，导入现有项目时使用",
            "input_schema": {
                "type": "object",
                "properties": {
                    "repo_path": {"type": "string"},
                },
                "required": ["repo_path"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        repo_path = (context.get("repo_path") or "").strip()
        if not repo_path:
            return ActionResult(success=False, error="缺 repo_path")

        root = Path(repo_path)
        if not root.is_dir():
            return ActionResult(success=False, error=f"路径不是目录或不存在: {repo_path}")

        # 收集 trait -> 最高 confidence + evidence
        trait_evidence: Dict[str, Dict[str, Any]] = {}
        matched_rules: List[Dict[str, Any]] = []

        for rule in RULES:
            matched_files = _match_rule(root, rule)
            if not matched_files:
                continue

            ev_file = matched_files[0]
            evidence_str = rule["evidence"].replace("{file}", ev_file)
            matched_rules.append({
                "evidence": evidence_str,
                "confidence": rule["confidence"],
                "traits": list(rule["emit"]),
                "matched_file": ev_file,
            })

            for t in rule["emit"]:
                prev = trait_evidence.get(t)
                if prev is None or rule["confidence"] > prev["confidence"]:
                    trait_evidence[t] = {
                        "trait": t,
                        "confidence": rule["confidence"],
                        "evidence": evidence_str,
                        "matched_file": ev_file,
                    }

        # 排序 candidates
        candidates = sorted(
            trait_evidence.values(),
            key=lambda c: c["confidence"],
            reverse=True,
        )

        # 推断 preset（从 presets.yaml 里找 traits 集合重合度最高的）
        suggested_preset, preset_score = _match_preset_by_traits(
            [c["trait"] for c in candidates]
        )

        warnings = _compute_warnings(candidates)

        return ActionResult(
            success=True,
            data={
                "type": "project_type_detected",
                "repo_path": str(root),
                "candidates": candidates,
                "matched_rules": matched_rules,
                "suggested_preset": suggested_preset,
                "preset_match_score": preset_score,
                "warnings": warnings,
            },
        )


# ==================== helpers ====================

def _match_rule(root: Path, rule: Dict[str, Any]) -> List[str]:
    """判断规则是否命中。命中返回匹配到的文件（相对路径）列表，未命中返回 []。"""
    import fnmatch

    globs = rule.get("glob") or []
    if not globs:
        return []

    matched: List[str] = []
    # 先根目录，再第一层子目录（monorepo 常见：backend/requirements.txt 等）
    # 不递归太深避免扫大项目太慢
    search_scopes = [root] + [d for d in root.iterdir() if d.is_dir() and not d.name.startswith(".")] \
        if root.is_dir() else [root]

    for pattern in globs:
        # 分两种：带 / 的当路径，不带的当当前目录 glob
        if "/" in pattern or "\\" in pattern:
            # 直接按相对路径检查是否存在（只在根目录下）
            p = root / pattern
            if p.exists():
                matched.append(pattern)
        else:
            for scope in search_scopes:
                try:
                    # scope 可能因权限问题报错
                    for f in scope.glob(pattern):
                        if f.is_file():
                            matched.append(f.relative_to(root).as_posix())
                            break
                except (PermissionError, OSError):
                    continue
                if matched:
                    break
    if not matched:
        return []

    # exists_also：还需要另一个文件也存在才算命中
    also_ok = True
    for also_pat in (rule.get("exists_also") or []):
        also_p = root / also_pat
        if not also_p.exists():
            also_ok = False
            break
    if not also_ok:
        return []

    # dep_any_of：命中文件如果是 package.json / requirements.txt，要解析依赖
    deps_required = rule.get("dep_any_of") or []
    if deps_required:
        dep_set = _extract_deps(root, matched[0])
        if not any(d.lower() in dep_set for d in deps_required):
            return []

    # contents_has：文件内容含任一子串
    contents_has = rule.get("contents_has") or []
    if contents_has:
        try:
            text = (root / matched[0]).read_text(encoding="utf-8", errors="ignore")
            if not any(s in text for s in contents_has):
                return []
        except Exception:
            return []

    return matched


def _extract_deps(root: Path, relative_file: str) -> set:
    """从 package.json / requirements.txt / pyproject.toml 提取依赖名（小写）"""
    deps: set = set()
    p = root / relative_file
    try:
        if relative_file.endswith("package.json"):
            data = json.loads(p.read_text(encoding="utf-8", errors="ignore"))
            for section in ("dependencies", "devDependencies", "peerDependencies"):
                for k in (data.get(section) or {}).keys():
                    deps.add(k.lower())
        elif relative_file.endswith("requirements.txt"):
            for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip().split("#")[0].strip()
                if not line:
                    continue
                # requirements 行例：fastapi==0.104 / django >= 4.2 / flask
                name = line.split("==")[0].split(">=")[0].split("<=")[0].split(">")[0].split("<")[0].split("[")[0].strip()
                if name:
                    deps.add(name.lower())
        elif relative_file.endswith("pyproject.toml"):
            # 简单文本搜索（避免引 tomllib 兼容性）
            text = p.read_text(encoding="utf-8", errors="ignore").lower()
            for kw in ("fastapi", "django", "flask", "pydantic", "sqlalchemy"):
                if kw in text:
                    deps.add(kw)
    except Exception as e:
        logger.debug("parse deps 失败 (%s): %s", relative_file, e)
    return deps


def _match_preset_by_traits(candidate_traits: List[str]) -> tuple:
    """从 candidates 反查 preset：跟哪个 preset 的 traits 交集最多就推荐它。
    返回 (preset_id, overlap_score)。无匹配返回 (None, 0)。
    """
    try:
        import yaml
        presets_path = Path(__file__).resolve().parent.parent.parent / "skills" / "rules" / "presets.yaml"
        if not presets_path.exists():
            return (None, 0)
        data = yaml.safe_load(presets_path.read_text(encoding="utf-8")) or {}
        presets = (data.get("presets") or {})
    except Exception as e:
        logger.warning("加载 presets.yaml 失败: %s", e)
        return (None, 0)

    cand_set = set(candidate_traits)
    best = (None, 0)
    for pid, cfg in presets.items():
        preset_traits = set(cfg.get("traits") or [])
        if not preset_traits:
            continue
        overlap = len(cand_set & preset_traits)
        # 也要求 preset 核心 traits（platform + category）必须在候选里
        preset_core = {t for t in preset_traits if t.startswith(("platform:", "category:", "engine:"))}
        if preset_core and not preset_core.issubset(cand_set):
            continue
        if overlap > best[1]:
            best = (pid, overlap)

    return best


def _compute_warnings(candidates: List[Dict]) -> List[str]:
    """探测结果的提示：缺 platform:* / category:* / 冲突等"""
    traits = [c["trait"] for c in candidates]
    warnings = []
    if not any(t.startswith("platform:") for t in traits):
        warnings.append("未探测到 platform:*，建议用户手选")
    if not any(t.startswith("category:") for t in traits):
        warnings.append("未探测到 category:*，建议用户手选（app / game / service）")
    if "category:game" in traits and not any(t.startswith("engine:") for t in traits):
        warnings.append("看起来是游戏项目但未识别到引擎，建议手选 engine:*")
    # 多引擎冲突
    engines = [t for t in traits if t.startswith("engine:") and t != "engine:none"]
    if len(engines) > 1:
        warnings.append(f"识别到多个引擎 {engines}，可能是残留文件，请人工确认")
    return warnings
