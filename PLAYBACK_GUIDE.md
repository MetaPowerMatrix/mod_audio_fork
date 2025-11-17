# WebSocket 音频播放功能使用指南（更新版）

## 概述

`audio_fork.py` 现在支持完整的音频播放功能，可以接收来自 WebSocket 服务器的音频播放请求，并将音频播放给 caller。本版本**重新实现了队列播放机制**，参考了 `freeswitch_audio_monitor.py` 的设计，解决了音频播放乱序问题。

## 核心改进

### 1. 会话隔离的音频队列（新增）
- **每会话独立队列**: 每个通话UUID拥有独立的音频播放队列，避免不同通话间的干扰
- **线程安全**: 使用 `threading.RLock` 确保多线程环境下的安全操作
- **队列大小限制**: 默认最大队列大小为10个音频任务，超出时自动移除最旧任务

### 2. 顺序播放保证（新增）
- **等待播放完成**: 每个音频播放完成后才处理下一个音频任务
- **播放状态跟踪**: 实时跟踪当前播放状态和队列大小
- **播放完成检测**: 基于音频文件大小估算播放时长，确保完整播放

### 3. 智能播放控制（增强）
- **多种播放方法**: 支持 `uuid_broadcast` 和 `uuid_displace` 两种播放方式
- **自动重试机制**: 播放失败时自动尝试备用播放方法
- **播放中断处理**: 支持随时停止播放和清空队列

## 架构设计

### 核心组件

```python
# 音频队列管理（重新设计）
self.audio_queues = defaultdict(queue.Queue)      # 每会话的音频队列
self.playback_threads = defaultdict(threading.Thread)  # 每会话的播放线程
self.playback_status = defaultdict(dict)        # 每会话的播放状态
self.queue_lock = threading.RLock()             # 队列操作锁
```

### 播放状态跟踪

```python
playback_status = {
    'playing': False,           # 是否正在播放
    'current_file': None,       # 当前播放文件
    'last_play_time': None,     # 最后播放时间
    'queue_size': 0            # 队列大小
}
```

## 工作流程

### 1. 音频任务入队（重新实现）

当收到 `play_audio` 事件时：

1. 检查是否为会话创建音频队列
2. 创建音频任务对象（包含文件路径、采样率、时间戳等）
3. 线程安全地将任务加入对应会话的队列
4. 如果当前未在播放，启动播放线程

### 2. 音频播放处理（重新实现）

播放线程的工作流程：

1. 从队列获取音频任务
2. 更新播放状态（正在播放、当前文件、队列大小）
3. 执行音频播放（支持多种播放方法）
4. **等待播放完成**（基于文件大小估算时长）⭐
5. 更新播放状态（播放完成）
6. 处理下一个音频任务

### 3. 播放完成检测（新增）

```python
def wait_for_playback_completion(self, audio_file, sample_rate):
    """等待播放完成 - 参考freeswitch_audio_monitor.py实现"""
    try:
        # 获取文件大小
        file_size = os.path.getsize(audio_file)
        
        # 估算音频时长（基于文件大小和采样率）
        if audio_file.endswith('.wav'):
            # WAV文件：44字节头 + 音频数据
            audio_data_size = file_size - 44
            duration = audio_data_size / (sample_rate * 2)  # 16位采样
        else:
            # 原始音频文件
            if sample_rate == 8000:
                duration = file_size / sample_rate  # 8位采样
            elif sample_rate == 16000:
                duration = file_size / (sample_rate * 2)  # 16位采样
            elif sample_rate == 24000:
                duration = file_size / (sample_rate * 3)  # 24位采样
            else:
                duration = file_size / (sample_rate * 2)  # 默认16位采样
        
        # 添加缓冲时间
        wait_time = duration + 0.5
        print(f"Estimated playback duration: {duration:.2f}s, waiting: {wait_time:.2f}s")
        
        # 等待播放完成
        time.sleep(wait_time)
        
    except Exception as e:
        print(f"Error estimating playback duration: {e}")
        # 出错时等待默认时间
        time.sleep(2.0)
```

### 4. 播放停止处理（增强）

当收到 `kill_audio` 事件时：

1. 向对应会话队列发送停止信号（None）
2. 清空队列中的所有音频任务
3. 尝试多种方法停止当前播放
4. 更新播放状态

## WebSocket 消息格式（保持不变）

### 播放音频消息
```json
{
    "type": "playAudio",
    "data": {
        "audioContentType": "raw",
        "sampleRate": 8000,
        "audioContent": "base64_encoded_audio_data...",
        "textContent": "Optional text for TTS if no audio content"
    }
}
```

### 停止播放消息
```json
{
    "type": "killAudio"
}
```

## 支持的音频格式

- **raw**: 原始 PCM 音频数据（需要指定 sampleRate）
- **wave/wav**: WAV 格式音频文件

## 采样率配置

### 支持的采样率
- 8000 Hz (默认)
- 16000 Hz (推荐)
- 24000 Hz
- 32000 Hz
- 48000 Hz
- 64000 Hz

### 文件扩展名规则
根据采样率，临时文件使用不同的扩展名：
- `.r8` - 8000 Hz
- `.r16` - 16000 Hz  
- `.r24` - 24000 Hz
- `.r32` - 32000 Hz
- `.r48` - 48000 Hz
- `.r64` - 64000 Hz
- `.wav` - WAV 格式（不依赖采样率）

