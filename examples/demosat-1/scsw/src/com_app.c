/* com_app.c - communications application (COM): telecommands and housekeeping */
#include "demosat_ids.h"
#include "com_app.h"

static uint32_t com_tc_count;

/* Handler for COMC3469 (COM_TX_ON): switch the transmitter on. Argument: COMP9910. */
static int com_tx_on(const tc_args_t *args)
{
    if (args == NULL) {
        return COM_ERR_RANGE;
    }
    return drv_command(DEV_COM, 0x0501u, args);
}

/* Handler for COMC0655 (COM_TX_OFF): switch the transmitter off. */
static int com_tx_off(const tc_args_t *args)
{
    (void)args;
    return drv_command(DEV_COM, 0x0502u, NULL);
}

/* Handler for COMC1263 (COM_XPD_MODE_SET): change the transponder mode. Argument: COMP1462. */
static int com_xpd_mode_set(const tc_args_t *args)
{
    if (args == NULL) {
        return COM_ERR_RANGE;
    }
    return drv_command(DEV_COM, 0x0503u, args);
}

/* Handler for COMC5525 (COM_ANT_SELECT): select the active antenna. Argument: COMP9173. */
static int com_ant_select(const tc_args_t *args)
{
    if (args == NULL) {
        return COM_ERR_RANGE;
    }
    return drv_command(DEV_COM, 0x0504u, args);
}

/* Handler for COMC0709 (COM_RX_RESET): reset the receiver. */
static int com_rx_reset(const tc_args_t *args)
{
    (void)args;
    return drv_command(DEV_COM, 0x0505u, NULL);
}

/* Dispatch the telecommands addressed to the communications application. */
int com_tc_dispatch(tc_id_t tc_id, const tc_args_t *args)
{
    com_tc_count++;
    switch (tc_id) {
    case TC_COMC3469:   /* COM_TX_ON */
        return com_tx_on(args);
    case TC_COMC0655:   /* COM_TX_OFF */
        return com_tx_off(args);
    case TC_COMC1263:   /* COM_XPD_MODE_SET */
        return com_xpd_mode_set(args);
    case TC_COMC5525:   /* COM_ANT_SELECT */
        return com_ant_select(args);
    case TC_COMC0709:   /* COM_RX_RESET */
        return com_rx_reset(args);
    default:
        return COM_ERR_UNKNOWN_TC;
    }
}

/* Fill the COM_HK packet, PUS (3,25). */
void com_hk_fill(hk_buf_t *buf)
{
    hk_put_u8(buf, PARAM_COMT5338, drv_state(DEV_COM, 0u));  /* RX_LOCK */
    hk_put_u16(buf, PARAM_COMT7144, adc_read(ADC_COM_01));  /* RX_AGC */
    hk_put_u16(buf, PARAM_COMT9701, adc_read(ADC_COM_02));  /* RX_SNR */
    hk_put_u8(buf, PARAM_COMT4549, drv_state(DEV_COM, 3u));  /* TX_STAT */
    hk_put_u16(buf, PARAM_COMT9236, adc_read(ADC_COM_04));  /* TX_PWR */
    hk_put_u16(buf, PARAM_COMT7650, adc_read(ADC_COM_05));  /* TX_TEMP */
    hk_put_u16(buf, PARAM_COMT6242, adc_read(ADC_COM_06));  /* TX_RATE */
    hk_put_u8(buf, PARAM_COMT1448, drv_state(DEV_COM, 7u));  /* XPD_MODE */
    hk_put_u16(buf, PARAM_COMT7974, adc_read(ADC_COM_08));  /* RX_FREQ_ERR */
    hk_put_u8(buf, PARAM_COMT3984, drv_state(DEV_COM, 9u));  /* ANT_SEL */
    hk_put_u16(buf, PARAM_COMT4629, adc_read(ADC_COM_10));  /* TX_I */
    hk_put_u16(buf, PARAM_COMT9823, adc_read(ADC_COM_11));  /* RX_TEMP */
    hk_put_u16(buf, PARAM_COMT8772, adc_read(ADC_COM_12));  /* FRAME_CNT */
}

/* Initialise the communications application. */
void com_init(void)
{
    com_tc_count = 0u;
}
