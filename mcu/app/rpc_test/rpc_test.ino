#include "Arduino_RouterBridge.h"

const int TEMP_PIN = A0;


void setup() {
    pinMode(LED_BUILTIN, OUTPUT);
    
    Bridge.begin();
    Bridge.provide("read_temperature", read_temperature);
    Bridge.provide("set_led_state", set_led_state);
    
    Monitor.begin();
    Monitor.println("Temperature sensor ready");
}

void loop() {}

float read_temperature() {
    int raw = analogRead(TEMP_PIN);
    float voltage = (raw / 16383.0) * 3.3;
    float temp_c = (voltage - 0.5) * 100.0;
    
    Monitor.print("Temperature: ");
    Monitor.println(temp_c);
    
    return temp_c;
}

void set_led_state(bool state) {
    digitalWrite(LED_BUILTIN, state ? LOW : HIGH);
}