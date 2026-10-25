"""FOP-PWR-001 Battery heater activation

Purpose: switch on battery heater A when the battery is cold.
Preconditions: BAT_V_MAIN (PWRT0012) above 26 V.
"""
from demoproc import step, send_tc, verify_tm, wait


@step(1, "Check battery voltage")
def step_1():
    verify_tm("PWRT0012", ">", 26.0)      # BAT_V_MAIN


@step(2, "Switch heater A on")
def step_2():
    send_tc("PWRC0101", PWRP0001=1)       # PWR_HTR_A_ON, thermostat mode
    wait(5)
    verify_tm("PWRT0031", "==", "ON")     # HTR_A_STAT
