#!/bin/bash
# arm-net-watch: 网络状态哨兵(用户会话内运行)
# 有有线或有 WiFi → 正常; 双无 → 桌面提醒"无网络" + 写状态文件; 恢复 → 提醒"已联网"
# 有网优先用网 = NetworkManager 默认路由(有线 metric 更低), 本脚本只做状态提醒
STATE=/tmp/claude/net_state
last=""
while true; do
  eth_ip=$(ip -4 -o addr show 2>/dev/null | awk '{print $2, $4}' | grep -E '^en' | grep -v 127.0.0.1 | head -1)
  wifi_conn=$(nmcli -t -f DEVICE,STATE dev 2>/dev/null | grep -E '^wl.*:connected' | head -1)
  if [ -n "$eth_ip" ] || [ -n "$wifi_conn" ]; then
    now="online"
    # 有网优先用网: 显示当前主路由出口
    route_via=$(ip route get 8.8.8.8 2>/dev/null | awk '{for(i=1;i<NF;i++) if($i=="dev") print $(i+1)}' | head -1)
    msg="已联网 (出口: $route_via)"
  else
    now="offline"
    msg="⚠️ 无网络! 界面连不上 Jetson——请插网线或开启电脑热点"
  fi
  echo "$now $msg" > "$STATE"
  if [ "$now" != "$last" ]; then
    if command -v notify-send >/dev/null 2>&1 && [ -n "$DISPLAY" ]; then
      notify-send -t 5000 "网络状态" "$msg" 2>/dev/null || true
    fi
    logger -t arm-net-watch "$msg"
    last="$now"
  fi
  sleep 30
done
