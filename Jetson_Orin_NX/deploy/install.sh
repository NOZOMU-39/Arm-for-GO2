#!/bin/bash
# Jetson 部署件安装脚本(在 Jetson 上运行, 需 sudo 密码, 会弹提示输入)
# 安装: arm-stack 开机自启 / arm-ip 工具 / arm-net-watch 网络哨兵
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "== [1/4] arm-stack.service (开机自启控制栈) =="
sudo cp "$HERE/arm-stack.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable arm-stack.service
sudo systemctl start arm-stack.service || echo "(启动失败可看: journalctl -u arm-stack -n 50)"

echo "== [2/4] arm-ip (IP/状态查询) =="
sudo cp "$HERE/arm-ip.sh" /usr/local/bin/arm-ip
sudo chmod +x /usr/local/bin/arm-ip

echo "== [3/4] arm-net-watch (网络哨兵, 用户自启) =="
mkdir -p ~/.local/bin ~/.config/systemd/user
cp "$HERE/arm-net-watch.sh" ~/.local/bin/arm-net-watch.sh
chmod +x ~/.local/bin/arm-net-watch.sh
cp "$HERE/arm-net-watch.service" ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable arm-net-watch.service
systemctl --user start arm-net-watch.service

echo "== [4/4] 验证 =="
arm-ip
systemctl --user status arm-net-watch --no-pager | head -3
echo "安装完成。文档见 deploy/README.md; 查询用 arm-ip"
