/*============================================================================
 * WS_Serial.cpp — USB CDC 串口指令处理
 *
 * 帧格式: [2B 大端长度] [1B 类型] [载荷]
 *
 * 第3级兜底通道：WiFi 不可用时通过 USB 线直连控制 CAN。
 * 命令分发由共享的 ProcessCommand() 处理（定义在 WS_CAN.cpp）。
 *============================================================================*/
#include "WS_Serial.h"
#include "WS_CAN.h"
#include "WS_RTC.h"
#include <Arduino.h>

// ---- 外部标志位 ----
uint8_t g_ip_query_flag = 0;
uint8_t g_can_query_flag = 0;
uint8_t g_rtc_query_flag = 0;

extern char g_device_ip[16];
extern SemaphoreHandle_t can_ring_mutex;

// ---- 帧解析状态机 ----
enum SerialState {
    SERIAL_WAIT_LEN_HI,
    SERIAL_WAIT_LEN_LO,
    SERIAL_WAIT_TYPE,
    SERIAL_WAIT_PAYLOAD
};
static SerialState s_state = SERIAL_WAIT_LEN_HI;
static uint16_t  s_payload_len = 0;
static uint8_t   s_frame_type = 0;
static uint8_t   s_payload[SERIAL_RX_BUF_SIZE];
static uint16_t  s_payload_pos = 0;

// ---- 发送辅助函数 ----
static void Serial_SendFrame(uint8_t frame_type, const uint8_t *payload, uint16_t payload_len) {
    // 帧格式: [2B 长度(不含自身)] [1B 类型] [载荷]
    uint16_t total = 1 + payload_len;  // 类型 + 载荷
    uint8_t header[3];
    header[0] = (total >> 8) & 0xFF;
    header[1] = total & 0xFF;
    header[2] = frame_type;
    Serial.write(header, 3);
    if (payload_len > 0) {
        Serial.write(payload, payload_len);
    }
}

void Serial_Init(void) {
    // Serial 由 Arduino 框架自动初始化（USB CDC）
    unsigned long start = millis();
    while (!Serial && (millis() - start < 3000)) {
        delay(10);
    }
    printf("[Serial] USB CDC 串口就绪\r\n");

    xTaskCreatePinnedToCore(SerialTask, "SerialTask", 4096, nullptr, 1, nullptr, 0);
}

void SerialTask(void *parameter) {
    const TickType_t loop_delay = pdMS_TO_TICKS(2);

    while (1) {
        // ---- 响应标志位查询 ----
        if (g_ip_query_flag) {
            g_ip_query_flag = 0;
            Serial_SendFrame(FRAME_CMD_RESP, (const uint8_t *)g_device_ip, strlen(g_device_ip));
            vTaskDelay(pdMS_TO_TICKS(10));
            continue;
        }
        if (g_can_query_flag) {
            g_can_query_flag = 0;
            CAN_Frame frame;
            if (CAN_ReadFrame(&can_ring_serial_tail, &frame)) {
                // 构造 CAN_FRAME 载荷
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
                Serial_SendFrame(FRAME_CAN_PUSH, buf, 10 + frame.dlc);
            } else {
                Serial_SendFrame(FRAME_CMD_RESP, (const uint8_t *)"[CAN Buffer Empty]", 18);
            }
            continue;
        }
        if (g_rtc_query_flag) {
            g_rtc_query_flag = 0;
            char time_str[50];
            RTC_GetTimeStr(time_str, sizeof(time_str));
            Serial_SendFrame(FRAME_CMD_RESP, (const uint8_t *)time_str, strlen(time_str));
            continue;
        }

        // ---- 解析串口输入 ----
        while (Serial.available() > 0) {
            uint8_t b = Serial.read();

            switch (s_state) {
                case SERIAL_WAIT_LEN_HI:
                    s_payload_len = ((uint16_t)b) << 8;
                    s_state = SERIAL_WAIT_LEN_LO;
                    break;

                case SERIAL_WAIT_LEN_LO:
                    s_payload_len |= b;
                    if (s_payload_len == 0 || s_payload_len > SERIAL_RX_BUF_SIZE) {
                        printf("[Serial] 无效帧长度: %d\r\n", s_payload_len);
                        s_state = SERIAL_WAIT_LEN_HI;
                    } else {
                        s_state = SERIAL_WAIT_TYPE;
                    }
                    break;

                case SERIAL_WAIT_TYPE:
                    s_frame_type = b;
                    s_payload_pos = 0;
                    if (s_payload_len == 1) {
                        // 只有类型，没有载荷 — 直接处理
                        uint8_t full[1] = {s_frame_type};
                        ProcessCommand(full, 1);
                        s_state = SERIAL_WAIT_LEN_HI;
                    } else {
                        s_payload_len--;  // 减去类型字节
                        s_state = SERIAL_WAIT_PAYLOAD;
                    }
                    break;

                case SERIAL_WAIT_PAYLOAD:
                    s_payload[s_payload_pos++] = b;
                    if (s_payload_pos >= s_payload_len) {
                        // 完整帧 — 构造 类型+载荷 提交给 ProcessCommand
                        uint8_t full[SERIAL_RX_BUF_SIZE + 1];
                        full[0] = s_frame_type;
                        memcpy(full + 1, s_payload, s_payload_len);
                        ProcessCommand(full, s_payload_len + 1);
                        s_state = SERIAL_WAIT_LEN_HI;
                    }
                    break;
            }
        }

        vTaskDelay(loop_delay);
    }
    vTaskDelete(nullptr);
}
