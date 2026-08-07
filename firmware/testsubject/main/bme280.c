/* Register-level BME280 driver implementation.
 *
 * DELIBERATELY UNIMPLEMENTED SCAFFOLD — write this yourself from the
 * datasheet during the Stage-0 weekend block (roadmap Stage 0, item 3).
 * The point of this file is that YOU can defend it line-by-line; generated
 * or copied compensation code defeats the purpose.
 *
 * Implementation order that works well:
 *  1. i2c_master bus + device setup (ESP-IDF v6 i2c_master driver, 100 kHz)
 *  2. read reg 0xD0, assert 0x60 — first sign of life
 *  3. soft reset (0xE0 <= 0xB6), wait for status im_update clear
 *  4. read calib 0x88..0xA1 and 0xE1..0xE7 into the dig_* struct
 *     (mind the signed/unsigned and the dig_H4/H5 nibble packing — the
 *     classic place everyone gets it wrong)
 *  5. ctrl_hum THEN ctrl_meas (order matters, datasheet §5.4.3), normal mode
 *  6. burst read 0xF7..0xFE, run the datasheet §8.1 compensation with t_fine
 *  7. sanity-check against a room: ~20-25C, ~1000 hPa, ~30-60 %RH
 */
#include "bme280.h"

int bme280_init(void)
{
    /* TODO(you): see header. Returning -1 keeps the app honest about a
     * missing sensor until the real driver exists. */
    return -1;
}

int bme280_read(float *temp_c, float *press_hpa, float *hum_pct)
{
    (void)temp_c; (void)press_hpa; (void)hum_pct;
    return -1;
}
