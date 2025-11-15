#!/usr/bin/env python3
"""
WebSocket Audio Server for mod_audio_fork
Supports receiving L16 audio stream and sending control commands
"""

import asyncio
import websockets
import json
import base64
import argparse
import logging
import struct
import wave
import tempfile
import os
from datetime import datetime
from typing import Optional, Dict, Any

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class AudioStreamHandler:
    """处理音频流数据"""
    
    def __init__(self, client_id: str, output_dir: str = "/tmp"):
        self.client_id = client_id
        self.output_dir = output_dir
        self.audio_file = None
        self.wav_writer = None
        self.sample_rate = 16000  # 默认采样率
        self.channels = 1  # 默认单声道
        self.audio_data_size = 0
        self.session_start_time = datetime.now()
        
    def start_recording(self, sample_rate: int = 16000, channels: int = 1):
        """开始录制音频"""
        self.sample_rate = sample_rate
        self.channels = channels
        
        # 创建输出文件
        timestamp = self.session_start_time.strftime("%Y%m%d_%H%M%S")
        filename = f"audio_{self.client_id}_{timestamp}.wav"
        filepath = os.path.join(self.output_dir, filename)
        
        self.audio_file = open(filepath, 'wb')
        self.wav_writer = wave.open(self.audio_file, 'wb')
        self.wav_writer.setnchannels(channels)
        self.wav_writer.setsampwidth(2)  # 16-bit = 2 bytes
        self.wav_writer.setframerate(sample_rate)
        
        logger.info(f"Started recording audio to {filepath}")
        return filepath
        
    def write_audio_data(self, audio_data: bytes):
        """写入音频数据"""
        if self.wav_writer:
            self.wav_writer.writeframes(audio_data)
            self.audio_data_size += len(audio_data)
            logger.debug(f"Received {len(audio_data)} bytes of audio data")
        else:
            logger.warning("Audio writer not initialized, dropping data")
            
    def stop_recording(self):
        """停止录制"""
        if self.wav_writer:
            self.wav_writer.close()
            self.wav_writer = None
        if self.audio_file:
            self.audio_file.close()
            self.audio_file = None
            
        duration = (datetime.now() - self.session_start_time).total_seconds()
        logger.info(f"Stopped recording. Total audio data: {self.audio_data_size} bytes, Duration: {duration:.2f} seconds")

