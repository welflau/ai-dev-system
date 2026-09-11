from config import settings
import socket

print(f"Host: {settings.HOST}, Port: {settings.PORT}")

# 测试端口是否可绑定
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('127.0.0.1', settings.PORT))
    print(f"Port {settings.PORT} is available")
    s.close()
    
    # 尝试8080端口
    s2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s2.bind(('127.0.0.1', 8080))
    print("Port 8080 is available")
    s2.close()
    
except Exception as e:
    print(f"Port error: {e}")
    import traceback
    traceback.print_exc()