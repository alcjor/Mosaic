/* tcs_app.c - thermal control application (TCS): telecommands and housekeeping */
#include "demosat_ids.h"
#include "tcs_app.h"

static uint32_t tcs_tc_count;

/* Handler for TCSC9695 (TCS_HL1_ON): switch heater line 1 on. Argument: TCSP6912. */
static int tcs_hl1_on(const tc_args_t *args)
{
    if (args == NULL) {
        return TCS_ERR_RANGE;
    }
    return drv_command(DEV_TCS, 0x0201u, args);
}

/* Handler for TCSC1330 (TCS_HL1_OFF): switch heater line 1 off. */
static int tcs_hl1_off(const tc_args_t *args)
{
    (void)args;
    return drv_command(DEV_TCS, 0x0202u, NULL);
}

/* Handler for TCSC1076 (TCS_SET_HL1_SETP): set the heater line 1 set point. Argument: TCSP9614. */
static int tcs_set_hl1_setp(const tc_args_t *args)
{
    if (args == NULL) {
        return TCS_ERR_RANGE;
    }
    return drv_command(DEV_TCS, 0x0203u, args);
}

/* Handler for TCSC1484 (TCS_MODE_SET): change the thermal control mode. Argument: TCSP2480. */
static int tcs_mode_set(const tc_args_t *args)
{
    if (args == NULL) {
        return TCS_ERR_RANGE;
    }
    return drv_command(DEV_TCS, 0x0204u, args);
}

/* Handler for TCSC0408 (TCS_HL2_ON): switch heater line 2 on. Argument: TCSP6912. */
static int tcs_hl2_on(const tc_args_t *args)
{
    if (args == NULL) {
        return TCS_ERR_RANGE;
    }
    return drv_command(DEV_TCS, 0x0205u, args);
}

/* Dispatch the telecommands addressed to the thermal control application. */
int tcs_tc_dispatch(tc_id_t tc_id, const tc_args_t *args)
{
    tcs_tc_count++;
    switch (tc_id) {
    case TC_TCSC9695:   /* TCS_HL1_ON */
        return tcs_hl1_on(args);
    case TC_TCSC1330:   /* TCS_HL1_OFF */
        return tcs_hl1_off(args);
    case TC_TCSC1076:   /* TCS_SET_HL1_SETP */
        return tcs_set_hl1_setp(args);
    case TC_TCSC1484:   /* TCS_MODE_SET */
        return tcs_mode_set(args);
    case TC_TCSC0408:   /* TCS_HL2_ON */
        return tcs_hl2_on(args);
    default:
        return TCS_ERR_UNKNOWN_TC;
    }
}

/* Fill the TCS_HK packet, PUS (3,25). */
void tcs_hk_fill(hk_buf_t *buf)
{
    hk_put_u8(buf, PARAM_TCST6132, drv_state(DEV_TCS, 0u));  /* HL1_STAT */
    hk_put_u8(buf, PARAM_TCST4051, drv_state(DEV_TCS, 1u));  /* HL2_STAT */
    hk_put_u8(buf, PARAM_TCST1019, drv_state(DEV_TCS, 2u));  /* HL3_STAT */
    hk_put_u8(buf, PARAM_TCST7244, drv_state(DEV_TCS, 3u));  /* HL1_MODE */
    hk_put_u16(buf, PARAM_TCST9481, adc_read(ADC_TCS_04));  /* HL1_SETP */
    hk_put_u16(buf, PARAM_TCST0779, adc_read(ADC_TCS_05));  /* RAD_TEMP_1 */
    hk_put_u16(buf, PARAM_TCST0971, adc_read(ADC_TCS_06));  /* RAD_TEMP_2 */
    hk_put_u16(buf, PARAM_TCST1795, adc_read(ADC_TCS_07));  /* TANK_TEMP */
    hk_put_u16(buf, PARAM_TCST3723, adc_read(ADC_TCS_08));  /* OBC_BRD_TEMP */
    hk_put_u16(buf, PARAM_TCST7158, adc_read(ADC_TCS_09));  /* PLD_IF_TEMP */
    hk_put_u8(buf, PARAM_TCST3307, drv_state(DEV_TCS, 10u));  /* TCS_MODE */
    hk_put_u16(buf, PARAM_TCST7930, adc_read(ADC_TCS_11));  /* HL_I_TOTAL */
    hk_put_u16(buf, PARAM_TCST2520, adc_read(ADC_TCS_12));  /* TH_FAIL_CNT */
    hk_put_u16(buf, PARAM_TCST8951, adc_read(ADC_TCS_13));  /* HL_V */
}

/* Initialise the thermal control application. */
void tcs_init(void)
{
    tcs_tc_count = 0u;
}
