import os
import sys

print("Working dir:", os.getcwd())
sys.path.insert(0, os.getcwd())

try:
    from main import app
    print("FastAPI app import successful")
    print("Testing database connection...")
    
    # 测试数据库连接
    try:
        from database import db
        print("Database module import successful")
    except Exception as e:
        print(f"Database import error: {e}")
        
except Exception as e:
    print(f"Import error: {e}")
    import traceback
    traceback.print_exc()