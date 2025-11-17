#!/usr/bin/env python3
"""
audio_fork.py - Python version of audio_fork.js
Freeswitch audio streaming application using ESL
"""

import sys
import json
import argparse
import threading
import queue
import time
import os
from ESL import ESLconnection

try:
    import librosa
    LIBROSA_AVAILABLE = True
except ImportError:
    LIBROSA_AVAILABLE = False

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
        
        # 音频播放队列和线程
        self.playback_queue = queue.Queue()
        self.playback_thread = None
        self.playback_active = False
        self.current_playback_file = None
        
    def connect(self):
        """连接到FreeSWITCH ESL"""
        print(f"Connecting to FreeSWITCH at {self.host}:{self.port}")
        try:
            self.con = ESLconnection(self.host, str(self.port), self.password)
            
            if not self.con.connected():
                error_info = self.con.getInfo() if hasattr(self.con, 'getInfo') else "Unknown error"
                print(f"Failed to connect to FreeSWITCH: {error_info}")
                return False
            
            print("Connected to FreeSWITCH")
            return True
            
        except Exception as e:
            print(f"Exception during connection: {e}")
            return False
            
    def wait_for_playback_completion(self, audio_file):
        """等待音频播放完成"""
        try:
            # 默认等待时间
            wait_time = 2.0
            
            # 根据文件大小估算播放时长
            if os.path.exists(audio_file):
                try:
                    # 尝试使用librosa获取准确的音频时长
                    if LIBROSA_AVAILABLE:
                        duration = librosa.get_duration(filename=audio_file)
                        wait_time = max(duration, 0.5)  # 最小0.5秒
                        print(f"Audio duration from librosa: {duration:.2f}s")
                    else:
                        # 如果没有librosa，使用文件大小估算
                        file_size = os.path.getsize(audio_file)
                        # 估算：24kHz, mono, 16bit (2 bytes per sample)
                        estimated_duration = file_size / (24000 * 2)
                        wait_time = max(estimated_duration, 0.5)  # 最小0.5秒
                        print(f"Estimated duration from file size: {estimated_duration:.2f}s")
                except Exception as e:
                    print(f"Failed to get audio duration, using default: {e}")
            
            # 限制最大等待时间
            wait_time = min(wait_time, 15.0)
            
            print(f"Waiting {wait_time:.2f} seconds for audio playback completion: {os.path.basename(audio_file)}")
            time.sleep(wait_time)
            
        except Exception as e:
            print(f"Error waiting for playback completion: {e}")
            
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
        
    def start_playback_thread(self):
        """启动音频播放处理线程"""
        if self.playback_thread is None or not self.playback_thread.is_alive():
            self.playback_active = True
            self.playback_thread = threading.Thread(target=self.playback_worker, daemon=True)
            self.playback_thread.start()
            print("Audio playback thread started")
            
    def stop_playback_thread(self):
        """停止音频播放处理线程"""
        self.playback_active = False
        # 发送停止信号到队列
        self.playback_queue.put(None)
        if self.playback_thread and self.playback_thread.is_alive():
            self.playback_thread.join(timeout=5)
            print("Audio playback thread stopped")
            
    def playback_worker(self):
        """音频播放工作线程"""
        print("Playback worker thread started")
        while self.playback_active:
            try:
                # 从队列获取音频播放任务（超时1秒，允许定期检查停止信号）
                playback_task = self.playback_queue.get(timeout=1)
                
                if playback_task is None:  # 停止信号
                    break
                    
                if not self.playback_active:  # 检查是否还需要继续处理
                    break
                    
                # 处理音频播放任务
                self.process_playback_task(playback_task)
                
            except queue.Empty:
                # 队列为空，继续循环
                continue
            except Exception as e:
                print(f"Error in playback worker: {e}")
                
        print("Playback worker thread stopped")
        
    def process_playback_task(self, task):
        """处理单个音频播放任务"""
        audio_file = task.get('file')
        audio_content_type = task.get('audioContentType')
        sample_rate = task.get('sampleRate')
        
        if not audio_file or not self.uuid:
            print("Missing audio file or UUID for playback")
            return
            
        self.current_playback_file = audio_file
        print(f"Processing playback task: {audio_file} (type: {audio_content_type}, rate: {sample_rate})")
        
        try:
            if audio_content_type == 'raw':
                success = self.play_raw_audio(audio_file, sample_rate)
            elif audio_content_type == 'wave' or audio_content_type == 'wav':
                success = self.play_wav_audio(audio_file)
            else:
                print(f"Unsupported audio content type: {audio_content_type}")
                success = False
                
            # 等待播放完成，确保顺序播放
            if success:
                self.wait_for_playback_completion(audio_file)
                
        except Exception as e:
            print(f"Exception during playback task processing: {e}")
        finally:
            self.current_playback_file = None
            
    def play_raw_audio(self, audio_file, sample_rate):
        """播放原始音频文件"""
        print(f"Playing raw audio file: {audio_file} (sample rate: {sample_rate})")
        
        # 尝试多种播放方法
        methods = [
            # 方法1: 使用uuid_broadcast
            lambda: self.con.api(f"uuid_broadcast {self.uuid} {audio_file}"),
            
            # 方法2: 使用playback命令（设置采样率）
            lambda: self.con.execute("set", f"playback_sample_rate={sample_rate}", self.uuid) and 
                   self.con.execute("playback", audio_file, self.uuid),
                   
            # 方法3: 使用uuid_displace
            lambda: self.con.api(f"uuid_displace {self.uuid} start {audio_file}"),
            
            # 方法4: 简单的playback
            lambda: self.con.execute("playback", audio_file, self.uuid)
        ]
        
        for i, method in enumerate(methods, 1):
            try:
                print(f"Trying playback method {i}...")
                result = method()
                
                if result:
                    result_body = result.getBody() if hasattr(result, 'getBody') else str(result)
                    print(f"Method {i} succeeded: {result_body}")
                    return True
                else:
                    print(f"Method {i} returned None")
                    
            except Exception as e:
                print(f"Method {i} failed: {e}")
                
        print("All playback methods failed for raw audio")
        return False
        
    def play_wav_audio(self, audio_file):
        """播放WAV音频文件"""
        print(f"Playing WAV audio file: {audio_file}")
        
        try:
            result = self.con.execute("playback", audio_file, self.uuid)
            if result:
                print(f"WAV playback result: {result.getBody()}")
                return True
            else:
                print("WAV playback returned None")
                return False
                
        except Exception as e:
            print(f"Exception during WAV playback: {e}")
            return False
        
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
        """处理播放音频事件 - 现在将音频任务加入队列"""
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
                # 创建音频播放任务
                playback_task = {
                    'file': audio_file,
                    'audioContentType': audio_content_type,
                    'sampleRate': sample_rate,
                    'textContent': text_content,
                    'timestamp': time.time()
                }
                
                # 将任务加入播放队列
                try:
                    self.playback_queue.put(playback_task, block=False)
                    print(f"Added playback task to queue. Queue size: {self.playback_queue.qsize()}")
                except queue.Full:
                    print("Playback queue is full, dropping audio task")
                    
            else:
                print("Missing audio file path or UUID")
                
        except json.JSONDecodeError as e:
            print(f"Failed to parse play_audio event JSON: {e}")
        except Exception as e:
            print(f"Error handling play_audio event: {e}")
            
    def handle_kill_audio(self, event):
        """处理停止播放音频事件 - 清空队列并停止当前播放"""
        print("Received kill_audio event - stopping current playback")
        
        # 清空播放队列
        while not self.playback_queue.empty():
            try:
                self.playback_queue.get_nowait()
            except queue.Empty:
                break
        print(f"Cleared playback queue. Current queue size: {self.playback_queue.qsize()}")
        
        # 停止当前播放
        if self.uuid:
            try:
                # 尝试多种停止播放的方法
                methods = [
                    lambda: self.con.execute("stop", "", self.uuid),
                    lambda: self.con.api(f"uuid_broadcast {self.uuid} stop"),
                    lambda: self.con.api(f"uuid_displace {self.uuid} stop")
                ]
                
                for i, method in enumerate(methods, 1):
                    try:
                        result = method()
                        if result:
                            print(f"Stop method {i} succeeded: {result.getBody() if hasattr(result, 'getBody') else str(result)}")
                            break
                    except Exception as e:
                        print(f"Stop method {i} failed: {e}")
                        
            except Exception as e:
                print(f"Exception during stop playback: {e}")
                
        print("Playback stopped")
        
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
        
        # 启动音频播放线程
        self.start_playback_thread()
        
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
            print("Failed to connect to FreeSWITCH, exiting...")
            return
            
        print("Successfully connected, subscribing to events...")
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
            # 停止播放线程
            self.stop_playback_thread()
            
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