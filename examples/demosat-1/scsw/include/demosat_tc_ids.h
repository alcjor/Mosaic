/* demosat_tc_ids.h - telecommand identifiers, generated from the SRDB */
#ifndef DEMOSAT_TC_IDS_H
#define DEMOSAT_TC_IDS_H

typedef enum {
    TC_PWRC0101 = 0x0101u,  /* PWR_HTR_A_ON */
    TC_PWRC0112 = 0x0102u,  /* PWR_HTR_A_OFF */
    TC_PWRC0123 = 0x0103u,  /* PWR_SET_BAT_EOC */
    TC_PWRC2476 = 0x0104u,  /* PWR_HTR_B_ON */
    TC_PWRC5141 = 0x0105u,  /* PWR_LCL_RESET */
    TC_TCSC9695 = 0x0201u,  /* TCS_HL1_ON */
    TC_TCSC1330 = 0x0202u,  /* TCS_HL1_OFF */
    TC_TCSC1076 = 0x0203u,  /* TCS_SET_HL1_SETP */
    TC_TCSC1484 = 0x0204u,  /* TCS_MODE_SET */
    TC_TCSC0408 = 0x0205u,  /* TCS_HL2_ON */
    TC_AOCC1067 = 0x0301u,  /* AOC_MODE_SET */
    TC_AOCC6804 = 0x0302u,  /* AOC_STR_ON */
    TC_AOCC9208 = 0x0303u,  /* AOC_STR_OFF */
    TC_AOCC7889 = 0x0304u,  /* AOC_RW_SPEED_SET */
    TC_AOCC6352 = 0x0305u,  /* AOC_GYR_RESET */
    TC_OBCC2858 = 0x0401u,  /* OBC_HK_ENABLE */
    TC_OBCC8719 = 0x0402u,  /* OBC_HK_DISABLE */
    TC_OBCC9182 = 0x0403u,  /* OBC_CONN_TEST */
    TC_OBCC2725 = 0x0404u,  /* OBC_PAR_REPORT */
    TC_OBCC1080 = 0x0405u,  /* OBC_PAR_SET */
    TC_COMC3469 = 0x0501u,  /* COM_TX_ON */
    TC_COMC0655 = 0x0502u,  /* COM_TX_OFF */
    TC_COMC1263 = 0x0503u,  /* COM_XPD_MODE_SET */
    TC_COMC5525 = 0x0504u,  /* COM_ANT_SELECT */
    TC_COMC0709 = 0x0505u,  /* COM_RX_RESET */
    TC_PLDC1133 = 0x0601u,  /* PLD_CAM_ON */
    TC_PLDC4748 = 0x0602u,  /* PLD_CAM_OFF */
    TC_PLDC9313 = 0x0603u,  /* PLD_IMG_TAKE */
    TC_PLDC8017 = 0x0604u,  /* PLD_COOLER_ON */
    TC_PLDC2062 = 0x0605u   /* PLD_STORE_CLEAR */
} tc_id_t;

#endif /* DEMOSAT_TC_IDS_H */
