#!/bin/bash
# 安装 WebSocket 音频服务器依赖

echo "Installing WebSocket Audio Server dependencies..."

# 安装 Python 依赖
pip install websockets numpy

# 创建音频数据目录
mkdir -p audio_data

echo "Installation completed!"
echo "You can now run:"
echo "  python3 ws_server.py     # Start the server"
echo "  python3 ws_server_demo.py # Run demo client"