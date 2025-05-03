#include <Arduino.h>
#include <WiFi.h>
#include <time.h>

#include <FastLED.h>
#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <iarduino_ADC_CS1237.h>

// ADC関連
const uint8_t HX711_dout_1 = 7;
const uint8_t HX711_dout_2 = 13;
const uint8_t HX711_dout_3 = 1;
const uint8_t HX711_dout_4 = 44;

const uint8_t HX711_sck_1 = 5;
const uint8_t HX711_sck_2 = 15;
const uint8_t HX711_sck_3 = 3;
const uint8_t HX711_sck_4 = 43;



//iarduino_ADC_CS1237 adc1(HX711_sck_1,HX711_dout_1); //SCLK, DATA
//iarduino_ADC_CS1237 adc2(HX711_sck_2,HX711_dout_2); //SCLK, DATA
iarduino_ADC_CS1237 adc3(HX711_sck_3,HX711_dout_3); //SCLK, DATA
//iarduino_ADC_CS1237 adc4(HX711_sck_4,HX711_dout_4); //SCLK, DATA
//iarduino_ADC_CS1237* adc_array[] = { &adc1, &adc2, &adc3, &adc4 };
iarduino_ADC_CS1237* adc_array[] = { &adc3 };

//ロードセル個数
const int load_cell_num = sizeof(adc_array) / sizeof(adc_array[0]);

// adc計測値と重量gの変換係数
float calibrationValues[load_cell_num] = {195.6042};


//データ送信先のURL
const char* serverUrl = "http://192.168.3.30:5000/post_data"; // 送信先サーバーのURL
//const char* serverUrl = "https://script.google.com/macros/s/---/exec";

// WiFi接続設定
const char* ssid = "-";
const char* password = "-";

//LED
const static uint8_t PIN_LED    = 21;   // 本体フルカラーLEDの使用端子（G21）
const static uint8_t NUM_LEDS   = 1;    // 本体フルカラーLEDの数
CRGB leds[NUM_LEDS];    // FastLEDで制御するLEDの数を指定して使用する準備

// ロードセル関連 計算用
int32_t tare_offsets[load_cell_num] = {0}; // 風袋引き
float loadCell_values[load_cell_num] = {0.0}; // 計測値 g

// 配信頻度調整用
uint32_t current_time = millis();
uint32_t last_post_time = millis();
const uint32_t post_rate_ms = 100; // 送信周期 ms


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

void set_ADC_params(iarduino_ADC_CS1237* adc){
  bool i;
  // ADCの設定（構成）
  i=adc->setPulseWidth(10);    if( !i ){ USBSerial.println("パルス幅エラー"  ); } // SCLラインのパルス幅 デフォルトは5us。長い配線ではパルス幅を増加させる必要がある。この関数はbegin()の前に呼び出す。
  i=adc->begin();              if( !i ){ USBSerial.println("開始エラー"  ); }   // ADCの動作を開始
  i=adc->setPinVrefOut(true);  if( !i ){ USBSerial.println("VrefOutエラー"); }  // VrefOutピン出力の有効化。デフォルトはtrue。VrefOutが有効になると、チップの電源電圧（Vcc）が出力され、これをVrefInに供給できる。
  i=adc->setVrefIn(2.5);       if( !i ){ USBSerial.println("VrefInエラー" ); }  // VrefInに供給される基準電圧を設定する。デフォルトは5V。VrefInは1.5VからVcc+0.1Vまでの外部電圧、またはVrefOutからの電源電圧（Vcc）を受け取れる。
  i=adc->setSpeed(10);         if( !i ){ USBSerial.println("サンプリングレートエラー"  ); }   // サンプリングレート デフォルト10Hzで、10, 40, 640, 1280Hzに設定可能。
  i=adc->setPGA(128);            if( !i ){ USBSerial.println("ゲインエラー"   ); } // ゲイン デフォルト128で、1, 2, 64, 128に設定可能。測定可能な電圧範囲は±0.5 VrefIn / PGA
  i=adc->setChannel(0);        if( !i ){ USBSerial.println("チャンネルエラー"); } // ADCチャンネルの選択。0-チャンネルA（デフォルト）、1-予約済み、2-温度、3-内部短絡。
  delay(100);
}

