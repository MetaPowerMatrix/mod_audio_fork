#!/usr/bin/env python3
"""
FreeSWITCH Audio Stream Monitor
自动监听FreeSWITCH事件并启动音频流转发
"""

import socket
import time
import json
import logging
import threading
import configparser
import signal
import sys
import queue
from datetime import datetime
from typing import Dict, Optional
from collections import defaultdict
import os
import vad_utils
import librosa
import numpy as np

class FreeSWITCHEventSocket:
    """FreeSWITCH Event Socket 客户端"""
    
    def __init__(self, host='localhost', port=8021, password='ClueCon'):
        self.host = host
        self.port = port
        self.password = password
        self.socket = None
        self.connected = False
        self.running = False
        
    def connect(self) -> bool:
        """连接到FreeSWITCH Event Socket"""
        try:
            logging.info(f"Attempting to connect to {self.host}:{self.port}")
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(30)
            self.socket.connect((self.host, self.port))
            logging.info("Socket connected successfully")
            
            # 读取欢迎消息
            welcome = self.socket.recv(1024).decode()
            logging.info(f"FreeSWITCH welcome: {welcome.strip()}")
            
            # 认证
            auth_cmd = f'auth {self.password}\n\n'
            logging.info(f"Sending auth command: {auth_cmd.strip()}")
            self.socket.send(auth_cmd.encode())
            auth_response = self.socket.recv(1024).decode()
            logging.info(f"Auth response: {auth_response.strip()}")

            if 'Reply-Text: +OK accepted' in auth_response:
                self.connected = True
                logging.info("Successfully authenticated with FreeSWITCH")
                return True
            else:
                logging.error(f"Authentication failed: {auth_response}")
                return False
                
        except Exception as e:
            logging.error(f"Failed to connect to FreeSWITCH: {e}")
            return False
    
    def subscribe_events(self, events: list) -> bool:
        """订阅事件"""
        try:
            for event in events:
                cmd = f'event plain {event}\n\n'
                self.socket.send(cmd.encode())
                response = self.socket.recv(1024).decode()
                logging.info(f"Subscribed to {event}: {response.strip()}")
                if '+OK' not in response:
                    logging.warning(f"Unexpected response for {event}: {response}")
            return True
        except Exception as e:
            logging.error(f"Failed to subscribe to events: {e}")
            return False
    
    def execute_api(self, command: str) -> str:
        """执行API命令"""
        try:
            cmd = f'api {command}\n\n'
            self.socket.send(cmd.encode())
            response = self.socket.recv(4096).decode()
            return response
        except Exception as e:
            logging.error(f"Failed to execute API command '{command}': {e}")
            return ""
    
    def listen_events(self, callback):
        """监听事件"""
        self.running = True
        buffer = ""
        
        while self.running:
            try:
                data = self.socket.recv(8192).decode()
                if not data:
                    logging.warning("Connection lost")
                    break
                    
                buffer += data
                logging.debug(f"DEBUG: Received data chunk: {len(data)} bytes")
                
                # 处理完整的事件消息
                while '\n\n' in buffer:
                    event_data, buffer = buffer.split('\n\n', 1)
                    if event_data.strip():
                        logging.debug(f"DEBUG: Processing event: {event_data[:100]}...")
                        callback(event_data)
                        
            except socket.timeout:
                continue
            except Exception as e:
                logging.error(f"Error listening to events: {e}")
                break
    
    def disconnect(self):
        self.running = False
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
        self.connected = False

