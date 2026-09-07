#!/bin/bash
# todesk-ui-conflict-guard.sh
# 作用:界面(TCP 8888)接入时自动退出 ToDesk 客户端,断开后自动恢复——避免"界面轮询+ToDesk"叠加触发系统崩溃
# 用法:部署为 systemd 服务(见同目录 service 文件);手动跑:nohup bash todesk-ui-conflict-guard.sh &
# 依赖:pgrep/kill/ss;ToDesk 客户端路径 /opt/todesk/bin/ToDesk
TODESK_BIN="/opt/todesk/bin/ToDesk"
LOG="/home/nvidia/todesk-ui-guard.log"
was_ui=0
while true; do
    ui_now=$(ss -tn 2>/dev/null | grep -c "ESTAB.*:8888")
    if [ "$ui_now" -gt 0 ] && [ "$was_ui" = "0" ]; then
        pid=$(pgrep -x ToDesk | head -1)
        if [ -n "$pid" ]; then
            kill -9 "$pid" 2>/dev/null
            echo "$(date +%F_%T) 界面接入 -> 已退出 ToDesk 客户端(PID $pid)" >> "$LOG"
        fi
        was_ui=1
    elif [ "$ui_now" = "0" ] && [ "$was_ui" = "1" ]; then
        if ! pgrep -x ToDesk >/dev/null; then
            export DISPLAY=:0 XAUTHORITY=/run/user/1000/gdm/Xauthority
            nohup "$TODESK_BIN" >/dev/null 2>&1 &
            echo "$(date +%F_%T) 界面断开 -> 已恢复 ToDesk 客户端" >> "$LOG"
        fi
        was_ui=0
    fi
    sleep 5
done
