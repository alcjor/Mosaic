/* aoc_app.c - attitude and orbit control application (AOC): telecommands and housekeeping */
#include "demosat_ids.h"
#include "aoc_app.h"

static uint32_t aoc_tc_count;

/* Handler for AOCC1067 (AOC_MODE_SET): change the attitude control mode. Argument: AOCP9017. */
static int aoc_mode_set(const tc_args_t *args)
{
    if (args == NULL) {
        return AOC_ERR_RANGE;
    }
    return drv_command(DEV_AOC, 0x0301u, args);
}

/* Handler for AOCC6804 (AOC_STR_ON): switch the star tracker on. */
static int aoc_str_on(const tc_args_t *args)
{
    (void)args;
    return drv_command(DEV_AOC, 0x0302u, NULL);
}

/* Handler for AOCC9208 (AOC_STR_OFF): switch the star tracker off. */
static int aoc_str_off(const tc_args_t *args)
{
    (void)args;
    return drv_command(DEV_AOC, 0x0303u, NULL);
}

/* Handler for AOCC7889 (AOC_RW_SPEED_SET): set a reaction wheel speed. Arguments: AOCP7625, AOCP5945. */
static int aoc_rw_speed_set(const tc_args_t *args)
{
    if (args == NULL) {
        return AOC_ERR_RANGE;
    }
    return drv_command(DEV_AOC, 0x0304u, args);
}

/* Handler for AOCC6352 (AOC_GYR_RESET): reset the gyro bias estimate. */
static int aoc_gyr_reset(const tc_args_t *args)
{
    (void)args;
    return drv_command(DEV_AOC, 0x0305u, NULL);
}

/* Dispatch the telecommands addressed to the attitude and orbit control application. */
int aoc_tc_dispatch(tc_id_t tc_id, const tc_args_t *args)
{
    aoc_tc_count++;
    switch (tc_id) {
    case TC_AOCC1067:   /* AOC_MODE_SET */
        return aoc_mode_set(args);
    case TC_AOCC6804:   /* AOC_STR_ON */
        return aoc_str_on(args);
    case TC_AOCC9208:   /* AOC_STR_OFF */
        return aoc_str_off(args);
    case TC_AOCC7889:   /* AOC_RW_SPEED_SET */
        return aoc_rw_speed_set(args);
    case TC_AOCC6352:   /* AOC_GYR_RESET */
        return aoc_gyr_reset(args);
    default:
        return AOC_ERR_UNKNOWN_TC;
    }
}

/* Fill the AOC_HK packet, PUS (3,25). */
void aoc_hk_fill(hk_buf_t *buf)
{
    hk_put_u8(buf, PARAM_AOCT2478, drv_state(DEV_AOC, 0u));  /* AOC_MODE */
    hk_put_u16(buf, PARAM_AOCT2611, adc_read(ADC_AOC_01));  /* GYR_RATE_X */
    hk_put_u16(buf, PARAM_AOCT6114, adc_read(ADC_AOC_02));  /* GYR_RATE_Y */
    hk_put_u16(buf, PARAM_AOCT5392, adc_read(ADC_AOC_03));  /* GYR_RATE_Z */
    hk_put_u16(buf, PARAM_AOCT0240, adc_read(ADC_AOC_04));  /* SUN_ANGLE */
    hk_put_u16(buf, PARAM_AOCT8321, adc_read(ADC_AOC_05));  /* RW1_SPEED */
    hk_put_u16(buf, PARAM_AOCT4403, adc_read(ADC_AOC_06));  /* RW2_SPEED */
    hk_put_u16(buf, PARAM_AOCT9618, adc_read(ADC_AOC_07));  /* RW3_SPEED */
    hk_put_u16(buf, PARAM_AOCT2376, adc_read(ADC_AOC_08));  /* MTQ_X_DIPOLE */
    hk_put_u8(buf, PARAM_AOCT8208, drv_state(DEV_AOC, 9u));  /* STR_STAT */
    hk_put_u8(buf, PARAM_AOCT3539, drv_state(DEV_AOC, 10u));  /* STR_LOCK */
    hk_put_u16(buf, PARAM_AOCT0932, adc_read(ADC_AOC_11));  /* ATT_ERR */
    hk_put_u16(buf, PARAM_AOCT8473, adc_read(ADC_AOC_12));  /* RW1_TEMP */
}

/* Initialise the attitude and orbit control application. */
void aoc_init(void)
{
    aoc_tc_count = 0u;
}
