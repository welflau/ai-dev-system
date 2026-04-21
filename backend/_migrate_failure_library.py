"""
一次性脚本：扫描 ticket_logs(action='reflection') 把历史反思回灌到 failure_cases。

幂等：按 (ticket_id, root_cause) 去重，重复跑不会产生冗余数据。
启动时不会自动跑 — 用户按需手动执行：

  cd backend && PYTHONIOENCODING=utf-8 python _migrate_failure_library.py

典型输出：
  已连接 DB: ./data/ai_dev_system.db
  📦 回灌 17 条历史反思到 failure_cases
"""
import asyncio
import logging
import sys


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s  %(message)s",
    )
    log = logging.getLogger("migrate")

    from database import db
    from failure_library import failure_library

    await db.connect()
    log.info("已连接 DB: %s", db.db_path)

    # 确保表存在（init_tables 会 IF NOT EXISTS，幂等）
    await db.init_tables()

    written = await failure_library.backfill_from_ticket_logs()
    log.info("📦 回灌完成：新增 %d 条案例到 failure_cases", written)

    await db.disconnect()
    return written


if __name__ == "__main__":
    written = asyncio.run(main())
    sys.exit(0 if written >= 0 else 1)
