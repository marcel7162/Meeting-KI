// -----------------------------------------------------------------------------
// Meeting-KI – ESP32-S3 Firmware
//
// Nimmt Audio vom INMP441 (I2S-MEMS-Mikrofon) auf und streamt es als
// 16-kHz-Mono-PCM (16 Bit, little-endian) per TCP an den Python-Server.
//
// Ablauf:
//   1. Mit WLAN verbinden.
//   2. I2S-Peripherie fürs INMP441 einrichten.
//   3. TCP-Verbindung zum Server aufbauen.
//   4. Endlos: I2S-Samples lesen, in 16-Bit-PCM wandeln, per TCP senden.
//   5. Bei Verbindungsabbruch automatisch neu verbinden.
//
// LED-Status (falls STATUS_LED_PIN gesetzt):
//   - schnelles Blinken: kein WLAN
//   - langsames Blinken: WLAN ok, aber keine Server-Verbindung
//   - dauerhaft an:      verbunden und streamend
// -----------------------------------------------------------------------------
#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClient.h>
#include <driver/i2s.h>

#include "config.h"

// I2S-Port und Puffergrößen
static const i2s_port_t I2S_PORT = I2S_NUM_0;
static const int        DMA_BUF_COUNT = 8;
static const int        DMA_BUF_LEN   = 256;   // Samples pro DMA-Puffer

// Anzahl der Samples, die pro Leseblock verarbeitet/gesendet werden
static const int        SAMPLES_PER_READ = 512;

static WiFiClient client;

// 32-Bit-Rohsamples vom I2S, danach die gewandelten 16-Bit-Samples
static int32_t raw_samples[SAMPLES_PER_READ];
static int16_t pcm_samples[SAMPLES_PER_READ];

// ---------------------------------------------------------------------------
// Status-LED
// ---------------------------------------------------------------------------
static void ledSet(bool on) {
#if STATUS_LED_PIN >= 0
  digitalWrite(STATUS_LED_PIN, on ? HIGH : LOW);
#endif
}

static void ledBlink(int on_ms, int off_ms) {
#if STATUS_LED_PIN >= 0
  ledSet(true);
  delay(on_ms);
  ledSet(false);
  delay(off_ms);
#else
  delay(on_ms + off_ms);
#endif
}

// ---------------------------------------------------------------------------
// I2S einrichten (RX vom INMP441)
// ---------------------------------------------------------------------------
static void setupI2S() {
  i2s_config_t i2s_config = {
      .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
      .sample_rate = SAMPLE_RATE,
      .bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT,   // INMP441 liefert 24 Bit in 32-Bit-Frames
      .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,    // L/R-Pin auf GND -> linker Kanal
      .communication_format = I2S_COMM_FORMAT_STAND_I2S,
      .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
      .dma_buf_count = DMA_BUF_COUNT,
      .dma_buf_len = DMA_BUF_LEN,
      .use_apll = false,
      .tx_desc_auto_clear = false,
      .fixed_mclk = 0,
  };

  i2s_pin_config_t pin_config = {
      .bck_io_num = I2S_SCK_PIN,
      .ws_io_num = I2S_WS_PIN,
      .data_out_num = I2S_PIN_NO_CHANGE,
      .data_in_num = I2S_SD_PIN,
  };

  esp_err_t err = i2s_driver_install(I2S_PORT, &i2s_config, 0, NULL);
  if (err != ESP_OK) {
    Serial.printf("[I2S] Installation fehlgeschlagen: %d\n", err);
    return;
  }
  err = i2s_set_pin(I2S_PORT, &pin_config);
  if (err != ESP_OK) {
    Serial.printf("[I2S] Pin-Konfiguration fehlgeschlagen: %d\n", err);
    return;
  }
  Serial.println("[I2S] bereit");
}

// ---------------------------------------------------------------------------
// WLAN verbinden (blockiert, bis Verbindung steht)
// ---------------------------------------------------------------------------
static void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;

  Serial.printf("[WiFi] verbinde mit \"%s\" ...\n", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  while (WiFi.status() != WL_CONNECTED) {
    ledBlink(80, 80);  // schnelles Blinken: kein WLAN
    Serial.print(".");
  }
  Serial.printf("\n[WiFi] verbunden, IP: %s\n", WiFi.localIP().toString().c_str());
}

// ---------------------------------------------------------------------------
// Server verbinden
// ---------------------------------------------------------------------------
static bool connectServer() {
  if (client.connected()) return true;

  Serial.printf("[TCP] verbinde mit %s:%d ...\n", SERVER_HOST, SERVER_PORT);
  if (client.connect(SERVER_HOST, SERVER_PORT)) {
    client.setNoDelay(true);
    Serial.println("[TCP] Server verbunden");
    return true;
  }
  Serial.println("[TCP] Verbindung fehlgeschlagen");
  return false;
}

// ---------------------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\n=== Meeting-KI Firmware ===");

#if STATUS_LED_PIN >= 0
  pinMode(STATUS_LED_PIN, OUTPUT);
  ledSet(false);
#endif

  connectWiFi();
  setupI2S();
  connectServer();
}

// ---------------------------------------------------------------------------
void loop() {
  // Verbindungen sicherstellen
  if (WiFi.status() != WL_CONNECTED) {
    connectWiFi();
    return;
  }
  if (!client.connected()) {
    ledBlink(500, 500);  // langsames Blinken: WLAN ok, aber kein Server
    if (!connectServer()) {
      delay(1000);
      return;
    }
  }

  // Audio lesen
  size_t bytes_read = 0;
  esp_err_t err = i2s_read(I2S_PORT, raw_samples, sizeof(raw_samples),
                           &bytes_read, portMAX_DELAY);
  if (err != ESP_OK || bytes_read == 0) {
    return;
  }

  int n = bytes_read / sizeof(int32_t);

  // 32-Bit-Rohwerte in 16-Bit-PCM wandeln (mit Software-Verstärkung + Clamping)
  for (int i = 0; i < n; i++) {
    int32_t v = raw_samples[i] >> MIC_SHIFT;
    if (v > 32767) v = 32767;
    else if (v < -32768) v = -32768;
    pcm_samples[i] = (int16_t)v;
  }

  // PCM per TCP senden
  size_t to_send = n * sizeof(int16_t);
  size_t sent = client.write((const uint8_t *)pcm_samples, to_send);
  if (sent != to_send) {
    Serial.println("[TCP] Sendefehler – Verbindung wird zurückgesetzt");
    client.stop();
    return;
  }

  ledSet(true);  // verbunden & streamend
}
