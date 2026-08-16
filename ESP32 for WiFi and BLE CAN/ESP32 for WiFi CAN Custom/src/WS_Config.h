#pragma once

#include <stdint.h>
#include <stddef.h>

/*============================================================================
 * WS_Config.h — ESP32 WiFi CAN 全局配置文件
 *
 * 本文件统一定义：设备标识、WiFi 默认参数、通信常量、帧协议、数据结构
 *============================================================================*/

/*============================================================================
 * 一、设备标识
 *============================================================================*/
#define DEVICE_NAME        "ESP32-WiFi-CAN"
#define FIRMWARE_VERSION   "2.1.3"

/*============================================================================
 * 二、WiFi 默认参数（编译期默认值，运行时可网页修改并存 NVS）
 *============================================================================*/
#define DEFAULT_AP_SSID    "ESP32-WiFi-CAN"
#define DEFAULT_AP_PSK     "12345678"
#define DEFAULT_STA_SSID   ""
#define DEFAULT_STA_PSK    ""

/*============================================================================
 * 三、通信常量
 *============================================================================*/
#define TCP_SERVER_PORT    8888
#define MAX_TCP_CLIENTS    4
#define TCP_RX_BUF_SIZE    2048
#define SERIAL_RX_BUF_SIZE 2048

// ---- 批帧推送 (v2.1) ----
// 攒批参数权衡：帧数越大包率越低（CPU开销越小），超时越长延迟越大。
// 满 64 帧立即发 + 10ms 超时兜底 → 1kHz 输入时约 100 包/s，延迟 ≤10ms。
#define CAN_BATCH_MAX_FRAMES    64     // 每批最多帧数 (64×18B ≈ 1.2KB, TCP 段内)
#define CAN_BATCH_TIMEOUT_MS    10     // 攒批超时 (ms)，超时即使不满也强制发

// ---- UDP 推送通道 (v2.1, 可选) ----
// 只做单向 CAN 批帧推送（订阅即推），控制命令仍走 TCP 8888（可靠）。
#define UDP_SERVER_PORT         8889
#define UDP_MAX_CLIENTS         4      // 最多订阅者数
#define UDP_KEEPALIVE_MS        30000  // 订阅者无活动超时移除 (ms)

/*============================================================================
 * 四、CAN 默认参数
 *============================================================================*/
#define CAN_DEFAULT_BITRATE_KBPS  1000
#define CAN_LOOP_INTERVAL_MS      1      // CANTask 循环间隔 (ms)，1ms ≈ 1000Hz 上限
#define CAN_RING_SIZE             512    // 环形缓冲区帧数 (~0.5秒 @ 1000fps)
#define CAN_ECHO_FILTER_SIZE      16     // 自收回显过滤：最近发送帧签名数
#define CAN_STATS_INTERVAL_MS     1000   // 速率统计打印间隔 (ms)
#define CAN_POLLING_RATE_MS       1      // TWAI 警报读取超时 (ms)
#define CAN_TX_TIMEOUT_MS         10     // 发送入队超时 (ms)。
                                          // 原 1000ms: 总线无 ACK 时每帧卡 1s → TCPTask 被拖死 (v2.1.1 修复)

/*============================================================================
 * 五、二进制帧协议
 *
 * 帧格式: [2B 大端长度] [1B 类型] [N字节载荷]
 *
 * 长度 = 类型(1) + 载荷(N) 的总字节数，不含长度字段自身。
 * 类型字节:
 *   0x01 CMD_REQ    PC → ESP32  命令请求
 *   0x02 CMD_RESP   ESP32 → PC  命令响应
 *   0x03 CAN_FRAME   ESP32 → PC  CAN 接收帧推送（单帧，兼容模式）
 *   0x04 CAN_SEND    PC → ESP32  CAN 发送帧
 *   0x05 CAN_BATCH   ESP32 → PC  CAN 批帧推送（协商后启用，高吞吐）
 *
 * 命令字（载荷的前2字节，仅 CMD_REQ/CMD_RESP）:
 *   0A 0C  发送 CAN 帧
 *   0A 0D  查询 WiFi IP
 *   0A 0F  查询 CAN 接收缓冲区
 *   0A 10  设置 CAN 波特率
 *   0A 11  查询 RTC 时间
 *   0A 13  启用批帧模式（客户端主动协商，启用后推送改为 0x05）
 *          ⚠️ 0x0A12 预留给心跳看门狗（见 AI间交流\情报.md 通信与控制节），勿占用
 *
 * 批帧 0x05 载荷格式:
 *   [2B 帧数N 大端] [N × 帧块]
 *   帧块: [4B CAN_ID 大端] [1B extd] [4B 时间戳ms 大端] [1B DLC] [0-8B data]
 *   （帧块与 0x03 单帧载荷完全一致，解析器可复用）
 *
 * 兼容性（重要）:
 *   旧客户端不发送 0x0A12 → ESP32 继续推 0x03 单帧，行为与 v2.0 完全一致。
 *   新客户端发送 0x0A12 → ESP32 对该客户端切换为 0x05 批帧推送。
 *   两种客户端可同时在线，各自独立协商。
 *============================================================================*/

// 帧类型
#define FRAME_CMD_REQ    0x01
#define FRAME_CMD_RESP   0x02
#define FRAME_CAN_PUSH   0x03
#define FRAME_CAN_SEND   0x04
#define FRAME_CAN_BATCH  0x05

// 命令字
#define CMD_CAN_SEND     0x0A0C
#define CMD_QUERY_IP     0x0A0D
#define CMD_QUERY_CAN    0x0A0F
#define CMD_SET_CAN_RATE 0x0A10
#define CMD_QUERY_RTC    0x0A11
#define CMD_ENABLE_BATCH 0x0A13   // 0x0A12 预留给心跳看门狗

/*============================================================================
 * 六、CAN 帧结构体（环形缓冲区条目）
 *
 * 每帧固定 20 字节，512 帧 ≈ 10KB PSRAM
 *============================================================================*/
typedef struct {
    uint32_t id;             // CAN ID (标准帧: 0x000~0x7FF, 扩展帧: 0x00000000~0x1FFFFFFF)
    uint8_t  extd;           // 0=标准帧, 1=扩展帧
    uint8_t  dlc;            // 数据长度 (0~8)
    uint8_t  data[8];        // 帧数据
    uint32_t timestamp_ms;   // 接收时间戳 (ms，从 RTC 或开机计时)
} CAN_Frame;

/*============================================================================
 * 七、CAN 推送到上位机的帧格式（类型 0x03）
 *
 * [4B CAN_ID 大端] [1B extd] [4B timestamp_ms 大端] [1B DLC] [0-8B data]
 * 固定 10 字节头部 + 0~8 字节数据 = 10~18 字节
 *============================================================================*/

/*============================================================================
 * 八、帧头大小常量
 *============================================================================*/
#define FRAME_HEADER_LEN     2     // 2字节大端长度
#define FRAME_TYPE_LEN       1     // 1字节类型
#define FRAME_META_LEN       (FRAME_HEADER_LEN + FRAME_TYPE_LEN)  // 3字节帧元数据

/*============================================================================
 * 九、功能开关
 *============================================================================*/
#define COMMUNICATION_FAILURE_ENABLE  1   // CAN 总线故障检测
#define BUS_ERROR_INTERVAL_MS         5000 // 总线错误打印间隔 (ms)
