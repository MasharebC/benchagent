/* Register-level BME280 driver — ESP-IDF v6 i2c_master, 100 kHz, addr 0x76.
 *
 * Implementation follows Bosch BST-BME280-DS002:
 *   register map    §5 / Table 18
 *   compensation    §8.1 int32 (T, H) and int64 (P) reference code
 *   init sequence   §5.4.3 — ctrl_hum BEFORE ctrl_meas, mandatory
 *
 * Wiring (DevKitC-1): BME280 SDA → GPIO8, SCL → GPIO9.
 */

#include "bme280.h"
#include <stdbool.h>
#include "driver/i2c_master.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "bme280";

#define I2C_SDA_PIN   8
#define I2C_SCL_PIN   9
#define I2C_FREQ_HZ   100000

/* What we program into the mode registers, and therefore what they must read
 * back as for the rest of the run. §5.4.3: ctrl_hum before ctrl_meas. */
#define CTRL_HUM_CFG  0x01  /* osrs_h ×1 */
#define CTRL_MEAS_CFG 0x27  /* osrs_t ×1, osrs_p ×1, normal mode */
#define CONFIG_CFG    0x00  /* t_sb 0.5 ms, filter off, I2C */

/* T×1 P×1 H×1 measures in ~9.3 ms (§9.1). Give it a generous margin before
 * concluding the part never measured. */
#define FIRST_MEAS_TIMEOUT_MS 200

/* Unpacked calibration coefficients — datasheet Tables 16 / 17. */
typedef struct {
    uint16_t dig_T1;
    int16_t  dig_T2, dig_T3;
    uint16_t dig_P1;
    int16_t  dig_P2, dig_P3, dig_P4, dig_P5;
    int16_t  dig_P6, dig_P7, dig_P8, dig_P9;
    uint8_t  dig_H1, dig_H3;
    int16_t  dig_H2, dig_H4, dig_H5;
    int8_t   dig_H6;
} bme280_calib_t;

static i2c_master_bus_handle_t s_bus;
static i2c_master_dev_handle_t s_dev;
static bme280_calib_t          s_cal;
static int32_t                 s_t_fine;   /* shared T→P→H; set by compensate_T */

/* ------------------------------------------------------------------ */
/* Low-level I2C                                                       */
/* ------------------------------------------------------------------ */

static esp_err_t reg_read(uint8_t reg, uint8_t *buf, size_t len)
{
    return i2c_master_transmit_receive(s_dev, &reg, 1, buf, len, 100);
}

static esp_err_t reg_write(uint8_t reg, uint8_t val)
{
    uint8_t pair[2] = {reg, val};
    return i2c_master_transmit(s_dev, pair, sizeof(pair), 100);
}

/* Write a register and confirm it reads back. A BME280 that is browning out
 * accepts the write and then loses it milliseconds later, so this is
 * necessary but not sufficient — bme280_read() re-checks on every sample. */
static esp_err_t reg_write_verify(uint8_t reg, uint8_t val)
{
    esp_err_t err = reg_write(reg, val);
    if (err != ESP_OK) { return err; }

    uint8_t got = 0;
    err = reg_read(reg, &got, 1);
    if (err != ESP_OK) { return err; }

    if (got != val) {
        ESP_LOGE(TAG, "reg 0x%02x: wrote 0x%02x, reads 0x%02x", reg, val, got);
        return ESP_ERR_INVALID_STATE;
    }
    return ESP_OK;
}

/* ------------------------------------------------------------------ */
/* Raw samples                                                         */
/* ------------------------------------------------------------------ */

typedef struct {
    int32_t adc_T, adc_P, adc_H;
} bme280_raw_t;

/* Burst-read 0xF7..0xFE and unpack the ADC words (§4.1): press[3] temp[3]
 * hum[2], each big-endian, T and P 20-bit left-aligned in 24. */
static esp_err_t read_raw(bme280_raw_t *out)
{
    uint8_t raw[8] = {0};
    esp_err_t err = reg_read(BME280_REG_DATA, raw, sizeof(raw));
    if (err != ESP_OK) { return err; }

    out->adc_P = (int32_t)(((uint32_t)raw[0] << 12) |
                           ((uint32_t)raw[1] <<  4) |
                           ((uint32_t)raw[2] >>  4));
    out->adc_T = (int32_t)(((uint32_t)raw[3] << 12) |
                           ((uint32_t)raw[4] <<  4) |
                           ((uint32_t)raw[5] >>  4));
    out->adc_H = (int32_t)(((uint32_t)raw[6] <<  8) |
                            (uint32_t)raw[7]);
    return ESP_OK;
}

