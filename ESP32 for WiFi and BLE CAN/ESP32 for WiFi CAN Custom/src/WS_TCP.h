#pragma once

/*============================================================================
 * WS_TCP.h — TCP 帧服务器
 *
 * 第1级主力通道：ESP32 连笔记本热点时，上位机通过 TCP 控制 CAN。
 * 帧格式: [2B 大端长度] [1B 类型] [载荷]
 *
 * 特性：
 *   - 最多 4 个并发客户端
 *   - CAN 数据自动推送到所有连接的客户端
 *   - Nagle 禁用，低延迟
 *
 * 命令协议见 WS_Config.h
 *============================================================================*/

#include <WiFi.h>
#include "WS_Config.h"

void TCP_Init(void);
void TCP_SendFrame(uint8_t frame_type, const uint8_t *payload, uint16_t payload_len);
void TCPTask(void *parameter);
