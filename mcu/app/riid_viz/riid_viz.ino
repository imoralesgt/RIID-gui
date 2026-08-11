#include "Arduino_RouterBridge.h"
#include "ArduinoGraphics.h"
#include "Arduino_LED_Matrix.h"

#define TEXT_SPACES_PRE  2
#define TEXT_SPACES_POST 5

// Onboard matrix display library
ArduinoLEDMatrix matrix;

// Text buffer size and scroll speed (pause between updates in ms)
const uint16_t BUF_SIZE = 256;
const uint16_t SCROLL_SPEED_DEFAULT = 80;
char messageBuffer[BUF_SIZE] = "Starting RIID...";

// RGB LED pins for status visualization
const int LED_R = LED4_R;
const int LED_G = LED4_G;
const int LED_B = LED4_B;

int scrollSpeed;

void setup() {
    // Initialize LED pins
    pinMode(LED_R, OUTPUT);
    pinMode(LED_G, OUTPUT);
    pinMode(LED_B, OUTPUT);

    // Set LED pins to high (inverse logic)
    digitalWrite(LED_R, 1);
    digitalWrite(LED_G, 1);
    digitalWrite(LED_B, 1);

    // Initialize matrix display
    matrix.begin();
    set_scroll_speed(SCROLL_SPEED_DEFAULT);
    
    // Initialize RPC router for inter-processor (MPU<->MCU) communication
    Bridge.begin();
    Bridge.provide("update_text_matrix", update_text_matrix);
    Bridge.provide("update_status_led", update_status_led);
    Bridge.provide("set_scroll_speed", set_scroll_speed);
    
}

void loop() {
    Bridge.update();
    matrix.beginDraw();
    matrix.stroke(0xFFFFFFFF);
    matrix.textFont(Font_5x7);
    matrix.textScrollSpeed(scrollSpeed);

    matrix.beginText(0, 1, 0xFFFFFF);
    matrix.print(messageBuffer);
    matrix.endText(SCROLL_LEFT);
    matrix.endDraw();
}

/**
 * Updates the status LED based on the RIID status. 
 * 0: Idle -> Blue
 * 1: Recording background -> Red
 * 2: Surveying RIID -> Green
 * 3: Batch recording -> Purple (Red + Blue)
 * 
 * Intended to be used with the `update_status_led` RPC call.
 * 
 * @param status The status index
 * 
 */
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
            digitalWrite(LED_R, 0);
            digitalWrite(LED_G, 1);
            digitalWrite(LED_B, 0);
            break;
        default:
            digitalWrite(LED_R, 1);
            digitalWrite(LED_G, 1);
            digitalWrite(LED_B, 1);
    }
}

/**
 * Updates the text scroll speed for the LED matrix. Intended to be used
 * with the `set_scroll_speed` RPC call.
 * 
 * @param speed The scroll speed: delay between updates, in milliseconds
 */
void set_scroll_speed(int speed) {
    scrollSpeed = speed;
}

/**
 * Updates the buffer containing the text that will be displayed
 * on the LED matrix. The text is truncated to BUF_SIZE - 5 characters to
 * accommodate the scrolling effect. Intended to be used with the
 * `update_text_matrix` RPC call.
 * 
 * @param text The text to be displayed on the LED matrix
 */
void update_text_matrix(String text) {
    memset(messageBuffer, 0, BUF_SIZE);
    memset(messageBuffer, ' ', TEXT_SPACES_PRE);
    strncpy(messageBuffer + TEXT_SPACES_PRE, text.c_str(), BUF_SIZE - TEXT_SPACES_PRE - TEXT_SPACES_POST);
    strcat(messageBuffer, "     ");
}