/* True when all three channels sit at their power-on reset values. Any one
 * channel could in principle land on mid-scale legitimately; all three at
 * once is the reset signature, not weather. */
static bool raw_is_reset_default(const bme280_raw_t *r)
{
    return r->adc_T == BME280_ADC_RESET_TP &&
           r->adc_P == BME280_ADC_RESET_TP &&
           r->adc_H == BME280_ADC_RESET_H;
}

/* ------------------------------------------------------------------ */
/* Calibration                                                         */
/* ------------------------------------------------------------------ */

static esp_err_t read_calibration(void)
{
    /* Bank 1: 0x88..0xA1 (26 bytes) — T1..T3, P1..P9, H1 */
    uint8_t c[26] = {0};
    esp_err_t err = reg_read(BME280_REG_CALIB00, c, sizeof(c));
    if (err != ESP_OK) { return err; }

    s_cal.dig_T1 = (uint16_t)((uint16_t)c[1]  << 8 | c[0]);
    s_cal.dig_T2 = (int16_t) ((uint16_t)c[3]  << 8 | c[2]);
    s_cal.dig_T3 = (int16_t) ((uint16_t)c[5]  << 8 | c[4]);
    s_cal.dig_P1 = (uint16_t)((uint16_t)c[7]  << 8 | c[6]);
    s_cal.dig_P2 = (int16_t) ((uint16_t)c[9]  << 8 | c[8]);
    s_cal.dig_P3 = (int16_t) ((uint16_t)c[11] << 8 | c[10]);
    s_cal.dig_P4 = (int16_t) ((uint16_t)c[13] << 8 | c[12]);
    s_cal.dig_P5 = (int16_t) ((uint16_t)c[15] << 8 | c[14]);
    s_cal.dig_P6 = (int16_t) ((uint16_t)c[17] << 8 | c[16]);
    s_cal.dig_P7 = (int16_t) ((uint16_t)c[19] << 8 | c[18]);
    s_cal.dig_P8 = (int16_t) ((uint16_t)c[21] << 8 | c[20]);
    s_cal.dig_P9 = (int16_t) ((uint16_t)c[23] << 8 | c[22]);
    s_cal.dig_H1 = c[25];  /* 0xA1 */

    /* Bank 2: 0xE1..0xE7 (7 bytes) — H2..H6 */
    uint8_t e[7] = {0};
    err = reg_read(BME280_REG_CALIB26, e, sizeof(e));
    if (err != ESP_OK) { return err; }

    s_cal.dig_H2 = (int16_t)((uint16_t)e[1] << 8 | e[0]);
    s_cal.dig_H3 = e[2];
    /* H4[11:4]=0xE4[7:0], H4[3:0]=0xE5[3:0] — classic nibble trap (§4.2.2) */
    s_cal.dig_H4 = (int16_t)((int16_t)(e[3]) << 4 | ((int16_t)(e[4]) & 0x0F));
    /* H5[11:4]=0xE6[7:0], H5[3:0]=0xE5[7:4] */
    s_cal.dig_H5 = (int16_t)((int16_t)(e[5]) << 4 | ((int16_t)(e[4]) >> 4));
    s_cal.dig_H6 = (int8_t)e[6];

    return ESP_OK;
}

/* ------------------------------------------------------------------ */
/* Compensation — Bosch BST-BME280-DS002 §8.1 reference code          */
/* ------------------------------------------------------------------ */

/* Returns temperature in hundredths of °C (2345 = 23.45 °C).
 * Side-effect: sets s_t_fine, which compensate_P and compensate_H require. */
static int32_t compensate_T(int32_t adc_T)
{
    int32_t var1 = ((((adc_T >> 3) - ((int32_t)s_cal.dig_T1 << 1))) *
                    (int32_t)s_cal.dig_T2) >> 11;
    int32_t var2 = (((((adc_T >> 4) - (int32_t)s_cal.dig_T1) *
                      ((adc_T >> 4) - (int32_t)s_cal.dig_T1)) >> 12) *
                    (int32_t)s_cal.dig_T3) >> 14;
    s_t_fine = var1 + var2;
    return (s_t_fine * 5 + 128) >> 8;
}

