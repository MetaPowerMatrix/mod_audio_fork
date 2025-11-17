#!/usr/bin/env python3
"""
创建测试音频文件的脚本
"""

import numpy as np
import wave
import struct
import os

def create_raw_audio_file(filename, sample_rate, duration, frequency, amplitude=0.8):
    """创建原始音频文件"""
    try:
        # 生成正弦波音频数据
        t = np.linspace(0, duration, int(sample_rate * duration), False)
        audio_data = amplitude * np.sin(2 * np.pi * frequency * t)
        
        # 根据采样率确定数据类型
        if sample_rate == 8000:
            # 8k采样率，8位无符号
            audio_bytes = (audio_data * 127 + 128).astype(np.uint8)
        elif sample_rate == 16000:
            # 16k采样率，16位有符号
            audio_bytes = (audio_data * 32767).astype(np.int16)
        elif sample_rate == 24000:
            # 24k采样率，24位有符号（打包为3字节）
            audio_int = (audio_data * 8388607).astype(np.int32)
            audio_bytes = b''.join(struct.pack('<i', val)[:3] for val in audio_int)
        else:
            # 默认16位
            audio_bytes = (audio_data * 32767).astype(np.int16)
        
        # 写入文件
        with open(filename, 'wb') as f:
            if isinstance(audio_bytes, np.ndarray):
                audio_bytes.tofile(f)
            else:
                f.write(audio_bytes)
        
        print(f"✓ 创建音频文件: {filename} ({sample_rate}Hz, {duration}s, {frequency}Hz音调)")
        return True
        
    except Exception as e:
        print(f"✗ 创建音频文件失败 {filename}: {e}")
        return False

def create_wav_audio_file(filename, sample_rate, duration, frequency, amplitude=0.8):
    """创建WAV音频文件"""
    try:
        # 生成正弦波音频数据
        t = np.linspace(0, duration, int(sample_rate * duration), False)
        audio_data = amplitude * np.sin(2 * np.pi * frequency * t)
        
        # 转换为16位整数
        audio_int = (audio_data * 32767).astype(np.int16)
        
        # 创建WAV文件
        with wave.open(filename, 'wb') as wav_file:
            wav_file.setnchannels(1)  # 单声道
            wav_file.setsampwidth(2)  # 16位
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(audio_int.tobytes())
        
        print(f"✓ 创建WAV文件: {filename} ({sample_rate}Hz, {duration}s, {frequency}Hz音调)")
        return True
        
    except Exception as e:
        print(f"✗ 创建WAV文件失败 {filename}: {e}")
        return False

def create_test_audio_files():
    """创建所有测试音频文件"""
    print("=== 创建测试音频文件 ===")
    
    # 创建标准测试文件
    test_files = [
        # 格式: (文件名, 采样率, 持续时间, 频率)
        ("/tmp/test_short.r8", 8000, 1.0, 440),      # 短音频，440Hz
        ("/tmp/test_medium.r16", 16000, 2.0, 880),   # 中音频，880Hz
        ("/tmp/test_long.r24", 24000, 3.0, 1320),   # 长音频，1320Hz
        ("/tmp/test_voice.wav", 16000, 1.5, 660),    # WAV格式，660Hz
    ]
    
    # 创建快速连续播放测试文件（数字编号）
    rapid_test_files = [
        ("/tmp/audio_001.r8", 8000, 1.0, 400),       # 音频001
        ("/tmp/audio_002.r16", 16000, 1.2, 500),     # 音频002
        ("/tmp/audio_003.r24", 24000, 1.5, 600),     # 音频003
        ("/tmp/audio_004.wav", 16000, 1.0, 700),      # 音频004
        ("/tmp/audio_005.r8", 8000, 1.8, 800),       # 音频005
    ]
    
    success_count = 0
    total_count = 0
    
    # 创建标准测试文件
    print("\n--- 创建标准测试文件 ---")
    for filename, sample_rate, duration, frequency in test_files:
        total_count += 1
        if filename.endswith('.wav'):
            if create_wav_audio_file(filename, sample_rate, duration, frequency):
                success_count += 1
        else:
            if create_raw_audio_file(filename, sample_rate, duration, frequency):
                success_count += 1
    
    # 创建快速连续播放测试文件
    print("\n--- 创建快速连续播放测试文件 ---")
    for filename, sample_rate, duration, frequency in rapid_test_files:
        total_count += 1
        if filename.endswith('.wav'):
            if create_wav_audio_file(filename, sample_rate, duration, frequency):
                success_count += 1
        else:
            if create_raw_audio_file(filename, sample_rate, duration, frequency):
                success_count += 1
    
    print(f"\n=== 音频文件创建完成 ===")
    print(f"成功: {success_count}/{total_count}")
    print(f"失败: {total_count - success_count}/{total_count}")
    
    if success_count == total_count:
        print("✓ 所有音频文件创建成功！")
        print("\n现在可以运行 test_queue_playback.py 进行测试了")
    else:
        print("✗ 部分音频文件创建失败，请检查错误信息")

if __name__ == "__main__":
    create_test_audio_files()