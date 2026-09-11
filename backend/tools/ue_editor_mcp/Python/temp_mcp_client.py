import socket, json, struct

HOST = '127.0.0.1'
PORT = 55558

def send_mcp(type_name, params=None):
    msg_obj = {'type': type_name}
    if params:
        msg_obj['params'] = params
    msg = json.dumps(msg_obj).encode('utf-8')
    length = len(msg)
    header = struct.pack('>I', length)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(10)
        s.connect((HOST, PORT))
        s.sendall(header + msg)
        # Read response
        resp_header = s.recv(4)
        if len(resp_header) == 4:
            resp_len = struct.unpack('>I', resp_header)[0]
            resp_data = b''
            while len(resp_data) < resp_len:
                chunk = s.recv(resp_len - len(resp_data))
                if not chunk:
                    break
                resp_data += chunk
            return json.loads(resp_data.decode('utf-8'))
    return None

# 先 ping 测试
ping_result = send_mcp('ping')
print('Ping:', ping_result)

# 尝试不同的 action 名称
for action_name in [
    'add_key_mapping_to_context',
    'create_input_mapping_context',
    'create_input_action',
]:
    result = send_mcp(action_name, {})
    status = result.get('status', 'unknown') if result else 'no response'
    error_type = result.get('error_type', '') if result else ''
    print(f'{action_name}: {status} ({error_type})')
