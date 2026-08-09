/*============================================================================
 * WS_RTC.cpp — RTC 时钟（精简版）
 *
 * 仅保留 PCF85063 初始化 + 按需读时间。
 * 砍掉原版的 RTCTask、Continuous_Task、TimerEvent_* 全部定时事件逻辑。
 *============================================================================*/
#include "WS_RTC.h"

void RTC_Init(void) {
    PCF85063_Init();
    RTC_Update();
    printf("[RTC] PCF85063 时钟就绪\r\n");
}

void RTC_Update(void) {
    PCF85063_Read_Time(&datetime);
}

void RTC_GetTimeStr(char *buf, size_t buf_size) {
    RTC_Update();
    datetime_to_str(buf, datetime);
}
