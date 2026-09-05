#include <Arduino.h>
#include "WS_Bluetooth.h"
#include "WS_RS485.h"
#include "WS_CAN.h"
#include "WS_RTC.h"
#include "WS_WIFI.h"


uint32_t Simulated_time=0;      // Analog time counting

/********************************************************  Initializing  ********************************************************/
void setup() {
  I2C_Init();
  RS485_Init();
  CAN_Init();
  RTC_Init();
  Bluetooth_Init();   // BLE 先于 WiFi 初始化，避免无线模块冲突
  WIFI_Init();

  printf("ESP32-BLE-CAN ready. BLE: ESP32-BLE-CAN | WiFi AP: ESP32-S3-RS485-CAN\r\n");
}

/**********************************************************  While  **********************************************************/
void loop() {

}
