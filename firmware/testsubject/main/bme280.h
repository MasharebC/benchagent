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

/* init: probe chip id, soft-reset, read calibration blob, configure
 * oversampling + normal mode. Returns 0 on success. */
int bme280_init(void);

/* read: burst-read 0xF7..0xFE, apply the datasheet compensation
 * (int32 t_fine dance) and return engineering units. Returns 0 on success. */
int bme280_read(float *temp_c, float *press_hpa, float *hum_pct);
