import asyncio
from database import db

async def check_requirements():
    await db.connect()
    
    # 查询当前活动需求
    active_reqs = await db.fetch_all('''
        SELECT id, title, status, created_at, updated_at 
        FROM requirements 
        WHERE status IN ('analyzing', 'decomposed', 'in_progress')
        ORDER BY updated_at DESC
    ''')
    
    # 查询所有需求状态分布
    status_counts = await db.fetch_all('''
        SELECT status, COUNT(*) as count 
        FROM requirements 
        GROUP BY status
    ''')
    
    print('当前活动需求:')
    if not active_reqs:
        print('没有活动中的需求')
    else:
        for req in active_reqs:
            print(str(req['id']) + ': ' + str(req['title']) + ' - ' + str(req['status']) + ' - ' + str(req['updated_at']))
    
    print('')
    print('需求状态分布:')
    for count in status_counts:
        print(str(count['status']) + ': ' + str(count['count']) + '个')
    
    await db.disconnect()

if __name__ == "__main__":
    asyncio.run(check_requirements())