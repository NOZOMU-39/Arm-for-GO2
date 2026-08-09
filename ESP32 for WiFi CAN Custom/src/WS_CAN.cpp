/*============================================================================
 * WS_CAN.cpp — CAN 总线驱动 + 环形缓冲区实现
 *
 * 环形缓冲区 (PSRAM): 512 帧，CANTask 写入，各消费者独立读取。
 * 自收回显过滤: 最近 16 个发送帧签名匹配后跳过。
 * 速率统计: 每秒打印一次 RX/TX 帧率。
 *============================================================================*/
#include "WS_CAN.h"
#include "WS_GPIO.h"         // TXD2, RXD2 引脚定义
#include "WS_PCF85063.h"     // RTC 时间戳

// ====== 环形缓冲区 (PSRAM) ======
CAN_Frame *can_ring = nullptr;
volatile uint16_t can_ring_head = 0;
volatile uint16_t can_ring_tcp_tail = 0;
volatile uint16_t can_ring_serial_tail = 0;
volatile uint16_t can_ring_web_tail = 0;
SemaphoreHandle_t can_ring_mutex = nullptr;

// ====== 自收回显过滤 ======
typedef struct {
    uint32_t id;
    uint8_t  data[8];
    uint8_t  dlc;
    uint8_t  extd;
    uint32_t timestamp_ms;
} EchoSignature;
static EchoSignature echo_filter[CAN_ECHO_FILTER_SIZE];
static uint8_t echo_filter_idx = 0;

// ====== CAN 状态 ======
uint32_t CAN_bitrate_kbps = CAN_DEFAULT_BITRATE_KBPS;
float    CAN_rx_rate = 0.0f;
float    CAN_tx_rate = 0.0f;
uint32_t CAN_rx_count = 0;
uint32_t CAN_tx_count = 0;

// ====== 内部变量 ======
static bool driver_installed = false;
static TaskHandle_t can_task_handle = nullptr;
static uint32_t g_rx_total = 0;
static uint32_t g_tx_total = 0;
static unsigned long g_last_stats_time = 0;
static uint32_t g_boot_time_ms = 0;    // 开机计时 (ms)
static unsigned long g_boot_millis = 0; // 记录 millis() 开机时刻

/*============================================================================
 * 时间戳：开机计时 (ms)
 *============================================================================*/
uint32_t CAN_GetTimestamp(void) {
    return (uint32_t)(millis() - g_boot_millis);
}

/*============================================================================
 * 自收回显过滤
 *============================================================================*/
static void echo_filter_add(uint32_t id, uint8_t extd, uint8_t dlc, uint8_t *data) {
    EchoSignature *sig = &echo_filter[echo_filter_idx];
    sig->id = id;
    sig->extd = extd;
    sig->dlc = dlc;
    sig->timestamp_ms = CAN_GetTimestamp();
    if (dlc > 0 && dlc <= 8) {
        memcpy(sig->data, data, dlc);
    }
    echo_filter_idx = (echo_filter_idx + 1) % CAN_ECHO_FILTER_SIZE;
}

static bool echo_filter_match(uint32_t id, uint8_t extd, uint8_t dlc, uint8_t *data) {
    uint32_t now = CAN_GetTimestamp();
    for (int i = 0; i < CAN_ECHO_FILTER_SIZE; i++) {
        EchoSignature *sig = &echo_filter[i];
        if (sig->dlc == 0) continue;
        // 过期清理（超过 500ms 的签名视为过期）
        if (now - sig->timestamp_ms > 500) {
            sig->dlc = 0;
            continue;
        }
        if (sig->id == id && sig->extd == extd && sig->dlc == dlc) {
            if (dlc == 0 || memcmp(sig->data, data, dlc) == 0) {
                sig->dlc = 0;  // 匹配一次后清除，避免重复过滤
                return true;
            }
        }
    }
    return false;
}

/*============================================================================
 * 环形缓冲区操作
 *============================================================================*/
