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
    """测试队列播放功能"""
    print("=== 测试队列播放机制 ===")
    
    # 测试音频文件
    test_files = [
        ("/tmp/test_8k.r8", "raw", 8000),
        ("/tmp/test_16k.r16", "raw", 16000),
        ("/tmp/test_24k.r24", "raw", 24000),
        ("/tmp/test.wav", "wav", 16000)
    ]
    
    # 获取当前活动的UUID（这里需要手动指定或从日志中获取）
    target_uuid = input("请输入要测试的UUID（从audio_fork.py日志中获取）: ").strip()
    
    if not target_uuid:
        print("未提供UUID，取消测试")
        return
        
    print(f"开始测试队列播放，目标UUID: {target_uuid}")
    print("将依次发送多个音频文件到播放队列...")
    
    # 发送多个音频文件到队列
    for i, (audio_file, content_type, sample_rate) in enumerate(test_files, 1):
        print(f"\n[{i}] 发送音频文件: {audio_file}")
        success = send_play_audio_event(target_uuid, audio_file, content_type, sample_rate)
        
        if success:
            print(f"✓ 成功发送到队列")
        else:
            print(f"✗ 发送失败")
            
        # 稍微延迟，模拟真实场景
        time.sleep(0.5)
    
    print(f"\n=== 所有音频文件已发送到播放队列 ===")
    print("请在audio_fork.py的日志中观察播放过程...")
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
    print("1. 测试队列播放")
    print("2. 测试停止播放")
    print("3. 退出")
    
    while True:
        choice = input("\n请选择测试项目 (1-3): ").strip()
        
        if choice == '1':
            test_queue_playback()
            break
        elif choice == '2':
            test_kill_audio()
            break
        elif choice == '3':
            print("退出测试")
            break
        else:
            print("无效选择，请重新输入")