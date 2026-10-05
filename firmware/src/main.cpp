// -----------------------------------------------------------------------------
// Meeting-KI – ESP32 Firmware (automatischer Betrieb)
//
// Verhalten:
//   Strom an  -> WLAN + Server verbinden -> SOFORT Aufnahme starten und
//                16-kHz-Mono-PCM per TCP streamen.
//   Strom weg -> der ESP ist aus; der Server erkennt den Abbruch und beendet
//                die Aufnahme automatisch (Transkription + Zusammenfassung).
//
// Keine Knöpfe, kein Deep Sleep. Ein Tonstream = ein Meeting.
//
// Übertragungsprotokoll (ein TCP-Stream, mit Framing):
//   Jeder Frame:  [1 Byte Typ][4 Byte Länge, little-endian][Nutzdaten]
//     Typ 0x01 = AUDIO   -> Nutzdaten = 16-Bit-PCM (mono, little-endian)
//     Typ 0x02 = CONTROL -> Nutzdaten = 1 Byte Kommando (0x10=START, 0x11=STOP)
//
// Status-LED:
//   rot blinkend    = kein WLAN
//   orange blinkend = WLAN ok, aber kein Server
//   rot (dauerhaft) = verbunden, Aufnahme läuft / streamt
// -----------------------------------------------------------------------------
#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClient.h>
#include <driver/i2s.h>

#include "config.h"

// ---- Protokoll-Konstanten (müssen mit dem Server übereinstimmen) ------------
static const uint8_t MSG_AUDIO   = 0x01;
static const uint8_t MSG_CONTROL = 0x02;
static const uint8_t CTRL_START  = 0x10;
static const uint8_t CTRL_STOP   = 0x11;

// I2S-Port und Puffergrößen
static const i2s_port_t I2S_PORT = I2S_NUM_0;
static const int        DMA_BUF_COUNT = 8;
static const int        DMA_BUF_LEN   = 256;   // Samples pro DMA-Puffer
static const int        SAMPLES_PER_READ = 512;

static WiFiClient client;

static int32_t raw_samples[SAMPLES_PER_READ];
static int16_t pcm_samples[SAMPLES_PER_READ];

static bool streaming = false;  // true = mit Server verbunden und Aufnahme läuft

// ---------------------------------------------------------------------------
// Status-LED (WS2812-RGB oder einfache Ein/Aus-LED)
// ---------------------------------------------------------------------------
static void ledColor(uint8_t r, uint8_t g, uint8_t b) {
#if STATUS_LED_PIN >= 0
#if STATUS_LED_IS_WS2812
  neopixelWrite(STATUS_LED_PIN, r, g, b);
#else
  bool on = (r || g || b);
  digitalWrite(STATUS_LED_PIN, (on ^ (bool)STATUS_LED_ACTIVE_LOW) ? HIGH : LOW);
#endif
#else
  (void)r; (void)g; (void)b;
#endif
}

static void ledOff() { ledColor(0, 0, 0); }
static void ledStreaming() { ledColor(LED_BRIGHTNESS, 0, 0); }  // rot

static void ledBlinkColor(uint8_t r, uint8_t g, uint8_t b, int on_ms, int off_ms) {
#if STATUS_LED_PIN >= 0
  ledColor(r, g, b);
  delay(on_ms);
  ledOff();
  delay(off_ms);
#else
  (void)r; (void)g; (void)b;
  delay(on_ms + off_ms);
#endif
}

// ---------------------------------------------------------------------------
// Framing: einen Frame an den Server senden
// ---------------------------------------------------------------------------
static bool sendFrame(uint8_t type, const uint8_t *payload, uint32_t len) {
  uint8_t header[5];
  header[0] = type;
  header[1] = (uint8_t)(len & 0xFF);
  header[2] = (uint8_t)((len >> 8) & 0xFF);
  header[3] = (uint8_t)((len >> 16) & 0xFF);
  header[4] = (uint8_t)((len >> 24) & 0xFF);

  if (client.write(header, sizeof(header)) != sizeof(header)) return false;
  if (len > 0 && client.write(payload, len) != len) return false;
  return true;
}

