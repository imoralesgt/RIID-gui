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

// RGB LED pins for WiFi AP/Station mode visualization ("LED3") - a second,
// physically distinct onboard RGB LED from the operating-status LED above
// (confirmed against the UNO Q User Manual's UI & Indicators pinout: LED3 ->
// PH10/PH11/PH12, LED4 -> PH13/PH14/PH15, both MCU-driven).
const int WIFI_LED_R = LED3_R;
const int WIFI_LED_G = LED3_G;
const int WIFI_LED_B = LED3_B;

// External momentary push-button, wired between D13/PB13 and GND (JDIGITAL
// pin 14, adjacent to a GND pin for easy wiring), polled by the standalone
// wifi/wifi_mode_daemon.py (over RPC) to drive the AP/Station toggle.
const int WIFI_BUTTON_PIN = 13;
const unsigned long HOLD_THRESHOLD_MS = 5000;

bool wifiButtonPressed = false;
unsigned long wifiButtonPressStartMs = 0;
bool wifiToggleRequested = false;
// Tracks whether the hold threshold has already latched for the CURRENT
// press, independent of wifiToggleRequested's read-clear semantics - without
// this, clearing wifiToggleRequested on poll_wifi_button() would let the
// still-satisfied hold-duration check immediately re-latch it on the very
// next loop() iteration, re-triggering every poll while the button stays held.
bool wifiHoldLatched = false;

int scrollSpeed;

// Transient matrix message state (see show_transient_text below)
char savedMessageBuffer[BUF_SIZE];
unsigned long transientUntilMs = 0;

// Manual (non-blocking) scroll state - see the note in loop() for why this
// replaced ArduinoGraphics's own endText(SCROLL_LEFT), which blocks for the
// entire scroll pass internally.
char lastDrawnBuffer[BUF_SIZE] = "";
int scrollX = 0;
unsigned long lastScrollStepMs = 0;
bool pendingClear = false;

void setup() {
    // Initialize LED pins
    pinMode(LED_R, OUTPUT);
    pinMode(LED_G, OUTPUT);
    pinMode(LED_B, OUTPUT);

    // Set LED pins to high (inverse logic)
    digitalWrite(LED_R, 1);
    digitalWrite(LED_G, 1);
    digitalWrite(LED_B, 1);

    // Initialize WiFi mode LED pins
    pinMode(WIFI_LED_R, OUTPUT);
    pinMode(WIFI_LED_G, OUTPUT);
    pinMode(WIFI_LED_B, OUTPUT);

    // Default to Station mode's white, matching the system's boot-into-STA
    // default - the wifi daemon re-confirms this shortly after boot once
    // NetworkManager reports the actual active connection.
    update_wifi_led(1);

    // Initialize the external WiFi-mode push-button (active-low, internal pull-up)
    pinMode(WIFI_BUTTON_PIN, INPUT_PULLUP);

    // Initialize matrix display
    matrix.begin();
    matrix.textFont(Font_5x7);
    set_scroll_speed(SCROLL_SPEED_DEFAULT);

    // Initialize RPC router for inter-processor (MPU<->MCU) communication
    Bridge.begin();
    Bridge.provide("update_text_matrix", update_text_matrix);
    Bridge.provide("update_status_led", update_status_led);
    Bridge.provide("set_scroll_speed", set_scroll_speed);
    Bridge.provide("update_wifi_led", update_wifi_led);
    Bridge.provide("show_transient_text", show_transient_text);
    Bridge.provide("poll_wifi_button", poll_wifi_button);

}

/**
 * Draws one step of the scrolling text, advancing `scrollX` by one pixel
 * each time it's called (throttled to `scrollSpeed` ms between steps).
 *
 * Replicates ArduinoGraphics's own endText(SCROLL_LEFT) frame-by-frame, but
 * as a single non-blocking step instead of a loop that blocks (via an
 * internal delay() per pixel) until the ENTIRE scroll pass finishes. That
 * blocking behavior starved Bridge.update() - and therefore every RPC call,
 * including the button-hold timing and show_transient_text - for as long as
 * a single scroll pass took (multiple seconds for a long message), causing
 * both imprecise button-hold timing and RPC calls that arrived mid-scroll
 * to be delayed or silently superseded before ever being rendered.
 */
void draw_scroll_step() {
    if (strcmp(messageBuffer, lastDrawnBuffer) != 0) {
        strncpy(lastDrawnBuffer, messageBuffer, BUF_SIZE);
        scrollX = 0;
        // Deferred (not cleared here) until the change is actually drawn
        // below - the throttle check below can return early first, and if
        // it did, comparing messageBuffer/lastDrawnBuffer again next call
        // would no longer detect a change.
        pendingClear = true;
    }

    if (millis() - lastScrollStepMs < (unsigned long)scrollSpeed) {
        return;
    }
    lastScrollStepMs = millis();

    const int textX = 0;
    const int textY = 1;
    const int textLen = strlen(messageBuffer);
    const int fontWidth = matrix.textFontWidth();
    const int scrollLength = textLen * fontWidth + textX + 1;

    matrix.beginDraw();

    if (pendingClear) {
        // A resumed/reset scroll position is a large jump, not a smooth 1px
        // step, so the incremental single-column clear below isn't enough -
        // it'd leave stale pixels from the previous message's old position
        // still lit, mixed in with the new text.
        matrix.clear();
        pendingClear = false;
    }

    const int text_x = textX - scrollX;
    matrix.stroke(0xFFFFFFFF);
    matrix.text(messageBuffer, text_x, textY);

    // Clear the column the text is about to vacate, matching endText's own
    // trailing-edge cleanup, so the scroll doesn't leave a ghost trail.
    const int clearX = text_x + textLen * fontWidth;
    matrix.stroke(0, 0, 0);
    matrix.line(clearX, textY, clearX, textY + matrix.textFontHeight() - 1);

    matrix.endDraw();

    scrollX++;
    if (scrollX >= scrollLength) {
        scrollX = 0;
    }
}

