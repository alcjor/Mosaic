/* obc_app.c - on-board computer application (OBC): telecommands and housekeeping */
#include "demosat_ids.h"
#include "obc_app.h"

static uint32_t obc_tc_count;

/* Handler for OBCC2858 (OBC_HK_ENABLE): enable a housekeeping report. Argument: OBCP4382. */
static int obc_hk_enable(const tc_args_t *args)
{
    if (args == NULL) {
        return OBC_ERR_RANGE;
    }
    return drv_command(DEV_OBC, 0x0401u, args);
}

/* Handler for OBCC8719 (OBC_HK_DISABLE): disable a housekeeping report. Argument: OBCP4382. */
static int obc_hk_disable(const tc_args_t *args)
{
    if (args == NULL) {
        return OBC_ERR_RANGE;
    }
    return drv_command(DEV_OBC, 0x0402u, args);
}

/* Handler for OBCC9182 (OBC_CONN_TEST): perform a connection test. */
static int obc_conn_test(const tc_args_t *args)
{
    (void)args;
    return drv_command(DEV_OBC, 0x0403u, NULL);
}

/* Handler for OBCC2725 (OBC_PAR_REPORT): report on-board parameter values. Argument: OBCP6968. */
static int obc_par_report(const tc_args_t *args)
{
    if (args == NULL) {
        return OBC_ERR_RANGE;
    }
    return drv_command(DEV_OBC, 0x0404u, args);
}

/* Handler for OBCC1080 (OBC_PAR_SET): set an on-board parameter value. Arguments: OBCP6968, OBCP8975. */
static int obc_par_set(const tc_args_t *args)
{
    if (args == NULL) {
        return OBC_ERR_RANGE;
    }
    return drv_command(DEV_OBC, 0x0405u, args);
}

/* Dispatch the telecommands addressed to the on-board computer application. */
int obc_tc_dispatch(tc_id_t tc_id, const tc_args_t *args)
{
    obc_tc_count++;
    switch (tc_id) {
    case TC_OBCC2858:   /* OBC_HK_ENABLE */
        return obc_hk_enable(args);
    case TC_OBCC8719:   /* OBC_HK_DISABLE */
        return obc_hk_disable(args);
    case TC_OBCC9182:   /* OBC_CONN_TEST */
        return obc_conn_test(args);
    case TC_OBCC2725:   /* OBC_PAR_REPORT */
        return obc_par_report(args);
    case TC_OBCC1080:   /* OBC_PAR_SET */
        return obc_par_set(args);
    default:
        return OBC_ERR_UNKNOWN_TC;
    }
}

/* Fill the OBC_HK packet, PUS (3,25). */
void obc_hk_fill(hk_buf_t *buf)
{
    hk_put_u16(buf, PARAM_OBCT3700, adc_read(ADC_OBC_00));  /* CPU_LOAD */
    hk_put_u16(buf, PARAM_OBCT9283, adc_read(ADC_OBC_01));  /* MEM_FREE */
    hk_put_u8(buf, PARAM_OBCT4639, drv_state(DEV_OBC, 2u));  /* WDG_STAT */
    hk_put_u16(buf, PARAM_OBCT0518, adc_read(ADC_OBC_03));  /* RESET_CNT */
    hk_put_u16(buf, PARAM_OBCT4211, adc_read(ADC_OBC_04));  /* EDAC_ERR_CNT */
    hk_put_u16(buf, PARAM_OBCT2880, adc_read(ADC_OBC_05));  /* OBT_DRIFT */
    hk_put_u8(buf, PARAM_OBCT6792, drv_state(DEV_OBC, 6u));  /* SW_MODE */
    hk_put_u16(buf, PARAM_OBCT5611, adc_read(ADC_OBC_07));  /* TC_ACC_CNT */
    hk_put_u16(buf, PARAM_OBCT9701, adc_read(ADC_OBC_08));  /* TC_REJ_CNT */
    hk_put_u16(buf, PARAM_OBCT4459, adc_read(ADC_OBC_09));  /* EVT_LAST_ID */
    hk_put_u16(buf, PARAM_OBCT8109, adc_read(ADC_OBC_10));  /* EVT_CNT */
    hk_put_u16(buf, PARAM_OBCT1310, adc_read(ADC_OBC_11));  /* RAIL_V_5V */
    hk_put_u16(buf, PARAM_OBCT9444, adc_read(ADC_OBC_12));  /* HK_ENA_CNT */
}

/* Initialise the on-board computer application. */
void obc_init(void)
{
    obc_tc_count = 0u;
}
