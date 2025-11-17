# WebSocket 音频播放功能使用指南

## 概述

`audio_fork.py` 现在支持完整的音频播放功能，可以接收来自 WebSocket 服务器的音频播放请求，并将音频播放给 caller。

## 新增功能

### 1. 播放音频事件处理 (`mod_audio_fork::play_audio`)

当 WebSocket 服务器发送 `playAudio` 消息时，系统会：
- 接收 base64 编码的音频数据
- 保存为临时文件
- 触发 `mod_audio_fork::play_audio` 事件
- 自动播放音频文件给 caller

### 2. 停止播放事件处理 (`mod_audio_fork::kill_audio`)

当 WebSocket 服务器发送 `killAudio` 消息时，系统会：
- 停止当前正在播放的音频
- 触发 `mod_audio_fork::kill_audio` 事件

## WebSocket 消息格式

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

### 采样率匹配问题解决方案

**问题**: FreeSWITCH 默认使用 8000Hz 采样率，当播放不同采样率的音频时会出现：
```
File sample rate 24000 doesn't match requested rate 8000
Codec Activated L16@8000hz 1 channels 20ms
```

**解决方案**: `audio_fork.py` 会自动检测 `sampleRate` 参数，并在播放 raw 音频时使用 FreeSWITCH 的采样率配置：

```bash
# 自动配置采样率
playback({playback_sample_rate=24000}/tmp/audio_file.r24)
```

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

### 1. 启动 audio_fork.py

```bash
python3 audio_fork.py ws://localhost:8080
```

### 2. 运行测试脚本

```bash
python3 test_playback.py
```

### 3. 或者手动发送 WebSocket 消息

使用任何 WebSocket 客户端连接到 `ws://localhost:8080`，发送播放音频消息。

## 事件处理流程

1. **WebSocket 服务器** 发送 `playAudio` 消息
2. **mod_audio_fork** 接收音频数据并保存为临时文件
3. **mod_audio_fork** 触发 `mod_audio_fork::play_audio` 事件
4. **audio_fork.py** 接收到事件并提取音频文件路径
5. **audio_fork.py** 使用 FreeSWITCH 的 `playback` 命令播放音频
6. **caller** 听到播放的音频

## 错误处理

系统会自动处理以下错误情况：
- JSON 解析错误
- 缺少音频文件路径
- 不支持的音频格式
- FreeSWITCH 播放命令失败
- 网络连接问题

## 示例输出

```
Received play_audio event:
  Audio content type: raw
  Sample rate: 8000
  Text content: Playing 1kHz test tone for 2 seconds
  Audio file: /tmp/7dd5e34e-5db4-4edb-a166-757e5d29b941_2.tmp.r8
Playing raw audio file: /tmp/7dd5e34e-5db4-4edb-a166-757e5d29b941_2.tmp.r8
Playback result: +OK Success
```

## 故障排除

### 播放结果为 None
如果看到 `Playback result: None`，说明播放命令执行失败。系统会自动尝试以下替代方案：

1. **设置采样率变量** - 先执行 `set playback_sample_rate=<rate>`
2. **标准播放命令** - 执行 `playback <filename>`
3. **广播命令** - 执行 `uuid_broadcast <uuid> <filename>`
4. **音频位移命令** - 执行 `uuid_displace <uuid> start <filename>`

### 调试步骤
1. 检查 FreeSWITCH 日志获取详细错误信息
2. 确认音频文件存在且 FreeSWITCH 有读取权限
3. 验证文件格式是否正确（16-bit PCM，小端序）
4. 尝试手动在 FreeSWITCH CLI 执行相同命令

### 手动测试命令
在 FreeSWITCH CLI 中可以手动测试：
```bash
# 设置采样率
uuid_setvar <uuid> playback_sample_rate 24000

# 播放音频
uuid_broadcast <uuid> /tmp/audio_file.r24

# 或使用位移
uuid_displace <uuid> start /tmp/audio_file.r24
```

## 注意事项

1. 临时音频文件会在 FreeSWITCH 会话结束时自动删除
2. 确保 FreeSWITCH 有权限访问临时文件目录
3. 音频播放是异步的，不会阻塞其他操作
4. 支持同时播放多个音频文件（队列播放）
5. 使用 `killAudio` 可以立即停止当前播放
6. **重要**: 对于 raw 音频文件，确保正确设置 `sampleRate` 参数，否则会出现采样率不匹配错误
7. **建议**: 使用 16000Hz 采样率作为默认设置，平衡音质和性能

## 队列播放机制

### 概述
`audio_fork.py` 现在实现了**队列播放机制**，可以处理多个音频播放请求，避免播放冲突和丢失。

### 工作原理
1. **音频任务队列**: 所有播放请求被加入到一个线程安全的队列中
2. **独立播放线程**: 专门的线程负责从队列中取出任务并执行播放
3. **顺序播放**: 音频文件按照接收顺序依次播放
4. **播放控制**: 支持停止当前播放和清空队列

### 队列处理流程
```
WebSocket playAudio事件 → 加入播放队列 → 播放线程处理 → FreeSWITCH播放 → 完成
```

### 队列状态监控
在日志中可以看到队列状态：
```
Added playback task to queue. Queue size: 3
Processing playback task: /tmp/audio1.r16 (type: raw, rate: 16000)
Playing raw audio file: /tmp/audio1.r16 (sample rate: 16000)
Method 1 succeeded: +OK Success
```

### 停止播放机制
当收到 `killAudio` 事件时：
1. **清空队列**: 移除所有待播放的音频任务
2. **停止当前播放**: 使用多种方法尝试停止当前播放
3. **状态重置**: 重置播放状态，准备接收新任务

### 播放失败处理
播放线程会自动尝试多种播放方法：
1. `uuid_broadcast` - 广播播放
2. `set playback_sample_rate + playback` - 设置采样率后播放
3. `uuid_displace` - 音频位移播放
4. 标准 `playback` 命令

### 测试队列播放
使用新的测试脚本测试队列播放功能：
```bash
python3 test_queue_playback.py
```

测试功能包括：
- 发送多个音频文件到播放队列
- 测试不同采样率的音频文件
- 测试停止播放功能
- 监控队列状态和播放结果

### 队列配置参数
- **队列大小**: 默认无限制（可以根据需要设置最大队列长度）
- **播放超时**: 播放线程每秒检查一次新任务
- **失败重试**: 每种播放方法失败后自动尝试下一种
- **线程安全**: 使用线程安全的队列实现

### 优势
1. **避免播放冲突**: 多个音频文件不会同时播放
2. **防止音频丢失**: 所有播放请求都会被处理
3. **更好的错误处理**: 集中处理播放失败情况
4. **可监控性**: 详细的日志输出便于调试
5. **灵活性**: 支持动态添加和停止播放任务