/* Returns pressure in Q24.8 Pa (divide by 25600 for hPa). */
static uint32_t compensate_P(int32_t adc_P)
{
    int64_t var1 = (int64_t)s_t_fine - 128000LL;
    int64_t var2 = var1 * var1 * (int64_t)s_cal.dig_P6;
    var2 += (var1 * (int64_t)s_cal.dig_P5) << 17;
    var2 += (int64_t)s_cal.dig_P4 << 35;
    var1  = ((var1 * var1 * (int64_t)s_cal.dig_P3) >> 8) +
            ((var1 * (int64_t)s_cal.dig_P2) << 12);
    var1  = ((((int64_t)1 << 47) + var1) * (int64_t)s_cal.dig_P1) >> 33;
    if (var1 == 0) { return 0; }   /* prevent div-by-zero */
    int64_t p = 1048576LL - (int64_t)adc_P;
    p = (((p << 31) - var2) * 3125LL) / var1;
    var1 = ((int64_t)s_cal.dig_P9 * (p >> 13) * (p >> 13)) >> 25;
    var2 = ((int64_t)s_cal.dig_P8 * p) >> 19;
    p = ((p + var1 + var2) >> 8) + ((int64_t)s_cal.dig_P7 << 4);
    return (uint32_t)p;
}

/* Returns humidity in Q22.10 %RH (divide by 1024 for %RH). */
static uint32_t compensate_H(int32_t adc_H)
{
    int32_t v = s_t_fine - (int32_t)76800;
    v = ((((adc_H << 14) -
           ((int32_t)s_cal.dig_H4 << 20) -
           ((int32_t)s_cal.dig_H5 * v) + (int32_t)16384) >> 15) *
         ((((((v * (int32_t)s_cal.dig_H6) >> 10) *
             (((v * (int32_t)s_cal.dig_H3) >> 11) + (int32_t)32768)) >> 10) +
           (int32_t)2097152) * (int32_t)s_cal.dig_H2 + 8192) >> 14);
    v -= ((((v >> 15) * (v >> 15)) >> 7) * (int32_t)s_cal.dig_H1) >> 4;
    if (v < 0) { v = 0; }
    if (v > 419430400) { v = 419430400; }
    return (uint32_t)(v >> 12);
}

/* ------------------------------------------------------------------ */
/* Public API                                                          */
/* ------------------------------------------------------------------ */

const char *bme280_strerror(int rc)
{
    switch (rc) {
    case BME280_OK:            return "ok";
    case BME280_ERR_IO:        return "i2c-io";
    case BME280_ERR_CHIP_ID:   return "chip-id";
    case BME280_ERR_CONFIG:    return "config-lost";
    case BME280_ERR_NO_DATA:   return "no-measurement";
    default:                   return "unknown";
    }
}

