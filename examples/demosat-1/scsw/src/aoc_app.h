/* aoc_app.h - attitude and orbit control application (AOC) interface */
#ifndef AOC_APP_H
#define AOC_APP_H

#include "demosat_tc_ids.h"
#include "scsw_types.h"

#define AOC_OK (0)
#define AOC_ERR_RANGE (-1)
#define AOC_ERR_UNKNOWN_TC (-2)

void aoc_init(void);
int aoc_tc_dispatch(tc_id_t tc_id, const tc_args_t *args);
void aoc_hk_fill(hk_buf_t *buf);

#endif /* AOC_APP_H */
