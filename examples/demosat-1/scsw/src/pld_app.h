/* pld_app.h - payload application (PLD) interface */
#ifndef PLD_APP_H
#define PLD_APP_H

#include "demosat_tc_ids.h"
#include "scsw_types.h"

#define PLD_OK (0)
#define PLD_ERR_RANGE (-1)
#define PLD_ERR_UNKNOWN_TC (-2)

void pld_init(void);
int pld_tc_dispatch(tc_id_t tc_id, const tc_args_t *args);
void pld_hk_fill(hk_buf_t *buf);

#endif /* PLD_APP_H */
