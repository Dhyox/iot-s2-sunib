/*
 * Smart Gate - ESP32 DevKit V1
 * Face recognition (laptop) + RFID RC522
 *
 * Library (Arduino Library Manager):
 *   - MFRC522      (by GithubCommunity / miguelbalboa)
 *   - ESP32Servo   (by Kevin Harrington)
 *
 * Alur (sesi proximity):
 *   IDLE : hanya cek sensor jarak.
 *   SESI : orang terdeteksi <= TRIGGER_DISTANCE_CM -> LED biru, kamera laptop
 *          DAN RFID aktif bersamaan. Mana yang berhasil duluan, gate terbuka.
 *          - wajah gagal -> alarm 3x + merah sebentar, kartu masih bisa dipakai
 *          - kartu salah -> bip pendek + merah sebentar, sesi lanjut
 *          - sesi habis tanpa berhasil -> bip panjang, sesi selesai
 *   Setelah sesi selesai, orang harus menjauh dulu sebelum sesi baru.
 *
 * Protokol serial 115200 baud, satu baris per pesan:
 *   ESP32 -> laptop : READY | SCAN | CANCEL | RFID,<uid> | DOOR,OPEN | DOOR,CLOSED
 *                     baris diawali '#' = pesan debug
 *   laptop -> ESP32 : FACE,OK,<nama> | FACE,FAIL | RFID,OK,<nama> | RFID,FAIL | OPEN
 *
 * Tes tanpa laptop (Serial Monitor 115200, line ending "Newline"):
 *   ketik OPEN, atau dekatkan tangan ke sensor lalu ketik FACE,OK,Tes
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
const int  TRIGGER_DISTANCE_CM = 30;     // jarak untuk memulai sesi
const int  NEAR_READINGS_NEEDED = 3;     // pembacaan dekat berturut-turut
const int  SERVO_CLOSED_DEG    = 0;
const int  SERVO_OPEN_DEG      = 90;
const unsigned long SESSION_MS        = 12000; // waktu untuk wajah ATAU kartu
const unsigned long RFID_TIMEOUT_MS   = 1500;  // tunggu jawaban laptop untuk RFID
const unsigned long RED_FLASH_MS      = 800;   // lama LED merah saat gagal
const unsigned long DOOR_OPEN_MS      = 5000;  // lama gate terbuka
const unsigned long COOLDOWN_MS       = 4000;  // jeda sebelum scan berikutnya
const unsigned long DISTANCE_EVERY_MS = 100;

// Kartu cadangan: dipakai HANYA kalau laptop tidak menjawab (misal laptop mati).
// UID kartumu muncul di Serial Monitor sebagai "# kartu terbaca: XXXXXXXX".
const char* LOCAL_CARDS[] = { "A1B2C3D4" };
const int LOCAL_CARD_COUNT = sizeof(LOCAL_CARDS) / sizeof(LOCAL_CARDS[0]);

// ---------- Objek & state ----------
MFRC522 rfid(RC522_SS, RC522_RST);
Servo gateServo;

enum State { IDLE, ACTIVE, DOOR_OPEN, COOLDOWN };
State state = IDLE;

unsigned long stateStart = 0;
unsigned long lastDistanceCheck = 0;
unsigned long flashUntil = 0;
unsigned long rfidSentAt = 0;
int nearCount = 0;
int clearCount = 0;
bool waitingClear = false;   // tunggu orang menjauh sebelum sesi baru
bool rfidPending = false;    // sedang menunggu jawaban laptop untuk kartu
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
void startSession() {
  rfidPending = false;
  flashUntil = 0;
  setLed(false, false, true);            // biru = sesi aktif
  Serial.println("SCAN");
  Serial.println("# sesi dimulai: hadapkan wajah atau tempel kartu");
  changeState(ACTIVE);
}

void grantAccess() {
  Serial.println("CANCEL");              // sesi selesai, laptop boleh berhenti scan
  rfidPending = false;
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
  waitingClear = true;
  changeState(COOLDOWN);
}

void faceFailed() {                      // sesi tetap lanjut, kartu masih bisa
  Serial.println("# wajah tidak dikenali, kartu masih bisa dipakai");
  setLed(true, false, false);            // merah
  beepPattern(3, 300, 150);              // alarm gagal face recognition
  flashUntil = millis() + RED_FLASH_MS;
}

void cardRejected() {                    // sesi tetap lanjut
  Serial.println("# kartu ditolak");
  setLed(true, false, false);            // merah
  beepPattern(1, 150, 0);
  flashUntil = millis() + RED_FLASH_MS;
}

void sessionTimeout() {
  Serial.println("CANCEL");
  Serial.println("# waktu sesi habis");
  setLed(true, false, false);            // merah
  buzz(600);
  delay(400);
  setLed(false, false, false);
  nearCount = 0;
  waitingClear = true;
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
      // Hanya cek jarak. RFID & kamera aktif setelah sesi dimulai.
      if (now - lastDistanceCheck < DISTANCE_EVERY_MS) break;
      lastDistanceCheck = now;

      long d = readDistanceCm();
      bool isNear = d > 0 && d <= TRIGGER_DISTANCE_CM;

      if (waitingClear) {                // orang sebelumnya belum menjauh
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
      // LED kembali biru setelah kedipan merah
      if (flashUntil != 0 && now > flashUntil) {
        flashUntil = 0;
        setLed(false, false, true);
      }

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
        // Laptop tidak menjawab -> pakai daftar kartu lokal
        rfidPending = false;
        Serial.println("# laptop tidak menjawab, cek kartu lokal");
        if (isLocalCard(pendingUid)) {
          grantAccess();
          break;
        }
        cardRejected();
      }

      if (state == ACTIVE && now - stateStart > SESSION_MS) sessionTimeout();
      break;
    }

    case DOOR_OPEN:
      if (now - stateStart > DOOR_OPEN_MS) closeDoor();
      break;

    case COOLDOWN:
      readCardUid();                     // abaikan kartu yang masih ditempel
      if (now - stateStart > COOLDOWN_MS) changeState(IDLE);
      break;
  }
}
