/* Register-level BME280 driver — written from the Bosch datasheet, no
 * libraries, no managed components. THIS FILE IS THE ONE YOU WRITE YOURSELF
 * over the Stage-0/Stage-1 weekend blocks: it's the code an embedded
 * reviewer opens first and the one you defend line-by-line in interviews.
 *
 * Scaffold provided: register map + interface. Implementation: yours.
 * Datasheet: BST-BME280-DS002 (registers §5, compensation formulas §4.2.3,
 * appendix 8.1 for the reference int32/int64 compensation code). */
#pragma once
#include <stdint.h>

/* 7-bit I2C address: 0x76 (SDO→GND) or 0x77 (SDO→VDDIO) */
#define BME280_I2C_ADDR      0x76

/* Register map (datasheet Table 18) */
#define BME280_REG_CALIB00   0x88  /* dig_T1..dig_P9, 26 bytes through 0xA1 */
#define BME280_REG_ID        0xD0  /* chip id, reads 0x60 */
#define BME280_REG_RESET     0xE0  /* write 0xB6 for soft reset */
#define BME280_REG_CALIB26   0xE1  /* dig_H2..dig_H6 */
#define BME280_REG_CTRL_HUM  0xF2  /* osrs_h; write BEFORE ctrl_meas to latch */
#define BME280_REG_STATUS    0xF3  /* bit3 measuring, bit0 im_update */
#define BME280_REG_CTRL_MEAS 0xF4  /* osrs_t | osrs_p | mode */
#define BME280_REG_CONFIG    0xF5  /* t_sb | filter | spi3w_en */
#define BME280_REG_DATA      0xF7  /* press[3] temp[3] hum[2] burst read */

#define BME280_CHIP_ID       0x60

/* Power-on reset defaults of the data registers (datasheet Table 18). A part
 * that has reset and not yet measured reads back exactly these. They are NOT
 * a measurement, but the compensation formulas will happily turn them into
 * plausible-looking engineering units — 22.30 C / 671 hPa / 0.0 %RH with a
 * typical calibration blob. Reject them at the source. */
#define BME280_ADC_RESET_TP  0x80000  /* 20-bit temperature and pressure */
#define BME280_ADC_RESET_H   0x8000   /* 16-bit humidity */

/* Return codes. Distinguishable so the serial log names the actual fault
 * instead of a generic failure — the bench classifies on these strings. */
#define BME280_OK             0
#define BME280_ERR_IO       (-1)  /* I2C transaction failed outright */
#define BME280_ERR_CHIP_ID  (-2)  /* wrong or absent chip id at 0x76 */
#define BME280_ERR_CONFIG   (-3)  /* ctrl_meas did not hold what we wrote —
                                   * the part reset under us (brown-out) */
#define BME280_ERR_NO_DATA  (-4)  /* registers still at reset defaults: the
                                   * sensor has never completed a measurement */

/* Human-readable name for a BME280_ERR_* code, for logging. */
const char *bme280_strerror(int rc);

/* init: probe chip id, soft-reset, read calibration blob, configure
 * oversampling + normal mode, then verify the configuration actually stuck
 * and that a first measurement completes. Returns BME280_OK on success. */
int bme280_init(void);

/* read: confirm the part is still configured, burst-read 0xF7..0xFE, reject
 * the reset defaults, then apply the datasheet compensation (int32 t_fine
 * dance) and return engineering units. Returns BME280_OK on success; on
 * failure the out-params are left untouched. */
int bme280_read(float *temp_c, float *press_hpa, float *hum_pct);
