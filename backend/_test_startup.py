"""Quick startup diagnostic"""
import asyncio, sys, traceback
sys.path.insert(0, ".")

async def main():
    print("1. importing database...")
    from database import db
    print("2. connecting...")
    await db.connect()
    print("3. init_tables...")
    await db.init_tables()
    print("4. DB OK!")
    await db.close()
    
    print("5. importing main...")
    from main import app
    print("6. ALL OK - app ready")

try:
    asyncio.run(main())
except Exception as e:
    traceback.print_exc()
    sys.exit(1)
