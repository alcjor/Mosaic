"""FOP-OBC-001 Housekeeping report recovery

Purpose: re-enable a housekeeping report after a software reset.
Preconditions: SW_MODE (OBCT6792) is NOMINAL.
"""
from demoproc import step, send_tc, verify_tm, get_tm, wait


@step(1, "Check the software")
def step_1():
    verify_tm("OBCT6792", "==", "NOMINAL")  # SW_MODE
    resets = get_tm("OBCT0518")           # RESET_CNT


@step(2, "Test the link")
def step_2():
    send_tc("OBCC9182")                   # OBC_CONN_TEST
    wait(2)


@step(3, "Enable the report")
def step_3():
    send_tc("OBCC2858", OBCP4382=1)       # OBC_HK_ENABLE, structure 1
    wait(10)
    verify_tm("OBCT9444", ">", 0)         # HK_ENA_CNT