void loop() {
    Bridge.update();
    poll_wifi_button_hold();

    if (transientUntilMs != 0 && millis() >= transientUntilMs) {
        memcpy(messageBuffer, savedMessageBuffer, BUF_SIZE);
        transientUntilMs = 0;
    }

    draw_scroll_step();
}

/**
 * Surveys the external WiFi-mode push-button (active-low, on WIFI_BUTTON_PIN)
 * every loop() iteration and latches `wifiToggleRequested` exactly once per
 * press held continuously for at least `HOLD_THRESHOLD_MS`. Does not re-arm
 * until the button is released, so a single long hold can only ever request
 * one toggle.
 */
void poll_wifi_button_hold() {
    bool pressed = (digitalRead(WIFI_BUTTON_PIN) == LOW);

    if (pressed && !wifiButtonPressed) {
        wifiButtonPressed = true;
        wifiButtonPressStartMs = millis();
        wifiHoldLatched = false;
    } else if (!pressed && wifiButtonPressed) {
        wifiButtonPressed = false;
        wifiHoldLatched = false;
    } else if (pressed && wifiButtonPressed && !wifiHoldLatched) {
        if (millis() - wifiButtonPressStartMs >= HOLD_THRESHOLD_MS) {
            wifiHoldLatched = true;
            wifiToggleRequested = true;
        }
    }
}

/**
 * Reports (and clears) whether a qualifying 5s+ button hold has occurred
 * since the last call. Intended to be polled once a second by the standalone
 * wifi/wifi_mode_daemon.py over RPC - the MCU itself surveys the hold
 * duration, so the caller only needs to react to a `true` result.
 *
 * @return Whether a WiFi mode toggle was requested since the last poll
 */
bool poll_wifi_button() {
    bool triggered = wifiToggleRequested;
    wifiToggleRequested = false;
    return triggered;
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
 * Fills `messageBuffer` with the padded/scroll-ready form of `text`, shared
 * by `update_text_matrix` and `show_transient_text`.
 */
void fill_message_buffer(const String &text) {
    memset(messageBuffer, 0, BUF_SIZE);
    memset(messageBuffer, ' ', TEXT_SPACES_PRE);
    strncpy(messageBuffer + TEXT_SPACES_PRE, text.c_str(), BUF_SIZE - TEXT_SPACES_PRE - TEXT_SPACES_POST);
    strcat(messageBuffer, "     ");
}

/**
 * Updates the buffer containing the text that will be displayed
 * on the LED matrix. The text is truncated to BUF_SIZE - 5 characters to
 * accommodate the scrolling effect. Intended to be used with the
 * `update_text_matrix` RPC call.
 *
 * Cancels any pending `show_transient_text` reversion - a real status text
 * update always wins over a leftover transient message.
 *
 * @param text The text to be displayed on the LED matrix
 */
void update_text_matrix(String text) {
    transientUntilMs = 0;
    fill_message_buffer(text);
}

/**
 * Sets the WiFi mode LED ("LED3", distinct from the operating-status LED) to
 * indicate the RIID system's current network mode. Intended to be used with
 * the `update_wifi_led` RPC call.
 * 0: Access Point -> Red
 * 1: Station -> White
 *
 * @param mode The WiFi mode index
 */
void update_wifi_led(int mode) {
    switch (mode) {
        case 0:
            digitalWrite(WIFI_LED_R, 0);
            digitalWrite(WIFI_LED_G, 1);
            digitalWrite(WIFI_LED_B, 1);
            break;
        case 1:
            digitalWrite(WIFI_LED_R, 0);
            digitalWrite(WIFI_LED_G, 0);
            digitalWrite(WIFI_LED_B, 0);
            break;
        default:
            digitalWrite(WIFI_LED_R, 1);
            digitalWrite(WIFI_LED_G, 1);
            digitalWrite(WIFI_LED_B, 1);
    }
}

/**
 * Temporarily replaces the LED matrix message for `duration_ms`, then
 * automatically reverts to whatever text was showing beforehand (handled in
 * `loop()`). Used by wifi/wifi_mode_daemon.py to flash a one-shot "AP MODE"/
 * "STA MODE" message without needing to know or restore the RIID system's
 * own operating-status text itself. Intended to be used with the
 * `show_transient_text` RPC call.
 *
 * @param text The text to be displayed temporarily
 * @param duration_ms How long to display it before reverting, in milliseconds
 */
void show_transient_text(String text, int duration_ms) {
    if (transientUntilMs == 0) {
        memcpy(savedMessageBuffer, messageBuffer, BUF_SIZE);
    }
    fill_message_buffer(text);
    transientUntilMs = millis() + duration_ms;
}
