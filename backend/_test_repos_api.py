"""仓库识别 + 懒加载文件树：跑真实库、真实磁盘
    cd backend && python _test_repos_api.py

为什么必须用真实数据：这个功能的两个核心难点都只在真实项目上才成立 ——
  1. 项目 OG 的 I:\\A_Works\\OG2\\P4\\UE5 **同时**是 git 仓库、又在 P4 client root
     I:\\A_Works\\OG2\\P4 下。detect_vcs 是 git 优先的单值返回，会把它判成纯 git，
     于是永远进不了 P4 子 Tab。造假数据造不出这个"两栖"形态。
  2. 那个目录递归下去有 103 万个文件。懒加载到底有没有用，只有对着它才测得出来
     —— 对着一个 69 个文件的 ThunderStrike 测，全绿也说明不了任何事。
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, '.')

PASS = FAIL = 0


def check(name, cond, detail=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"[OK] {name}" + (f" -- {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"[FAIL] {name}" + (f" -- {detail}" if detail else ""))


async def main():
    from database import db
    await db.connect()
    try:
        from fastapi import HTTPException
        import api.repos as R

        # ── 项目定位（按名字查，id 会变）──────────────────────────
        async def pid_of(name):
            row = await db.fetch_one("SELECT id FROM projects WHERE name = ?", (name,))
            return row['id'] if row else None

        og = await pid_of('OG')
        thunder = await pid_of('ThunderStrike')
        check('找到测试项目 OG / ThunderStrike', bool(og and thunder), f'{og} / {thunder}')
        if not og:
            print('\n=== 缺少项目 OG，无法继续 ===')
            return

        # ── 1. 识别：两栖仓库 ────────────────────────────────────
        R._repos_cache.clear()
        t = time.time()
        data = await R.list_project_repos(og)
        cold_ms = (time.time() - t) * 1000

        check('OG 识别出 ≥2 个仓库', data['counts']['total'] >= 2, str(data['counts']))
        # p4 info 走网络（10s 超时），首次别太慢，否则切 tab 会卡一下
        check('首次识别 < 5s（p4 info 走网络）', cold_ms < 5000, f'{cold_ms:.0f}ms')

        t = time.time()
        await R.list_project_repos(og)
        warm_ms = (time.time() - t) * 1000
        check('二次识别走缓存（< 50ms）', warm_ms < 50, f'{warm_ms:.0f}ms')

        ue5 = next((r for r in data['repos']
                    if r['path'].replace('\\', '/').lower().endswith('og2/p4/ue5')), None)
        check('识别出 UE5 根', ue5 is not None)
        if ue5:
            # 这条是整个功能的核心：两个子 Tab 下都要出现
            check('UE5 根判为 git', ue5['vcs'] == 'git', ue5['vcs'])
            check('UE5 根同时标记 also_p4（detect_vcs 只会报 git）', ue5['also_p4'] is True)
            check('UE5 根带 git 分支信息', bool(ue5.get('git', {}).get('branch')),
                  ue5.get('git', {}).get('branch', ''))
            check('UE5 根带 P4 stream', bool(ue5.get('p4', {}).get('stream')),
                  ue5.get('p4', {}).get('stream', ''))
            check('P4 client root 是上一层（不是 UE5 自己）',
                  (ue5.get('p4', {}).get('client_root') or '').replace('\\', '/').lower()
                  .endswith('og2/p4'), ue5.get('p4', {}).get('client_root', ''))

        git_keys = {r['key'] for r in data['git']}
        p4_keys = {r['key'] for r in data['p4']}
        check('UE5 根同时进了 git 和 p4 两个分组',
              bool(ue5) and ue5['key'] in git_keys and ue5['key'] in p4_keys)

        # 配置里写着但实际不是仓库的路径，不能凭空消失
        all_keys = {r['key'] for r in data['repos']}
        bucketed = git_keys | p4_keys | {r['key'] for r in data['other']}
        check('每条仓库都落在某个分组里（没有条目被静默丢掉）',
              all_keys == bucketed, f'{len(all_keys)} vs {len(bucketed)}')

        # ── 2. 普通单仓库项目不受影响 ────────────────────────────
        if thunder:
            td = await R.list_project_repos(thunder)
            check('ThunderStrike 只有 1 个仓库', td['counts']['total'] == 1, str(td['counts']))
            check('ThunderStrike 不误报 P4', td['counts']['p4'] == 0)
            check('ThunderStrike 是 git', td['repos'][0]['vcs'] == 'git')

        # ── 3. 懒加载：103 万文件的仓库要秒开 ────────────────────
        key = ue5['key']
        timings = {}
        for rel, label in [('', '根'), ('Engine', 'Engine'), ('Engine/Source', 'Engine/Source')]:
            t = time.time()
            tr = await R.get_repo_tree(og, key, path=rel)
            timings[label] = ((time.time() - t) * 1000, tr)

        root_ms, root_tr = timings['根']
        check('UE5 根一层 < 1s（对照：整树 103 万文件）', root_ms < 1000, f'{root_ms:.0f}ms')
        check('UE5 根返回上百项', root_tr['total'] > 100, f"{root_tr['total']} 项")

        eng_ms, eng_tr = timings['Engine']
        check('Engine 子层 < 1s', eng_ms < 1000, f'{eng_ms:.0f}ms')
        check('Engine 下能看到 Source', any(e['name'] == 'Source' for e in eng_tr['entries']))

        # 默认 depth=1：只给一层，目录节点不带 children
        dirs = [e for e in root_tr['entries'] if e['type'] == 'directory']
        check('depth=1 时目录节点不含 children（证明是懒加载不是全量）',
              all('children' not in d for d in dirs), f'{len(dirs)} 个目录')
        check('目录节点带 has_children 标记（决定要不要画展开箭头）',
              all('has_children' in d for d in dirs))
        check('至少有一个目录 has_children=True', any(d['has_children'] for d in dirs))

        # depth=2 时才展开一层子节点
        tr2 = await R.get_repo_tree(og, key, path='Engine', depth=2)
        d2 = [e for e in tr2['entries'] if e['type'] == 'directory']
        check('depth=2 时目录节点带 children', any('children' in d for d in d2))

        # 排序：目录在前、文件在后，和前端 renderFileTree 一致
        types = [e['type'] for e in root_tr['entries']]
        first_file = types.index('file') if 'file' in types else len(types)
        check('目录排在文件前面', 'directory' not in types[first_file:])

        # ── 4. 每层条数上限 ──────────────────────────────────────
        # UE 引擎里真实存在 >500 项的目录（Slate/Icons 有 1098 个）
        big = 'Engine/Content/Editor/Slate/Icons'
        if os.path.isdir(os.path.join(ue5['path'], *big.split('/'))):
            bt = await R.get_repo_tree(og, key, path=big)
            check(f'{big} 触发截断', bt['truncated'] is True)
            check('截断后只返回 limit 条', len(bt['entries']) == bt['limit'],
                  f"{len(bt['entries'])} / {bt['limit']}")
            check('截断时仍报告真实总数', bt['total'] > bt['limit'], f"total={bt['total']}")
        else:
            check(f'跳过截断测试（{big} 不存在）', True)

        # ── 5. 目录穿越 ──────────────────────────────────────────
        # key 白名单是第一道防线，_safe_join 的 resolve+relative_to 是第二道
        for bad in ['../../../Windows', '/C:/Windows', '..\\..',
                    'Engine/../../..', './../../etc']:
            try:
                await R.get_repo_tree(og, key, path=bad)
                check(f'拦截穿越 {bad!r}', False, '未拦截！')
            except HTTPException as e:
                check(f'拦截穿越 {bad!r}', e.status_code in (400, 404), f'{e.status_code}')

        for bad_key in ['deadbeefcafe', '../../etc', '']:
            try:
                await R.get_repo_tree(og, bad_key, path='')
                check(f'拒绝伪造 key {bad_key!r}', False, '未拦截！')
            except HTTPException as e:
                check(f'拒绝伪造 key {bad_key!r}', e.status_code in (400, 404), f'{e.status_code}')

        # ── 6. 读文件 ────────────────────────────────────────────
        root_files = [e for e in root_tr['entries'] if e['type'] == 'file']
        md = next((f for f in root_files if f['name'].lower().endswith('.md')), None)
        if md:
            fr = await R.get_repo_file(og, key, path=md['path'])
            check('按仓库根读到文件内容', len(fr['content']) > 0, f"{md['name']} {fr['size']}B")
            # 返回形状要和 /git/file 一致，前端渲染分支才能直接复用
            check('返回形状含 path / content', 'path' in fr and 'content' in fr)

        try:
            await R.get_repo_file(og, key, path='../../../Windows/win.ini')
            check('读文件也拦穿越', False, '未拦截！')
        except HTTPException as e:
            check('读文件也拦穿越', e.status_code in (400, 404), f'{e.status_code}')

        try:
            await R.get_repo_file(og, key, path='不存在的文件.txt')
            check('不存在的文件 404', False, '未拦截！')
        except HTTPException as e:
            check('不存在的文件 404', e.status_code == 404)

        # ── 7. /git/tree 的深度上限（回归：OG 打开必卡死）────────
        from git_manager import git_manager
        git_manager.set_project_path('__repotest__', ue5['path'])
        t = time.time()
        tree = await git_manager.get_file_tree('__repotest__')
        tree_ms = (time.time() - t) * 1000
        check('/git/tree 在 OG 上 < 3s（原来要扫 103 万文件）',
              tree_ms < 3000, f'{tree_ms:.0f}ms')
        check('/git/tree 返回深度上限标记', tree.get('max_depth') == 3)

        def deepest(nodes, d=1):
            m = d
            for n in nodes:
                if n.get('children'):
                    m = max(m, deepest(n['children'], d + 1))
            return m
        check('/git/tree 实际深度不超过 max_depth',
              deepest(tree['children']) <= 3, f"深度 {deepest(tree['children'])}")

        def has_trunc(nodes):
            return any(n.get('truncated') or has_trunc(n.get('children') or []) for n in nodes)
        check('/git/tree 超深目录标了 truncated（前端能提示）', has_trunc(tree['children']))

    finally:
        await db.disconnect()

    print(f"\n=== {PASS} 通过 / {FAIL} 失败 ===")
    sys.exit(1 if FAIL else 0)


asyncio.run(main())
