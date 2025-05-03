#include <Arduino.h>
#include <WiFi.h>
#include <time.h>

#include <FastLED.h>
#include <HX711_ADC.h>
#include <ArduinoJson.h>
#include <HTTPClient.h>

//データ送信先のURL
const char* serverUrl = "http://192.168.3.30:5000/post_data"; // 送信先サーバーのURL
//const char* serverUrl = "https://script.google.com/macros/s/hogehoge/exec";

// WiFi接続設定
const char* ssid = "SSID";
const char* password = "PASSWORD";

//LED
const static uint8_t PIN_LED    = 21;   // 本体フルカラーLEDの使用端子（G21）
const static uint8_t NUM_LEDS   = 1;    // 本体フルカラーLEDの数
CRGB leds[NUM_LEDS];    // FastLEDで制御するLEDの数を指定して使用する準備

// ピンアウト
const uint8_t HX711_dout_1 = 7;
const uint8_t HX711_dout_2 = 13;
const uint8_t HX711_dout_3 = 1;
const uint8_t HX711_dout_4 = 44;

const uint8_t HX711_sck_1 = 5;
const uint8_t HX711_sck_2 = 15;
const uint8_t HX711_sck_3 = 3;
const uint8_t HX711_sck_4 = 43;


const uint8_t load_cell_num = 4; //ロードセル個数

//HX711 constructor (dout pin, sck pin)
HX711_ADC LoadCell_1(HX711_dout_1, HX711_sck_1); //HX711 1
HX711_ADC LoadCell_2(HX711_dout_2, HX711_sck_2); //HX711 2
HX711_ADC LoadCell_3(HX711_dout_3, HX711_sck_3); //HX711 3
HX711_ADC LoadCell_4(HX711_dout_4, HX711_sck_4); //HX711 4

float loadCell_values[load_cell_num] = {0.0};
static bool newDataReady = false;

uint32_t current_time = millis();
uint32_t last_post_time = millis();
const uint32_t post_rate_ms = 1000;


void led_setup(){
  FastLED.addLeds<WS2812B, PIN_LED, GRB>(leds, NUM_LEDS); // LED型式、使用端子、LED数
  // LED初期点灯色
  leds[0] = CRGB(0, 0, 100);
  FastLED.show();
}

void show_led(uint8_t r,uint8_t g,uint8_t b){
  leds[0] = CRGB(r, g, b);
  FastLED.show();
}

void init_loadCells(){
  // HX711
  float calibrationValue_1 = 209.2094; // calibration value load cell 1
  float calibrationValue_2 = 206.5882; // calibration value load cell 2
  float calibrationValue_3 = 195.6042; // calibration value load cell 3
  float calibrationValue_4 = 212.2887; // calibration value load cell 4

  LoadCell_1.begin();
  LoadCell_2.begin();
  LoadCell_3.begin();
  LoadCell_4.begin();

  unsigned long stabilizingtime = 2000; // 風袋引き前の静定時間
  boolean _tare = true; //風袋引きしない場合はfalseにする

  //ロードセルの準備完了判定用
  byte loadcell_1_rdy = 0;
  byte loadcell_2_rdy = 0;
  byte loadcell_3_rdy = 0;
  byte loadcell_4_rdy = 0;

  while ((loadcell_1_rdy + loadcell_2_rdy + loadcell_3_rdy + loadcell_4_rdy) < load_cell_num) { //起動, 安定化, 風袋引きを同時に実行する
    if (!loadcell_1_rdy) loadcell_1_rdy = LoadCell_1.startMultiple(stabilizingtime, _tare);
    if (!loadcell_2_rdy) loadcell_2_rdy = LoadCell_2.startMultiple(stabilizingtime, _tare);
    if (!loadcell_3_rdy) loadcell_3_rdy = LoadCell_3.startMultiple(stabilizingtime, _tare);
    if (!loadcell_4_rdy) loadcell_4_rdy = LoadCell_4.startMultiple(stabilizingtime, _tare);
  }
  if (LoadCell_1.getTareTimeoutFlag()) {
    USBSerial.println("Timeout, check MCU>HX711 no.1 wiring and pin designations");
  }
  if (LoadCell_2.getTareTimeoutFlag()) {
    USBSerial.println("Timeout, check MCU>HX711 no.2 wiring and pin designations");
  }
  if (LoadCell_3.getTareTimeoutFlag()) {
    USBSerial.println("Timeout, check MCU>HX711 no.3 wiring and pin designations");
  }
  if (LoadCell_4.getTareTimeoutFlag()) {
    USBSerial.println("Timeout, check MCU>HX711 no.4 wiring and pin designations");
  }
  LoadCell_1.setCalFactor(calibrationValue_1); // user set calibration value (float)
  LoadCell_2.setCalFactor(calibrationValue_2); // user set calibration value (float)
  LoadCell_3.setCalFactor(calibrationValue_3); // user set calibration value (float)
  LoadCell_4.setCalFactor(calibrationValue_4); // user set calibration value (float)
  USBSerial.println("Startup is complete");
}

