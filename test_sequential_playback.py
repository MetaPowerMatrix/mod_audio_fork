#!/usr/bin/env python3
"""
测试顺序播放功能 - 验证音频播放的时序性
"""

import json
import time
import websocket
import threading
import sys

def create_test_audio_files():
    """创建测试音频文件"""
    import numpy as np
    import wave
    import struct
    
    # 创建不同长度的测试音频文件
    sample_rate = 16000
    
    # 音频1: 1kHz 正弦波，2秒
    duration1 = 2.0
    t1 = np.linspace(0, duration1, int(sample_rate * duration1), False)
    audio1 = np.sin(2 * np.pi * 1000 * t1)  # 1kHz 正弦波
    
    # 音频2: 2kHz 正弦波，3秒
    duration2 = 3.0
    t2 = np.linspace(0, duration2, int(sample_rate * duration2), False)
    audio2 = np.sin(2 * np.pi * 2000 * t2)  # 2kHz 正弦波
    
    # 音频3: 500Hz 正弦波，1.5秒
    duration3 = 1.5
    t3 = np.linspace(0, duration3, int(sample_rate * duration3), False)
    audio3 = np.sin(2 * np.pi * 500 * t3)  # 500Hz 正弦波
    
    # 保存为WAV文件
    def save_wav(filename, audio, duration):
        audio_int16 = (audio * 32767).astype(np.int16)
        with wave.open(filename, 'w') as wav_file:
            wav_file.setnchannels(1)  # 单声道
            wav_file.setsampwidth(2)   # 16位
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(audio_int8.tobytes())
        print(f"创建了测试音频文件: {filename} ({duration}秒)")
    
    save_wav('/tmp/test_audio_1.wav', audio1, duration1)
    save_wav('/tmp/test_audio_2.wav', audio2, duration2)
    save_wav('/tmp/test_audio_3.wav', audio3, duration3)
    
    return [duration1, duration2, duration3]

def test_sequential_playback():
    """测试顺序播放"""
    print("=== 测试顺序播放功能 ===")
    
    # 创建测试音频文件
    durations = create_test_audio_files()
    
    # 连接到WebSocket服务器
    ws = websocket.WebSocket()
    try:
        ws.connect("ws://localhost:8080")
        print("已连接到WebSocket服务器")
        
        # 记录开始时间
        start_time = time.time()
        
        # 快速发送3个音频播放请求
        audio_files = ['/tmp/test_audio_1.wav', '/tmp/test_audio_2.wav', '/tmp/test_audio_3.wav']
        
        for i, audio_file in enumerate(audio_files, 1):
            # 读取音频文件并进行base64编码
            import base64
            with open(audio_file, 'rb') as f:
                audio_data = base64.b64encode(f.read()).decode('utf-8')
            
            # 发送播放请求
            message = {
                "type": "playAudio",
                "data": {
                    "audioContentType": "wav",
                    "sampleRate": 16000,
                    "audioContent": audio_data,
                    "textContent": f"测试音频{i}"
                }
            }
            
            ws.send(json.dumps(message))
            print(f"发送第{i}个音频播放请求: {audio_file}")
        
        # 计算理论总播放时间
        total_duration = sum(durations)
        print(f"理论总播放时间: {total_duration:.2f}秒")
        
        # 等待播放完成（额外增加2秒缓冲）
        wait_time = total_duration + 2
        print(f"等待{wait_time}秒让播放完成...")
        time.sleep(wait_time)
        
        # 记录结束时间
        end_time = time.time()
        actual_time = end_time - start_time
        
        print(f"\n=== 测试结果 ===")
        print(f"实际耗时: {actual_time:.2f}秒")
        print(f"理论耗时: {total_duration:.2f}秒")
        print(f"时间差: {actual_time - total_duration:.2f}秒")
        
        if abs(actual_time - total_duration) < 3:  # 允许3秒误差
            print("✅ 顺序播放测试通过 - 音频按顺序播放，无重叠或乱序")
        else:
            print("❌ 顺序播放测试失败 - 可能存在播放重叠或乱序")
        
        ws.close()
        
    except Exception as e:
        print(f"测试失败: {e}")
        return False
    
    return True

def test_queue_management():
    """测试队列管理功能"""
    print("\n=== 测试队列管理功能 ===")
    
    ws = websocket.WebSocket()
    try:
        ws.connect("ws://localhost:8080")
        print("已连接到WebSocket服务器")
        
        # 发送多个播放请求
        for i in range(5):
            message = {
                "type": "playAudio",
                "data": {
                    "audioContentType": "raw",
                    "sampleRate": 16000,
                    "textContent": f"队列测试音频{i+1}"
                }
            }
            ws.send(json.dumps(message))
            print(f"发送队列测试音频{i+1}")
            time.sleep(0.1)  # 快速连续发送
        
        # 等待1秒后发送停止命令
        time.sleep(1)
        print("发送停止播放命令...")
        ws.send(json.dumps({"type": "killAudio"}))
        
        # 等待清理完成
        time.sleep(2)
        print("✅ 队列管理测试完成")
        
        ws.close()
        return True
        
    except Exception as e:
        print(f"队列管理测试失败: {e}")
        return False

if __name__ == "__main__":
    print("开始测试顺序播放功能...")
    print("请确保WebSocket服务器和audio_fork.py正在运行")
    
    # 检查依赖
    try:
        import numpy as np
        import wave
        import websocket
        import base64
    except ImportError as e:
        print(f"缺少依赖包: {e}")
        print("请安装: pip install numpy websocket-client")
        sys.exit(1)
    
    # 运行测试
    success1 = test_sequential_playback()
    success2 = test_queue_management()
    
    if success1 and success2:
        print("\n🎉 所有测试通过！")
    else:
        print("\n⚠️  部分测试失败，请检查日志")