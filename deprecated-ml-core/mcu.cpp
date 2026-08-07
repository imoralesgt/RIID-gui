#define SERIAL_LINUX Serial1

const char* CLASES[] = {
  'bkg', 'co', 'coeu', 'cs', 'csco', 'eu'
};

void setup() {
  Serial.begin(115200);
  SERIAL_LINUX.begin(115200);
}

void loop() {
  if (SERIAL_LINUX.available()) {
    String resp = SERIAL_LINUX.readStringUntil('\n');
    int idx = resp.substring(0, resp.indexOf(',')).toInt();
    float conf = resp.substring(resp.indexOf(',') + 1).toFloat();

    Serial.print("Detected: ");
    Serial.print(CLASES[idx]);
    Serial.print(" | Confidence: ");
    Serial.print(conf * 100, 1);
    Serial.println("%");
  }
}