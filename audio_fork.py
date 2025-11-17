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
            EVENT_ERROR, EVENT_MAINTENANCE, EVENT_PLAY_AUDIO, EVENT_KILL_AUDIO
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
        
    def handle_play_audio(self, event):
        """处理播放音频事件"""
        try:
            event_body = event.getBody()
            if not event_body:
                print("No event body in play_audio event")
                return
                
            data = json.loads(event_body)
            audio_content_type = data.get('audioContentType')
            sample_rate = data.get('sampleRate')
            text_content = data.get('textContent')
            audio_file = data.get('file')
            
            print(f"Received play_audio event:")
            print(f"  Audio content type: {audio_content_type}")
            print(f"  Sample rate: {sample_rate}")
            print(f"  Text content: {text_content}")
            print(f"  Audio file: {audio_file}")
            
            if audio_file and self.uuid:
                # 播放音频文件给caller
                if audio_content_type == 'raw':
                    # 对于raw音频文件，使用playback命令播放，指定采样率
                    print(f"Playing raw audio file: {audio_file}")
                    try:
                        if sample_rate:
                            # 先设置采样率变量，再播放
                            print(f"Setting sample rate to {sample_rate} Hz")
                            set_result = self.con.execute("set", f"playback_sample_rate={sample_rate}")
                            if set_result:
                                print(f"Set command result: {set_result.getBody()}")
                            else:
                                print("Set command returned None")
                        
                        # 执行播放命令
                        print(f"Executing playback command for file: {audio_file}")
                        result = self.con.execute("playback", audio_file, self.uuid)
                        
                        if result.getBody() != None:
                            print(f"Playback result: {result.getBody()}")
                        else:
                            print("Playback command returned None - trying alternative methods")
                            # 尝试使用api命令
                            api_cmd = f"uuid_broadcast {self.uuid} {audio_file}"
                            print(f"Trying API command: {api_cmd}")
                            api_result = self.con.api(api_cmd)
                            if api_result:
                                print(f"API broadcast result: {api_result.getBody()}")
                            else:
                                print("API command also failed")
                                
                            # 尝试使用uuid_displace
                            print("Trying uuid_displace command...")
                            displace_cmd = f"uuid_displace {self.uuid} start {audio_file}"
                            displace_result = self.con.api(displace_cmd)
                            if displace_result:
                                print(f"Displace result: {displace_result.getBody()}")
                            else:
                                print("Displace command also failed")
                                
                    except Exception as e:
                        print(f"Exception during playback: {e}")
                        
                elif audio_content_type == 'wave' or audio_content_type == 'wav':
                    # 对于wav文件，直接播放
                    print(f"Playing wav audio file: {audio_file}")
                    try:
                        result = self.con.execute("playback", audio_file)
                        if result:
                            print(f"Playback result: {result.getBody()}")
                        else:
                            print("WAV playback returned None")
                    except Exception as e:
                        print(f"Exception during WAV playback: {e}")
                else:
                    print(f"Unsupported audio content type: {audio_content_type}")
                                            
            else:
                print("Missing audio file path or UUID")
                
        except json.JSONDecodeError as e:
            print(f"Failed to parse play_audio event JSON: {e}")
        except Exception as e:
            print(f"Error handling play_audio event: {e}")
            
    def handle_kill_audio(self, event):
        """处理停止播放音频事件"""
        print("Received kill_audio event - stopping current playback")
        if self.uuid:
            # 停止当前播放
            result = self.con.execute("stop", "", self.uuid)
            if result:
                print(f"Stop playback result: {result.getBody()}")
        
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
        # self.con.execute("playback", "silence_stream://1000", self.uuid)
        
        # 使用Google TTS播放欢迎消息
        # tts_text = "Hi there. Please go ahead and make a recording and then hangup"
        # self.con.execute("speak", f"google_tts:en-GB-Wavenet-A:{tts_text}", self.uuid)
        
        # 启动音频流转发
        metadata_str = json.dumps(metadata)
        cmd = f"uuid_audio_fork {self.uuid} start {self.ws_url} mono 16000"
        
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
            elif event_subclass == EVENT_PLAY_AUDIO:
                self.handle_play_audio(event)
            elif event_subclass == EVENT_KILL_AUDIO:
                self.handle_kill_audio(event)
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