void get_data_from_loadCells(){
  
  // check for new data/start next conversion:
  if (LoadCell_1.update()) newDataReady = true;
  LoadCell_2.update();
  LoadCell_3.update();
  LoadCell_4.update();

  //get smoothed value from data set
  if ((newDataReady)) {
    loadCell_values[0] = LoadCell_1.getData();
    loadCell_values[1] = LoadCell_2.getData();
    loadCell_values[2] = LoadCell_3.getData();
    loadCell_values[3] = LoadCell_4.getData();

    USBSerial.print("Load_cell output val: ");
    for (int i = 0; i < load_cell_num; i++) {
      USBSerial.print(loadCell_values[i]);
      USBSerial.print(", ");
    }
    USBSerial.println("");
    newDataReady = false;
  }
}

void init_wifi(){
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(1000);
    USBSerial.println("Connecting to WiFi...");
  }
}

String getISO8601Time() {
  time_t now;
  struct tm timeinfo;
  char isoTime[30];

  if (!getLocalTime(&timeinfo)) {
    delay(3000);
  }
  
  unsigned long ms = millis() % 1000;
  strftime(isoTime, sizeof(isoTime), "%Y-%m-%dT%H:%M:%S", &timeinfo);
  sprintf(isoTime + strlen(isoTime), ".%03lu+0900", ms);

  return String(isoTime);
}

String pack_json_data() {
  JsonDocument jsonDoc;
  String isoTime = getISO8601Time();
  jsonDoc["timestamp"] = isoTime;

  JsonArray sensors = jsonDoc.createNestedArray("sensors");
  for (int i = 0; i < load_cell_num; i++) {
    JsonObject sensor = sensors.createNestedObject();
    sensor["id"] = i + 1;
    sensor["value"] = loadCell_values[i];
    sensor["status"] = "OK"; //いつか死活監視書く
  }

  String jsonString;
  serializeJson(jsonDoc, jsonString);
  return jsonString;
}

void postRequest(const String& jsonString) {
  if (WiFi.status() == WL_CONNECTED) {
    //USBSerial.print("IP Address: ");
    //USBSerial.println(WiFi.localIP());
    HTTPClient http;
    http.begin(serverUrl);
    http.addHeader("Content-Type", "application/json");

    int httpResponseCode = http.POST(jsonString);

    if (httpResponseCode == 200) {
      String response = http.getString();
      USBSerial.println("Response code: " + String(httpResponseCode));
      USBSerial.println("Response: " + response);
      show_led(0,100,0);
    } else {
      USBSerial.println("Error code: " + String(httpResponseCode));
      USBSerial.println(http.errorToString(httpResponseCode));
      show_led(100,0,0);
    }
    http.end();
  } else {
    USBSerial.println("Error: WiFi not connected");
  }
}

void setup() {
  USBSerial.begin(115200);
  delay(1000);

  led_setup();
  init_wifi();
  configTzTime("JST-9", "ntp.nict.jp", "ntp.jst.mfeed.ad.jp");
  init_loadCells();
}

void loop() {
  get_data_from_loadCells(); //読み出したデータはloadCell_values配列に保存

  current_time = millis();
  // 約49日に一度millis()はオーバーフローするのでcurrent_time < last_post_timeの条件を書いてある
  if (current_time - last_post_time > post_rate_ms || (current_time < last_post_time && (UINT32_MAX - last_post_time + current_time > post_rate_ms))){
    String jsonString = pack_json_data(); //jsonにタイムスタンプ, ロードセルのデータを詰める
    postRequest(jsonString); //サーバにデータ送信
    last_post_time = millis();
  }
}