uint16_t CAN_AvailableFrames(volatile uint16_t *tail) {
    uint16_t head = can_ring_head;
    uint16_t t = *tail;
    if (head >= t) return head - t;
    return CAN_RING_SIZE - t + head;
}

bool CAN_ReadFrame(volatile uint16_t *tail, CAN_Frame *out_frame) {
    if (*tail == can_ring_head) return false;
    memcpy(out_frame, &can_ring[*tail], sizeof(CAN_Frame));
    *tail = (*tail + 1) % CAN_RING_SIZE;
    return true;
}

static void can_ring_push(CAN_Frame *frame) {
    can_ring[can_ring_head] = *frame;
    can_ring_head = (can_ring_head + 1) % CAN_RING_SIZE;

    // 如果覆盖了最慢的消费者，推进其指针
    uint16_t h = can_ring_head;
    if (h == can_ring_tcp_tail)
        can_ring_tcp_tail = (can_ring_tcp_tail + 1) % CAN_RING_SIZE;
    if (h == can_ring_serial_tail)
        can_ring_serial_tail = (can_ring_serial_tail + 1) % CAN_RING_SIZE;
    if (h == can_ring_web_tail)
        can_ring_web_tail = (can_ring_web_tail + 1) % CAN_RING_SIZE;
}

/*============================================================================
 * CAN 初始化
 *============================================================================*/
void CAN_Init(void) {
    twai_general_config_t g_config = TWAI_GENERAL_CONFIG_DEFAULT(
        (gpio_num_t)TXD2, (gpio_num_t)RXD2, TWAI_MODE_NORMAL);
    twai_timing_config_t t_config = TWAI_TIMING_CONFIG_1MBITS();
    twai_filter_config_t f_config = TWAI_FILTER_CONFIG_ACCEPT_ALL();

    if (twai_driver_install(&g_config, &t_config, &f_config) != ESP_OK) {
        printf("[CAN] 驱动安装失败\r\n");
        return;
    }
    if (twai_start() != ESP_OK) {
        printf("[CAN] 驱动启动失败\r\n");
        return;
    }

    uint32_t alerts = TWAI_ALERT_RX_DATA | TWAI_ALERT_ERR_PASS |
                      TWAI_ALERT_BUS_ERROR | TWAI_ALERT_RX_QUEUE_FULL |
                      TWAI_ALERT_TX_IDLE | TWAI_ALERT_TX_SUCCESS |
                      TWAI_ALERT_TX_FAILED;
    twai_reconfigure_alerts(alerts, nullptr);

    driver_installed = true;
    g_boot_millis = millis();
    printf("[CAN] 驱动就绪, 默认 %lu kbps\r\n", CAN_bitrate_kbps);

    // 创建 CANTask
    xTaskCreatePinnedToCore(CANTask, "CANTask", 4096, nullptr, 3,
                            &can_task_handle, 0);
}

/*============================================================================
 * 波特率切换
 *============================================================================*/