int bme280_init(void)
{
    /* Create I2C master bus on GPIO8 (SDA) / GPIO9 (SCL) */
    i2c_master_bus_config_t bus_cfg = {
        .clk_source        = I2C_CLK_SRC_DEFAULT,
        .i2c_port          = I2C_NUM_0,
        .scl_io_num        = I2C_SCL_PIN,
        .sda_io_num        = I2C_SDA_PIN,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,
    };
    if (i2c_new_master_bus(&bus_cfg, &s_bus) != ESP_OK) {
        ESP_LOGE(TAG, "i2c bus init failed");
        return BME280_ERR_IO;
    }

    /* Add BME280 as 7-bit device at 100 kHz */
    i2c_device_config_t dev_cfg = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address  = BME280_I2C_ADDR,
        .scl_speed_hz    = I2C_FREQ_HZ,
    };
    if (i2c_master_bus_add_device(s_bus, &dev_cfg, &s_dev) != ESP_OK) {
        ESP_LOGE(TAG, "i2c device add failed");
        return BME280_ERR_IO;
    }

    /* First sign of life: probe chip ID */
    uint8_t id = 0;
    if (reg_read(BME280_REG_ID, &id, 1) != ESP_OK || id != BME280_CHIP_ID) {
        ESP_LOGE(TAG, "chip id: got 0x%02x, want 0x%02x — check wiring at 0x76",
                 id, BME280_CHIP_ID);
        return BME280_ERR_CHIP_ID;
    }
    ESP_LOGI(TAG, "chip id 0x%02x ok", id);

    /* Soft-reset (§5.4.2); reset takes ~2 ms */
    if (reg_write(BME280_REG_RESET, 0xB6) != ESP_OK) { return BME280_ERR_IO; }
    vTaskDelay(pdMS_TO_TICKS(10));

    /* Wait for NVM copy to finish (im_update bit, status[0]) */
    uint8_t status = 0;
    for (int i = 0; i < 10; i++) {
        if (reg_read(BME280_REG_STATUS, &status, 1) != ESP_OK) {
            return BME280_ERR_IO;
        }
        if (!(status & 0x01)) { break; }
        vTaskDelay(pdMS_TO_TICKS(5));
    }

    /* Load calibration from both register banks */
    if (read_calibration() != ESP_OK) {
        ESP_LOGE(TAG, "calibration read failed");
        return BME280_ERR_IO;
    }

    /* §5.4.3: ctrl_hum MUST be written before ctrl_meas for the value to
     * latch. Each write is read straight back — a part that cannot hold its
     * configuration must fail here, not silently emit compensated blanks. */
    if (reg_write_verify(BME280_REG_CTRL_HUM,  CTRL_HUM_CFG)  != ESP_OK ||
        reg_write_verify(BME280_REG_CTRL_MEAS, CTRL_MEAS_CFG) != ESP_OK ||
        reg_write_verify(BME280_REG_CONFIG,    CONFIG_CFG)    != ESP_OK) {
        ESP_LOGE(TAG, "configuration did not stick — sensor resetting? "
                      "check VDD/GND and whether the breakout needs 5V");
        return BME280_ERR_CONFIG;
    }

    /* Configured is not the same as measuring. Wait for the data registers to
     * leave their reset defaults, so init cannot report success for a part
     * that is stuck in sleep. */
    bme280_raw_t raw = {0};
    for (int waited = 0; waited < FIRST_MEAS_TIMEOUT_MS; waited += 10) {
        if (read_raw(&raw) != ESP_OK) { return BME280_ERR_IO; }
        if (!raw_is_reset_default(&raw)) {
            ESP_LOGI(TAG, "init ok — normal mode, osrs T×1 P×1 H×1, filter off");
            return BME280_OK;
        }
        vTaskDelay(pdMS_TO_TICKS(10));
    }

    ESP_LOGE(TAG, "no measurement after %d ms — data registers still at reset "
                  "defaults (adc_T=0x%05lx adc_P=0x%05lx adc_H=0x%04lx)",
             FIRST_MEAS_TIMEOUT_MS, (unsigned long)raw.adc_T,
             (unsigned long)raw.adc_P, (unsigned long)raw.adc_H);
    return BME280_ERR_NO_DATA;
}

int bme280_read(float *temp_c, float *press_hpa, float *hum_pct)
{
    /* Cheapest possible liveness check, one byte per sample: if the part
     * reset since init it is back in sleep and ctrl_meas reads 0x00. Catching
     * it here is what stops a brown-out from looking like steady telemetry. */
    uint8_t ctrl_meas = 0;
    if (reg_read(BME280_REG_CTRL_MEAS, &ctrl_meas, 1) != ESP_OK) {
        return BME280_ERR_IO;
    }
    if (ctrl_meas != CTRL_MEAS_CFG) {
        ESP_LOGE(TAG, "ctrl_meas is 0x%02x, configured 0x%02x — sensor reset",
                 ctrl_meas, CTRL_MEAS_CFG);
        return BME280_ERR_CONFIG;
    }

    bme280_raw_t raw = {0};
    if (read_raw(&raw) != ESP_OK) { return BME280_ERR_IO; }

    /* Never compensate the reset defaults. Doing so is what produced the
     * frozen, plausible-looking 22.30C / 671.23hPa / 0.0%RH that hid a dead
     * sensor behind a healthy-looking log. */
    if (raw_is_reset_default(&raw)) {
        ESP_LOGE(TAG, "data registers at reset defaults — no measurement");
        return BME280_ERR_NO_DATA;
    }

    /* compensate_T MUST run first — populates s_t_fine for P and H */
    int32_t  t100 = compensate_T(raw.adc_T);
    uint32_t p256 = compensate_P(raw.adc_P);
    uint32_t h1k  = compensate_H(raw.adc_H);

    *temp_c    = (float)t100 / 100.0f;
    *press_hpa = (float)p256 / 25600.0f;   /* Q24.8 Pa → hPa: ÷256÷100 */
    *hum_pct   = (float)h1k  / 1024.0f;

    return BME280_OK;
}
