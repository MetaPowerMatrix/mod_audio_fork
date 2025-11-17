#!/usr/bin/env python3

"""测试FreeSWITCH ESL连接的简单脚本"""

import sys

def test_connection():
    try:
        from ESL import ESLconnection
        print("ESL module imported successfully")
    except ImportError:
        print("Error: ESL module not found. Please install python3-esl package")
        print("On Debian/Ubuntu: apt-get install python3-esl")
        print("Or build from FreeSWITCH source: make mod_event_socket-install-python3")
        return False
    
    # 测试连接参数
    host = 'localhost'
    port = 8021
    password = 'ClueCon'
    
    print(f"Testing connection to FreeSWITCH at {host}:{port}")
    
    try:
        con = ESLconnection(host, str(port), password)
        
        if con.connected():
            print("✓ Successfully connected to FreeSWITCH!")
            print(f"Connection info: {con.getInfo()}")
            con.disconnect()
            return True
        else:
            print("✗ Failed to connect to FreeSWITCH")
            info = con.getInfo() if hasattr(con, 'getInfo') else "No info available"
            print(f"Error info: {info}")
            return False
            
    except Exception as e:
        print(f"✗ Exception during connection: {e}")
        return False

if __name__ == "__main__":
    success = test_connection()
    sys.exit(0 if success else 1)