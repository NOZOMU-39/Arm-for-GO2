#!/bin/bash
# arm-ip: 显示 Jetson 当前全部 IPv4(野外查界面该填哪个 IP)
echo "=== Jetson IP(界面连接用) ==="
ip -4 -o addr show 2>/dev/null | awk '{print $2": "$4}' | grep -v '^lo:'
echo "=== 控制栈状态 ==="
systemctl is-active arm-stack 2>/dev/null | sed 's/^/arm-stack: /'
ip -d link show can0 2>/dev/null | head -1 | sed 's/^/can0: /'
