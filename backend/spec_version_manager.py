"""
spec_version_manager.py — OpenSpec specs 版本管理

负责在 partial 变更时对 specs.md 做版本化备份，
生成 spec delta，并更新 ticket_spec_versions 表。
"""
import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("spec_version")


class SpecVersionManager:
    """管理单个工单的 OpenSpec specs 版本。"""

    def __init__(self, ticket_id: str, repo_path: str):
        self.ticket_id = ticket_id
        self.repo_path = repo_path
        self.specs_path = Path(repo_path) / "openspec" / "changes" / ticket_id / "specs.md"
        self.changes_dir = self.specs_path.parent

    def read_current_specs(self) -> Optional[str]:
        """读取当前 specs.md 内容，不存在返回 None。"""
        if not self.specs_path.exists():
            return None
        try:
            return self.specs_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return None

    def snapshot(self) -> Optional[int]:
        """把当前 specs.md 备份为 specs.v{n}.md，返回版本号，失败返回 None。"""
        current = self.read_current_specs()
        if not current:
            return None
        try:
            # 找下一个版本号
            existing = list(self.changes_dir.glob("specs.v*.md"))
            nums = []
            for f in existing:
                try:
                    nums.append(int(f.stem.replace("specs.v", "")))
                except ValueError:
                    pass
            next_ver = max(nums) + 1 if nums else 1

            backup = self.changes_dir / f"specs.v{next_ver}.md"
            backup.write_text(current, encoding="utf-8")
            logger.info("specs 已备份: %s -> %s", self.specs_path.name, backup.name)
            return next_ver
        except Exception as e:
            logger.warning("specs snapshot 失败: %s", e)
            return None

    def apply_delta(self, new_content: str) -> bool:
        """用新内容覆盖 specs.md，并追加变更日志。"""
        try:
            self.changes_dir.mkdir(parents=True, exist_ok=True)
            self.specs_path.write_text(new_content, encoding="utf-8")
            return True
        except Exception as e:
            logger.warning("apply_delta 失败: %s", e)
            return False

    @property
    def current_version(self) -> int:
        """当前版本号（备份文件数 + 1）。"""
        existing = list(self.changes_dir.glob("specs.v*.md"))
        return len(existing) + 1

    async def save_version_to_db(
        self,
        content: str,
        change_summary: str,
        comment_id: Optional[str] = None,
    ) -> None:
        """持久化版本快照到 ticket_spec_versions 表。"""
        try:
            from database import db
            from utils import generate_id, now_iso
            await db.insert("ticket_spec_versions", {
                "id": generate_id("SPV"),
                "ticket_id": self.ticket_id,
                "version": self.current_version,
                "content": content,
                "change_summary": change_summary,
                "triggered_by": comment_id or "",
                "created_at": now_iso(),
            })
            await db.execute(
                "UPDATE tickets SET spec_version=?, updated_at=? WHERE id=?",
                (self.current_version, now_iso(), self.ticket_id),
            )
        except Exception as e:
            logger.debug("save_version_to_db 失败（忽略）: %s", e)


async def generate_spec_delta(
    current_specs: str,
    change_request: str,
    affected_specs: list,
) -> str:
    """
    用 LLM 生成 specs 增量：只返回新增/修改的场景，保留已有场景。
    返回完整的新 specs.md 内容。
    """
    affected_str = "\n".join(f"- {s}" for s in affected_specs) if affected_specs else "（由 LLM 判断）"

    prompt = f"""当前 OpenSpec specs：
{current_specs[:2000]}

需求变更请求：
{change_request}

受影响的场景：
{affected_str}

请生成更新后的完整 specs.md 内容（GIVEN/WHEN/THEN 格式）。
要求：
1. 保留所有原有场景（不删除）
2. 针对变更请求新增或修改相关场景
3. 保持 Markdown 格式，用 ## 分隔场景

直接输出 Markdown，不要解释："""

    try:
        from llm_client import llm_client
        result = await llm_client.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=2000,
        )
        return result.strip()
    except Exception as e:
        logger.warning("generate_spec_delta 失败: %s", e)
        # 降级：在原有 specs 后追加变更请求作为新场景
        return current_specs + f"\n\n## 变更请求（待细化）\n\n{change_request}\n"
