/* obc_app.h - on-board computer application (OBC) interface */
#ifndef OBC_APP_H
#define OBC_APP_H

#include "demosat_tc_ids.h"
#include "scsw_types.h"

#define OBC_OK (0)
#define OBC_ERR_RANGE (-1)
#define OBC_ERR_UNKNOWN_TC (-2)

void obc_init(void);
int obc_tc_dispatch(tc_id_t tc_id, const tc_args_t *args);
void obc_hk_fill(hk_buf_t *buf);

#endif /* OBC_APP_H */
