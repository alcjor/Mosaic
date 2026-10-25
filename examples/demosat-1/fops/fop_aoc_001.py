"""FOP-AOC-001 Transition to nadir pointing

Purpose: bring the spacecraft from sun pointing to nadir pointing.
Preconditions: AOC_MODE (AOCT2478) is SUN.
"""
from demoproc import step, send_tc, verify_tm, wait


@step(1, "Check attitude mode")
def step_1():
    verify_tm("AOCT2478", "==", "SUN")    # AOC_MODE


@step(2, "Switch the star tracker on")
def step_2():
    send_tc("AOCC6804")                   # AOC_STR_ON
    wait(30)
    verify_tm("AOCT3539", "==", "LOCKED")  # STR_LOCK


@step(3, "Command nadir mode")
def step_3():
    send_tc("AOCC1067", AOCP9017=3)       # AOC_MODE_SET, nadir
    wait(60)
    verify_tm("AOCT2478", "==", "NADIR")  # AOC_MODE
    verify_tm("AOCT0932", "<", 1.0)       # ATT_ERR
