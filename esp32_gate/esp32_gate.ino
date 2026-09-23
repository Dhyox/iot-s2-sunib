/*
 * Smart Gate - ESP32 DevKit V1
 * Face recognition (laptop) + RFID RC522
 *
 * Library (Arduino Library Manager):
 *   - MFRC522      (by GithubCommunity / miguelbalboa)
 *   - ESP32Servo   (by Kevin Harrington)
 *
 * Protokol serial 115200 baud, satu baris per pesan:
 *   ESP32 -> laptop : READY | SCAN | RFID,<uid> | DOOR,OPEN | DOOR,CLOSED
 *                     baris diawali '#' = pesan debug
 *   laptop -> ESP32 : OK,<nama> | FAIL | OPEN (buka manual dari dashboard)
 */

#include <SPI.h>
#include <MFRC522.h>
#include <ESP32Servo.h>

// ---------- Pin (sesuai diagram wiring) ----------
#define RC522_SS    5
#define RC522_RST   4
#define TRIG_PIN    26
#define ECHO_PIN    27
#define SERVO_PIN   13
#define BUZZER_PIN  25
#define LED_R       32
#define LED_G       33
#define LED_B       21

// ---------- Pengaturan ----------
const bool LED_COMMON_ANODE    = false;  // true kalau LED RGB common anode
const bool BUZZER_PASSIVE      = false;  // true kalau buzzer pasif (butuh tone)
const int  TRIGGER_DISTANCE_CM = 30;     // jarak untuk aktifkan kamera
const int  NEAR_READINGS_NEEDED = 3;     // pembacaan dekat berturut-turut
const int  SERVO_CLOSED_DEG    = 0;
const int  SERVO_OPEN_DEG      = 90;
const unsigned long FACE_TIMEOUT_MS   = 10000; // tunggu hasil face recog
const unsigned long RFID_TIMEOUT_MS   = 1500;  // tunggu jawaban laptop untuk RFID
const unsigned long DOOR_OPEN_MS      = 5000;  // lama gate terbuka
const unsigned long COOLDOWN_MS       = 4000;  // jeda sebelum scan berikutnya
const unsigned long DISTANCE_EVERY_MS = 100;

// Kartu cadangan: dipakai HANYA kalau laptop tidak menjawab (misal laptop mati).
// Isi dengan UID kartumu (lihat log dashboard), huruf besar tanpa spasi.
const char* LOCAL_CARDS[] = { "A1B2C3D4" };
const int LOCAL_CARD_COUNT = sizeof(LOCAL_CARDS) / sizeof(LOCAL_CARDS[0]);

// ---------- Objek & state ----------
MFRC522 rfid(RC522_SS, RC522_RST);
Servo gateServo;

enum State { IDLE, WAIT_FACE, WAIT_RFID, DOOR_OPEN, COOLDOWN };
State state = IDLE;

unsigned long stateStart = 0;
unsigned long lastDistanceCheck = 0;
int nearCount = 0;
String pendingUid = "";
String serialBuf = "";

// ---------- Output ----------
void setLed(bool r, bool g, bool b) {
  bool on = !LED_COMMON_ANODE;
  digitalWrite(LED_R, r ? on : !on);
  digitalWrite(LED_G, g ? on : !on);
  digitalWrite(LED_B, b ? on : !on);
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

void beepPattern(int count, int onMs, int offMs) {
  for (int i = 0; i < count; i++) {
    buzz(onMs);
    delay(offMs);
  }
}

void changeState(State s) {
  state = s;
  stateStart = millis();
}

// ---------- Aksi gate ----------
void grantAccess() {
  setLed(false, true, false);            // hijau
  gateServo.write(SERVO_OPEN_DEG);
  Serial.println("DOOR,OPEN");
  changeState(DOOR_OPEN);
}

void closeDoor() {
  gateServo.write(SERVO_CLOSED_DEG);
  setLed(false, false, false);
  Serial.println("DOOR,CLOSED");
  nearCount = 0;
  changeState(COOLDOWN);
}

void denyAccess(bool faceFailure) {
  setLed(true, false, false);            // merah
  if (faceFailure) beepPattern(3, 300, 150);  // alarm gagal face recognition
  else             beepPattern(1, 150, 0);    // kartu tidak dikenal
  delay(700);
  setLed(false, false, false);
  nearCount = 0;
  changeState(COOLDOWN);
}

// ---------- Sensor ----------
long readDistanceCm() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);
  long duration = pulseIn(ECHO_PIN, HIGH, 25000); // timeout ~4 m
  if (duration == 0) return -1;                   // tidak ada pantulan
  return duration / 58;                           // mikrodetik -> cm
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

// ---------- Pesan dari laptop ----------
void handleLine(String line) {
  line.trim();
  if (line.length() == 0) return;

  if (line.startsWith("OK")) {
    if (state == WAIT_FACE || state == WAIT_RFID) grantAccess();
  } else if (line == "FAIL") {
    if (state == WAIT_FACE)      denyAccess(true);
    else if (state == WAIT_RFID) denyAccess(false);
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

// ---------- Setup & loop ----------
void setup() {
  Serial.begin(115200);

  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  pinMode(LED_R, OUTPUT);
  pinMode(LED_G, OUTPUT);
  pinMode(LED_B, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW);
  setLed(false, false, false);

  SPI.begin();               // VSPI default: SCK 18, MISO 19, MOSI 23
  rfid.PCD_Init();

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
      // 1) RFID
      String uid = readCardUid();
      if (uid.length() > 0) {
        pendingUid = uid;
        setLed(false, false, true);      // biru = memproses
        Serial.println("RFID," + uid);
        changeState(WAIT_RFID);
        break;
      }

      // 2) Proximity -> aktifkan face recognition
      if (now - lastDistanceCheck >= DISTANCE_EVERY_MS) {
        lastDistanceCheck = now;
        long d = readDistanceCm();
        if (d > 0 && d <= TRIGGER_DISTANCE_CM) nearCount++;
        else nearCount = 0;

        if (nearCount >= NEAR_READINGS_NEEDED) {
          nearCount = 0;
          setLed(false, false, true);    // biru = scanning wajah
          Serial.println("SCAN");
          changeState(WAIT_FACE);
        }
      }
      break;
    }

    case WAIT_FACE:
      if (now - stateStart > FACE_TIMEOUT_MS) {
        Serial.println("# face timeout, laptop tidak menjawab");
        denyAccess(true);
      }
      break;

    case WAIT_RFID:
      if (now - stateStart > RFID_TIMEOUT_MS) {
        // Laptop tidak menjawab -> pakai daftar kartu lokal
        Serial.println("# laptop tidak menjawab, cek kartu lokal");
        if (isLocalCard(pendingUid)) grantAccess();
        else denyAccess(false);
      }
      break;

    case DOOR_OPEN:
      if (now - stateStart > DOOR_OPEN_MS) closeDoor();
      break;

    case COOLDOWN:
      readCardUid();                     // abaikan kartu yang masih ditempel
      if (now - stateStart > COOLDOWN_MS) changeState(IDLE);
      break;
  }
}