class AudioStreamManager:
    """音频流管理器"""
    
    def __init__(self, config):
        self.config = config
        self.active_streams = {}  # uuid -> stream_info
        self.fs_client = None
        # self.uuid = None
        # self.wait_for_json = False
        self.audio_queue = queue.Queue() # 音频播放队列
        self.playback_threads = defaultdict(threading.Thread) # 每个UUID对应一个播放线程
        self.audio_queues = defaultdict(queue.Queue)  # 每个UUID对应一个音频队列
        self.playback_status = defaultdict(dict)  # 播放状态跟踪
        self.queue_lock = threading.RLock()  # 队列操作锁（可重入锁）
        
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
                logging.info(f"Created audio queue for session: {uuid}")
    
    def add_audio_to_queue(self, uuid: str, audio_file: str, priority: int = 0):
        """添加音频文件到播放队列"""
        with self.queue_lock:
            if uuid not in self.audio_queues:
                self.create_audio_queue_for_session(uuid)
                        
            # 检查队列大小限制
            max_queue_size = self.config.getint('audio_stream', 'max_queue_size', fallback=10)  # 优化：降低队列大小限制
            if max_queue_size > 0 and self.audio_queues[uuid].qsize() >= max_queue_size:
                logging.warning(f"Audio queue for {uuid} is full (size: {self.audio_queues[uuid].qsize()}), dropping oldest item")
                try:
                    # 移除最旧的项目
                    self.audio_queues[uuid].get_nowait()
                except queue.Empty:
                    pass
            
            audio_item = {
                'file': audio_file,
                'priority': priority,
                'timestamp': datetime.now(),
                'uuid': uuid
            }
            
            self.audio_queues[uuid].put(audio_item)
            self.playback_status[uuid]['queue_size'] = self.audio_queues[uuid].qsize()
            
            logging.info(f"Added audio to queue for {uuid}: {audio_file} (queue size: {self.playback_status[uuid]['queue_size']})")
            
            # 如果当前没有在播放，启动播放线程
            if not self.playback_status[uuid]['playing']:
                self.start_audio_playback_thread(uuid)
    
    def start_audio_playback_thread(self, uuid: str):
        """启动音频播放线程"""
        with self.queue_lock:
            self.playback_status[uuid]['playing'] = True
            
        # 启动播放线程
        thread = threading.Thread(target=self.audio_playback_worker, args=(uuid,))
        thread.daemon = True
        thread.start()
        self.playback_threads[uuid] = thread
        logging.info(f"Started audio playback thread for session: {uuid}")
    
    def audio_playback_worker(self, uuid: str):
        """音频播放工作线程"""
        try:
            # 从配置获取队列超时时间
            queue_timeout = self.config.getfloat('audio_stream', 'queue_timeout', fallback=5.0)
            
            while True:
                try:
                    # 检查会话是否还活跃
                    # if not self.check_session_active(uuid):
                    #     logging.info(f"Session {uuid} no longer active, stopping playback thread")
                    #     break
                    
                    # 从队列获取音频项目
                    audio_item = self.audio_queues[uuid].get(timeout=queue_timeout)
                    
                    # 检查是否为停止信号
                    if audio_item is None:
                        logging.info(f"Received stop signal for {uuid}, stopping playback thread")
                        self.audio_queues[uuid].task_done()  # 标记停止信号任务完成
                        break  # 退出循环
                    
                    logging.info(f"Audio item: {audio_item}")
                    
                    try:
                        # 更新播放状态
                        with self.queue_lock:
                            self.playback_status[uuid]['current_file'] = audio_item['file']
                            self.playback_status[uuid]['last_play_time'] = datetime.now()
                            self.playback_status[uuid]['queue_size'] = self.audio_queues[uuid].qsize()
                        
                        # 执行音频播放
                        self.execute_audio_playback(uuid, audio_item['file'])
                        
                    except Exception as e:
                        logging.error(f"Error executing audio playback for {uuid}: {e}")
                    finally:
                        # 无论播放成功与否，都要标记任务完成
                        self.audio_queues[uuid].task_done()
                    
                except queue.Empty:
                    # 队列空了，继续等待
                    continue
                except Exception as e:
                    logging.error(f"Error in audio playback worker for {uuid}: {e}")
                    continue
        finally:
            # 清理播放状态
            with self.queue_lock:
                self.playback_status[uuid]['playing'] = False
                self.playback_status[uuid]['current_file'] = None
            logging.info(f"Audio playback thread stopped for session: {uuid}")
    

    def calculate_rms(self, input_path, sr):
        audio_data, _ = librosa.load(input_path, sr=sr)
        return (np.sqrt(np.mean(audio_data**2)) > 0.02)

    def vad_check_audio_bytes_original(self, input_audio_vad_path, sr):
        try:
            with open(input_audio_vad_path,"rb") as f:
                temp_audio = f.read()
            dur_vad, vad_audio_bytes, time_vad = vad_utils.run_vad(temp_audio, sr)
            vad_threshold = 0.15  # 优化：降低阈值以减少正常语音被误判为静音
            
            # 添加详细的VAD调试日志
            rms_result = self.calculate_rms(input_audio_vad_path, sr)
            logging.info(f"VAD Debug: dur_vad={dur_vad:.3f}, vad_threshold={vad_threshold:.3f}")
            logging.info(f"VAD Debug: rms_check={rms_result}")
            
            if rms_result and dur_vad > vad_threshold:
                logging.info(f"VAD: Not silence, dur_vad={dur_vad:.3f}, vad_threshold={vad_threshold:.3f}")
                return True
                                
        except Exception as e:
            logging.error(f"VAD error: {e}")

        return False


    def execute_audio_playback(self, uuid: str, file_path: str):
        """执行音频播放"""
        try:
            # 优化：由于入队前已经进行VAD检测，这里直接播放
            # 注释掉重复的VAD检测以提高性能
            # if not self.vad_check_audio_bytes_original(file_path, 24000):
            #     logging.info(f"Playing audio file: silence audio -- skip")
            #     return

            logging.info(f"Playing audio file: {file_path} for UUID: {uuid} -- final")
            
            # 首先尝试使用 uuid_broadcast
            # chunk_size = "{STREAM_BUFFER_SIZE=20}"
            play_command = f"uuid_broadcast {uuid} {file_path}"
            try:
                response = self.fs_client.execute_api(play_command)
                # logging.info(f"Broadcast command executed: {response.strip()}")
                
                # 等待播放完成
                self.wait_for_playback_completion(uuid, file_path)
                
            except Exception as e:
                logging.error(f"Error executing broadcast command: {e}")
                # 尝试使用 uuid_displace 作为备选
                try:
                    alt_command = f"uuid_displace {uuid} start {file_path} 0 mux"
                    response = self.fs_client.execute_api(alt_command)
                    logging.info(f"Alternative displace command executed: {response.strip()}")
                    
                    # 等待播放完成
                    self.wait_for_playback_completion(uuid, file_path)
                    
                    # 停止displace
                    stop_command = f"uuid_displace {uuid} stop {file_path}"
                    self.fs_client.execute_api(stop_command)
                    
                except Exception as alt_e:
                    logging.error(f"Alternative playback also failed: {alt_e}")
                    
        except Exception as e:
            logging.error(f"Error in execute_audio_playback for {uuid}: {e}")
    
    def wait_for_playback_completion(self, uuid: str, file_path: str):
        """等待音频播放完成"""
        try:
            # 从配置获取默认播放时长
            wait_time = 2.0
           
            # 简单的启发式方法：根据文件大小估算
            import os
            if os.path.exists(file_path):
                try:
                    # 尝试使用librosa获取准确的音频时长
                    duration = librosa.get_duration(filename=file_path)
                    wait_time = max(duration, 0.5)  # 最小0.5秒
                    logging.debug(f"Audio duration from librosa: {duration:.2f}s")
                except ImportError:
                    # 如果没有librosa，使用文件大小估算
                    file_size = os.path.getsize(file_path)
                    estimated_duration = file_size / (24000 * 1 * 2)  # 24kHz, mono, 16bit
                    wait_time = max(estimated_duration, 0.5)  # 最小0.5秒
                    logging.debug(f"Estimated duration from file size: {estimated_duration:.2f}s")
                except Exception as e:
                    logging.warning(f"Failed to get audio duration, using default: {e}")
            
            # 限制最大等待时间
            wait_time = min(wait_time, 15.0)
            
            logging.info(f"Waiting {wait_time:.2f} seconds for audio playback completion: {os.path.basename(file_path)}")
            time.sleep(wait_time)
            
        except Exception as e:
            logging.error(f"Error waiting for playback completion: {e}")
    
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
                    
                    logging.info(f"Stopped audio queue for session: {uuid}")
                    
        except Exception as e:
            logging.error(f"Error stopping audio queue for {uuid}: {e}")
    
    def get_queue_status(self, uuid: str) -> Dict:
        """获取队列状态"""
        with self.queue_lock:
            if uuid in self.playback_status:
                status = self.playback_status[uuid].copy()
                status['queue_size'] = self.audio_queues[uuid].qsize() if uuid in self.audio_queues else 0
                return status
            return {}
    
    def clear_all_audio_queues(self):
        """清空所有音频队列"""
        with self.queue_lock:
            for uuid in list(self.audio_queues.keys()):
                self.stop_audio_queue(uuid)
            logging.info("Cleared all audio queues")
        
    def parse_event(self, event_data: str) -> Dict:
        """解析事件数据"""
        event = {}
        lines = event_data.split('\n')
        
        # 首先解析头部
        for i, line in enumerate(lines):
            if ':' in line:
                key, value = line.split(':', 1)
                key = key.strip()
                value = value.strip()
                event[key] = value
        
        return event
    
    def handle_channel_answer(self, event: Dict):
        """处理呼叫应答事件"""
        uuid = event.get('Unique-ID')
        caller_number = event.get('Caller-Caller-ID-Number', 'Unknown')
        callee_number = event.get('Caller-Destination-Number', 'Unknown')
        call_direction = event.get('Call-Direction', 'Unknown')
        
        if not uuid:
            return
            
        logging.info(f"Call answered: {caller_number} -> {callee_number} (UUID: {uuid}, Direction: {call_direction})")
        
        # 检查是否需要启动音频流
        if self.should_start_audio_stream(caller_number, callee_number, call_direction):
            # 对于外呼，如果配置为应答时启动
            if call_direction == 'outbound':
                start_trigger = self.config.get('outbound', 'start_trigger', fallback='bridge')
                if start_trigger == 'answer':
                    self.start_audio_stream(uuid, caller_number, callee_number, call_direction)
            else:
                # 呼入直接启动
                self.start_audio_stream(uuid, caller_number, callee_number, call_direction)
    
    def handle_channel_bridge(self, event: Dict):
        """处理通道桥接事件 - 外呼场景下用户接通"""
        uuid = event.get('Unique-ID')
        other_leg_uuid = event.get('Other-Leg-Unique-ID')
        caller_number = event.get('Caller-Caller-ID-Number', 'Unknown')
        callee_number = event.get('Caller-Destination-Number', 'Unknown')
        call_direction = event.get('Call-Direction', 'Unknown')
        
        if not uuid:
            return
            
        logging.info(f"Channel bridge: {caller_number} <-> {callee_number} (UUID: {uuid}, Other: {other_leg_uuid}, Direction: {call_direction})")
        
        # 对于外呼场景，在桥接时启动音频流
        if call_direction == 'outbound':
            start_trigger = self.config.get('outbound', 'start_trigger', fallback='bridge')
            if start_trigger == 'bridge':
                if self.should_start_audio_stream(caller_number, callee_number, call_direction):
                    start_delay = self.config.getfloat('outbound', 'start_delay', fallback=0)
                    if start_delay > 0:
                        # 延迟启动
                        threading.Timer(start_delay, self._delayed_start_audio_stream, 
                                      args=(uuid, caller_number, callee_number, call_direction)).start()
                        logging.info(f"Scheduled delayed audio stream start in {start_delay}s for UUID: {uuid}")
                    else:
                        self.start_audio_stream(uuid, caller_number, callee_number, call_direction)
                    
                    # 如果配置了同时监控对方通道
                    if other_leg_uuid and self.config.getboolean('audio_stream', 'monitor_both_legs', fallback=False):
                        if start_delay > 0:
                            threading.Timer(start_delay, self._delayed_start_audio_stream,
                                          args=(other_leg_uuid, callee_number, caller_number, 'outbound-leg')).start()
                        else:
                            self.start_audio_stream(other_leg_uuid, callee_number, caller_number, 'outbound-leg')
    
    def handle_channel_unbridge(self, event: Dict):
        """处理通道取消桥接事件"""
        uuid = event.get('Unique-ID')
        other_leg_uuid = event.get('Other-Leg-Unique-ID')
        
        # 停止相关的音频流
        if uuid and uuid in self.active_streams:
            logging.info(f"Channel unbridge, stopping audio stream for UUID: {uuid}")
            self.stop_audio_stream(uuid)
            
        if other_leg_uuid and other_leg_uuid in self.active_streams:
            logging.info(f"Channel unbridge, stopping audio stream for other leg UUID: {other_leg_uuid}")
            self.stop_audio_stream(other_leg_uuid)
    
    def handle_channel_hangup(self, event: Dict):
        """处理呼叫挂断事件"""
        uuid = event.get('Unique-ID')
        
        if uuid and uuid in self.active_streams:
            logging.info(f"Call hangup, stopping audio stream for UUID: {uuid}")
            self.stop_audio_stream(uuid)
    
    def check_session_active(self, uuid: str) -> bool:
        """检查session是否还活跃"""
        try:
            response = self.fs_client.execute_api(f"uuid_exists {uuid}")
            return "true" in response.lower()
        except Exception as e:
            logging.error(f"Error checking session {uuid}: {e}")
            return False
    
    def handle_audio_playback(self, body: str, uuid: str):
        # self.wait_for_json = False
        try:
            play_params = json.loads(body)
            file_path = play_params.get('file', None)
            priority = play_params.get('priority', 0)  # 播放优先级（默认为0）

            if file_path and uuid:
                logging.info(f"Received audio playback request: {file_path} for UUID: {uuid} with priority: {priority}")
                
                # 将音频文件添加到播放队列而不是直接播放
                # move这个临时音频文件到本目录下的audios子目录下
                import shutil
                shutil.move(file_path, os.path.join('audios', os.path.basename(file_path)))
                # 获取完整路径
                file_path = os.path.join(os.path.dirname(__file__), 'audios', os.path.basename(file_path))
                logging.info(f"DEBUG: file_path: {file_path}")

                # 优化：在入队前进行VAD检测，避免静音文件进入队列
                if self.vad_check_audio_bytes_original(file_path, 24000):
                    self.add_audio_to_queue(uuid, file_path, priority)
                else:
                    logging.info(f"Skipping silent audio before queuing: {file_path}")
                    return  # 直接跳过静音音频，不入队
                
                # 记录队列状态
                queue_status = self.get_queue_status(uuid)
                logging.info(f"Queue status for {uuid}: {queue_status}")
                
            else:
                logging.warning(f"Invalid playback data: missing file or UUID. UUID={uuid}, file_path={file_path}")
                
        except Exception as e:
            logging.error(f"Error in handle_audio_playback: {e}")
    
    def should_start_audio_stream(self, caller: str, callee: str, direction: str = 'Unknown') -> bool:
        """判断是否需要启动音频流"""
        # 根据配置决定是否启动音频流
        enabled_patterns = self.config.get('audio_stream', 'enabled_patterns', fallback='').split(',')
        disabled_patterns = self.config.get('audio_stream', 'disabled_patterns', fallback='').split(',')
        
        # 检查呼叫方向配置
        enabled_directions = self.config.get('audio_stream', 'enabled_directions', fallback='inbound,outbound').split(',')
        enabled_directions = [d.strip().lower() for d in enabled_directions if d.strip()]
        
        if direction != 'Unknown' and direction.lower() not in enabled_directions:
            logging.debug(f"Audio stream disabled for direction: {direction}")
            return False
        
        # 检查禁用模式
        for pattern in disabled_patterns:
            pattern = pattern.strip()
            if pattern and (pattern in caller or pattern in callee):
                logging.debug(f"Audio stream disabled by pattern: {pattern}")
                return False
        
        # 检查启用模式（如果配置了的话）
        if enabled_patterns and enabled_patterns[0]:
            for pattern in enabled_patterns:
                pattern = pattern.strip()
                if pattern and (pattern in caller or pattern in callee):
                    logging.debug(f"Audio stream enabled by pattern: {pattern}")
                    return True
            return False
        
        # 默认启用
        return True
    
    def _send_registration_message(self, uuid: str, registration_message: str):
        """发送注册消息的辅助方法"""
        try:
            # 等待一小段时间确保WebSocket连接已建立
            time.sleep(0.5)
            
            # 发送注册消息
            cmd = f'uuid_audio_stream {uuid} send_text {registration_message}'
            logging.info(f"Sending registration message: {cmd}")
            
            response = self.fs_client.execute_api(cmd)
            
            if '+OK' in response:
                logging.info(f"Successfully sent registration message for UUID: {uuid}")
            else:
                logging.error(f"Failed to send registration message: {response}")
                
        except Exception as e:
            logging.error(f"Error sending registration message for {uuid}: {e}")
    
    def start_audio_stream(self, uuid: str, caller: str, callee: str, direction: str = 'Unknown'):
        """启动音频流"""
        try:
            # 避免重复启动
            if uuid in self.active_streams:
                logging.warning(f"Audio stream already exists for UUID: {uuid}")
                return
            
            # 检查session是否还活跃
            # if not self.check_session_active(uuid):
            #     logging.error(f"Session {uuid} is not active, cannot start audio stream")
            #     return
                
            # 设置通道变量
            channel_vars = {
                'STREAM_BUFFER_SIZE': self.config.get('audio_stream', 'buffer_size', fallback='20'),
                'STREAM_HEART_BEAT': self.config.get('audio_stream', 'heart_beat', fallback='30'),
                'STREAM_SUPPRESS_LOG': self.config.get('audio_stream', 'suppress_log', fallback='false'),
                'STREAM_MESSAGE_DEFLATE': self.config.get('audio_stream', 'message_deflate', fallback='true'),
                # 添加超时设置保持session活跃
                # 'session_timeout': '3600',  # 1小时超时
                # 'media_timeout': '0',       # 禁用媒体超时
                # 'rtp_timeout_sec': '0'      # 禁用RTP超时
            }
            
            # 设置通道变量
            for var, value in channel_vars.items():
                cmd = f"uuid_setvar {uuid} {var} {value}"
                response = self.fs_client.execute_api(cmd)
                logging.debug(f"Set {var}={value}: {response.strip()}")
            
            # 构建音频流启动命令
            ws_url = self.config.get('websocket', 'url', fallback='ws://localhost:8080/audio')
            mix_type = self.config.get('audio_stream', 'mix_type', fallback='mono')
            sample_rate = self.config.get('audio_stream', 'sample_rate', fallback='8000')
            
            # 添加会话元数据
            metadata = json.dumps({
                'client_type': 'freeswitch',
                'call_id': uuid,
                'audio_config': {
                    "audioDataType": "raw",
                    "sampleRate": 16000,
                    "channels": 1,
                    "bitDepth": 16
                }
            })
            
            # 启动音频流
            cmd = f'uuid_audio_stream {uuid} start {ws_url} {mix_type} {sample_rate} {metadata}'
            logging.info(f"Starting audio stream: {cmd}")
            
            response = self.fs_client.execute_api(cmd)
            
            if '+OK' in response:
                # 音频流启动成功后，创建音频播放队列
                self.create_audio_queue_for_session(uuid)
                
                # 发送注册消息（如果需要的话）
                # self._send_registration_message(uuid, registration_message)
                
                self.active_streams[uuid] = {
                    'caller': caller,
                    'callee': callee,
                    'direction': direction,
                    'start_time': datetime.now(),
                    'ws_url': ws_url
                }
                logging.info(f"Started audio stream for {caller}->{callee} (UUID: {uuid}, Direction: {direction})")
            else:
                logging.error(f"Failed to start audio stream: {response}")
                
        except Exception as e:
            logging.error(f"Error starting audio stream for {uuid}: {e}")
    
    def _delayed_start_audio_stream(self, uuid: str, caller: str, callee: str, direction: str):
        """延迟启动音频流的辅助方法"""
        logging.info(f"Starting delayed audio stream for UUID: {uuid}")
        self.start_audio_stream(uuid, caller, callee, direction)
    
    def stop_audio_stream(self, uuid: str):
        """停止音频流"""
        try:
            # 首先停止音频播放队列
            self.stop_audio_queue(uuid)
            
            if uuid in self.active_streams:
                stream_info = self.active_streams[uuid]
                
                # 发送停止元数据
                metadata = json.dumps({
                    'session_id': uuid,
                    'end_time': datetime.now().isoformat(),
                    'duration': str(datetime.now() - stream_info['start_time'])
                })
                
                cmd = f'uuid_audio_stream {uuid} stop {metadata}'
                response = self.fs_client.execute_api(cmd)
                
                del self.active_streams[uuid]
                logging.info(f"Stopped audio stream for UUID: {uuid}")
            
            # 清理队列相关的数据结构
            with self.queue_lock:
                if uuid in self.audio_queues:
                    del self.audio_queues[uuid]
                if uuid in self.playback_status:
                    del self.playback_status[uuid]
                if uuid in self.playback_threads:
                    del self.playback_threads[uuid]
            
        except Exception as e:
            logging.error(f"Error stopping audio stream for {uuid}: {e}")
    
    def handle_audio_stream_event(self, event: Dict):
        """处理音频流相关事件"""
        import urllib.parse
        event_subclass = event.get('Event-Subclass', '')
        # URL解码事件子类
        event_subclass = urllib.parse.unquote(event_subclass)
        uuid = event.get('Unique-ID')
        
        if 'mod_audio_stream::' in event_subclass:
            if event_subclass == 'mod_audio_stream::connect':
                logging.info(f"Audio stream connected for UUID: {uuid}")
            elif event_subclass == 'mod_audio_stream::disconnect':
                logging.info(f"Audio stream disconnected for UUID: {uuid}")
            elif event_subclass == 'mod_audio_stream::error':
                body = event.get('_body', '')
                logging.error(f"Audio stream error for UUID {uuid}: {body}")
            elif event_subclass == 'mod_audio_stream::play':
                logging.info(f"Audio playback event for UUID: {uuid}")
                # self.uuid = uuid
                content_body = urllib.parse.unquote(event.get('Content-Body', ''))
                content_length = int(event.get('Content-Length', 0)) 
                self.handle_audio_playback(content_body, uuid)
            elif event_subclass == 'mod_audio_stream::json':
                logging.info(f"Audio json event for UUID: {uuid}")
                # self.handle_audio_json(event)
            else:
                logging.warning(f"Unknown mod_audio_stream event: '{event_subclass}'")
        else:
            logging.warning(f"Non-mod_audio_stream event received: '{event_subclass}'")

