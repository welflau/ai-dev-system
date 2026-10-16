"""从真实库导出几条 CI 构建输出，给 _test_task_output_render.js 当样本。

挑选依据：覆盖不同长度与结果（49 行的 package / 3 行的 ubt_compile / failed 的），
不是挑最长的 —— 排版 bug 恰恰是在"多行但不算长"的输出上最刺眼。

    cd backend && python _dump_ci_output.py
"""
import json
import sqlite3
import sys

sys.path.insert(0, '.')
from config import settings   # noqa: E402

KEEP = ('id', 'build_type', 'status', 'raw_output_tail')


def main():
    c = sqlite3.connect(settings.DB_PATH)
    c.row_factory = sqlite3.Row
    rows = c.execute(
        "SELECT * FROM ci_builds "
        "WHERE raw_output_tail IS NOT NULL AND raw_output_tail != '' "
        "ORDER BY created_at DESC LIMIT 6"
    ).fetchall()

    out = []
    for r in rows:
        d = dict(r)
        out.append({
            'id': d['id'],
            'build_type': d.get('build_type') or '',
            'status': d.get('status') or '',
            'log_tail': d['raw_output_tail'],
        })
        n = d['raw_output_tail'].count('\n') + 1
        print(f"{d['id']}  {d.get('build_type'):<16} {d.get('status'):<9} {n} 行")

    with open('_fixture_ci_output.json', 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"已写入 _fixture_ci_output.json（{len(out)} 条）")
    c.close()


main()
