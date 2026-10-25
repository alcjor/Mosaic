"""FOP-COM-001 Downlink start

Purpose: start the high-rate downlink at the beginning of a pass.
Preconditions: RX_LOCK (COMT5338) is LOCKED.
"""
from demoproc import step, send_tc, verify_tm, wait


@step(1, "Check the uplink")
def step_1():
    verify_tm("COMT5338", "==", "LOCKED")  # RX_LOCK


@step(2, "Switch the transmitter on")
def step_2():
    send_tc("COMC3469", COMP9910=2)       # COM_TX_ON, high rate
    wait(5)
    verify_tm("COMT4549", "==", "ON")     # TX_STAT
    verify_tm("COMT9236", ">", 1.0)       # TX_PWR
