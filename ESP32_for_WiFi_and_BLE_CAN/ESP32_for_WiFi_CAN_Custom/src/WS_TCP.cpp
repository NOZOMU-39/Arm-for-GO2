/*============================================================================
 * WS_TCP.cpp — TCP 帧服务器
 *
 * 帧格式: [2B 大端长度] [1B 类型] [载荷]
 *
 * 第1级主力通道。CANTask 接收到的 CAN 帧自动推送到所有连接的 TCP 客户端。
 * 命令分发由共享的 ProcessCommand() 处理（定义在 WS_CAN.cpp）。
 *============================================================================*/
#include "WS_TCP.h"
#include "WS_CAN.h"
#include "WS_RTC.h"

// ---- 外部变量 ----
extern uint8_t g_ip_query_flag;
extern uint8_t g_can_query_flag;
extern uint8_t g_rtc_query_flag;
extern char g_device_ip[16];

// ---- TCP 服务器 ----
static WiFiServer *tcp_server = nullptr;
static WiFiClient  tcp_clients[MAX_TCP_CLIENTS];

// ---- 帧解析状态机 ----
enum TcpState {
    TCP_WAIT_LEN_HI,
    TCP_WAIT_LEN_LO,
    TCP_WAIT_TYPE,
    TCP_WAIT_PAYLOAD
};

struct TcpClientState {
    TcpState  state;
    uint16_t  payload_len;
    uint8_t   frame_type;
    uint8_t   payload[TCP_RX_BUF_SIZE];
    uint16_t  payload_pos;
    bool      batch_enabled;   // v2.1: 客户端协商启用批帧模式后为 true
};

// ---- 批帧攒批缓冲 (v2.1) ----
// 满 CAN_BATCH_MAX_FRAMES 帧立即发，或攒批超过 CAN_BATCH_TIMEOUT_MS 强制发。
// 参数权衡见 WS_Config.h。
typedef struct {
    CAN_Frame frames[CAN_BATCH_MAX_FRAMES];
    uint16_t  count;
    uint32_t  start_ms;
} BatchBuffer;

static BatchBuffer batch;   // TCP 通道的批帧缓冲

static TcpClientState client_state[MAX_TCP_CLIENTS];

/*============================================================================
 * TCP 帧发送
 *============================================================================*/
void TCP_SendFrame(uint8_t frame_type, const uint8_t *payload, uint16_t payload_len) {
    // v2.1.3: 头+载荷拼一个缓冲一次 write (原 2 次 write 每帧多一次 lwIP 调用)
    uint16_t total = 1 + payload_len;  // 类型 + 载荷
    uint8_t buf[3 + TCP_RX_BUF_SIZE];
    buf[0] = (total >> 8) & 0xFF;
    buf[1] = total & 0xFF;
    buf[2] = frame_type;
    if (payload_len > 0) {
        memcpy(buf + 3, payload, payload_len);
    }

    for (int i = 0; i < MAX_TCP_CLIENTS; i++) {
        if (tcp_clients[i] && tcp_clients[i].connected()) {
            tcp_clients[i].write(buf, 3 + payload_len);
        }
    }
}

/*============================================================================
 * 推送 CAN 帧给 TCP 客户端（v2.1 双路径）
 *
 * - 未协商的客户端（旧版）：每帧一个 0x03 单帧包（保持 v2.0 行为）
 * - 已协商的客户端：帧攒入批缓冲，满 CAN_BATCH_MAX_FRAMES 帧
 *   或超 CAN_BATCH_TIMEOUT_MS 后以 0x05 批帧一次性发送
 *
 * 一个环形尾指针读出的帧同时喂两条路径：旧客户端收单帧，新客户端收批。
 * 两种客户端可同时在线，互不影响。
 *============================================================================*/
static void TCP_FlushBatch(void) {
    if (batch.count == 0) return;
    uint8_t buf[2 + CAN_BATCH_MAX_FRAMES * 18];
    uint16_t len = CAN_SerializeBatch(buf, batch.frames, batch.count);
    for (int i = 0; i < MAX_TCP_CLIENTS; i++) {
        if (tcp_clients[i] && tcp_clients[i].connected() &&
            client_state[i].batch_enabled) {
            TCP_SendFrame(FRAME_CAN_BATCH, buf, len);
        }
    }
    batch.count = 0;
}

