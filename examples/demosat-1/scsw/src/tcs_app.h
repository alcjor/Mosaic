/* tcs_app.h - thermal control application (TCS) interface */
#ifndef TCS_APP_H
#define TCS_APP_H

#include "demosat_tc_ids.h"
#include "scsw_types.h"

#define TCS_OK (0)
#define TCS_ERR_RANGE (-1)
#define TCS_ERR_UNKNOWN_TC (-2)

void tcs_init(void);
int tcs_tc_dispatch(tc_id_t tc_id, const tc_args_t *args);
void tcs_hk_fill(hk_buf_t *buf);

#endif /* TCS_APP_H */
