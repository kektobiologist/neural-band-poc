// Standalone Samsung AC bench remote. No Bluetooth, Wi-Fi or saved credentials.
#include <Arduino.h>
#include <IRremoteESP8266.h>
#include <IRrecv.h>
#include <IRutils.h>
#include <IRac.h>
#include <ir_Samsung.h>

constexpr uint16_t kTxPin = 4;
constexpr uint16_t kRxPin = 5;
// Allow the indoor unit to process each step of its cleaning-cancel sequence.
constexpr uint32_t kOffSequenceGapMs = 1000;
IRSamsungAc ac(kTxPin);
IRrecv receiver(kRxPin, 1024, 50, true);
decode_results received;
bool listening = false;
bool loopback = false;
bool powerKnown = false;
String input;
bool overflow = false;
uint32_t lastByte = 0;

void status() {
  Serial.print("Requested state (not AC feedback): ");
  Serial.println(ac.toString());
  if (!powerKnown) Serial.println("AC power unknown since boot. Send on or off first.");
}

void help() {
  Serial.println("on | off | up/+ | down/- | temp 16..30 | status | help");
  Serial.println("off: OFF -> ON -> OFF with 1 s gaps; off single: one extended OFF frame");
  Serial.println("off legacy: diagnostic fixed OFF frame used by the previous build");
  Serial.println("listen on/off: optional GPIO5 remote capture (does not sync TX state)");
  Serial.println("loopback on/off: experimental self-reception; on also enables listening");
  Serial.println("Cooling, auto fan, swing off. No transmission at startup.");
}

void transmit(bool explicitPower, bool legacyOff = false) {
  const bool pauseReceiver = listening && !loopback;
  if (pauseReceiver) receiver.disableIRIn();
  if (loopback) receiver.resume();  // Discard any stale capture before our send.
  // Always send an extended power frame, even for a repeated explicit command:
  // the real remote may have changed the appliance without our knowledge.
  if (legacyOff) ac.sendOff();
  else if (explicitPower) ac.sendExtended();
  else ac.send();
  if (pauseReceiver) receiver.enableIRIn(true);
  Serial.println("IR sent; verify the AC's display/beep. No acknowledgement available.");
  status();
}

void command(String line) {
  line.trim();
  line.toLowerCase();
  if (!line.length()) return;
  if (line == "help") { help(); return; }
  if (line == "status") { status(); return; }
  if (line == "loopback on" || line == "loopback off") {
    loopback = line == "loopback on";
    if (loopback && !listening) {
      receiver.enableIRIn(true);
      listening = true;
    }
    Serial.println(loopback
        ? "Loopback ON: RX stays active during TX. Timing may be affected; no AC acknowledgement."
        : "Loopback OFF: normal remote capture; RX pauses during TX.");
    return;
  }
  if (line == "listen on" || line == "listen off") {
    const bool enable = line == "listen on";
    if (enable && !listening) receiver.enableIRIn(true);
    if (!enable && listening) receiver.disableIRIn();
    listening = enable;
    if (!listening) loopback = false;
    Serial.println(listening ? "Capture enabled on GPIO5." : "Capture disabled.");
    return;
  }
  if (line == "off") {
    Serial.println("Shutdown sequence: OFF -> ON -> OFF (1 s gaps).");
    powerKnown = true;
    // Each step uses a generated extended frame, retaining temperature/mode/fan.
    // Finish the sequence before processing another serial command.
    ac.setPower(false);
    transmit(true);
    delay(kOffSequenceGapMs);
    ac.setPower(true);
    transmit(true);
    delay(kOffSequenceGapMs);
    ac.setPower(false);
    transmit(true);
    Serial.println("Shutdown sequence sent; verify the AC has stopped cleaning.");
    return;
  }
  if (line == "on" || line == "off single" || line == "off legacy") {
    ac.setPower(line == "on");
    powerKnown = true;
    transmit(true, line == "off legacy");
    return;
  }
  int nextTemp = ac.getTemp();
  if (line == "up" || line == "+") nextTemp++;
  else if (line == "down" || line == "-") nextTemp--;
  else if (line.startsWith("temp ")) {
    String value = line.substring(5);
    value.trim();
    if (value.length() != 2 || !isDigit(value[0]) || !isDigit(value[1])) {
      Serial.println("Use temp 16..30 (integer Celsius)."); return;
    }
    nextTemp = value.toInt();
  } else { Serial.println("Unknown command. Type help."); return; }
  if (nextTemp < kSamsungAcMinTemp || nextTemp > kSamsungAcMaxTemp) {
    Serial.println("Temperature range is 16..30 C. Nothing sent."); return;
  }
  if (!powerKnown || !ac.getPower()) {
    Serial.println("Send on first; temperature commands do not turn the AC on."); return;
  }
  ac.setTemp(nextTemp);
  transmit(false);
}

void finishInput() {
  if (overflow) Serial.println("Command too long; discarded.");
  else command(input);
  input = "";
  overflow = false;
}

void setup() {
  digitalWrite(kTxPin, LOW);
  pinMode(kTxPin, OUTPUT);
  ac.begin();
  ac.stateReset(true, false);
  ac.setMode(kSamsungAcCool);
  ac.setTemp(24);
  ac.setFan(kSamsungAcFanAuto);
  ac.setSwing(false);
  ac.setSwingH(false);
  Serial.begin(115200);
  input.reserve(64);
  delay(1000);
  help();
  status();
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    lastByte = millis();
    if (c == '\r' || c == '\n') finishInput();
    else if (!overflow) {
      if (input.length() >= 63) { overflow = true; input = ""; }
      else input += c;
    }
  }
  // Supports Arduino Serial Monitor's "No line ending" setting too.
  if ((input.length() || overflow) && millis() - lastByte >= 300) finishInput();
  if (listening && receiver.decode(&received)) {
    Serial.println(loopback ? "RX (loopback mode; not AC feedback):" : "RX:");
    if (received.overflow) Serial.println("RX overflow: capture incomplete.");
    Serial.println(resultToHumanReadableBasic(&received));
    Serial.println(IRAcUtils::resultAcToString(&received));
    Serial.println(resultToSourceCode(&received));
    receiver.resume();
  }
  delay(1);
}
