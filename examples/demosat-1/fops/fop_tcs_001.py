"""FOP-TCS-001 Heater line 1 activation

Purpose: switch on heater line 1 to warm the propellant tank.
Preconditions: TCS_MODE (TCST3307) is NOMINAL.
"""
from demoproc import step, send_tc, verify_tm, get_tm, wait


@step(1, "Check thermal mode")
def step_1():
    verify_tm("TCST3307", "==", "NOMINAL")  # TCS_MODE


@step(2, "Set the set point")
def step_2():
    send_tc("TCSC1076", TCSP9614=12.0)    # TCS_SET_HL1_SETP, 12 degC
    wait(2)


@step(3, "Switch heater line 1 on")
def step_3():
    send_tc("TCSC9695", TCSP6912=1)       # TCS_HL1_ON, thermostat mode
    wait(5)
    verify_tm("TCST6132", "==", "ON")     # HL1_STAT
    tank_temp = get_tm("TCST1795")        # TANK_TEMP
