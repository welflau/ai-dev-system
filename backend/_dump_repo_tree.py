"""导出真实仓库树的前两层，给 _test_repos_tree_render.js 当 fixture
    cd backend && python _dump_repo_tree.py

为什么要 fixture：渲染测试要断言"点开一个目录只发一次请求、且渲染出正确层级"，
这需要真实的 entries 形状（has_children / 有没有 children / 截断标记）。
手搓的假数据永远是"刚好能过"的形状。
"""
import asyncio
import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, '.')


async def main():
    from database import db
    await db.connect()
    try:
        import api.repos as R

        row = await db.fetch_one("SELECT id FROM projects WHERE name = ?", ('OG',))
        if not row:
            print('没有项目 OG，跳过')
            return
        pid = row['id']

        data = await R.list_project_repos(pid)
        ue5 = next((r for r in data['repos']
                    if r['path'].replace('\\', '/').lower().endswith('og2/p4/ue5')), None)
        if not ue5:
            print('没找到 UE5 根，跳过')
            return

        key = ue5['key']
        levels = {}
        for rel in ['', 'Engine', 'Engine/Source',
                    'Engine/Content/Editor/Slate/Icons']:   # 最后一个会触发截断
            try:
                levels[rel] = await R.get_repo_tree(pid, key, path=rel)
            except Exception as e:
                print(f'跳过 {rel}: {e}')

        out = {
            'repos': {k: data[k] for k in ('git', 'p4', 'other', 'counts')},
            'levels': levels,
        }
        with open('_fixture_repo_tree.json', 'w', encoding='utf-8') as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        print(f'已导出 {len(levels)} 层：' +
              ', '.join(f'{k or "<根>"}={len(v["entries"])}项' for k, v in levels.items()))
    finally:
        await db.disconnect()


asyncio.run(main())