static esp_err_t CAN_SetBitrate(uint32_t bitrate_kbps) {
    if (!driver_installed) {
        printf("[CAN] 驱动未安装, 无法切换速率\r\n");
        return ESP_ERR_INVALID_STATE;
    }

    twai_timing_config_t t_config;
    switch (bitrate_kbps) {
        case 25:   t_config = TWAI_TIMING_CONFIG_25KBITS();  break;
        case 50:   t_config = TWAI_TIMING_CONFIG_50KBITS();  break;
        case 100:  t_config = TWAI_TIMING_CONFIG_100KBITS(); break;
        case 125:  t_config = TWAI_TIMING_CONFIG_125KBITS(); break;
        case 250:  t_config = TWAI_TIMING_CONFIG_250KBITS(); break;
        case 500:  t_config = TWAI_TIMING_CONFIG_500KBITS(); break;
        case 800:  t_config = TWAI_TIMING_CONFIG_800KBITS(); break;
        case 1000: t_config = TWAI_TIMING_CONFIG_1MBITS();   break;
        default:
            printf("[CAN] 不支持的波特率: %lu kbps\r\n", bitrate_kbps);
            return ESP_ERR_INVALID_ARG;
    }

    uint32_t old_rate = CAN_bitrate_kbps;

    if (can_task_handle) vTaskSuspend(can_task_handle);

    twai_stop();
    vTaskDelay(pdMS_TO_TICKS(10));
    twai_driver_uninstall();
    driver_installed = false;

    twai_general_config_t g_config = TWAI_GENERAL_CONFIG_DEFAULT(
        (gpio_num_t)TXD2, (gpio_num_t)RXD2, TWAI_MODE_NORMAL);
    twai_filter_config_t f_config = TWAI_FILTER_CONFIG_ACCEPT_ALL();

    if (twai_driver_install(&g_config, &t_config, &f_config) != ESP_OK) {
        printf("[CAN] 重装驱动失败\r\n");
        if (old_rate != bitrate_kbps) {
            printf("[CAN] 尝试恢复旧速率 %lu kbps...\r\n", old_rate);
            CAN_SetBitrate(old_rate);
        }
        return ESP_FAIL;
    }
    if (twai_start() != ESP_OK) {
        printf("[CAN] 重启驱动失败\r\n");
        return ESP_FAIL;
    }

    uint32_t alerts = TWAI_ALERT_RX_DATA | TWAI_ALERT_ERR_PASS |
                      TWAI_ALERT_BUS_ERROR | TWAI_ALERT_RX_QUEUE_FULL |
                      TWAI_ALERT_TX_IDLE | TWAI_ALERT_TX_SUCCESS |
                      TWAI_ALERT_TX_FAILED;
    twai_reconfigure_alerts(alerts, nullptr);

    CAN_bitrate_kbps = bitrate_kbps;
    driver_installed = true;
    printf("[CAN] 速率切换: %lu kbps\r\n", bitrate_kbps);

    if (can_task_handle) vTaskResume(can_task_handle);
    return ESP_OK;
}

void CAN_UpdateRate(uint32_t bitrate_kbps) {
    if (CAN_SetBitrate(bitrate_kbps) == ESP_OK)
        printf("[CAN] 当前速率: %lu kbps\r\n", bitrate_kbps);
    else
        printf("[CAN] 速率更新失败\r\n");
}

/*============================================================================
 * CAN 发送
 *============================================================================*/
void CAN_SendMessage(twai_message_t message) {
    CAN_Send(message.identifier, message.data, message.data_length_code, message.extd);
}

void CAN_Send(uint32_t CAN_ID, uint8_t *Data, uint8_t Data_length, bool Frame_type) {
    twai_message_t msg;
    msg.identifier = CAN_ID;
    msg.rtr = 0;

    // 标准帧 ID 溢出时自动升级为扩展帧
    if (!Frame_type && CAN_ID > 0x7FF) {
        printf("[CAN] 警告: 标准帧ID 0x%lX 溢出, 自动升级为扩展帧\r\n", CAN_ID);
        msg.extd = 1;
    } else {
        msg.extd = Frame_type ? 1 : 0;
    }

    // >8 字节自动分帧发送
    if (Data_length > 8) {
        uint16_t frame_count = Data_length / 8;
        for (int i = 0; i < frame_count; i++) {
            msg.data_length_code = 8;
            memcpy(msg.data, Data + (i * 8), 8);
            twai_transmit(&msg, pdMS_TO_TICKS(1000));
        }
        uint8_t remainder = Data_length % 8;
        if (remainder) {
            msg.data_length_code = remainder;
            memcpy(msg.data, Data + (Data_length - remainder), remainder);
            twai_transmit(&msg, pdMS_TO_TICKS(1000));
        }
    } else {
        msg.data_length_code = Data_length;
        if (Data_length > 0) {
            memcpy(msg.data, Data, Data_length);
        }
        twai_transmit(&msg, pdMS_TO_TICKS(1000));
    }

    // 记录发送签名用于回显过滤
    echo_filter_add(CAN_ID, msg.extd, Data_length > 8 ? 8 : Data_length, Data);
}

