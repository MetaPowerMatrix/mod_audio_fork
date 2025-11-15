#!/usr/bin/env python3
"""
WebSocket Audio Server Demo
演示如何使用WebSocket音频服务器
"""

import asyncio
import websockets
import json
import base64
import numpy as np

async def test_audio_server():
    """测试音频服务器"""
    uri = "ws://localhost:8080"
    
    try:
        async with websockets.connect(uri, subprotocols=['audio.drachtio.org']) as websocket:
            print(f"Connected to {uri}")
            
            # 发送开始录制请求
            start_recording = {
                "type": "startRecording",
                "sampleRate": 16000,
                "channels": 1
            }
            await websocket.send(json.dumps(start_recording))
            print("Sent start recording request")
            
            # 接收响应
            response = await websocket.recv()
            print(f"Received: {response}")
            
            # 模拟发送音频数据（16kHz，16位，单声道）
            # 生成1秒的静音数据（16000个采样点）
            sample_rate = 16000
            duration = 1  # 1秒
            samples = int(sample_rate * duration)
            
            # 生成静音数据（全零）
            audio_data = np.zeros(samples, dtype=np.int16)
            
            # 转换为字节
            audio_bytes = audio_data.tobytes()
            
            print(f"Sending {len(audio_bytes)} bytes of audio data...")
            await websocket.send(audio_bytes)
            
            # 等待一会儿
            await asyncio.sleep(2)
            
            # 发送停止录制请求
            stop_recording = {
                "type": "stopRecording"
            }
            await websocket.send(json.dumps(stop_recording))
            print("Sent stop recording request")
            
            # 接收响应
            response = await websocket.recv()
            print(f"Received: {response}")
            
    except Exception as e:
        print(f"Error: {e}")

async def test_play_audio():
    """测试播放音频功能"""
    uri = "ws://localhost:8080"
    
    try:
        async with websockets.connect(uri, subprotocols=['audio.drachtio.org']) as websocket:
            print(f"Connected to {uri}")
            
            # 创建简单的音频数据（1kHz正弦波，1秒）
            sample_rate = 16000
            duration = 1
            frequency = 1000  # 1kHz
            
            t = np.linspace(0, duration, int(sample_rate * duration))
            audio_data = (np.sin(2 * np.pi * frequency * t) * 32767).astype(np.int16)
            audio_bytes = audio_data.tobytes()
            
            # base64编码
            audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')
            
            # 发送播放音频请求
            play_audio = {
                "type": "playAudio",
                "data": {
                    "audioContentType": "raw",
                    "sampleRate": 16000,
                    "audioContent": audio_base64,
                    "textContent": "Playing 1kHz test tone"
                }
            }
            
            await websocket.send(json.dumps(play_audio))
            print("Sent play audio request")
            
            # 接收响应
            response = await websocket.recv()
            print(f"Received: {response}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    print("Testing WebSocket Audio Server...")
    
    # 测试音频录制
    print("\n=== Testing Audio Recording ===")
    asyncio.run(test_audio_server())
    
    # 测试音频播放
    print("\n=== Testing Audio Playback ===")
    asyncio.run(test_play_audio())
    
    print("\nTest completed!")