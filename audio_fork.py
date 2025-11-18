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
import logging
from datetime import datetime
from collections import defaultdict
from ESL import ESLconnection
import librosa
import os

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
        
        # 配置日志
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        self.logger = logging.getLogger(__name__)
        
        # 音频播放队列和线程 - 参考freeswitch_audio_monitor.py的实现
        self.audio_queues = defaultdict(queue.Queue)  # 每个UUID对应一个音频队列
        self.playback_threads = defaultdict(threading.Thread)  # 每个UUID对应一个播放线程
        self.playback_status = defaultdict(dict)  # 播放状态跟踪
        self.queue_lock = threading.RLock()  # 队列操作锁（可重入锁）
        
    def connect(self):
        """连接到FreeSWITCH ESL"""
        self.logger.info(f"Connecting to FreeSWITCH at {self.host}:{self.port}")
        self.con = ESLconnection(self.host, str(self.port), self.password)
        
        if not self.con.connected():
            self.logger.error(f"Failed to connect to FreeSWITCH: {self.con.getInfo()}")
            return False
            
        self.logger.info("Connected to FreeSWITCH")
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
        
    def create_audio_queue_for_session(self, uuid: str):
        """为指定会话创建音频播放队列"""
        with self.queue_lock:
            if uuid not in self.audio_queues:
                self.audio_queues[uuid] = queue.Queue()
                self.playback_status[uuid] = {
                    'playing': False,
                    'queue_size': 0,
                    'current_file': None,
                    'last_play_time': None
                }
                self.logger.info(f"Created audio queue for session: {uuid}")
    
    def start_playback_thread(self, uuid: str):
        """启动音频播放处理线程"""
        with self.queue_lock:
            if uuid not in self.playback_status or not self.playback_status[uuid]['playing']:
                self.playback_status[uuid]['playing'] = True
                
                # 启动播放线程
                thread = threading.Thread(target=self.audio_playback_worker, args=(uuid,), daemon=True)
                thread.start()
                self.playback_threads[uuid] = thread
                self.logger.info(f"Started audio playback thread for session: {uuid}")
            
    def stop_playback_thread(self, uuid: str = None):
        """停止音频播放处理线程"""
        if uuid:
            # 停止指定会话的播放线程
            self.stop_audio_queue(uuid)
        else:
            # 停止所有会话的播放线程
            for session_uuid in list(self.audio_queues.keys()):
                self.stop_audio_queue(session_uuid)
    
    def stop_audio_queue(self, uuid: str):
        """停止指定会话的音频播放队列"""
        try:
            with self.queue_lock:
                if uuid in self.audio_queues:
                    # 添加停止信号到队列
                    self.audio_queues[uuid].put(None)
                    
                    # 清空队列中剩余的项目
                    while not self.audio_queues[uuid].empty():
                        try:
                            self.audio_queues[uuid].get_nowait()
                            self.audio_queues[uuid].task_done()
                        except queue.Empty:
                            break
                    
                    # 标记为非播放状态
                    if uuid in self.playback_status:
                        self.playback_status[uuid]['playing'] = False
                    
                    self.logger.info(f"Stopped audio queue for session: {uuid}")
                    
        except Exception as e:
            self.logger.error(f"Error stopping audio queue for {uuid}: {e}")
            
    def audio_playback_worker(self, uuid: str):
        """音频播放工作线程 - 参考freeswitch_audio_monitor.py的实现"""
        self.logger.info(f"Audio playback worker thread started for session: {uuid}")
        try:
            while True:
                try:
                    # 从队列获取音频播放任务（超时1秒，允许定期检查停止信号）
                    audio_item = self.audio_queues[uuid].get(timeout=1)
                    
                    # 检查是否为停止信号
                    if audio_item is None:
                        self.logger.info(f"Received stop signal for {uuid}, stopping playback thread")
                        self.audio_queues[uuid].task_done()  # 标记停止信号任务完成
                        break  # 退出循环
                    
                    self.logger.debug(f"Audio item: {audio_item}")
                    
                    try:
                        # 更新播放状态
                        with self.queue_lock:
                            self.playback_status[uuid]['current_file'] = audio_item['file']
                            self.playback_status[uuid]['last_play_time'] = datetime.now()
                            self.playback_status[uuid]['queue_size'] = self.audio_queues[uuid].qsize()
                        
                        # 执行音频播放
                        if audio_item['audioContentType'] == 'wav' or audio_item['audioContentType'] == 'wave':
                            self.play_wav_audio(audio_item['file'], uuid)
                        # 等待播放完成 - 这是关键，确保顺序播放
                        # self.wait_for_playback_completion(audio_item['file'])
                        
                    except Exception as e:
                        self.logger.error(f"Error executing audio playback for {uuid}: {e}")
                    finally:
                        # 无论播放成功与否，都要标记任务完成
                        self.audio_queues[uuid].task_done()
                        
                except queue.Empty:
                    # 队列空了，继续等待
                    continue
                except Exception as e:
                    self.logger.error(f"Error in audio playback worker for {uuid}: {e}")
                    continue
        finally:
            # 清理播放状态
            with self.queue_lock:
                self.playback_status[uuid]['playing'] = False
                self.playback_status[uuid]['current_file'] = None
            self.logger.info(f"Audio playback worker thread stopped for session: {uuid}")
        
    def wait_for_playback_completion(self, file_path: str):
        """等待音频播放完成"""
        try:
            # 从配置获取默认播放时长
            wait_time = 2.0
           
            if os.path.exists(file_path):
                try:
                    # 尝试使用librosa获取准确的音频时长
                    duration = librosa.get_duration(filename=file_path)
                    wait_time = max(duration, 0.5)  # 最小0.5秒
                    self.logger.debug(f"Audio duration from librosa: {duration:.2f}s")
                except ImportError:
                    # 如果没有librosa，使用文件大小估算
                    file_size = os.path.getsize(file_path)
                    estimated_duration = file_size / (24000 * 1 * 2)  # 24kHz, mono, 16bit
                    wait_time = max(estimated_duration, 0.5)  # 最小0.5秒
                    self.logger.debug(f"Estimated duration from file size: {estimated_duration:.2f}s")
                except Exception as e:
                    self.logger.warning(f"Failed to get audio duration, using default: {e}")
            
            # 限制最大等待时间
            wait_time = min(wait_time, 15.0)
            
            self.logger.info(f"Waiting {wait_time:.2f} seconds for audio playback completion: {os.path.basename(file_path)}")
            time.sleep(wait_time)
            
        except Exception as e:
            self.logger.error(f"Error waiting for playback completion: {e}")
            
    def play_raw_audio(self, audio_file, sample_rate):
        """播放原始音频文件"""
        self.logger.info(f"Playing raw audio file: {audio_file} (sample rate: {sample_rate})")
        
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
                self.logger.info(f"Trying playback method {i}...")
                result = method()
                
                if result:
                    result_body = result.getBody() if hasattr(result, 'getBody') else str(result)
                    self.logger.info(f"Method {i} succeeded: {result_body}")
                    return
                else:
                    self.logger.warning(f"Method {i} returned None")
                    
            except Exception as e:
                self.logger.error(f"Method {i} failed: {e}")
                
        self.logger.error("All playback methods failed for raw audio")
        
    def play_wav_audio(self, audio_file,uuid):
        """播放WAV音频文件"""
        self.logger.info(f"Playing WAV audio file: {audio_file} for UUID: {uuid}")
        
        try:
            result = self.con.execute("playback", audio_file, uuid)
            if result:
                self.logger.info(f"WAV playback result: {result}")
            else:
                self.logger.warning("WAV playback returned None")
                
        except Exception as e:
            self.logger.error(f"Exception during WAV playback: {e}")
        
    def on_connect(self, event):
        """连接成功事件处理"""
        self.logger.info("successfully connected")
        
    def on_connect_failed(self, event):
        """连接失败事件处理"""
        self.logger.error("connection failed")
        
    def on_disconnect(self, event):
        """断开连接事件处理"""
        self.logger.info("far end dropped connection")
        
    def on_error(self, event):
        """错误事件处理"""
        self.logger.error(f"got error: {event.getBody()}")
        
    def on_maintenance(self, event):
        """维护事件处理"""
        self.logger.info(f"got event: {event.getBody()}")
        
    def handle_play_audio(self, event):
        """处理播放音频事件 - 参考freeswitch_audio_monitor.py的实现"""
        try:
            event_body = event.getBody()
            if not event_body:
                self.logger.warning("No event body in play_audio event")
                return
                
            # 从事件中获取UUID
            event_uuid = event.getHeader("Unique-ID")
            if not event_uuid:
                self.logger.error("No UUID found in play_audio event")
                return
                
            data = json.loads(event_body)
            audio_content_type = data.get('audioContentType')
            sample_rate = data.get('sampleRate')
            text_content = data.get('textContent')
            audio_file = data.get('file')
            
            self.logger.info(f"Received play_audio event for UUID {event_uuid}:")
            self.logger.debug(f"  Audio content type: {audio_content_type}")
            self.logger.debug(f"  Sample rate: {sample_rate}")
            self.logger.debug(f"  Text content: {text_content}")
            self.logger.debug(f"  Audio file: {audio_file}")
            
            if audio_file and event_uuid:
                # 确保为当前会话创建音频队列
                self.create_audio_queue_for_session(event_uuid)
                
                # 创建音频播放任务
                audio_item = {
                    'file': audio_file,
                    'priority': 0,  # 默认优先级
                    'timestamp': datetime.now(),
                    'uuid': event_uuid,
                    'audioContentType': audio_content_type,
                    'sampleRate': sample_rate,
                    'textContent': text_content
                }
                
                # 将任务加入播放队列
                with self.queue_lock:
                    # 检查队列大小限制
                    max_queue_size = 100  # 默认最大队列大小
                    if self.audio_queues[event_uuid].qsize() >= max_queue_size:
                        self.logger.warning(f"Audio queue for {event_uuid} is full (size: {self.audio_queues[event_uuid].qsize()}), dropping oldest item")
                        try:
                            # 移除最旧的项目
                            self.audio_queues[event_uuid].get_nowait()
                        except queue.Empty:
                            pass
                    
                    self.audio_queues[event_uuid].put(audio_item)
                    self.playback_status[event_uuid]['queue_size'] = self.audio_queues[event_uuid].qsize()
                
                self.logger.info(f"Added audio to queue for {event_uuid}: {audio_file} (queue size: {self.playback_status[event_uuid]['queue_size']})")
                
                # 如果当前没有在播放，启动播放线程
                if not self.playback_status[event_uuid]['playing']:
                    self.logger.info(f"Starting playback thread for {event_uuid}")
                    self.start_playback_thread(event_uuid)
                    
            else:
                self.logger.error("Missing audio file path or UUID")
                
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse play_audio event JSON: {e}")
        except Exception as e:
            self.logger.error(f"Error handling play_audio event: {e}")
            
    def handle_kill_audio(self, event):
        """处理停止音频事件 - 参考freeswitch_audio_monitor.py的实现"""
        try:
            self.logger.info("Received kill_audio event, stopping audio playback")
            
            # 从事件中获取UUID
            event_uuid = event.getHeader("Unique-ID")
            if event_uuid:
                # 停止特定会话的音频队列
                self.stop_audio_queue(event_uuid)
            else:
                # 如果没有指定UUID，停止所有会话的音频队列
                for uuid in list(self.audio_queues.keys()):
                    self.stop_audio_queue(uuid)
            
            self.logger.info("Audio playback stopped successfully")
            
        except Exception as e:
            self.logger.error(f"Error handling kill_audio event: {e}")
        
    def handle_dtmf(self, event):
        """处理DTMF事件"""
        self.logger.info(f"Received DTMF event: {event.getBody()}")
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
        
        self.logger.info(f"Channel answered: {self.uuid}")
        
        # 为当前会话创建音频队列
        self.create_audio_queue_for_session(self.uuid)
        
        self.init_audio_fork(call_id, to_uri, from_uri)

    def cleanup_session(self, uuid: str):
        """清理会话资源"""
        with self.queue_lock:
            if uuid in self.audio_queues:
                del self.audio_queues[uuid]
            if uuid in self.playback_threads:
                del self.playback_threads[uuid]
            if uuid in self.playback_status:
                del self.playback_status[uuid]

    def handle_hangup(self, event):
        """处理挂断事件"""
        self.logger.info(f"Received hangup event: {event.getBody()}")
        
        # 获取UUID并清理相关资源
        event_uuid = event.getHeader("Unique-ID")
        if event_uuid:
            self.stop_audio_queue(event_uuid)
            self.cleanup_session(event_uuid)
            self.logger.info(f"Cleaned up resources for UUID {event_uuid}")
        else:
            self.logger.warning("No UUID found in hangup event, stopping all audio")
            # 停止所有音频
            with self.queue_lock:
                for uuid in list(self.audio_queues.keys()):
                    self.stop_audio_queue(uuid)
                    self.cleanup_session(uuid)
            self.logger.info("All audio stopped and resources cleaned up")
            
    def handle_hangup_complete(self, event):
        """处理挂断完成事件"""
        self.logger.info(f"Received hangup complete event: {event.getBody()}")
        
        # 获取UUID并清理相关资源
        event_uuid = event.getHeader("Unique-ID")
        if event_uuid:
            self.stop_audio_queue(event_uuid)
            self.cleanup_session(event_uuid)
            self.logger.info(f"Cleaned up resources for UUID {event_uuid}")
        else:
            self.logger.warning("No UUID found in hangup complete event, stopping all audio")
            # 停止所有音频
            with self.queue_lock:
                for uuid in list(self.audio_queues.keys()):
                    self.stop_audio_queue(uuid)
                    self.cleanup_session(uuid)
            self.logger.info("All audio stopped and resources cleaned up")
        
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
            self.logger.error(f"Failed to start audio fork: {result.getBody() if result else 'No response'}")
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
        elif event_name == "CHANNEL_HANGUP":
            self.handle_hangup(event)
        elif event_name == "CHANNEL_HANGUP_COMPLETE":
            self.handle_hangup_complete(event)
            
    def run(self):
        """主事件循环"""
        self.logger.info(f"Audio will be streamed to: {self.ws_url}")
        
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
                        self.logger.warning("Disconnected from FreeSWITCH")
                        break
        except KeyboardInterrupt:
            self.logger.info("Shutting down...")
        finally:
            # 停止所有播放线程
            self.stop_playback_thread()
            
            if self.con and self.con.connected():
                self.con.disconnect()
                self.logger.info("Disconnected from FreeSWITCH")

def main():
    parser = argparse.ArgumentParser(description='Audio Fork - Stream audio to WebSocket server')
    parser.add_argument('ws_url', help='WebSocket server URL (e.g., ws://localhost:8080)')
    parser.add_argument('--host', default='localhost', help='FreeSWITCH host (default: localhost)')
    parser.add_argument('--port', type=int, default=8021, help='FreeSWITCH ESL port (default: 8021)')
    parser.add_argument('--password', default='ClueCon', help='FreeSWITCH ESL password (default: ClueCon)')
    
    args = parser.parse_args()
    
    if not args.ws_url:
        logger = logging.getLogger('AudioFork')
        logger.error("Error: must specify WebSocket server URL")
        sys.exit(1)
        
    # 检查ESL模块
    try:
        from ESL import ESLconnection
    except ImportError:
        logger = logging.getLogger('AudioFork')
        logger.error("Error: ESL module not found. Please install python3-esl package")
        logger.error("On Debian/Ubuntu: apt-get install python3-esl")
        logger.error("Or build from FreeSWITCH source: make mod_event_socket-install-python3")
        sys.exit(1)
        
    app = AudioForkSession(args.ws_url, args.host, args.port, args.password)
    app.run()

if __name__ == "__main__":
    main()