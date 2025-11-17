#!/usr/bin/env python3
"""
测试队列播放机制的脚本
"""

import asyncio
import json
import time
import threading
from ESL import ESLconnection

def send_play_audio_event(uuid, audio_file, audio_content_type='raw', sample_rate=16000):
    """发送播放音频事件到FreeSWITCH"""
    try:
        # 连接到FreeSWITCH ESL
        con = ESLconnection("localhost", "8021", "ClueCon")
        
        if not con.connected():
            print("Failed to connect to FreeSWITCH")
            return False
            
        # 构建播放音频事件数据
        event_data = {
            "audioContentType": audio_content_type,
            "sampleRate": sample_rate,
            "file": audio_file,
            "textContent": ""
        }
        
        # 发送自定义事件
        cmd = f"uuid_sendevent {uuid} mod_audio_fork::play_audio {json.dumps(event_data)}"
        result = con.api(cmd)
        
        if result:
            print(f"Sent play_audio event: {audio_file} (type: {audio_content_type}, rate: {sample_rate})")
            return True
        else:
            print("Failed to send play_audio event")
            return False
            
    except Exception as e:
        print(f"Error sending play_audio event: {e}")
        return False
    finally:
        if con and con.connected():
            con.disconnect()

def test_queue_playback():
    """测试队列播放功能 - 测试顺序播放"""
    print("=== 测试队列播放机制（顺序播放） ===")
    
    # 测试音频文件 - 使用不同长度和采样率的文件
    test_files = [
        ("/tmp/test_short.r8", "raw", 8000, "短音频-8k"),
        ("/tmp/test_medium.r16", "raw", 16000, "中音频-16k"),
        ("/tmp/test_long.r24", "raw", 24000, "长音频-24k"),
        ("/tmp/test_voice.wav", "wav", 16000, "语音文件-wav")
    ]
    
    # 获取当前活动的UUID（这里需要手动指定或从日志中获取）
    target_uuid = input("请输入要测试的UUID（从audio_fork.py日志中获取）: ").strip()
    
    if not target_uuid:
        print("未提供UUID，取消测试")
        return
        
    print(f"开始测试队列播放，目标UUID: {target_uuid}")
    print("将依次发送多个音频文件到播放队列，观察是否按顺序播放...")
    
    # 发送多个音频文件到队列
    for i, (audio_file, content_type, sample_rate, description) in enumerate(test_files, 1):
        print(f"\n[{i}] 发送音频文件: {description} ({audio_file})")
        success = send_play_audio_event(target_uuid, audio_file, content_type, sample_rate)
        
        if success:
            print(f"✓ 成功发送到队列")
        else:
            print(f"✗ 发送失败")
            
        # 稍微延迟，模拟真实场景
        time.sleep(0.3)
    
    print(f"\n=== 所有音频文件已发送到播放队列 ===")
    print("请在audio_fork.py的日志中观察播放过程...")
    print("重点观察：")
    print("1. 音频是否按发送顺序播放")
    print("2. 是否有等待播放完成的日志")
    print("3. 队列大小的变化")
    print("按Ctrl+C可以停止测试程序")
    
    try:
        # 等待用户中断
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n测试结束")

def test_rapid_playback():
    """测试快速连续播放 - 验证是否乱序"""
    print("\n=== 测试快速连续播放（验证乱序问题） ===")
    
    # 测试音频文件 - 使用数字编号便于观察顺序
    test_files = [
        ("/tmp/audio_001.r8", "raw", 8000, "音频001"),
        ("/tmp/audio_002.r16", "raw", 16000, "音频002"),
        ("/tmp/audio_003.r24", "raw", 24000, "音频003"),
        ("/tmp/audio_004.wav", "wav", 16000, "音频004"),
        ("/tmp/audio_005.r8", "raw", 8000, "音频005")
    ]
    
    target_uuid = input("请输入要测试的UUID: ").strip()
    
    if not target_uuid:
        print("未提供UUID，取消测试")
        return
        
    print(f"开始测试快速连续播放，目标UUID: {target_uuid}")
    print("将快速连续发送多个音频文件到播放队列...")
    
    # 快速连续发送音频文件（几乎无延迟）
    for i, (audio_file, content_type, sample_rate, description) in enumerate(test_files, 1):
        print(f"[{i}] 快速发送: {description}")
        success = send_play_audio_event(target_uuid, audio_file, content_type, sample_rate)
        
        if success:
            print(f"✓ 已发送")
        else:
            print(f"✗ 发送失败")
            
        # 极短延迟，模拟快速连续发送
        time.sleep(0.1)
    
    print(f"\n=== 所有音频文件已快速发送到播放队列 ===")
    print("请在audio_fork.py的日志中观察播放过程...")
    print("重点验证：音频是否严格按照001->002->003->004->005的顺序播放")
    print("按Ctrl+C可以停止测试程序")
    
    try:
        # 等待用户中断
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n测试结束")

def test_kill_audio():
    """测试停止播放功能"""
    print("\n=== 测试停止播放功能 ===")
    
    target_uuid = input("请输入要测试的UUID: ").strip()
    
    if not target_uuid:
        print("未提供UUID，取消测试")
        return
        
    try:
        con = ESLconnection("localhost", "8021", "ClueCon")
        
        if not con.connected():
            print("Failed to connect to FreeSWITCH")
            return
            
        # 发送停止播放事件
        result = con.api(f"uuid_sendevent {target_uuid} mod_audio_fork::kill_audio")
        
        if result:
            print("✓ 成功发送停止播放事件")
        else:
            print("✗ 发送停止播放事件失败")
            
    except Exception as e:
        print(f"Error sending kill_audio event: {e}")
    finally:
        if con and con.connected():
            con.disconnect()

if __name__ == "__main__":
    print("音频队列播放测试工具")
    print("==================")
    print("1. 测试队列播放（顺序播放）")
    print("2. 测试快速连续播放（验证乱序问题）")
    print("3. 测试停止播放")
    print("4. 退出")
    
    while True:
        choice = input("\n请选择测试项目 (1-4): ").strip()
        
        if choice == '1':
            test_queue_playback()
            break
        elif choice == '2':
            test_rapid_playback()
            break
        elif choice == '3':
            test_kill_audio()
            break
        elif choice == '4':
            print("退出测试")
            break
        else:
            print("无效选择，请重新输入")