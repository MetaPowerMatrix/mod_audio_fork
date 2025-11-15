#!/usr/bin/env python3
"""
测试播放音频功能的演示脚本
用于测试audio_fork.py的音频播放功能
"""

import asyncio
import websockets
import json
import base64
import numpy as np

async def test_play_audio():
    """测试播放音频功能"""
    uri = "ws://localhost:8080"
    
    try:
        async with websockets.connect(uri, subprotocols=['audio.drachtio.org']) as websocket:
            print(f"Connected to {uri}")
            
            # 创建简单的音频数据（1kHz正弦波，2秒）
            sample_rate = 8000
            duration = 2
            frequency = 1000  # 1kHz
            
            t = np.linspace(0, duration, int(sample_rate * duration))
            audio_data = (np.sin(2 * np.pi * frequency * t) * 32767).astype(np.int16)
            audio_bytes = audio_data.tobytes()
            
            # base64编码
            audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')
            
            # 发送播放音频请求 - 使用raw格式
            play_audio_raw = {
                "type": "playAudio",
                "data": {
                    "audioContentType": "raw",
                    "sampleRate": 8000,
                    "audioContent": audio_base64,
                    "textContent": "Playing 1kHz test tone for 2 seconds"
                }
            }
            
            print("Sending playAudio request (raw format)...")
            await websocket.send(json.dumps(play_audio_raw))
            
            # 等待音频播放完成
            await asyncio.sleep(3)
            
            # 发送播放音频请求 - 仅文本（TTS）
            play_audio_tts = {
                "type": "playAudio", 
                "data": {
                    "audioContentType": "raw",
                    "sampleRate": 8000,
                    "textContent": "This is a text to speech test message"
                }
            }
            
            print("Sending playAudio request (TTS only)...")
            await websocket.send(json.dumps(play_audio_tts))
            
            # 等待TTS播放完成
            await asyncio.sleep(4)
            
            # 测试停止播放功能
            kill_audio = {
                "type": "killAudio"
            }
            
            print("Sending killAudio request...")
            await websocket.send(json.dumps(kill_audio))
            
            # 等待响应
            await asyncio.sleep(1)
            
    except Exception as e:
        print(f"Error: {e}")

async def test_multiple_audio_files():
    """测试多个音频文件播放"""
    uri = "ws://localhost:8080"
    
    try:
        async with websockets.connect(uri, subprotocols=['audio.drachtio.org']) as websocket:
            print(f"Connected to {uri}")
            
            # 创建不同频率的音频数据
            sample_rate = 16000
            
            for i, freq in enumerate([500, 1000, 1500], 1):
                duration = 1
                t = np.linspace(0, duration, int(sample_rate * duration))
                audio_data = (np.sin(2 * np.pi * freq * t) * 32767).astype(np.int16)
                audio_bytes = audio_data.tobytes()
                audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')
                
                play_audio = {
                    "type": "playAudio",
                    "data": {
                        "audioContentType": "raw",
                        "sampleRate": 16000,
                        "audioContent": audio_base64,
                        "textContent": f"Playing {freq}Hz test tone ({i}/3)"
                    }
                }
                
                print(f"Sending {freq}Hz audio...")
                await websocket.send(json.dumps(play_audio))
                await asyncio.sleep(2)
                
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    print("Testing Audio Playback Functionality...")
    
    # 测试基本播放功能
    print("\n=== Testing Basic Audio Playback ===")
    asyncio.run(test_play_audio())
    
    # 测试多个音频文件
    print("\n=== Testing Multiple Audio Files ===")
    asyncio.run(test_multiple_audio_files())
    
    print("\nTest completed!")
    print("\nNote: Make sure audio_fork.py is running and connected to FreeSWITCH")
    print("You should see the audio playback events being processed in the audio_fork.py console")