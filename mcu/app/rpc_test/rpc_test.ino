#include "Arduino_RouterBridge.h"
#include "ArduinoGraphics.h"
#include "Arduino_LED_Matrix.h"

ArduinoLEDMatrix matrix;

const uint16_t BUF_SIZE = 256;
char messageBuffer[BUF_SIZE] = "Starting RIID...";

const int TEMP_PIN = A0;
const int LED_R = LED4_R;
const int LED_G = LED4_G;
const int LED_B = LED4_B;


void setup() {
    pinMode(LED_R, OUTPUT);
    pinMode(LED_G, OUTPUT);
    pinMode(LED_B, OUTPUT);

    digitalWrite(LED_R, 1);
    digitalWrite(LED_G, 1);
    digitalWrite(LED_B, 1);

    matrix.begin();
    
    Bridge.begin();
    Bridge.provide("update_text_matrix", update_text_matrix);
    Bridge.provide("update_status_led", update_status_led);
    
    Monitor.begin();
    Monitor.println("Temperature sensor ready");

    
}

void loop() {
    Bridge.update();
    matrix.beginDraw();
    matrix.stroke(0xFFFFFFFF);
    matrix.textFont(Font_5x7);
    matrix.textScrollSpeed(40);

    matrix.beginText(0, 1, 0xFFFFFF);
    matrix.print(messageBuffer);
    matrix.endText(SCROLL_LEFT);
    matrix.endDraw();
}

void update_status_led(int status) {
    switch(status) {
        case 0:
            digitalWrite(LED_R, 1);
            digitalWrite(LED_G, 1);
            digitalWrite(LED_B, 0);
            break;
        case 1:
            digitalWrite(LED_R, 0);
            digitalWrite(LED_G, 1);
            digitalWrite(LED_B, 1);
            break;
        case 2:
            digitalWrite(LED_R, 1);
            digitalWrite(LED_G, 0);
            digitalWrite(LED_B, 1);
            break;
        case 3:
            digitalWrite(LED_R, 1);
            digitalWrite(LED_G, 0);
            digitalWrite(LED_B, 0);
            break;
        default:
            digitalWrite(LED_R, 1);
            digitalWrite(LED_G, 1);
            digitalWrite(LED_B, 1);
    }
}

void update_text_matrix(String text) {
    strncpy(messageBuffer, text.c_str(), BUF_SIZE - 5);
    strcat(messageBuffer, "    ");
}
