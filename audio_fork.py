#!/usr/bin/env python3
"""
audio_fork.py - Python version of audio_fork.js
Freeswitch audio streaming application using ESL
"""

import sys
import json
import argparse
from ESL import ESLconnection

# 事件定义
EVENT_TRANSCRIPT = "mod_audio_fork::transcription"
EVENT_TRANSFER = "mod_audio_fork::transfer"
EVENT_PLAY_AUDIO = "mod_audio_fork::play_audio"
EVENT_KILL_AUDIO = "mod_audio_fork::kill_audio"
EVENT_DISCONNECT = "mod_audio_fork::disconnect"
EVENT_CONNECT = "mod_audio_fork::connect"
EVENT_CONNECT_FAILED = "mod_audio_fork::connect_failed"
EVENT_MAINTENANCE = "mod_audio_fork::maintenance"
EVENT_ERROR = "mod_audio_fork::error"

class AudioForkSession:
    def __init__(self, ws_url, host='localhost', port=8021, password='ClueCon'):
        self.ws_url = ws_url
        self.host = host
        self.port = port
        self.password = password
        self.con = None
        self.uuid = None
        
    def connect(self):
        """连接到FreeSWITCH ESL"""
        print(f"Connecting to FreeSWITCH at {self.host}:{self.port}")
        self.con = ESLconnection(self.host, str(self.port), self.password)
        
        if not self.con.connected():
            print(f"Failed to connect to FreeSWITCH: {self.con.getInfo()}")
            return False
            
        print("Connected to FreeSWITCH")
        return True
        
    def subscribe_events(self):
        """订阅相关事件"""
        # 订阅自定义事件
        custom_events = [
            EVENT_CONNECT, EVENT_CONNECT_FAILED, EVENT_DISCONNECT,
            EVENT_ERROR, EVENT_MAINTENANCE
        ]
        self.con.events("plain", f"CUSTOM {' '.join(custom_events)}")
        
        # 订阅通道事件
        self.con.events("plain", "DTMF") 
        self.con.events("plain", "CHANNEL_ANSWER")
        
    def on_connect(self, event):
        """连接成功事件处理"""
        print("successfully connected")
        
    def on_connect_failed(self, event):
        """连接失败事件处理"""
        print("connection failed")
        
    def on_disconnect(self, event):
        """断开连接事件处理"""
        print("far end dropped connection")
        
    def on_error(self, event):
        """错误事件处理"""
        print(f"got error: {event.getBody()}")
        
    def on_maintenance(self, event):
        """维护事件处理"""
        print(f"got event: {event.getBody()}")
        
    def handle_dtmf(self, event):
        """处理DTMF事件"""
        dtmf = event.getHeader("DTMF-Digit")
        if dtmf and self.uuid:
            cmd = f"uuid_audio_fork {self.uuid} send_text {dtmf}"
            self.con.api(cmd)
            
    def handle_channel_answer(self, event):
        """处理通道应答事件"""
        self.uuid = event.getHeader("Unique-ID")
        call_id = event.getHeader("variable_sip_call_id")
        to_uri = event.getHeader("variable_sip_to_uri")
        from_uri = event.getHeader("variable_sip_from_uri")
        
        print(f"Channel answered: {self.uuid}")
        self.init_audio_fork(call_id, to_uri, from_uri)
        
    def init_audio_fork(self, call_id, to_uri, from_uri):
        """初始化音频流转发"""
        # 构建metadata JSON
        metadata = {
            "callId": call_id,
            "to": to_uri,
            "from": from_uri
        }
        
        # 播放静音
        self.con.execute("playback", "silence_stream://1000", self.uuid)
        
        # 使用Google TTS播放欢迎消息
        # tts_text = "Hi there. Please go ahead and make a recording and then hangup"
        # self.con.execute("speak", f"google_tts:en-GB-Wavenet-A:{tts_text}", self.uuid)
        
        # 启动音频流转发
        metadata_str = json.dumps(metadata)
        cmd = f"uuid_audio_fork {self.uuid} start {self.ws_url} mono 16000 {metadata_str}"
        
        result = self.con.api(cmd)
        if not result or result.getBody().strip() != "+OK Success":
            print(f"Failed to start audio fork: {result.getBody() if result else 'No response'}")
            return False
            
        return True
        
    def handle_event(self, event):
        """处理接收到的ESL事件"""
        event_name = event.getHeader("Event-Name")
        event_subclass = event.getHeader("Event-Subclass")
        
        if event_name == "CUSTOM" and event_subclass:
            if event_subclass == EVENT_CONNECT:
                self.on_connect(event)
            elif event_subclass == EVENT_CONNECT_FAILED:
                self.on_connect_failed(event)
            elif event_subclass == EVENT_DISCONNECT:
                self.on_disconnect(event)
            elif event_subclass == EVENT_ERROR:
                self.on_error(event)
            elif event_subclass == EVENT_MAINTENANCE:
                self.on_maintenance(event)
        elif event_name == "DTMF":
            self.handle_dtmf(event)
        elif event_name == "CHANNEL_ANSWER":
            self.handle_channel_answer(event)
            
    def run(self):
        """主事件循环"""
        print(f"Audio will be streamed to: {self.ws_url}")
        
        if not self.connect():
            return
            
        self.subscribe_events()
        
        try:
            while True:
                event = self.con.recvEvent()
                if event:
                    self.handle_event(event)
                else:
                    # 检查连接状态
                    if not self.con.connected():
                        print("Disconnected from FreeSWITCH")
                        break
        except KeyboardInterrupt:
            print("\nShutting down...")
        finally:
            if self.con and self.con.connected():
                self.con.disconnect()
                print("Disconnected from FreeSWITCH")

def main():
    parser = argparse.ArgumentParser(description='Audio Fork - Stream audio to WebSocket server')
    parser.add_argument('ws_url', help='WebSocket server URL (e.g., ws://localhost:8080)')
    parser.add_argument('--host', default='localhost', help='FreeSWITCH host (default: localhost)')
    parser.add_argument('--port', type=int, default=8021, help='FreeSWITCH ESL port (default: 8021)')
    parser.add_argument('--password', default='ClueCon', help='FreeSWITCH ESL password (default: ClueCon)')
    
    args = parser.parse_args()
    
    if not args.ws_url:
        print("Error: must specify WebSocket server URL")
        sys.exit(1)
        
    # 检查ESL模块
    try:
        from ESL import ESLconnection
    except ImportError:
        print("Error: ESL module not found. Please install python3-esl package")
        print("On Debian/Ubuntu: apt-get install python3-esl")
        print("Or build from FreeSWITCH source: make mod_event_socket-install-python3")
        sys.exit(1)
        
    app = AudioForkSession(args.ws_url, args.host, args.port, args.password)
    app.run()

if __name__ == "__main__":
    main()