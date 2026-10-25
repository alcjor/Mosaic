/* pld_app.c - payload application (PLD): telecommands and housekeeping */
#include "demosat_ids.h"
#include "pld_app.h"

static uint32_t pld_tc_count;

/* Handler for PLDC1133 (PLD_CAM_ON): switch the camera on. Argument: PLDP3324. */
static int pld_cam_on(const tc_args_t *args)
{
    if (args == NULL) {
        return PLD_ERR_RANGE;
    }
    return drv_command(DEV_PLD, 0x0601u, args);
}

/* Handler for PLDC4748 (PLD_CAM_OFF): switch the camera off. */
static int pld_cam_off(const tc_args_t *args)
{
    (void)args;
    return drv_command(DEV_PLD, 0x0602u, NULL);
}

/* Handler for PLDC9313 (PLD_IMG_TAKE): take a series of images. Arguments: PLDP3136, PLDP7412. */
static int pld_img_take(const tc_args_t *args)
{
    if (args == NULL) {
        return PLD_ERR_RANGE;
    }
    return drv_command(DEV_PLD, 0x0603u, args);
}

/* Handler for PLDC8017 (PLD_COOLER_ON): switch the focal plane cooler on. */
static int pld_cooler_on(const tc_args_t *args)
{
    (void)args;
    return drv_command(DEV_PLD, 0x0604u, NULL);
}

/* Handler for PLDC2062 (PLD_STORE_CLEAR): clear the image store. */
static int pld_store_clear(const tc_args_t *args)
{
    (void)args;
    return drv_command(DEV_PLD, 0x0605u, NULL);
}

/* Dispatch the telecommands addressed to the payload application. */
int pld_tc_dispatch(tc_id_t tc_id, const tc_args_t *args)
{
    pld_tc_count++;
    switch (tc_id) {
    case TC_PLDC1133:   /* PLD_CAM_ON */
        return pld_cam_on(args);
    case TC_PLDC4748:   /* PLD_CAM_OFF */
        return pld_cam_off(args);
    case TC_PLDC9313:   /* PLD_IMG_TAKE */
        return pld_img_take(args);
    case TC_PLDC8017:   /* PLD_COOLER_ON */
        return pld_cooler_on(args);
    case TC_PLDC2062:   /* PLD_STORE_CLEAR */
        return pld_store_clear(args);
    default:
        return PLD_ERR_UNKNOWN_TC;
    }
}

/* Fill the PLD_HK packet, PUS (3,25). */
void pld_hk_fill(hk_buf_t *buf)
{
    hk_put_u8(buf, PARAM_PLDT8785, drv_state(DEV_PLD, 0u));  /* CAM_STAT */
    hk_put_u8(buf, PARAM_PLDT3063, drv_state(DEV_PLD, 1u));  /* CAM_MODE */
    hk_put_u16(buf, PARAM_PLDT0056, adc_read(ADC_PLD_02));  /* FPA_TEMP */
    hk_put_u16(buf, PARAM_PLDT2237, adc_read(ADC_PLD_03));  /* CAM_I */
    hk_put_u16(buf, PARAM_PLDT7193, adc_read(ADC_PLD_04));  /* CAM_V */
    hk_put_u16(buf, PARAM_PLDT8768, adc_read(ADC_PLD_05));  /* IMG_CNT */
    hk_put_u16(buf, PARAM_PLDT8949, adc_read(ADC_PLD_06));  /* EXP_TIME */
    hk_put_u8(buf, PARAM_PLDT7797, drv_state(DEV_PLD, 7u));  /* COOLER_STAT */
    hk_put_u16(buf, PARAM_PLDT1679, adc_read(ADC_PLD_08));  /* COOLER_PWR */
    hk_put_u16(buf, PARAM_PLDT6795, adc_read(ADC_PLD_09));  /* STORE_FILL */
    hk_put_u16(buf, PARAM_PLDT7871, adc_read(ADC_PLD_10));  /* OPT_TEMP */
    hk_put_u8(buf, PARAM_PLDT7699, drv_state(DEV_PLD, 11u));  /* SHUTTER_STAT */
    hk_put_u16(buf, PARAM_PLDT9158, adc_read(ADC_PLD_12));  /* CMP_RATIO */
}

/* Initialise the payload application. */
void pld_init(void)
{
    pld_tc_count = 0u;
}
