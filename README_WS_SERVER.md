# WebSocket Audio Server

基于 `mod_audio_fork` 的 WebSocket 音频服务器，使用 Python 编写。

## 功能特性

- 支持 `audio.drachtio.org` WebSocket 子协议
- 接收和发送音频数据（16位 PCM，16kHz）
- JSON 控制消息（播放、停止、录制等）
- 音频文件保存和播放
- 支持 base64 编码的音频数据传输

## 安装依赖

```bash
pip install websockets numpy
```

## 使用方法

### 1. 启动服务器

```bash
python3 ws_server.py
```

服务器将在 `ws://localhost:8080` 启动。

### 2. 运行演示客户端

```bash
python3 ws_server_demo.py
```

### 3. 使用 FreeSWITCH 连接

在 FreeSWITCH 中使用 `uuid_audio_fork` 命令：

```
# 启动音频流
uuid_audio_fork <uuid> start ws://localhost:8080

# 停止音频流
uuid_audio_fork <uuid> stop
```

## 数据包格式

### 连接时发送的元数据
```json
{
  "content-type": "audio/l16",
  "rate": 16000,
  "channels": 1
}
```

### 音频数据
- 二进制格式：16位 PCM 音频数据
- 采样率：16kHz
- 通道数：单声道

### 控制消息

#### 播放音频
```json
{
  "type": "playAudio",
  "data": {
    "audioContentType": "raw",
    "sampleRate": 16000,
    "audioContent": "<base64_encoded_audio>",
    "textContent": "播放文本"
  }
}
```

#### 停止播放
```json
{
  "type": "killAudio"
}
```

#### 开始录制
```json
{
  "type": "startRecording",
  "sampleRate": 16000,
  "channels": 1
}
```

#### 停止录制
```json
{
  "type": "stopRecording"
}
```

## 文件说明

- `ws_server.py` - WebSocket 音频服务器主程序
- `ws_server_demo.py` - 演示客户端，用于测试服务器功能
- `audio_data/` - 音频文件存储目录（自动创建）

## 注意事项

1. 确保防火墙允许 WebSocket 连接
2. 音频数据使用小端序格式
3. 服务器支持多客户端同时连接
4. 音频文件会自动保存在 `audio_data/` 目录下

## 错误处理

服务器会自动处理以下情况：
- WebSocket 连接错误
- JSON 消息解析错误
- 音频数据格式错误
- 文件操作错误

## 扩展功能

你可以根据需要扩展服务器功能：
- 添加音频格式转换
- 实现语音识别集成
- 添加音频效果处理
- 支持更多音频格式

## 许可证

MIT License