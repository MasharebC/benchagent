/* testsubject — FreeRTOS firmware under test for BenchAgent / FaultBench.
 *
 * Architecture (deliberate, not default):
 *   gpio ISR ──► xQueueSendFromISR ──► sensor_task (prio 5, feeds task WDT)
 *   sensor_task ──► sample queue ──► logger_task (prio 3)
 *   heartbeat_task (prio 1): 1 Hz liveness line + free-heap telemetry
 *
 * Rules this file must obey (see docs/failure-modes.md):
 *   - ISR-safe APIs only inside ISRs; all real work deferred to tasks
 *   - explicit stack sizes per task, chosen from measured high-water marks
 *   - task WDT subscribed deliberately by sensor_task; idle-task WDT left on
 *   - NO sleep modes ever (keeps USB-Serial-JTAG alive — roadmap Stage 1)
 *   - builds with -Wall -Wextra -Werror
 *
 * Planted bugs are compile-flag gated so ground truth is falsifiable:
 *   -DBUG_WDT_STARVE   busy-loop in sensor_task starves IDLE0's WDT feed
 *   -DBUG_HEAP_LEAK    (Stage 1) slow leak in logger path
 *   -DBUG_BUF_OVF      (Stage 1) off-by-one memcpy → LoadProhibited
 */

#include <stdio.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "esp_log.h"
#include "esp_task_wdt.h"
#include "esp_heap_caps.h"
#include "bme280.h"

static const char *TAG = "testsubject";

/* Explicit stack sizing — revisit against uxTaskGetStackHighWaterMark()
 * once running on hardware; numbers below are conservative starting points. */
#define SENSOR_TASK_STACK    3072
#define LOGGER_TASK_STACK    2560
#define HEARTBEAT_TASK_STACK 2048

typedef struct {
    float temp_c;
    float press_hpa;
    float hum_pct;
    int64_t ts_us;
} sample_t;

static QueueHandle_t s_sample_q;

#ifndef BUG_FLAGS_STR
#define BUG_FLAGS_STR "none"
#endif

static void sensor_task(void *arg)
{
    (void)arg;
    ESP_ERROR_CHECK(esp_task_wdt_add(NULL)); /* subscribe deliberately */

    for (;;) {
#ifdef BUG_WDT_STARVE
        /* BUG: poll "until data ready" with a busy-wait. Never blocks, never
         * yields to IDLE0, whose WDT feed then times out. Signature:
         * task_wdt names IDLE0 starved, sensor_task running on CPU0,
         * abort() → SW_CPU_RESET, boot loop. */
        volatile uint32_t spin = 0;
        while (1) { spin++; }
#endif
        sample_t s = {0};
        if (bme280_read(&s.temp_c, &s.press_hpa, &s.hum_pct) == 0) {
            s.ts_us = esp_timer_get_time();
            (void)xQueueSend(s_sample_q, &s, 0);
        }
        ESP_ERROR_CHECK(esp_task_wdt_reset());
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}

static void logger_task(void *arg)
{
    (void)arg;
    sample_t s;
    for (;;) {
        if (xQueueReceive(s_sample_q, &s, portMAX_DELAY) == pdTRUE) {
            ESP_LOGI(TAG, "sensor: T=%.2fC P=%.2fhPa H=%.1f%%",
                     s.temp_c, s.press_hpa, s.hum_pct);
        }
    }
}

static void heartbeat_task(void *arg)
{
    (void)arg;
    uint32_t n = 0;
    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(1000));
        ESP_LOGI(TAG, "heartbeat #%lu uptime=%.1fs free_heap=%u",
                 (unsigned long)++n,
                 (double)esp_timer_get_time() / 1e6,
                 (unsigned)heap_caps_get_free_size(MALLOC_CAP_DEFAULT));
    }
}

void app_main(void)
{
    ESP_LOGI(TAG, "build: BUG_FLAGS=%s", BUG_FLAGS_STR);

    if (bme280_init() != 0) {
        ESP_LOGE(TAG, "i2c: BME280 probe failed — check wiring at 0x76");
        /* Keep running: the bench must be able to classify sensor-absent
         * boots as their own story, not a crash. */
    }

    s_sample_q = xQueueCreate(8, sizeof(sample_t));
    configASSERT(s_sample_q != NULL);

    xTaskCreatePinnedToCore(sensor_task, "sensor_task", SENSOR_TASK_STACK,
                            NULL, 5, NULL, 0);
    xTaskCreatePinnedToCore(logger_task, "logger_task", LOGGER_TASK_STACK,
                            NULL, 3, NULL, 0);
    xTaskCreatePinnedToCore(heartbeat_task, "heartbeat_task",
                            HEARTBEAT_TASK_STACK, NULL, 1, NULL, 1);

    ESP_LOGI(TAG, "tasks: sensor_task(prio 5) logger_task(prio 3) heartbeat_task(prio 1)");
}