void show_ADC_params(iarduino_ADC_CS1237* adc){
  // ADC設定の表示:
  bool pin   = adc->getPinVrefOut();                                     // VrefOutピンの状態を取得する。返り値はtrue=有効、false=無効
  uint16_t speed = adc->getSpeed();                                          // 現在のサンプリングレート（Hz）を取得する。
  uint8_t  gain  = adc->getPGA();                                            // 現在のゲインを取得する。
  uint8_t  chan  = adc->getChannel();                                        // 使用しているADCチャンネルを取得する。
  uint16_t width = adc->getPulseWidth();                                     // パルス幅を取得する。
  float    Vref  = adc->getVrefIn();                                         // 関数getVoltage()が返す電圧計算に使用するVrefIn基準電圧の値を取得する。
  // 読み取ったADC設定の表示:
  USBSerial.println( (String) "VrefOutピン:"+(pin?"有効":"無効")); //
  USBSerial.println( (String) "サンプリングレート: "+speed+" Hz"); //
  USBSerial.println( (String) "ゲイン: "+gain+"倍"); //
  USBSerial.println( (String) "使用チャンネル: "+chan); //
  USBSerial.println( (String) "SCLライン パルス幅: "+width + " us"); //
  USBSerial.println( (String) "基準電圧VrefIn: "+Vref+" V"); //
}

void calculate_tare_offsets(unsigned long duration){
  // durationミリ秒間の計測値の平均を使って風袋引きの値を求める。

  unsigned long startTime = millis();
  int32_t sum_array[load_cell_num] = {0};
  int32_t count = 0;

  while (millis() - startTime < duration) {
    for (int i=0; i<load_cell_num; i++){
      sum_array[i] += adc_array[i]->analogRead(); // ADCそれぞれの計測値を累積
    }
    count++;
    delay(10);
    }

  if (count > 0) {
    for (int i = 0; i < load_cell_num; i++){
      tare_offsets[i] = sum_array[i] / count;
      }
      USBSerial.println("風袋引き完了");
    }
}

void get_loadCell_values(){
  for (int i=0; i<load_cell_num; i++){
    int32_t adc_value = adc_array[i]->analogRead();
    loadCell_values[i] = -(adc_value - tare_offsets[i]) / calibrationValues[i];
  }
}

void init_loadCells(){  
  // ADCの設定
  for (int i=0; i<load_cell_num; i++){
    USBSerial.println((String) "ADC番号 " + i + " :");
    set_ADC_params(adc_array[i]);
    show_ADC_params(adc_array[i]);
    USBSerial.println("");
  }

  // 5000ms計測して風袋引きのオフセットを計算
  calculate_tare_offsets(5000); 
}


void setup(){
  USBSerial.begin(115200);
  delay(1000);

  led_setup();
  init_wifi();
  configTzTime("JST-9", "ntp.nict.jp", "ntp.jst.mfeed.ad.jp");
  init_loadCells();

}

void loop(){
// ADC値と電圧をディスプレイに表示します:
  get_loadCell_values(); // ロードセルの値を読んでloadCell_values配列に保存
  USBSerial.print("ADC="); USBSerial.print(loadCell_values[0]);        //   ADCの符号付き値を読み取り、表示します。範囲は0〜±8388607です。
  USBSerial.println(" g"); delay(1000);

  current_time = millis();
  // millis()は約50日周期でオーバーフローするらしい。後ろの条件はその対応
  if (current_time - last_post_time > post_rate_ms || (current_time < last_post_time && (UINT32_MAX - last_post_time + current_time > post_rate_ms))){
    String jsonString = pack_json_data(); //jsonにタイムスタンプ, ロードセルのデータを詰める
    postRequest(jsonString); //サーバにデータ送信
    last_post_time = millis();
  }

  delay(100);
}