/*============================================================================
 * 速率统计
 *============================================================================*/
static void update_can_stats(void) {
    unsigned long now = millis();
    if (now - g_last_stats_time >= CAN_STATS_INTERVAL_MS) {
        float elapsed = (now - g_last_stats_time) / 1000.0f;
        CAN_rx_rate = g_rx_total / elapsed;
        CAN_tx_rate = g_tx_total / elapsed;
        CAN_rx_count = g_rx_total;
        CAN_tx_count = g_tx_total;
        printf("[CAN] RX: %.1f fps (%lu帧) | TX: %.1f fps (%lu帧)\r\n",
               CAN_rx_rate, g_rx_total, CAN_tx_rate, g_tx_total);
        g_rx_total = 0;
        g_tx_total = 0;
        g_last_stats_time = now;
    }
}

/*============================================================================
 * CANTask — 1ms 循环，目标 1000Hz
 *============================================================================*/
void CANTask(void *parameter) {
    // 分配 PSRAM 环形缓冲区
    can_ring = (CAN_Frame *)heap_caps_malloc(
        sizeof(CAN_Frame) * CAN_RING_SIZE, MALLOC_CAP_SPIRAM);
    if (!can_ring) {
        printf("[CAN] PSRAM 分配失败!\r\n");
        vTaskDelete(nullptr);
        return;
    }
    memset(can_ring, 0, sizeof(CAN_Frame) * CAN_RING_SIZE);

    can_ring_mutex = xSemaphoreCreateMutex();
    if (!can_ring_mutex) {
        printf("[CAN] 互斥锁创建失败!\r\n");
        vTaskDelete(nullptr);
        return;
    }

    static unsigned long prev_bus_error_time = 0;

    while (1) {
        if (!driver_installed) {
            vTaskDelay(pdMS_TO_TICKS(10));
            continue;
        }

        uint32_t alerts_triggered;
        twai_read_alerts(&alerts_triggered, pdMS_TO_TICKS(CAN_POLLING_RATE_MS));
        twai_status_info_t twai_status;
        twai_get_status_info(&twai_status);

        // ---- 总线告警 ----
        if (alerts_triggered & TWAI_ALERT_ERR_PASS) {
            printf("[CAN] 告警: 进入 Error Passive 状态\r\n");
        }
#if COMMUNICATION_FAILURE_ENABLE
        if (alerts_triggered & TWAI_ALERT_BUS_ERROR) {
            unsigned long now = millis();
            if (now - prev_bus_error_time >= BUS_ERROR_INTERVAL_MS) {
                printf("[CAN] 提示: 检查总线上是否有其他设备且波特率一致\r\n");
                prev_bus_error_time = now;
            }
        }
#endif
        if (alerts_triggered & TWAI_ALERT_RX_QUEUE_FULL) {
            printf("[CAN] 告警: RX队列满! 丢帧: RX缓冲=%ld RX丢失=%ld RX溢出=%ld\r\n",
                   twai_status.msgs_to_rx, twai_status.rx_missed_count,
                   twai_status.rx_overrun_count);
        }
        if (alerts_triggered & TWAI_ALERT_TX_FAILED) {
            printf("[CAN] 告警: 发送失败 TX错误计数=%ld TX失败=%ld\r\n",
                   twai_status.tx_error_counter, twai_status.tx_failed_count);
        }
        if (alerts_triggered & TWAI_ALERT_TX_SUCCESS) {
            g_tx_total++;
        }

        // ---- 接收帧 → 环形缓冲区 ----
        if (alerts_triggered & TWAI_ALERT_RX_DATA) {
            twai_message_t msg;
            while (twai_receive(&msg, 0) == ESP_OK) {
                // 自收回显过滤
                if (echo_filter_match(msg.identifier, msg.extd,
                                      msg.data_length_code, msg.data)) {
                    continue;  // 跳过自己发出的帧
                }

                // 构造环形缓冲区条目
                CAN_Frame frame;
                frame.id = msg.identifier;
                frame.extd = msg.extd ? 1 : 0;
                frame.dlc = msg.data_length_code;
                frame.timestamp_ms = CAN_GetTimestamp();
                if (msg.data_length_code > 0 && msg.data_length_code <= 8) {
                    memcpy(frame.data, msg.data, msg.data_length_code);
                } else {
                    memset(frame.data, 0, 8);
                }

                // 写入环形缓冲区
                if (xSemaphoreTake(can_ring_mutex, pdMS_TO_TICKS(5)) == pdTRUE) {
                    can_ring_push(&frame);
                    xSemaphoreGive(can_ring_mutex);
                }
                g_rx_total++;
            }
        }

        update_can_stats();
        vTaskDelay(pdMS_TO_TICKS(CAN_LOOP_INTERVAL_MS));
    }
    vTaskDelete(nullptr);
}