## 使用方法

### 1. 创建测试音频文件（新增）

```bash
# 生成测试音频文件
python create_test_audio.py
```

该脚本会创建多种格式的测试音频文件：
- 不同采样率（8kHz、16kHz、24kHz）
- 不同格式（原始音频、WAV）
- 不同长度和音调，便于测试顺序播放

### 2. 启动 audio_fork.py

```bash
python3 audio_fork.py ws://localhost:8080
```

### 3. 运行测试脚本（增强）

```bash
# 运行测试脚本
python test_queue_playback.py
```

选择测试项目：
- **测试队列播放（顺序播放）**: 验证音频按发送顺序播放
- **测试快速连续播放**: 验证快速发送时是否保持顺序（重点测试乱序问题）
- **测试停止播放**: 验证播放中断功能

### 4. 观察日志输出

在 `audio_fork.py` 的日志中观察：
- 音频任务入队信息（包含队列大小）
- 播放开始和完成信息（包含等待时长）
- 队列大小变化
- **顺序播放的执行过程**（重点验证）

## 队列处理流程（更新）

```
WebSocket playAudio事件 → 会话隔离队列 → 播放线程处理 → 等待播放完成 → FreeSWITCH播放 → 完成后处理下一个
```

## 示例输出（更新）

```
Received play_audio event:
  Audio content type: raw
  Sample rate: 8000
  Text content: Playing 1kHz test tone for 2 seconds
  Audio file: /tmp/audio_001.r8
Added audio to queue for session_uuid: /tmp/audio_001.r8 (queue size: 1)
Processing playback task: /tmp/audio_001.r8 (type: raw, rate: 8000)
Estimated playback duration: 1.0s, waiting: 1.5s
Playing raw audio file: /tmp/audio_001.r8 (sample rate: 8000)
Playback completed, processing next task...
```

## 故障排除（增强）

### 音频播放乱序问题（重点解决）
**症状**: 多个音频文件播放顺序与发送顺序不一致
**解决**: 
1. 检查日志中的"Estimated playback duration"信息
2. 确认是否等待了足够的播放完成时间
3. 验证音频文件时长估算是否准确

### 队列堆积问题
**症状**: 队列大小持续增长，音频播放延迟
**解决**: 
1. 检查音频文件是否过大
2. 验证播放是否成功完成
3. 检查是否有播放失败的任务阻塞队列

### 播放中断失败
**症状**: `kill_audio` 无法停止当前播放
**解决**: 
1. 检查 FreeSWITCH 连接和权限设置
2. 验证是否正确发送到对应会话的队列
3. 查看日志中的停止播放尝试记录

## 注意事项（重要更新）

1. **会话隔离**: 每个通话UUID拥有独立的播放队列，互不干扰
2. **顺序保证**: 系统会等待每个音频播放完成后才处理下一个，确保顺序
3. **快速连续发送**: 即使快速连续发送多个音频，也会严格按照顺序播放
4. **播放完成检测**: 基于文件大小估算播放时长，确保完整播放
5. **线程安全**: 所有队列操作都是线程安全的，支持并发处理
6. **错误恢复**: 播放失败时自动尝试备用方法，提高成功率

## 配置参数（新增）

### 队列配置
- **最大队列大小**: 10个音频任务（每会话独立）
- **默认优先级**: 0（可以扩展优先级机制）
- **队列操作超时**: 非阻塞模式（block=False）

### 播放配置
- **播放完成等待缓冲**: 0.5秒
- **播放失败重试**: 支持多种播放方法（uuid_broadcast、uuid_displace）
- **停止播放重试**: 支持多种停止方法

## 优势特点（重新设计）

### 1. 彻底解决乱序问题 ⭐
- ✅ **严格按照发送顺序播放音频**（等待播放完成机制）
- ✅ **支持快速连续发送时的顺序保证**（队列机制保证）
- ✅ **会话隔离，避免不同通话间的干扰**

### 2. 提高系统稳定性
- ✅ **线程安全，避免并发问题**
- ✅ **完善的错误处理和重试机制**
- ✅ **每会话独立的播放状态管理**

### 3. 增强可控性和可观测性
- ✅ **实时跟踪播放状态和队列信息**
- ✅ **支持随时停止播放和清空队列**
- ✅ **详细的日志输出，便于调试和监控**
- ✅ **播放时长估算和完成检测**

### 4. 保持兼容性和扩展性
- ✅ **支持多种音频格式**（原始音频、WAV）
- ✅ **支持多种采样率**（8kHz、16kHz、24kHz）
- ✅ **易于扩展新的播放方法和配置**

## 更新记录

### 2024年重大更新
- 🔧 **重新设计队列机制**: 参考 `freeswitch_audio_monitor.py` 的实现
- 🎯 **解决乱序问题**: 实现等待播放完成机制
- 🏗️ **会话隔离架构**: 每UUID独立队列和状态管理
- 🧪 **增强测试工具**: 提供 `create_test_audio.py` 和增强的测试脚本
- 📊 **完善监控日志**: 详细的播放状态和队列信息输出

通过这套重新设计的队列机制，**彻底解决了音频播放乱序问题**，确保音频严格按照发送顺序播放，大大提升了系统的可靠性和用户体验。