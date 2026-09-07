# Jetson 部署件（系统级，不在 ROS2 工作区内）

开机自启与联网相关的**系统级部署件**（装到 /etc、/usr/local、用户目录），源码归档在此，换机/重刷后一键恢复。

## 清单

| 文件 | 装到 | 干什么 |
|---|---|---|
| `arm-stack.service` | `/etc/systemd/system/` | 开机自启控制栈（界面主模式：can_bridge+tcp_gateway；等 can0 容错，缺失安静等待） |
| `arm-ip.sh` | `/usr/local/bin/arm-ip` | 查 Jetson 当前 IP + 控制栈状态（野外填界面 IP 用） |
| `arm-net-watch.sh` | `~/.local/bin/` | 网络哨兵：双无（无有线无 WiFi）时桌面提醒；恢复提醒 |
| `arm-net-watch.service` | `~/.config/systemd/user/` | 哨兵的用户自启服务 |

## 网络策略（三档，装完即生效）

1. **有网优先用网**：插网线(路由器) → NetworkManager 默认走有线（metric 更低），热点待命不干扰
2. **没网等热点**：WiFi 连 `NOZOMU` 热点（autoconnect=yes，开机自动连，热点网段 192.168.137.x）
3. **双无提醒**：哨兵每 30s 查一次，无任何网络时桌面弹"⚠️ 无网络"（状态变化才弹，不刷屏）

## 安装（在 Jetson 上跑 `install.sh`，需要 sudo 密码）

```bash
# 先把本 deploy 目录拷到 Jetson 任意位置, 然后:
./install.sh
```

## 常用运维

```bash
arm-ip                        # 查 IP/栈状态(野外第一步)
systemctl status arm-stack    # 控制栈服务状态
systemctl restart arm-stack   # 重启控制栈
journalctl -u arm-stack -n 50 # 控制栈日志
systemctl --user status arm-net-watch   # 网络哨兵状态
```

## 注意

- arm-stack 自启的是**界面主模式**；自主任模式（controller 主）手动：`ros2 launch arm_bringup arm_bringup.launch.py controller:=true`（先 `systemctl stop arm-stack`）
- 改服务文件后：`sudo systemctl daemon-reload && sudo systemctl restart arm-stack`
