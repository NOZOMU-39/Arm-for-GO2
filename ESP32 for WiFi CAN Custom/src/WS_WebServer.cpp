/*============================================================================
 * WS_WebServer.cpp — HTTP 路由处理 + 内嵌 SPA Web 控制台
 *
 * 单页应用 (SPA)，功能：
 *   - 通道状态监控 (WiFi STA/AP、CAN 速率、RX/TX 帧率)
 *   - CAN 帧发送 (标准帧/扩展帧, hex 数据)
 *   - CAN 帧接收实时显示 (100ms 轮询, 双速率: 本地渲染/ESP32真实)
 *   - 设置面板 (WiFi 凭据 + CAN 波特率 + NVS 保存)
 *
 * HTML 用 C++11 raw string literal 内嵌在固件中。
 * 开发时：修改独立 CAN_WiFi助手.html → 浏览器调好 → 复制粘贴进下方 R"====(...)===="。
 *============================================================================*/
#include "WS_WebServer.h"

static WebServer server(80);

/*============================================================================
 * 内嵌 SPA 页面 (raw string literal)
 *
 * 技术路线：C++11 R"====(raw string)====" 语法。
 * 这样 HTML 在编译时嵌入固件，烧录一次即可，
 * 不需要 SPIFFS/LittleFS 等额外文件系统。
 *============================================================================*/