static bool sendControl(uint8_t command) {
  return sendFrame(MSG_CONTROL, &command, 1);
}

// ---------------------------------------------------------------------------
// I2S einrichten (RX vom INMP441)
// ---------------------------------------------------------------------------
static void setupI2S() {
  i2s_config_t i2s_config = {
      .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
      .sample_rate = SAMPLE_RATE,
      .bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT,   // INMP441: 24 Bit in 32-Bit-Frames
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

  if (i2s_driver_install(I2S_PORT, &i2s_config, 0, NULL) != ESP_OK) {
    Serial.println("[I2S] Installation fehlgeschlagen");
    return;
  }
  if (i2s_set_pin(I2S_PORT, &pin_config) != ESP_OK) {
    Serial.println("[I2S] Pin-Konfiguration fehlgeschlagen");
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
    ledBlinkColor(LED_BRIGHTNESS, 0, 0, 80, 80);  // rot blinkend: kein WLAN
    Serial.print(".");
  }
  Serial.printf("\n[WiFi] verbunden, IP: %s\n", WiFi.localIP().toString().c_str());
}

// ---------------------------------------------------------------------------
// Server verbinden und sofort Aufnahme starten
// ---------------------------------------------------------------------------
static bool connectServerAndStart() {
  if (client.connected()) return true;

  Serial.printf("[TCP] verbinde mit %s:%d ...\n", SERVER_HOST, SERVER_PORT);
  if (!client.connect(SERVER_HOST, SERVER_PORT)) {
    Serial.println("[TCP] Verbindung fehlgeschlagen");
    return false;
  }
  client.setNoDelay(true);
  Serial.println("[TCP] Server verbunden");

  if (!sendControl(CTRL_START)) {
    Serial.println("[TCP] START konnte nicht gesendet werden");
    client.stop();
    return false;
  }
  streaming = true;
  ledStreaming();
  Serial.println("[REC] Aufnahme gestartet (automatisch)");
  return true;
}

// ---------------------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\n=== Meeting-KI Firmware (Auto-Start) ===");

#if STATUS_LED_PIN >= 0 && !STATUS_LED_IS_WS2812
  pinMode(STATUS_LED_PIN, OUTPUT);
#endif
  ledOff();

  // L/R-Kanalwahl des Mikrofons fest über GPIO treiben
  pinMode(MIC_LR_PIN, OUTPUT);
  digitalWrite(MIC_LR_PIN, MIC_LR_LEVEL);

  connectWiFi();
  setupI2S();
  connectServerAndStart();
}

// ---------------------------------------------------------------------------
void loop() {
  // WLAN sicherstellen
  if (WiFi.status() != WL_CONNECTED) {
    streaming = false;
    connectWiFi();
    return;
  }

  // Serververbindung sicherstellen (startet bei Erfolg automatisch eine Aufnahme)
  if (!client.connected()) {
    streaming = false;
    ledBlinkColor(LED_BRIGHTNESS, LED_BRIGHTNESS / 2, 0, 500, 500);  // orange: kein Server
    if (!connectServerAndStart()) {
      delay(1000);
      return;
    }
  }

  // Audio lesen und senden
  size_t bytes_read = 0;
  esp_err_t err = i2s_read(I2S_PORT, raw_samples, sizeof(raw_samples),
                           &bytes_read, portMAX_DELAY);
  if (err != ESP_OK || bytes_read == 0) {
    return;
  }

  int n = bytes_read / sizeof(int32_t);
  for (int i = 0; i < n; i++) {
    int32_t v = raw_samples[i] >> MIC_SHIFT;
    if (v > 32767) v = 32767;
    else if (v < -32768) v = -32768;
    pcm_samples[i] = (int16_t)v;
  }

  if (!sendFrame(MSG_AUDIO, (const uint8_t *)pcm_samples, n * sizeof(int16_t))) {
    Serial.println("[TCP] Sendefehler – Verbindung wird zurückgesetzt");
    client.stop();
    streaming = false;
  }
}