/*============================================================================
 * ProcessCommand — 帧协议命令分发（TCP 和 Serial 共用）
 *
 * 载荷格式：
 *   [1B 帧类型] [2B 命令字] [命令参数...]
 *   帧类型 + 命令字 + 参数都在载荷中，类型已由调用方剥离
 *============================================================================*/
void ProcessCommand(uint8_t *buf, uint16_t len) {
    if (len < 1) return;

    uint8_t frame_type = buf[0];

    switch (frame_type) {

        // ---- 命令请求 ----
        case FRAME_CMD_REQ: {
            if (len < 3) return;
            uint16_t cmd = (buf[1] << 8) | buf[2];

            if (cmd == CMD_CAN_SEND && len >= 8) {
                // 0A 0C + 4B ID + 1B extd + N字节 data
                uint32_t id = (buf[3] << 24) | (buf[4] << 16) | (buf[5] << 8) | buf[6];
                uint8_t extd = buf[7];
                uint8_t dlc = len - 8;
                CAN_Send(id, buf + 8, dlc > 8 ? 8 : dlc, extd != 0);
                printf("[CMD] CAN发送 ID=0x%lX extd=%d len=%d\r\n", id, extd, dlc);
            }
            else if (cmd == CMD_QUERY_IP) {
                // 设置标志位，由 TCPTask/SerialTask 各自响应
                extern uint8_t g_ip_query_flag;
                g_ip_query_flag = 1;
                printf("[CMD] 查询WiFi IP\r\n");
            }
            else if (cmd == CMD_QUERY_CAN) {
                extern uint8_t g_can_query_flag;
                g_can_query_flag = 1;
                printf("[CMD] 查询CAN缓冲区\r\n");
            }
            else if (cmd == CMD_SET_CAN_RATE && len >= 7) {
                uint32_t rate = (buf[3] << 24) | (buf[4] << 16) | (buf[5] << 8) | buf[6];
                printf("[CMD] 设置CAN速率: %lu kbps\r\n", rate);
                CAN_UpdateRate(rate);
            }
            else if (cmd == CMD_QUERY_RTC) {
                extern uint8_t g_rtc_query_flag;
                g_rtc_query_flag = 1;
                printf("[CMD] 查询RTC时间\r\n");
            }
            else {
                printf("[CMD] 未知命令: 0x%04X (len=%d)\r\n", cmd, len);
            }
            break;
        }

        // ---- CAN 发送帧（类型 0x04，简化版无命令头）----
        case FRAME_CAN_SEND: {
            if (len < 7) return;
            uint32_t id = (buf[1] << 24) | (buf[2] << 16) | (buf[3] << 8) | buf[4];
            uint8_t extd = buf[5];
            uint8_t dlc = len - 6;
            CAN_Send(id, buf + 6, dlc > 8 ? 8 : dlc, extd != 0);
            printf("[CMD] CAN发送(直通) ID=0x%lX extd=%d len=%d\r\n", id, extd, dlc);
            break;
        }

        default:
            printf("[CMD] 未知帧类型: 0x%02X\r\n", frame_type);
            break;
    }
}