static const char PAGE_MAIN[] = R"====(
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>ESP32 WiFi CAN</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:"Microsoft YaHei","PingFang SC",sans-serif;background:#1a1a2e;color:#eee;padding:16px;max-width:720px;margin:auto}
h1{text-align:center;color:#00d4ff;margin-bottom:12px;font-size:1.3em;display:flex;align-items:center;justify-content:center;gap:12px}
h1 .gear{cursor:pointer;font-size:0.8em;opacity:0.6;transition:opacity 0.2s}
h1 .gear:hover{opacity:1}
.card{background:#16213e;border-radius:10px;padding:14px;margin-bottom:12px;border:1px solid #0f3460}
.card-title{font-size:0.95em;color:#00d4ff;margin-bottom:8px;padding-bottom:6px;border-bottom:1px solid #0f3460;display:flex;justify-content:space-between;align-items:center}
button{background:#0f3460;color:#00d4ff;border:1px solid #00d4ff;padding:7px 14px;border-radius:6px;cursor:pointer;font-size:0.85em;margin:3px}
button:hover{background:#1a5276}
button:disabled{opacity:0.4;cursor:not-allowed}
button.primary{background:#00d4ff;color:#1a1a2e;font-weight:bold;border:none}
button.primary:hover{background:#33ddff}
input,select,textarea{background:#0d1b36;color:#eee;border:1px solid #0f3460;padding:7px;border-radius:4px;font-size:0.85em;font-family:inherit}
input{width:100%;margin:3px 0}
select{margin:3px}
textarea{width:100%;height:220px;resize:vertical;margin-top:6px;font-family:"Consolas","Courier New",monospace;font-size:0.78em;white-space:pre-wrap;word-break:break-all;background:#0a1120}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.row label{white-space:nowrap;color:#aaa;font-size:0.82em;min-width:45px}
.hint{color:#888;font-size:0.75em;margin-top:4px}
.tag{display:inline-block;font-size:0.72em;padding:2px 7px;border-radius:10px;margin-left:3px}
.tag.green{background:#1b5e20;color:#a5d6a7}
.tag.yellow{background:#4a3f00;color:#ffd54f}
.tag.red{background:#4a0000;color:#fcc}
.tag.cyan{background:#004d40;color:#80deea}
#settingsPanel{display:none}
.fps{font-family:"Consolas",monospace;color:#ffd54f;font-size:0.85em}
#statusBar{font-size:0.82em;line-height:1.6}
</style>
</head>
<body>

<h1>
  ESP32 WiFi CAN
  <span class="gear" onclick="toggleSettings()" title="设置">&#9881;</span>
</h1>

<!-- 通道状态 -->
<div class="card">
  <div class="card-title">通道状态</div>
  <div id="statusBar" class="hint">加载中...</div>
</div>

<!-- 设置面板 (默认隐藏) -->
<div class="card" id="settingsPanel">
  <div class="card-title">设置</div>
  <div class="hint" style="margin-bottom:8px">主力通道：笔记本热点名，配一次永不变。留空=不启用STA</div>
  <div class="row"><label>STA热点:</label><input type="text" id="sta_ssid" placeholder="MyHotspot" style="flex:1"></div>
  <div class="row" style="margin-top:4px"><label>STA密码:</label><input type="text" id="sta_psk" placeholder="热点密码" style="flex:1"></div>
  <div style="margin-top:8px;padding-top:8px;border-top:1px solid #0f3460">
    <div class="hint" style="margin-bottom:4px">备用通道：AP始终在线</div>
    <div class="row"><label>AP名称:</label><input type="text" id="ap_ssid" value="ESP32-WiFi-CAN" style="flex:1"></div>
    <div class="row" style="margin-top:4px"><label>AP密码:</label><input type="text" id="ap_psk" value="12345678" style="flex:1"></div>
  </div>
  <div style="margin-top:8px;padding-top:8px;border-top:1px solid #0f3460">
    <div class="row"><label>CAN速率:</label>
      <select id="can_rate" style="width:130px">
        <option value="25">25 kbps</option><option value="50">50 kbps</option>
        <option value="100">100 kbps</option><option value="125">125 kbps</option>
        <option value="250">250 kbps</option><option value="500">500 kbps</option>
        <option value="800">800 kbps</option><option value="1000" selected>1 Mbps</option>
      </select>
    </div>
  </div>
  <button class="primary" onclick="saveSettings()" style="width:100%;margin-top:8px">保存设置</button>
  <div id="saveResult" class="hint" style="margin-top:6px"></div>
</div>

<!-- 发送 CAN -->
<div class="card">
  <div class="card-title">发送 CAN <span class="fps" id="txFps">TX: 0 fps</span></div>
  <div class="row">
    <label>ID: 0x</label>
    <input type="text" id="canId" value="0000007B" maxlength="8" style="width:110px"
           oninput="this.value=this.value.replace(/[^0-9a-fA-F]/g,'')">
    <select id="canExtd" style="width:100px">
      <option value="0">标准帧</option><option value="1">扩展帧</option>
    </select>
  </div>
  <div class="row" style="margin-top:6px">
    <label>数据:</label>
    <input type="text" id="canData" value="11 22 33 44 55 66 77 88" placeholder="hex空格分隔 1-8字节" style="flex:1">
    <button class="primary" onclick="sendCAN()">发送</button>
  </div>
</div>

<!-- 接收 CAN -->
<div class="card">
  <div class="card-title">接收 CAN <span class="fps" id="rxFps">RX: 0 fps</span></div>
  <textarea id="rxArea" readonly placeholder="等待接收..."></textarea>
  <div style="margin-top:6px;display:flex;gap:8px;align-items:center">
    <button onclick="document.getElementById('rxArea').value=''">清空</button>
    <label style="color:#aaa;font-size:0.82em;cursor:pointer">
      <input type="checkbox" id="autoScroll" checked> 自动滚动
    </label>
  </div>
</div>

<script>
// ====== 状态变量 ======
let txCount=0, txLast=Date.now(), txRate=0;
let rxCount=0, rxLast=Date.now(), rxRate=0;
let esp32RxRate=0;  // ESP32 内部真实 RX 帧率

// ====== 工具函数 ======
function el(id){return document.getElementById(id)}
function ts(){const d=new Date();return d.toLocaleTimeString('zh-CN',{hour12:false})+'.'+String(d.getMilliseconds()).padStart(3,'0')}

// ====== 设置面板 ======
function toggleSettings(){
  const p=el('settingsPanel');
  p.style.display=(p.style.display==='none'||p.style.display==='')?'block':'none';
}

// ====== 更新状态栏 ======
function updateStatus(){
  fetch('/getStatus').then(r=>r.json()).then(j=>{
    let html='';
    if(j.sta_connected){
      html+='STA <span class="tag green">已连接</span> '+j.sta_ip+' (可上网+控制)';
    }else if(j.sta_ssid){
      html+='STA <span class="tag yellow">连接中 '+j.sta_ssid+'</span>';
    }else{
      html+='STA <span class="tag red">未配置</span> (进设置配热点)';
    }
    html+='<br>AP <span class="tag cyan">在线</span> '+j.ap_ssid+' @ 192.168.4.1';
    html+='<br>CAN '+j.can_rate+'kbps | RX '+j.can_rx_rate.toFixed(1)+'fps TX '+j.can_tx_rate.toFixed(1)+'fps | '+j.firmware;
    el('statusBar').innerHTML=html;
    // 同步设置面板
    el('sta_ssid').value=j.sta_ssid||'';
    el('ap_ssid').value=j.ap_ssid;
    el('can_rate').value=j.can_rate;
    // 记录 ESP32 真实 RX 帧率用于接收区显示
    esp32RxRate=j.can_rx_rate||0;
  });
}

// ====== 接收 CAN 数据 ======
function pollCAN(){
  fetch('/getCANData').then(r=>r.json()).then(arr=>{
    if(!arr||arr.length===0||arr[0]==='')return;
    const now=Date.now();
    const auto=el('autoScroll').checked;
    // 批量构建字符串，一次赋值避免多次 DOM 重排
    let chunk='';
    for(let i=0;i<arr.length;i++){
      rxCount++;
      chunk+='['+ts()+'] '+arr[i]+'\n';
    }
    const ta=el('rxArea');
    ta.value+=chunk;
    // 限制文本区行数，超过 2000 行裁剪前半
    const lines=ta.value.split('\n');
    if(lines.length>2000) ta.value=lines.slice(-1500).join('\n');
    if(now-rxLast>=1000){
      rxRate=(rxCount/((now-rxLast)/1000)).toFixed(1);
      rxCount=0;rxLast=now;
    }
    // 显示: 本地渲染速率 / ESP32 真实速率
    el('rxFps').textContent='RX: '+rxRate+' / '+esp32RxRate.toFixed(0)+' fps';
    if(auto)ta.scrollTop=ta.scrollHeight;
  });
}

// ====== 发送 CAN ======
function sendCAN(){
  const id=el('canId').value.padStart(8,'0').toUpperCase();
  const extd=parseInt(el('canExtd').value);
  const dataStr=el('canData').value.trim();
  fetch('/CANSend',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({id:parseInt(id,16),extd:extd,data:dataStr})
  }).then(r=>r.text()).then(()=>{
    txCount++;
    const now=Date.now();
    if(now-txLast>=1000){txRate=(txCount/((now-txLast)/1000)).toFixed(1);txCount=0;txLast=now}
    el('txFps').textContent='TX: '+txRate+' fps';
  });
}

// ====== 保存设置 ======
function saveSettings(){
  const fd=new FormData();
  fd.append('sta_ssid',el('sta_ssid').value);
  fd.append('sta_psk',el('sta_psk').value);
  fd.append('ap_ssid',el('ap_ssid').value);
  fd.append('ap_psk',el('ap_psk').value);
  fd.append('can_rate',el('can_rate').value);
  fetch('/SaveSettings',{method:'POST',body:fd}).then(r=>r.text()).then(()=>{
    el('saveResult').innerHTML='<span style="color:#a5d6a7">已保存! 新设置立即生效</span>';
  });
}

// ====== 初始化 ======
updateStatus();
setInterval(pollCAN,100);
setInterval(updateStatus,3000);
</script>
</body>
</html>
)====";

/*============================================================================
 * HTTP 路由处理
 *============================================================================*/

// GET / — 主控制台 (SPA)
static void handleRoot(void) {
    server.send(200, "text/html", PAGE_MAIN);
    printf("[Web] 用户访问主控制台\r\n");
}

// GET /getStatus — 设备状态 JSON
static void handleGetStatus(void) {
    char json[512];
    snprintf(json, sizeof(json),
        "{"
        "\"ap_ssid\":\"%s\","
        "\"sta_ssid\":\"%s\","
        "\"sta_connected\":%s,"
        "\"sta_ip\":\"%s\","
        "\"can_rate\":%lu,"
        "\"can_rx_rate\":%.1f,"
        "\"can_tx_rate\":%.1f,"
        "\"can_rx_count\":%lu,"
        "\"can_tx_count\":%lu,"
        "\"firmware\":\"%s\""
        "}",
        g_ap_ssid,
        g_sta_ssid,
        g_sta_connected ? "true" : "false",
        g_sta_ip,
        CAN_bitrate_kbps,
        CAN_rx_rate,
        CAN_tx_rate,
        CAN_rx_count,
        CAN_tx_count,
        FIRMWARE_VERSION
    );
    server.send(200, "application/json", json);
}

// GET /getCANData — CAN 接收缓冲区 (JSON 数组)
// 每帧格式: "ID:0xXXXXXXXX extd:0/1 DLC:N HH HH ... [ms]"
// 每 100ms 轮询一次，200帧上限支持完整 1000fps 显示
static void handleGetCANData(void) {
    String json = "[";
    CAN_Frame frame;
    int count = 0;
    while (count < 200 && CAN_ReadFrame(&can_ring_web_tail, &frame)) {
        if (count > 0) json += ',';

        char line[100];
        int off = snprintf(line, sizeof(line),
            "ID:0x%lX %c DLC:%d ",
            frame.id, frame.extd ? 'E' : 'S', frame.dlc);
        for (int i = 0; i < frame.dlc && i < 8; i++) {
            off += snprintf(line + off, sizeof(line) - off, "%02X ", frame.data[i]);
        }
        off += snprintf(line + off, sizeof(line) - off, " [%lums]", frame.timestamp_ms);

        // 构建 JSON 字符串（line 不含 " \ 等需转义字符，直接拼接）
        json += '"';
        json += line;
        json += '"';
        count++;
    }
    json += ']';
    server.send(200, "application/json", json);
}

// POST /CANSend — 发送 CAN 帧
static void handleCANSend(void) {
    if (!server.hasArg("plain")) {
        server.send(400, "text/plain", "Missing body");
        return;
    }
    String body = server.arg("plain");
    // 简单 JSON 解析: {"id":123,"extd":0,"data":"11 22 33"}
    // 用 ArduinoJson 太重，手写简易解析
    uint32_t can_id = 0;
    uint8_t  extd = 0;
    String   hex_data;

    int id_pos = body.indexOf("\"id\":");
    if (id_pos >= 0) {
        can_id = strtoul(body.c_str() + id_pos + 5, nullptr, 10);
    }
    int extd_pos = body.indexOf("\"extd\":");
    if (extd_pos >= 0) {
        extd = body[extd_pos + 7] == '1' ? 1 : 0;
    }
    int data_pos = body.indexOf("\"data\":\"");
    if (data_pos >= 0) {
        int data_end = body.indexOf("\"", data_pos + 8);
        if (data_end > data_pos) {
            hex_data = body.substring(data_pos + 8, data_end);
        }
    }

    // 解析 hex 数据
    hex_data.trim();
    uint8_t buf[64];
    uint8_t len = 0;
    const char *p = hex_data.c_str();
    while (*p && len < 64) {
        while (*p == ' ') p++;
        if (!*p) break;
        char high = (*p >= 'a' && *p <= 'f') ? (*p - 'a' + 10) :
                    (*p >= 'A' && *p <= 'F') ? (*p - 'A' + 10) :
                    (*p >= '0' && *p <= '9') ? (*p - '0') : -1;
        p++;
        if (!*p || high < 0) break;
        char low = (*p >= 'a' && *p <= 'f') ? (*p - 'a' + 10) :
                   (*p >= 'A' && *p <= 'F') ? (*p - 'A' + 10) :
                   (*p >= '0' && *p <= '9') ? (*p - '0') : -1;
        if (low < 0) break;
        buf[len++] = (high << 4) | low;
        p++;
    }

    if (len > 0) {
        CAN_Send(can_id, buf, len, extd != 0);
    }
    server.send(200, "text/plain", "OK");
}

// POST /CANSetRate — 设置 CAN 波特率
static void handleCANSetRate(void) {
    if (!server.hasArg("plain")) {
        server.send(400, "text/plain", "Missing body");
        return;
    }
    String body = server.arg("plain");
    int rate_pos = body.indexOf("\"rate\":");
    if (rate_pos >= 0) {
        uint32_t rate = strtoul(body.c_str() + rate_pos + 7, nullptr, 10);
        if (rate > 0) CAN_UpdateRate(rate);
    }
    server.send(200, "text/plain", "OK");
}

// POST /SaveSettings — 保存 WiFi 设置到 NVS
static void handleSaveSettings(void) {
    if (server.hasArg("sta_ssid")) strncpy(g_sta_ssid, server.arg("sta_ssid").c_str(), 32);
    if (server.hasArg("sta_psk"))  strncpy(g_sta_psk, server.arg("sta_psk").c_str(), 32);
    if (server.hasArg("ap_ssid"))  strncpy(g_ap_ssid, server.arg("ap_ssid").c_str(), 32);
    if (server.hasArg("ap_psk"))   strncpy(g_ap_psk, server.arg("ap_psk").c_str(), 32);
    if (server.hasArg("can_rate")) {
        uint32_t rate = server.arg("can_rate").toInt();
        if (rate > 0) CAN_UpdateRate(rate);
    }
    WIFI_SaveSettings();
    server.send(200, "text/plain", "Saved");
    printf("[Web] 设置已保存: sta=%s ap=%s can=%lu\r\n", g_sta_ssid, g_ap_ssid, CAN_bitrate_kbps);
}

// GET /GetRtcTime — 查询 RTC 时间
static void handleGetRtcTime(void) {
    char time_str[50];
    RTC_GetTimeStr(time_str, sizeof(time_str));
    server.send(200, "text/plain", time_str);
}

/*============================================================================
 * Web 服务器初始化 & 主循环
 *============================================================================*/
void WebServer_Init(void) {
    server.on("/", HTTP_GET, handleRoot);
    server.on("/getStatus", HTTP_GET, handleGetStatus);
    server.on("/getCANData", HTTP_GET, handleGetCANData);
    server.on("/CANSend", HTTP_POST, handleCANSend);
    server.on("/CANSetRate", HTTP_POST, handleCANSetRate);
    server.on("/SaveSettings", HTTP_POST, handleSaveSettings);
    server.on("/GetRtcTime", HTTP_GET, handleGetRtcTime);

    server.begin();
    printf("[Web] HTTP 服务器启动\r\n");
}

void WebServer_HandleClient(void) {
    server.handleClient();
}
