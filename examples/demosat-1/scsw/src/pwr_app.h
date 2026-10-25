/* pwr_app.h - power application (PWR) interface */
#ifndef PWR_APP_H
#define PWR_APP_H

#include "demosat_tc_ids.h"
#include "scsw_types.h"

#define PWR_OK (0)
#define PWR_ERR_RANGE (-1)
#define PWR_ERR_UNKNOWN_TC (-2)

void pwr_init(void);
int pwr_tc_dispatch(tc_id_t tc_id, const tc_args_t *args);
void pwr_hk_fill(hk_buf_t *buf);

#endif /* PWR_APP_H */
