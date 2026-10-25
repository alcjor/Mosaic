/* com_app.h - communications application (COM) interface */
#ifndef COM_APP_H
#define COM_APP_H

#include "demosat_tc_ids.h"
#include "scsw_types.h"

#define COM_OK (0)
#define COM_ERR_RANGE (-1)
#define COM_ERR_UNKNOWN_TC (-2)

void com_init(void);
int com_tc_dispatch(tc_id_t tc_id, const tc_args_t *args);
void com_hk_fill(hk_buf_t *buf);

#endif /* COM_APP_H */
