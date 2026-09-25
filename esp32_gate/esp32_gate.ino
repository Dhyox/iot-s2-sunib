// Smart Gate - ESP32 DevKit V1
// library: MFRC522, ESP32Servo
// protokol serial liat README
// tes tanpa laptop: serial monitor 115200 (newline), ketik OPEN atau FACE,OK,Tes

#include <SPI.h>
#include <MFRC522.h>
#include <ESP32Servo.h>

// pin, sesuai wiring
#define RC522_SS    5
#define RC522_RST   4
#define TRIG_PIN    26
#define ECHO_PIN    27
#define SERVO_PIN   13
#define BUZZER_PIN  21
#define LED_R       32
#define LED_G       33

// setting
const bool BUZZER_PASSIVE      = false;  // true kalo buzzernya pasif
const int  TRIGGER_DISTANCE_CM = 30;
const int  NEAR_READINGS_NEEDED = 3;     // biar ga ke-trigger noise sensor
const int  SERVO_CLOSED_DEG    = 0;
const int  SERVO_OPEN_DEG      = 90;
const unsigned long SESSION_MS        = 12000;
const unsigned long RFID_TIMEOUT_MS   = 1500;  // nunggu jawaban laptop
const unsigned long FAIL_GRACE_MS     = 2000;  // abis wajah gagal, sisa waktu buat tap kartu
const unsigned long DOOR_OPEN_MS      = 5000;
const unsigned long COOLDOWN_MS       = 1000;
const unsigned long DISTANCE_EVERY_MS = 100;

// cadangan kalo laptop mati / ga jawab
// NOTE: jangan taro UID asli disini, repo publik
const char* LOCAL_CARDS[] = { "A1B2C3D4" };
const int LOCAL_CARD_COUNT = sizeof(LOCAL_CARDS) / sizeof(LOCAL_CARDS[0]);

MFRC522 rfid(RC522_SS, RC522_RST);
Servo gateServo;

enum State { IDLE, ACTIVE, DOOR_OPEN, COOLDOWN };
State state = IDLE;

unsigned long stateStart = 0;
unsigned long sessionMs = SESSION_MS;
unsigned long lastDistanceCheck = 0;
unsigned long rfidSentAt = 0;
int nearCount = 0;
int clearCount = 0;
bool waitingClear = false;   // abis gate kebuka, orangnya harus lewat/pergi dulu baru bisa sesi baru
bool rfidPending = false;
String pendingUid = "";
String serialBuf = "";

void setLed(bool red, bool green) {
  digitalWrite(LED_R, red);
  digitalWrite(LED_G, green);
}

void buzz(int ms) {
  if (BUZZER_PASSIVE) {
    tone(BUZZER_PIN, 2000, ms);
    delay(ms);
  } else {
    digitalWrite(BUZZER_PIN, HIGH);
    delay(ms);
    digitalWrite(BUZZER_PIN, LOW);
  }
}

// merah kedip-kedip, `beeps` kedipan pertama sambil bunyi
// abis itu balik merah nyala terus (sesi masih jalan)
void blinkRed(int count, int onMs, int offMs, int beeps) {
  for (int i = 0; i < count; i++) {
    setLed(true, false);
    if (i < beeps) buzz(onMs);
    else delay(onMs);
    setLed(false, false);
    delay(offMs);
  }
  setLed(true, false);
}

void changeState(State s) {
  state = s;
  stateStart = millis();
}

void startSession() {
  rfidPending = false;
  sessionMs = SESSION_MS;
  setLed(true, false);                   // merah = nunggu wajah / kartu
  Serial.println("SCAN");
  Serial.println("# sesi dimulai: hadapkan wajah atau tempel kartu");
  changeState(ACTIVE);
}

void grantAccess() {
  Serial.println("CANCEL");              // stop scan wajah di laptop
  rfidPending = false;
  setLed(false, true);
  gateServo.write(SERVO_OPEN_DEG);
  Serial.println("DOOR,OPEN");
  changeState(DOOR_OPEN);
}

void closeDoor() {
  gateServo.write(SERVO_CLOSED_DEG);
  setLed(false, false);
  Serial.println("DOOR,CLOSED");
  nearCount = 0;
  waitingClear = true;
  changeState(COOLDOWN);
}

// sesi ga langsung selesai, masih bisa pake kartu
void faceFailed() {
  Serial.println("# wajah tidak dikenali, kartu masih bisa dipakai");
  blinkRed(3, 300, 150, 3);
  // gausah nunggu full 12 detik, kasih waktu dikit buat kartu aja
  unsigned long elapsed = millis() - stateStart;
  if (elapsed + FAIL_GRACE_MS < sessionMs) sessionMs = elapsed + FAIL_GRACE_MS;
}

void cardRejected() {
  Serial.println("# kartu ditolak");
  blinkRed(3, 150, 100, 1);
}

