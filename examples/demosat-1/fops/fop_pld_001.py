"""FOP-PLD-001 Imaging session

Purpose: cool the focal plane and take a series of images.
Preconditions: STORE_FILL (PLDT6795) below 90 %.
"""
from demoproc import step, send_tc, verify_tm, get_tm, wait


@step(1, "Cool the focal plane")
def step_1():
    send_tc("PLDC8017")                   # PLD_COOLER_ON
    wait(600)
    verify_tm("PLDT0056", "<", -15.0)     # FPA_TEMP


@step(2, "Switch the camera on")
def step_2():
    send_tc("PLDC1133", PLDP3324=2)       # PLD_CAM_ON, imaging
    wait(5)
    verify_tm("PLDT8785", "==", "ON")     # CAM_STAT


@step(3, "Take the images")
def step_3():
    send_tc("PLDC9313", PLDP3136=20, PLDP7412=10)  # PLD_IMG_TAKE, 20 ms
    wait(30)
    images = get_tm("PLDT8768")           # IMG_CNT
