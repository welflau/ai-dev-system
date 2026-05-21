"""
rules-bridge-mcp — 为外部 IDE（Claude Code、Cursor 等）提供 ADS 规则查询

用法：
  python -m mcps.rules-bridge-mcp.server          # stdio 模式（Claude Code MCP）
  python -m mcps.rules-bridge-mcp.server --http 3100  # HTTP 模式

MCP 工具：
  get_coding_rules(file_path, project_path?, traits?) → 返回适用规则文本
  list_rules(project_path?)                          → 列出所有规则元信息
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Optional

# 把 backend/ 加入 sys.path（从任意目录启动都能 import）
_BACKEND = Path(__file__).parent.parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from skills.loader import SkillLoader

logger = logging.getLogger("rules-bridge-mcp")
_loader = SkillLoader()


# ==================== MCP 工具实现 ====================

def get_coding_rules(
    file_path: str = "",
    project_path: str = "",
    traits: list[str] | None = None,
    scene: str = "",
) -> str:
    """返回适用于当前编辑文件的所有规则文本。

    Args:
        file_path:    当前编辑的文件路径（用于 paths: glob 匹配）
        project_path: 项目仓库根路径（加载 .ads/rules/）
        traits:       项目 trait 列表（如 ["ue5", "game"]）
        scene:        触发场景（"autoaicr" / "precommit" / 空）
    """
    traits = traits or []
    rule_ids = _loader.get_rules_for_context(
        traits=traits,
        current_file=file_path or None,
        scene=scene or None,
    )
    sections: list[str] = []
    for rid in rule_ids:
        content = _loader.rules.get(rid, {}).get("content", "")
        if content:
            sections.append(f"<!-- Rule: {rid} -->\n{content}")

    if project_path:
        project_rules = _loader.load_project_rules(
            project_path,
            current_file=file_path or None,
            scene=scene or None,
        )
        if project_rules:
            sections.append(project_rules)

    return "\n\n---\n\n".join(sections) if sections else "(无适用规则)"


def list_rules(project_path: str = "") -> list[dict]:
    """列出所有已加载的规则元信息（id / description / paths / scene / alwaysApply）。"""
    result = []
    for rid, cfg in _loader.rules.items():
        result.append({
            "id":          rid,
            "description": cfg.get("description", ""),
            "paths":       cfg.get("paths") or [],
            "scene":       cfg.get("scene") or "",
            "alwaysApply": cfg.get("alwaysApply", False),
            "priority":    cfg.get("priority", "medium"),
        })
    if project_path:
        proj_rules_dir = Path(project_path) / ".ads" / "rules"
        if proj_rules_dir.exists():
            for md_file in sorted(proj_rules_dir.rglob("*.md")):
                try:
                    from skills.loader import _parse_frontmatter
                    fm, _ = _parse_frontmatter(md_file.read_text(encoding="utf-8"))
                    result.append({
                        "id":          f"project.{md_file.stem}",
                        "description": fm.get("description", ""),
                        "paths":       fm.get("paths") or [],
                        "scene":       fm.get("scene") or "",
                        "alwaysApply": fm.get("alwaysApply", True),
                        "priority":    fm.get("priority", "medium"),
                        "source":      "project",
                    })
                except Exception:
                    pass
    return result


# ==================== stdio MCP 协议 ====================

_TOOLS = {
    "get_coding_rules": {
        "description": "返回适用于当前编辑文件的规则文本，供 AI IDE 插件注入上下文。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path":    {"type": "string", "description": "当前编辑文件路径"},
                "project_path": {"type": "string", "description": "项目仓库根路径"},
                "traits":       {"type": "array",  "items": {"type": "string"}, "description": "项目 trait 列表"},
                "scene":        {"type": "string", "description": "触发场景（autoaicr/precommit/空）"},
            },
        },
    },
    "list_rules": {
        "description": "列出所有可用规则的元信息（id/paths/scene/alwaysApply）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_path": {"type": "string", "description": "项目仓库根路径（可选，加载项目规则）"},
            },
        },
    },
}


def _handle_request(req: dict) -> dict:
    method = req.get("method", "")
    req_id = req.get("id")

    def ok(result):
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    def err(code, msg):
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": msg}}

    if method == "initialize":
        return ok({
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "ads-rules-bridge", "version": "1.0.0"},
        })
    elif method == "tools/list":
        tools_list = [{"name": k, **v} for k, v in _TOOLS.items()]
        return ok({"tools": tools_list})
    elif method == "tools/call":
        name = req.get("params", {}).get("name", "")
        args = req.get("params", {}).get("arguments", {})
        try:
            if name == "get_coding_rules":
                text = get_coding_rules(**{k: v for k, v in args.items()
                                           if k in ("file_path","project_path","traits","scene")})
                return ok({"content": [{"type": "text", "text": text}]})
            elif name == "list_rules":
                data = list_rules(project_path=args.get("project_path", ""))
                return ok({"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False, indent=2)}]})
            else:
                return err(-32601, f"Unknown tool: {name}")
        except Exception as e:
            return err(-32000, str(e))
    elif method == "notifications/initialized":
        return None  # 无需响应
    else:
        return err(-32601, f"Method not found: {method}")


def run_stdio():
    """stdio 模式：逐行读取 JSON-RPC 请求，写出响应。"""
    import sys
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            resp = _handle_request(req)
            if resp is not None:
                print(json.dumps(resp, ensure_ascii=False), flush=True)
        except json.JSONDecodeError:
            pass
        except Exception as e:
            print(json.dumps({"jsonrpc": "2.0", "id": None,
                              "error": {"code": -32700, "message": str(e)}}), flush=True)


def run_http(port: int = 3100):
    """HTTP 模式（简单 POST /mcp）。"""
    from http.server import HTTPServer, BaseHTTPRequestHandler

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                req = json.loads(body)
                resp = _handle_request(req)
                data = json.dumps(resp or {}, ensure_ascii=False).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(data)
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(e).encode())

    print(f"[rules-bridge-mcp] HTTP 监听 0.0.0.0:{port}", file=sys.stderr)
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()


def main():
    parser = argparse.ArgumentParser(description="ADS Rules Bridge MCP Server")
    parser.add_argument("--http", type=int, metavar="PORT",
                        help="HTTP 模式，指定端口（默认 stdio 模式）")
    args = parser.parse_args()
    if args.http:
        run_http(args.http)
    else:
        run_stdio()


if __name__ == "__main__":
    main()
