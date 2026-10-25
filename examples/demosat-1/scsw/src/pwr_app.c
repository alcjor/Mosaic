/* pwr_app.c - power application (PWR): telecommands and housekeeping */
#include "demosat_ids.h"
#include "pwr_app.h"

static uint32_t pwr_tc_count;

/* Handler for PWRC0101 (PWR_HTR_A_ON): switch battery heater A on. Argument: PWRP0001. */
static int pwr_htr_a_on(const tc_args_t *args)
{
    if (args == NULL) {
        return PWR_ERR_RANGE;
    }
    return drv_command(DEV_PWR, 0x0101u, args);
}

/* Handler for PWRC0112 (PWR_HTR_A_OFF): switch battery heater A off. */
static int pwr_htr_a_off(const tc_args_t *args)
{
    (void)args;
    return drv_command(DEV_PWR, 0x0102u, NULL);
}

/* Handler for PWRC0123 (PWR_SET_BAT_EOC): set the battery end-of-charge voltage. Argument: PWRP0010. */
static int pwr_set_bat_eoc(const tc_args_t *args)
{
    if (args == NULL) {
        return PWR_ERR_RANGE;
    }
    return drv_command(DEV_PWR, 0x0103u, args);
}

/* Handler for PWRC2476 (PWR_HTR_B_ON): switch battery heater B on. Argument: PWRP0001. */
static int pwr_htr_b_on(const tc_args_t *args)
{
    if (args == NULL) {
        return PWR_ERR_RANGE;
    }
    return drv_command(DEV_PWR, 0x0104u, args);
}

/* Handler for PWRC5141 (PWR_LCL_RESET): reset a tripped latching current limiter. Argument: PWRP9190. */
static int pwr_lcl_reset(const tc_args_t *args)
{
    if (args == NULL) {
        return PWR_ERR_RANGE;
    }
    return drv_command(DEV_PWR, 0x0105u, args);
}

/* Dispatch the telecommands addressed to the power application. */
int pwr_tc_dispatch(tc_id_t tc_id, const tc_args_t *args)
{
    pwr_tc_count++;
    switch (tc_id) {
    case TC_PWRC0101:   /* PWR_HTR_A_ON */
        return pwr_htr_a_on(args);
    case TC_PWRC0112:   /* PWR_HTR_A_OFF */
        return pwr_htr_a_off(args);
    case TC_PWRC0123:   /* PWR_SET_BAT_EOC */
        return pwr_set_bat_eoc(args);
    case TC_PWRC2476:   /* PWR_HTR_B_ON */
        return pwr_htr_b_on(args);
    case TC_PWRC5141:   /* PWR_LCL_RESET */
        return pwr_lcl_reset(args);
    default:
        return PWR_ERR_UNKNOWN_TC;
    }
}

/* Fill the PWR_HK packet, PUS (3,25). */
void pwr_hk_fill(hk_buf_t *buf)
{
    hk_put_u16(buf, PARAM_PWRT0012, adc_read(ADC_PWR_00));  /* BAT_V_MAIN */
    hk_put_u16(buf, PARAM_PWRT0281, adc_read(ADC_PWR_01));  /* BAT_I_MAIN */
    hk_put_u16(buf, PARAM_PWRT0020, adc_read(ADC_PWR_02));  /* BAT_TEMP_1 */
    hk_put_u16(buf, PARAM_PWRT0324, adc_read(ADC_PWR_03));  /* BAT_TEMP_2 */
    hk_put_u8(buf, PARAM_PWRT0031, drv_state(DEV_PWR, 4u));  /* HTR_A_STAT */
    hk_put_u8(buf, PARAM_PWRT8596, drv_state(DEV_PWR, 5u));  /* HTR_B_STAT */
    hk_put_u8(buf, PARAM_PWRT9647, drv_state(DEV_PWR, 6u));  /* HTR_A_MODE */
    hk_put_u16(buf, PARAM_PWRT0045, adc_read(ADC_PWR_07));  /* SA_I_TOTAL */
    hk_put_u16(buf, PARAM_PWRT0694, adc_read(ADC_PWR_08));  /* SA_V_OUT */
    hk_put_u16(buf, PARAM_PWRT1392, adc_read(ADC_PWR_09));  /* BUS_V_MAIN */
    hk_put_u8(buf, PARAM_PWRT5284, drv_state(DEV_PWR, 10u));  /* BCR_MODE */
    hk_put_u16(buf, PARAM_PWRT9077, adc_read(ADC_PWR_11));  /* BAT_EOC_V */
    hk_put_u16(buf, PARAM_PWRT8638, adc_read(ADC_PWR_12));  /* LCL_TRIP_CNT */
    hk_put_u16(buf, PARAM_PWRT2959, adc_read(ADC_PWR_13));  /* BAT_V */
}

/* Initialise the power application. */
void pwr_init(void)
{
    pwr_tc_count = 0u;
}