static void TCP_PushCANFrames(void) {
    bool any_legacy = false;
    bool any_batch  = false;
    for (int i = 0; i < MAX_TCP_CLIENTS; i++) {
        if (tcp_clients[i] && tcp_clients[i].connected()) {
            if (client_state[i].batch_enabled) any_batch = true;
            else any_legacy = true;
        }
    }
    if (!any_legacy && !any_batch) return;

    // 攒批超时兜底：没有新帧也要把已攒的帧发出去
    if (batch.count > 0 &&
        (uint32_t)(millis() - batch.start_ms) >= CAN_BATCH_TIMEOUT_MS) {
        TCP_FlushBatch();
    }

    CAN_Frame frame;
    while (CAN_ReadFrame(&can_ring_tcp_tail, &frame)) {
        // 旧客户端：保持单帧推送
        if (any_legacy) {
            uint8_t buf[18];
            buf[0] = (frame.id >> 24) & 0xFF;
            buf[1] = (frame.id >> 16) & 0xFF;
            buf[2] = (frame.id >> 8) & 0xFF;
            buf[3] = frame.id & 0xFF;
            buf[4] = frame.extd;
            buf[5] = (frame.timestamp_ms >> 24) & 0xFF;
            buf[6] = (frame.timestamp_ms >> 16) & 0xFF;
            buf[7] = (frame.timestamp_ms >> 8) & 0xFF;
            buf[8] = frame.timestamp_ms & 0xFF;
            buf[9] = frame.dlc;
            if (frame.dlc > 0) {
                memcpy(buf + 10, frame.data, frame.dlc);
            }
            TCP_SendFrame(FRAME_CAN_PUSH, buf, 10 + frame.dlc);
        }

        // 新客户端：攒入批缓冲
        if (any_batch) {
            if (batch.count == 0) batch.start_ms = millis();
            batch.frames[batch.count++] = frame;
            if (batch.count >= CAN_BATCH_MAX_FRAMES) TCP_FlushBatch();
        }
    }
}

/*============================================================================
 * 帧提交处理（v2.1）
 *
 * 先拦截批帧协商命令 CMD_ENABLE_BATCH (0x0A13)：
 *   收到后启用该客户端的批帧模式并回确认，其余命令交给 ProcessCommand。
 * 这样旧客户端不受影响（不发 0x0A13 → 一直收 0x03 单帧），
 * 两种客户端可同时在线，各自独立协商。
 *============================================================================*/
static void TCP_HandleFrame(int client_idx, uint8_t *full, uint16_t len) {
    if (len == 3 && full[0] == FRAME_CMD_REQ &&
        full[1] == (uint8_t)(CMD_ENABLE_BATCH >> 8) &&
        full[2] == (uint8_t)(CMD_ENABLE_BATCH & 0xFF)) {
        client_state[client_idx].batch_enabled = true;
        TCP_SendFrame(FRAME_CMD_RESP, (const uint8_t *)"BATCH", 5);
        printf("[TCP] 客户端%d 已启用批帧模式\r\n", client_idx);
        return;
    }
    ProcessCommand(full, len);
}

/*============================================================================
 * 帧解析：逐字节喂入
 *============================================================================*/
static void TCP_ParseByte(int client_idx, uint8_t b) {
    TcpClientState *cs = &client_state[client_idx];

    switch (cs->state) {
        case TCP_WAIT_LEN_HI:
            cs->payload_len = ((uint16_t)b) << 8;
            cs->state = TCP_WAIT_LEN_LO;
            break;

        case TCP_WAIT_LEN_LO:
            cs->payload_len |= b;
            if (cs->payload_len == 0 || cs->payload_len > TCP_RX_BUF_SIZE) {
                printf("[TCP] 客户端%d 无效帧长度: %d\r\n", client_idx, cs->payload_len);
                cs->state = TCP_WAIT_LEN_HI;
            } else {
                cs->state = TCP_WAIT_TYPE;
            }
            break;

        case TCP_WAIT_TYPE:
            cs->frame_type = b;
            cs->payload_pos = 0;
            if (cs->payload_len == 1) {
                // 只有类型字节 — 直接处理
                uint8_t full[1] = {cs->frame_type};
                TCP_HandleFrame(client_idx, full, 1);
                cs->state = TCP_WAIT_LEN_HI;
            } else {
                cs->payload_len--;  // 减去类型字节
                cs->state = TCP_WAIT_PAYLOAD;
            }
            break;

        case TCP_WAIT_PAYLOAD:
            cs->payload[cs->payload_pos++] = b;
            if (cs->payload_pos >= cs->payload_len) {
                // 完整帧 — 提交处理（含协商拦截）
                uint8_t full[TCP_RX_BUF_SIZE + 1];
                full[0] = cs->frame_type;
                memcpy(full + 1, cs->payload, cs->payload_len);
                TCP_HandleFrame(client_idx, full, cs->payload_len + 1);
                cs->state = TCP_WAIT_LEN_HI;
            }
            break;
    }
}

/*============================================================================
 * TCP 初始化
 *============================================================================*/
