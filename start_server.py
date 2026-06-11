import sys, os

BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backend')
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)

# 直接导入 app 对象传给 uvicorn，避免字符串解析走错路径
from main import app
import uvicorn
uvicorn.run(app, host='0.0.0.0', port=8000, reload=False)