void sessionTimeout() {
  Serial.println("CANCEL");
  Serial.println("# waktu sesi habis");
  buzz(600);
  delay(400);
  setLed(false, false);
  nearCount = 0;
  waitingClear = false;   // gagal, orangnya boleh langsung coba lagi ga usah pergi dulu
  changeState(COOLDOWN);
}

long readDistanceCm() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);
  long duration = pulseIn(ECHO_PIN, HIGH, 25000); // timeout kira2 4m
  if (duration == 0) return -1;
  return duration / 58;
}

String readCardUid() {
  if (!rfid.PICC_IsNewCardPresent() || !rfid.PICC_ReadCardSerial()) return "";
  String uid = "";
  for (byte i = 0; i < rfid.uid.size; i++) {
    if (rfid.uid.uidByte[i] < 0x10) uid += "0";
    uid += String(rfid.uid.uidByte[i], HEX);
  }
  uid.toUpperCase();
  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();
  return uid;
}

bool isLocalCard(const String& uid) {
  for (int i = 0; i < LOCAL_CARD_COUNT; i++) {
    if (uid.equals(LOCAL_CARDS[i])) return true;
  }
  return false;
}

// pesan dari laptop
void handleLine(String line) {
  line.trim();
  if (line.length() == 0) return;

  if (line.startsWith("FACE,OK")) {
    if (state == ACTIVE) grantAccess();
  } else if (line == "FACE,FAIL") {
    if (state == ACTIVE) faceFailed();
  } else if (line.startsWith("RFID,OK")) {
    if (state == ACTIVE && rfidPending) grantAccess();
  } else if (line == "RFID,FAIL") {
    if (state == ACTIVE && rfidPending) {
      rfidPending = false;
      cardRejected();
    }
  } else if (line == "OPEN") {
    if (state != DOOR_OPEN) grantAccess();
  }
}

void readSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      handleLine(serialBuf);
      serialBuf = "";
    } else if (c != '\r' && serialBuf.length() < 64) {
      serialBuf += c;
    }
  }
}

void setup() {
  Serial.begin(115200);

  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  pinMode(LED_R, OUTPUT);
  pinMode(LED_G, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW);
  setLed(false, false);

  SPI.begin();               // SCK 18, MISO 19, MOSI 23
  rfid.PCD_Init();
  delay(50);
  byte ver = rfid.PCD_ReadRegister(MFRC522::VersionReg);
  if (ver == 0x00 || ver == 0xFF) {
    Serial.println("# RC522 TIDAK terdeteksi! Cek kabel SPI, RST, dan 3.3V");
  } else {
    Serial.print("# RC522 OK, versi 0x");
    Serial.println(ver, HEX);
  }

  gateServo.setPeriodHertz(50);
  gateServo.attach(SERVO_PIN, 500, 2400);
  gateServo.write(SERVO_CLOSED_DEG);

  delay(300);
  Serial.println("READY");
  Serial.println("DOOR,CLOSED");
}

void loop() {
  readSerial();
  unsigned long now = millis();

  switch (state) {
    case IDLE: {
      // idle cuma cek jarak, rfid baru aktif pas sesi
      if (now - lastDistanceCheck < DISTANCE_EVERY_MS) break;
      lastDistanceCheck = now;

      long d = readDistanceCm();
      bool isNear = d > 0 && d <= TRIGGER_DISTANCE_CM;

      if (waitingClear) {
        clearCount = isNear ? 0 : clearCount + 1;
        if (clearCount >= 3) {
          waitingClear = false;
          clearCount = 0;
        }
        break;
      }

      nearCount = isNear ? nearCount + 1 : 0;
      if (nearCount >= NEAR_READINGS_NEEDED) {
        nearCount = 0;
        startSession();
      }
      break;
    }

    case ACTIVE: {
      if (!rfidPending) {
        String uid = readCardUid();
        if (uid.length() > 0) {
          pendingUid = uid;
          rfidPending = true;
          rfidSentAt = now;
          Serial.println("RFID," + uid);
          Serial.println("# kartu terbaca: " + uid);
        }
      } else if (now - rfidSentAt > RFID_TIMEOUT_MS) {
        // laptop ga jawab, cek LOCAL_CARDS
        rfidPending = false;
        Serial.println("# laptop tidak menjawab, cek kartu lokal");
        if (isLocalCard(pendingUid)) {
          grantAccess();
          break;
        }
        cardRejected();
      }

      // jangan timeout kalo kartu lagi dicek laptop
      if (state == ACTIVE && !rfidPending && now - stateStart > sessionMs) sessionTimeout();
      break;
    }

    case DOOR_OPEN:
      if (now - stateStart > DOOR_OPEN_MS) closeDoor();
      break;

    case COOLDOWN:
      readCardUid();                     // buang kartu yg masih ditempel
      if (now - stateStart > COOLDOWN_MS) changeState(IDLE);
      break;
  }
}