class AudioMonitorService:
    """音频监控服务主类"""
    
    def __init__(self, config_file='audio_monitor.conf'):
        self.config = configparser.ConfigParser()
        self.config.read(config_file)
        
        self.setup_logging()
        self.audio_manager = AudioStreamManager(self.config)
        self.running = False
        
        # 注册信号处理
        signal.signal(signal.SIGTERM, self.signal_handler)
        signal.signal(signal.SIGINT, self.signal_handler)
    
    def setup_logging(self):
        """设置日志"""
        log_level = self.config.get('logging', 'level', fallback='INFO')
        log_file = self.config.get('logging', 'file', fallback='/tmp/freeswitch-audio-monitor.log')
        
        # 确保日志目录存在且有写权限
        log_dir = os.path.dirname(log_file)
        if not os.path.exists(log_dir):
            try:
                os.makedirs(log_dir, exist_ok=True)
            except PermissionError:
                # 如果无法创建目录，使用当前目录
                log_file = './freeswitch-audio-monitor.log'
                print(f"Warning: Cannot create log directory, using: {log_file}")
        
        handlers = []
        
        # 尝试创建文件处理器
        try:
            file_handler = logging.FileHandler(log_file)
            handlers.append(file_handler)
        except PermissionError:
            # 如果无法写入指定位置，尝试当前目录
            try:
                log_file = './freeswitch-audio-monitor.log'  
                file_handler = logging.FileHandler(log_file)
                handlers.append(file_handler)
                print(f"Warning: Using log file in current directory: {log_file}")
            except Exception as e:
                print(f"Warning: Cannot create log file, using console only: {e}")
        
        # 始终添加控制台处理器
        handlers.append(logging.StreamHandler())
        
        logging.basicConfig(
            level=getattr(logging, log_level),
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=handlers
        )
    
    def signal_handler(self, signum, frame):
        """信号处理器"""
        logging.info(f"Received signal {signum}, shutting down...")
        self.stop()
    
    def event_callback(self, event_data: str):
        """事件回调函数"""
        # logging.info(f"DEBUG: Raw event data length: {len(event_data)}")
        try:
            # if self.audio_manager.wait_for_json:
            #     self.audio_manager.handle_audio_playback(event_data[:self.audio_manager.content_length])
            #     return

            # logging.info(f"DEBUG: Raw event data: \n{event_data}")
            event = self.audio_manager.parse_event(event_data)
            event_name = event.get('Event-Name', '')
            
            # 添加调试日志
            if event_name == 'CUSTOM':
                import urllib.parse
                event_subclass = event.get('Event-Subclass', '')
                decoded_subclass = urllib.parse.unquote(event_subclass)
                logging.info(f"DEBUG: Received CUSTOM event - Subclass: {decoded_subclass}")
                self.audio_manager.handle_audio_stream_event(event)
            
            if event_name == 'CHANNEL_ANSWER':
                self.audio_manager.handle_channel_answer(event)
            elif event_name == 'CHANNEL_BRIDGE':
                self.audio_manager.handle_channel_bridge(event)
            elif event_name == 'CHANNEL_UNBRIDGE':
                self.audio_manager.handle_channel_unbridge(event)
            elif event_name == 'CHANNEL_HANGUP':
                self.audio_manager.handle_channel_hangup(event)
                
        except Exception as e:
            logging.error(f"Error processing event: {e}")
    
    def run(self):
        """运行服务"""
        logging.info("Starting FreeSWITCH Audio Monitor Service")
        
        # 连接到FreeSWITCH
        fs_host = self.config.get('freeswitch', 'host', fallback='localhost')
        fs_port = self.config.getint('freeswitch', 'port', fallback=8021)
        fs_password = self.config.get('freeswitch', 'password', fallback='ClueCon')
        
        fs_client = FreeSWITCHEventSocket(fs_host, fs_port, fs_password)
        self.audio_manager.fs_client = fs_client
        
        while not self.running:
            try:
                if fs_client.connect():
                    # 订阅需要的事件
                    events = ['CHANNEL_ANSWER', 'CHANNEL_BRIDGE', 'CHANNEL_UNBRIDGE', 'CHANNEL_HANGUP', 'CUSTOM mod_audio_stream::play', 'CUSTOM mod_audio_stream::connect', 'CUSTOM mod_audio_stream::disconnect', 'CUSTOM mod_audio_stream::error', 'CUSTOM mod_audio_stream::json']
                    if fs_client.subscribe_events(events):
                        logging.info("Successfully subscribed to events")
                        self.running = True
                        fs_client.listen_events(self.event_callback)
                    else:
                        logging.error("Failed to subscribe to events")
                else:
                    logging.error("Failed to connect to FreeSWITCH")
                
                if not self.running:
                    logging.info("Retrying connection in 10 seconds...")
                    time.sleep(10)
                    
            except KeyboardInterrupt:
                break
            except Exception as e:
                logging.error(f"Unexpected error: {e}")
                time.sleep(10)
        
        fs_client.disconnect()
        logging.info("FreeSWITCH Audio Monitor Service stopped")
    
    def stop(self):
        """停止服务"""
        self.running = False
        
        # 停止所有活动的音频流
        for uuid in list(self.audio_manager.active_streams.keys()):
            self.audio_manager.stop_audio_stream(uuid)
        
        # 清空所有音频播放队列
        self.audio_manager.clear_all_audio_queues()

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='FreeSWITCH Audio Stream Monitor')
    parser.add_argument('-c', '--config', default='audio_monitor.conf',
                        help='Configuration file path')
    parser.add_argument('-d', '--daemon', action='store_true',
                        help='Run as daemon')
    
    args = parser.parse_args()
    
    service = AudioMonitorService(args.config)
    
    if args.daemon:
        # 简单的守护进程实现
        if os.fork() > 0:
            sys.exit(0)
        os.setsid()
        if os.fork() > 0:
            sys.exit(0)
    
    try:
        service.run()
    except KeyboardInterrupt:
        service.stop()

if __name__ == '__main__':
    main()