class WebSocketAudioServer:
    """WebSocket音频服务器"""
    
    def __init__(self, host: str = "0.0.0.0", port: int = 8080, output_dir: str = "/tmp"):
        self.host = host
        self.port = port
        self.output_dir = output_dir
        self.clients = {}  # 存储客户端连接
        
        # 确保输出目录存在
        os.makedirs(output_dir, exist_ok=True)
        
    async def handle_client(self, websocket, path):
        """处理客户端连接"""
        client_id = f"{websocket.remote_address[0]}_{websocket.remote_address[1]}"
        logger.info(f"New connection from {client_id}")
        
        # 创建音频处理器
        audio_handler = AudioStreamHandler(client_id, self.output_dir)
        self.clients[client_id] = {
            'websocket': websocket,
            'audio_handler': audio_handler,
            'connected': True
        }
        
        try:
            # 处理消息
            async for message in websocket:
                await self.process_message(websocket, client_id, message, audio_handler)
                
        except websockets.exceptions.ConnectionClosed:
            logger.info(f"Client {client_id} disconnected")
        except Exception as e:
            logger.error(f"Error handling client {client_id}: {e}")
        finally:
            # 清理
            if client_id in self.clients:
                audio_handler.stop_recording()
                del self.clients[client_id]
                logger.info(f"Cleaned up client {client_id}")
                
    async def process_message(self, websocket, client_id: str, message, audio_handler: AudioStreamHandler):
        """处理接收到的消息"""
        
        if isinstance(message, str):
            # 文本消息（JSON格式）
            await self.handle_text_message(websocket, client_id, message, audio_handler)
            
        elif isinstance(message, bytes):
            # 二进制音频数据
            await self.handle_audio_data(websocket, client_id, message, audio_handler)
            
    async def handle_text_message(self, websocket, client_id: str, message: str, audio_handler: AudioStreamHandler):
        """处理文本消息"""
        try:
            data = json.loads(message)
            msg_type = data.get('type', 'unknown')
            
            logger.info(f"Received text message from {client_id}: {msg_type}")
            
            if msg_type == 'playAudio':
                await self.handle_play_audio(websocket, client_id, data, audio_handler)
            elif msg_type == 'killAudio':
                await self.handle_kill_audio(websocket, client_id, data)
            elif msg_type == 'startRecording':
                await self.handle_start_recording(websocket, client_id, data, audio_handler)
            elif msg_type == 'stopRecording':
                await self.handle_stop_recording(websocket, client_id, audio_handler)
            else:
                logger.warning(f"Unknown message type: {msg_type}")
                
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON message from {client_id}: {e}")
            
    async def handle_audio_data(self, websocket, client_id: str, audio_data: bytes, audio_handler: AudioStreamHandler):
        """处理音频数据"""
        logger.debug(f"Received {len(audio_data)} bytes of audio data from {client_id}")
        
        # 写入音频数据
        audio_handler.write_audio_data(audio_data)
        
    async def handle_play_audio(self, websocket, client_id: str, data: Dict[str, Any], audio_handler: AudioStreamHandler):
        """处理播放音频请求"""
        audio_data = data.get('data', {})
        audio_content_type = audio_data.get('audioContentType', 'raw')
        sample_rate = audio_data.get('sampleRate', 16000)
        audio_content = audio_data.get('audioContent', '')
        text_content = audio_data.get('textContent', '')
        
        logger.info(f"Play audio request: type={audio_content_type}, sampleRate={sample_rate}")
        
        if audio_content:
            try:
                # 解码base64音频数据
                audio_bytes = base64.b64decode(audio_content)
                
                # 创建临时文件
                with tempfile.NamedTemporaryFile(mode='wb', suffix='.raw', delete=False) as f:
                    f.write(audio_bytes)
                    temp_file = f.name
                    
                logger.info(f"Audio content saved to temporary file: {temp_file}")
                
                # 发送确认消息
                response = {
                    'type': 'playAudioResponse',
                    'status': 'success',
                    'file': temp_file,
                    'sampleRate': sample_rate,
                    'textContent': text_content
                }
                await websocket.send(json.dumps(response))
                
            except Exception as e:
                logger.error(f"Failed to process audio content: {e}")
                error_response = {
                    'type': 'playAudioResponse',
                    'status': 'error',
                    'error': str(e)
                }
                await websocket.send(json.dumps(error_response))
                
    async def handle_kill_audio(self, websocket, client_id: str, data: Dict[str, Any]):
        """处理停止音频播放请求"""
        logger.info(f"Kill audio request from {client_id}")
        
        # 发送确认消息
        response = {
            'type': 'killAudioResponse',
            'status': 'success'
        }
        await websocket.send(json.dumps(response))
        
    async def handle_start_recording(self, websocket, client_id: str, data: Dict[str, Any], audio_handler: AudioStreamHandler):
        """处理开始录制请求"""
        sample_rate = data.get('sampleRate', 16000)
        channels = data.get('channels', 1)
        
        filepath = audio_handler.start_recording(sample_rate, channels)
        
        response = {
            'type': 'startRecordingResponse',
            'status': 'success',
            'file': filepath,
            'sampleRate': sample_rate,
            'channels': channels
        }
        await websocket.send(json.dumps(response))
        
    async def handle_stop_recording(self, websocket, client_id: str, audio_handler: AudioStreamHandler):
        """处理停止录制请求"""
        audio_handler.stop_recording()
        
        response = {
            'type': 'stopRecordingResponse',
            'status': 'success'
        }
        await websocket.send(json.dumps(response))
        
    async def start_server(self):
        """启动WebSocket服务器"""
        logger.info(f"Starting WebSocket audio server on {self.host}:{self.port}")
        
        # 设置WebSocket服务器参数
        server_config = {
            'host': self.host,
            'port': self.port,
            'subprotocols': ['audio.drachtio.org'],  # 支持mod_audio_fork的子协议
            'process_request': self.handle_protocol_handshake
        }
        
        async with websockets.serve(self.handle_client, **server_config):
            logger.info(f"WebSocket server started on ws://{self.host}:{self.port}")
            logger.info(f"Output directory: {self.output_dir}")
            logger.info("Waiting for connections...")
            
            # 保持服务器运行
            await asyncio.Future()  # 运行 forever
            
    def handle_protocol_handshake(self, path, request_headers):
        """处理协议握手"""
        logger.info(f"New connection request from {path}")
        logger.debug(f"Headers: {dict(request_headers)}")
        
        # 可以在这里添加认证逻辑
        return None  # 接受所有连接

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='WebSocket Audio Server for mod_audio_fork')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to (default: 0.0.0.0)')
    parser.add_argument('--port', type=int, default=8080, help='Port to listen on (default: 8080)')
    parser.add_argument('--output-dir', default='/tmp', help='Directory to save audio files (default: /tmp)')
    parser.add_argument('--log-level', default='INFO', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], 
                       help='Log level (default: INFO)')
    
    args = parser.parse_args()
    
    # 设置日志级别
    logging.getLogger().setLevel(getattr(logging, args.log_level))
    
    # 创建并启动服务器
    server = WebSocketAudioServer(args.host, args.port, args.output_dir)
    
    try:
        asyncio.run(server.start_server())
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server error: {e}")

if __name__ == '__main__':
    main()