void TCP_Init(void) {
    tcp_server = new WiFiServer(TCP_SERVER_PORT);
    tcp_server->begin();
    tcp_server->setNoDelay(true);

    for (int i = 0; i < MAX_TCP_CLIENTS; i++) {
        tcp_clients[i] = WiFiClient();
        client_state[i].state = TCP_WAIT_LEN_HI;
        client_state[i].batch_enabled = false;
    }
    batch.count = 0;

    printf("[TCP] 服务器启动, 端口 %d (批帧: 满%d帧/超%dms)\r\n",
           TCP_SERVER_PORT, CAN_BATCH_MAX_FRAMES, CAN_BATCH_TIMEOUT_MS);

    // 核心 1 (APP_CPU): 核心 0 必须独占给 WiFi/lwIP 协议栈 (v2.1.2 修复)
    xTaskCreatePinnedToCore(TCPTask, "TCPTask", 8192, nullptr, 3, nullptr, 1);
}

/*============================================================================
 * TCPTask 主循环
 *============================================================================*/
void TCPTask(void *parameter) {
    const TickType_t loop_delay = pdMS_TO_TICKS(1);

    while (1) {
        // ---- 响应标志位查询（给所有客户端）----
        if (g_ip_query_flag) {
            g_ip_query_flag = 0;
            TCP_SendFrame(FRAME_CMD_RESP, (const uint8_t *)g_device_ip, strlen(g_device_ip));
            vTaskDelay(pdMS_TO_TICKS(10));
            continue;
        }
        if (g_can_query_flag) {
            g_can_query_flag = 0;
            CAN_Frame frame;
            if (CAN_ReadFrame(&can_ring_tcp_tail, &frame)) {
                uint8_t buf[18];
                buf[0] = (frame.id >> 24) & 0xFF;
                buf[1] = (frame.id >> 16) & 0xFF;
                buf[2] = (frame.id >> 8) & 0xFF;
                buf[3] = frame.id & 0xFF;
                buf[4] = frame.extd;
                buf[5] = (frame.timestamp_ms >> 24) & 0xFF;
                buf[6] = (frame.timestamp_ms >> 16) & 0xFF;
                buf[7] = (frame.timestamp_ms >> 8) & 0xFF;
                buf[8] = frame.timestamp_ms & 0xFF;
                buf[9] = frame.dlc;
                if (frame.dlc > 0) memcpy(buf + 10, frame.data, frame.dlc);
                TCP_SendFrame(FRAME_CAN_PUSH, buf, 10 + frame.dlc);
            } else {
                TCP_SendFrame(FRAME_CMD_RESP, (const uint8_t *)"[CAN Buffer Empty]", 18);
            }
            continue;
        }
        if (g_rtc_query_flag) {
            g_rtc_query_flag = 0;
            char time_str[50];
            RTC_GetTimeStr(time_str, sizeof(time_str));
            TCP_SendFrame(FRAME_CMD_RESP, (const uint8_t *)time_str, strlen(time_str));
            continue;
        }

        // ---- 推送 CAN 帧 ----
        TCP_PushCANFrames();

        // ---- 接受新连接 ----
        if (tcp_server->hasClient()) {
            WiFiClient new_client = tcp_server->accept();
            bool added = false;
            for (int i = 0; i < MAX_TCP_CLIENTS; i++) {
                if (!tcp_clients[i] || !tcp_clients[i].connected()) {
                    tcp_clients[i] = new_client;
                    tcp_clients[i].setNoDelay(true);
                    client_state[i].state = TCP_WAIT_LEN_HI;
                    client_state[i].batch_enabled = false;  // 新连接默认单帧模式
                    printf("[TCP] 客户端%d 已连接: %s\r\n", i,
                           tcp_clients[i].remoteIP().toString().c_str());
                    added = true;
                    break;
                }
            }
            if (!added) {
                printf("[TCP] 客户端已满 (%d), 拒绝新连接\r\n", MAX_TCP_CLIENTS);
                new_client.stop();
            }
        }

        // ---- 处理客户端数据 (v2.1.3: 批量读, 每帧 1 次 read 替代逐字节) ----
        // 原逐字节 read() 每帧 13 次 lwIP 系统调用, 是发送吞吐瓶颈之一
        for (int i = 0; i < MAX_TCP_CLIENTS; i++) {
            if (tcp_clients[i] && tcp_clients[i].connected()) {
                uint8_t rbuf[256];
                int n;
                while ((n = tcp_clients[i].read(rbuf, sizeof(rbuf))) > 0) {
                    for (int k = 0; k < n; k++) {
                        TCP_ParseByte(i, rbuf[k]);
                    }
                }
            } else if (tcp_clients[i]) {
                printf("[TCP] 客户端%d 已断开\r\n", i);
                tcp_clients[i].stop();
                client_state[i].state = TCP_WAIT_LEN_HI;
                client_state[i].batch_enabled = false;
                // 断开的若是批帧客户端，清掉积攒的批数据避免发给残留连接
                if (batch.count > 0) batch.count = 0;
            }
        }

        vTaskDelay(loop_delay);
    }
    vTaskDelete(nullptr);
}
