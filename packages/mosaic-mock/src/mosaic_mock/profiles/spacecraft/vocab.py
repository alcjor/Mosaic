"""Vocabulary of the invented DEMOSAT-1 mission (MOCK-04: everything is invented).

The six small-mission subsystems are curated so the demo reads well; the PWR entries carry
fixed numbers so the small mission reproduces the examples in the specs (FOP-PWR-001,
PWRC0101, PWRT0012). Larger sizes top these up with generated items and add subsystems.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class P:
    """A telemetry parameter."""

    mn: str
    ld: str
    unit: str = ""
    kind: str = "analogue"  # analogue | status | counter
    states: tuple[str, ...] = ()
    lo: float = 0.0
    hi: float = 100.0
    limits: tuple[float, float] | None = None  # soft limits; hard limits are wider
    cal: str = "lin"  # lin | poly | log
    num: int | None = None


@dataclass(frozen=True)
class A:
    """A telecommand argument."""

    mn: str
    ld: str
    ptc: int = 3
    pfc: int = 4
    unit: str = ""
    lo: str = "1"
    hi: str = "2"
    typical: str = "1"
    phrase: str = ""  # how a FOP comment describes the typical value
    num: int | None = None


@dataclass(frozen=True)
class C:
    """A telecommand. ``status``/``expect`` name the parameter that confirms it."""

    mn: str
    ld: str
    args: tuple[str, ...] = ()
    service: tuple[int, int] = (8, 1)
    critical: bool = False
    status: str | None = None
    expect: str | None = None
    num: int | None = None


@dataclass(frozen=True)
class Step:
    title: str
    actions: tuple[tuple, ...]  # ("verify", mn, op, value) | ("send", tc, {arg: value}, phrase)
    # | ("get", mn, var) | ("wait", seconds)


@dataclass(frozen=True)
class Fop:
    title: str
    purpose: str
    pre: tuple[str, str, str]  # (parameter mnemonic, condition words, value with unit)
    steps: tuple[Step, ...]


@dataclass(frozen=True)
class Sub:
    code: str
    name: str  # "Power"
    adj: str  # "power", as in "the power application"
    purpose: str
    period: int  # housekeeping period in seconds
    devices: tuple[tuple[str, str], ...]  # for generated items: (code, name)
    params: tuple[P, ...] = ()
    args: tuple[A, ...] = ()
    tcs: tuple[C, ...] = ()
    fops: tuple[Fop, ...] = ()
    notes: tuple[str, ...] = field(default=())  # operations notes, with ⟦mn⟧ placeholders


ONOFF = ("OFF", "ON")
LOCK = ("UNLOCKED", "LOCKED")

PWR = Sub(
    "PWR",
    "Power",
    "power",
    "conditions the main bus, charges the battery and controls the two battery heaters",
    8,
    (("BAT", "battery"), ("SA", "solar array"), ("BUS", "main bus"), ("LCL", "current limiter")),
    params=(
        P("BAT_V_MAIN", "Main battery voltage", "V", lo=0, hi=40.95, limits=(26.0, 33.0), num=12),
        P("BAT_I_MAIN", "Main battery current", "A", lo=-10, hi=10, limits=(-8.0, 8.0)),
        P(
            "BAT_TEMP_1",
            "Battery temperature, sensor 1",
            "degC",
            lo=-40,
            hi=85,
            limits=(-5.0, 40.0),
            cal="poly",
            num=20,
        ),
        P("BAT_TEMP_2", "Battery temperature, sensor 2", "degC", lo=-40, hi=85, cal="poly"),
        P("HTR_A_STAT", "Battery heater A status", kind="status", states=ONOFF, num=31),
        P("HTR_B_STAT", "Battery heater B status", kind="status", states=ONOFF),
        P(
            "HTR_A_MODE",
            "Battery heater A control mode",
            kind="status",
            states=("OFF", "THERMOSTAT", "FORCED"),
        ),
        P("SA_I_TOTAL", "Solar array total current", "A", lo=0, hi=12, limits=(0.5, 11.0), num=45),
        P("SA_V_OUT", "Solar array output voltage", "V", lo=0, hi=60),
        P("BUS_V_MAIN", "Main bus voltage", "V", lo=0, hi=40, limits=(27.0, 29.0)),
        P(
            "BCR_MODE",
            "Battery charge regulator mode",
            kind="status",
            states=("TRICKLE", "NORMAL", "BOOST"),
        ),
        P("BAT_EOC_V", "Battery end-of-charge voltage limit", "V", lo=28, hi=34),
        P("LCL_TRIP_CNT", "Latching current limiter trip count", kind="counter"),
    ),
    args=(
        A(
            "HTR_MODE",
            "Heater control mode: 1 thermostat, 2 forced on",
            typical="1",
            phrase="thermostat mode",
            num=1,
        ),
        A(
            "EOC_V",
            "End-of-charge voltage, 30.0 to 33.6 V",
            ptc=5,
            pfc=1,
            unit="V",
            lo="30.0",
            hi="33.6",
            typical="32.8",
            num=10,
        ),
        A(
            "LCL_ID",
            "Current limiter number, 1 to 16",
            lo="1",
            hi="16",
            typical="3",
            phrase="limiter 3",
        ),
    ),
    tcs=(
        C(
            "PWR_HTR_A_ON",
            "Switch battery heater A on",
            ("HTR_MODE",),
            status="HTR_A_STAT",
            expect="ON",
            num=101,
        ),
        C(
            "PWR_HTR_A_OFF",
            "Switch battery heater A off",
            status="HTR_A_STAT",
            expect="OFF",
            num=112,
        ),
        C(
            "PWR_SET_BAT_EOC",
            "Set the battery end-of-charge voltage",
            ("EOC_V",),
            critical=True,
            status="BAT_EOC_V",
            num=123,
        ),
        C(
            "PWR_HTR_B_ON",
            "Switch battery heater B on",
            ("HTR_MODE",),
            status="HTR_B_STAT",
            expect="ON",
        ),
        C(
            "PWR_LCL_RESET",
            "Reset a tripped latching current limiter",
            ("LCL_ID",),
            status="LCL_TRIP_CNT",
        ),
    ),
    fops=(
        Fop(
            "Battery heater activation",
            "switch on battery heater A when the battery is cold.",
            ("BAT_V_MAIN", "above", "26 V"),
            (
                Step("Check battery voltage", (("verify", "BAT_V_MAIN", ">", "26.0"),)),
                Step(
                    "Switch heater A on",
                    (
                        ("send", "PWR_HTR_A_ON", {"HTR_MODE": "1"}, "thermostat mode"),
                        ("wait", 5),
                        ("verify", "HTR_A_STAT", "==", '"ON"'),
                    ),
                ),
            ),
        ),
    ),
    notes=(
        "Before switching a heater on, check that ⟦BAT_V_MAIN:mn⟧ is above 26 V. In forced mode "
        "(⟦HTR_MODE:id⟧ = 2) the heater stays on until ⟦PWR_HTR_A_OFF:id⟧ is sent.",
        "Lowering the end-of-charge voltage with ⟦PWR_SET_BAT_EOC:mn⟧ slows battery ageing. The "
        "new limit shows in ⟦BAT_EOC_V:id⟧ at the end of the next charge cycle.",
    ),
)

TCS = Sub(
    "TCS",
    "Thermal control",
    "thermal control",
    "keeps every unit within its temperature limits with heater lines and thermistors",
    16,
    (("HL", "heater line"), ("RAD", "radiator"), ("TH", "thermistor")),
    params=(
        P("HL1_STAT", "Heater line 1 status", kind="status", states=ONOFF),
        P("HL2_STAT", "Heater line 2 status", kind="status", states=ONOFF),
        P("HL3_STAT", "Heater line 3 status", kind="status", states=ONOFF),
        P(
            "HL1_MODE",
            "Heater line 1 control mode",
            kind="status",
            states=("OFF", "THERMOSTAT", "FORCED"),
        ),
        P("HL1_SETP", "Heater line 1 set point", "degC", lo=-20, hi=40),
        P(
            "RAD_TEMP_1",
            "Radiator temperature, panel 1",
            "degC",
            lo=-80,
            hi=60,
            limits=(-60.0, 40.0),
            cal="poly",
        ),
        P("RAD_TEMP_2", "Radiator temperature, panel 2", "degC", lo=-80, hi=60, cal="poly"),
        P(
            "TANK_TEMP",
            "Propellant tank temperature",
            "degC",
            lo=-20,
            hi=60,
            limits=(5.0, 45.0),
            cal="poly",
        ),
        P("OBC_BRD_TEMP", "On-board computer board temperature", "degC", lo=-40, hi=85, cal="poly"),
        P("PLD_IF_TEMP", "Payload interface temperature", "degC", lo=-40, hi=85, cal="poly"),
        P("TCS_MODE", "Thermal control mode", kind="status", states=("SAFE", "NOMINAL")),
        P("HL_I_TOTAL", "Heater lines total current", "A", lo=0, hi=6, limits=(0.0, 5.0)),
        P("TH_FAIL_CNT", "Thermistor failure count", kind="counter"),
    ),
    args=(
        A(
            "HL_MODE",
            "Heater line mode: 1 thermostat, 2 forced on",
            typical="1",
            phrase="thermostat mode",
        ),
        A(
            "SETP_DEGC",
            "Set point, -20 to 40 degC",
            ptc=5,
            pfc=1,
            unit="degC",
            lo="-20.0",
            hi="40.0",
            typical="12.0",
        ),
        A(
            "TCS_MODE_REQ",
            "Requested thermal mode: 1 safe, 2 nominal",
            typical="2",
            phrase="nominal",
        ),
    ),
    tcs=(
        C("TCS_HL1_ON", "Switch heater line 1 on", ("HL_MODE",), status="HL1_STAT", expect="ON"),
        C("TCS_HL1_OFF", "Switch heater line 1 off", status="HL1_STAT", expect="OFF"),
        C("TCS_SET_HL1_SETP", "Set the heater line 1 set point", ("SETP_DEGC",), status="HL1_SETP"),
        C(
            "TCS_MODE_SET",
            "Change the thermal control mode",
            ("TCS_MODE_REQ",),
            status="TCS_MODE",
            expect="NOMINAL",
        ),
        C("TCS_HL2_ON", "Switch heater line 2 on", ("HL_MODE",), status="HL2_STAT", expect="ON"),
    ),
    fops=(
        Fop(
            "Heater line 1 activation",
            "switch on heater line 1 to warm the propellant tank.",
            ("TCS_MODE", "is", "NOMINAL"),
            (
                Step("Check thermal mode", (("verify", "TCS_MODE", "==", '"NOMINAL"'),)),
                Step(
                    "Set the set point",
                    (("send", "TCS_SET_HL1_SETP", {"SETP_DEGC": "12.0"}, "12 degC"), ("wait", 2)),
                ),
                Step(
                    "Switch heater line 1 on",
                    (
                        ("send", "TCS_HL1_ON", {"HL_MODE": "1"}, "thermostat mode"),
                        ("wait", 5),
                        ("verify", "HL1_STAT", "==", '"ON"'),
                        ("get", "TANK_TEMP", "tank_temp"),
                    ),
                ),
            ),
        ),
    ),
    notes=(
        "Heater line 1 warms the propellant tank. Keep ⟦TANK_TEMP:mn⟧ between 5 and 45 degC; "
        "below 5 degC, check ⟦HL1_STAT:id⟧ before commanding ⟦TCS_HL1_ON:mn⟧.",
        "After a thermistor failure, ⟦TH_FAIL_CNT:mn⟧ increases and the affected line falls back "
        "to forced mode.",
    ),
)

AOC = Sub(
    "AOC",
    "Attitude and orbit control",
    "attitude and orbit control",
    "points the spacecraft with gyros, sun sensors, a star tracker and three reaction wheels",
    4,
    (("GYR", "gyro"), ("RW", "reaction wheel"), ("STR", "star tracker"), ("MTQ", "magnetorquer")),
    params=(
        P(
            "AOC_MODE",
            "Attitude control mode",
            kind="status",
            states=("SAFE", "SUN", "NADIR", "FINE"),
        ),
        P("GYR_RATE_X", "Gyro rate, X axis", "deg/s", lo=-5, hi=5, limits=(-2.0, 2.0)),
        P("GYR_RATE_Y", "Gyro rate, Y axis", "deg/s", lo=-5, hi=5),
        P("GYR_RATE_Z", "Gyro rate, Z axis", "deg/s", lo=-5, hi=5),
        P("SUN_ANGLE", "Sun sensor angle", "deg", lo=0, hi=180),
        P(
            "RW1_SPEED",
            "Reaction wheel 1 speed",
            "rpm",
            lo=-6000,
            hi=6000,
            limits=(-5000.0, 5000.0),
        ),
        P("RW2_SPEED", "Reaction wheel 2 speed", "rpm", lo=-6000, hi=6000),
        P("RW3_SPEED", "Reaction wheel 3 speed", "rpm", lo=-6000, hi=6000),
        P("MTQ_X_DIPOLE", "Magnetorquer X dipole", "Am2", lo=-30, hi=30),
        P("STR_STAT", "Star tracker status", kind="status", states=ONOFF),
        P("STR_LOCK", "Star tracker lock", kind="status", states=LOCK),
        P("ATT_ERR", "Attitude error", "deg", lo=0, hi=20, limits=(0.0, 1.0), cal="log"),
        P("RW1_TEMP", "Reaction wheel 1 temperature", "degC", lo=-40, hi=85, cal="poly"),
    ),
    args=(
        A(
            "AOC_MODE_REQ",
            "Requested attitude mode: 1 safe, 2 sun, 3 nadir, 4 fine",
            lo="1",
            hi="4",
            typical="3",
            phrase="nadir",
        ),
        A("RW_ID", "Reaction wheel number, 1 to 3", lo="1", hi="3", typical="1", phrase="wheel 1"),
        A(
            "RW_SPEED_REQ",
            "Requested wheel speed, -5000 to 5000 rpm",
            ptc=4,
            pfc=12,
            unit="rpm",
            lo="-5000",
            hi="5000",
            typical="1500",
        ),
    ),
    tcs=(
        C(
            "AOC_MODE_SET",
            "Change the attitude control mode",
            ("AOC_MODE_REQ",),
            status="AOC_MODE",
            expect="NADIR",
        ),
        C("AOC_STR_ON", "Switch the star tracker on", status="STR_STAT", expect="ON"),
        C("AOC_STR_OFF", "Switch the star tracker off", status="STR_STAT", expect="OFF"),
        C(
            "AOC_RW_SPEED_SET",
            "Set a reaction wheel speed",
            ("RW_ID", "RW_SPEED_REQ"),
            status="RW1_SPEED",
        ),
        C("AOC_GYR_RESET", "Reset the gyro bias estimate", status="GYR_RATE_X"),
    ),
    fops=(
        Fop(
            "Transition to nadir pointing",
            "bring the spacecraft from sun pointing to nadir pointing.",
            ("AOC_MODE", "is", "SUN"),
            (
                Step("Check attitude mode", (("verify", "AOC_MODE", "==", '"SUN"'),)),
                Step(
                    "Switch the star tracker on",
                    (
                        ("send", "AOC_STR_ON", {}, ""),
                        ("wait", 30),
                        ("verify", "STR_LOCK", "==", '"LOCKED"'),
                    ),
                ),
                Step(
                    "Command nadir mode",
                    (
                        ("send", "AOC_MODE_SET", {"AOC_MODE_REQ": "3"}, "nadir"),
                        ("wait", 60),
                        ("verify", "AOC_MODE", "==", '"NADIR"'),
                        ("verify", "ATT_ERR", "<", "1.0"),
                    ),
                ),
            ),
        ),
    ),
    notes=(
        "Do not command ⟦AOC_MODE_SET:mn⟧ to fine pointing before ⟦STR_LOCK:mn⟧ reports LOCKED.",
        "Wheel speeds above 5000 rpm in ⟦RW1_SPEED:id⟧ trigger a momentum unload with the "
        "magnetorquers.",
    ),
)

OBC = Sub(
    "OBC",
    "On-board computer",
    "on-board computer",
    "runs the software, keeps on-board time and handles housekeeping and events",
    8,
    (("CPU", "processor"), ("MEM", "memory"), ("WDG", "watchdog"), ("OBT", "on-board time")),
    params=(
        P("CPU_LOAD", "Processor load", "%", lo=0, hi=100, limits=(0.0, 80.0)),
        P("MEM_FREE", "Free memory", "kB", lo=0, hi=65535),
        P("WDG_STAT", "Watchdog status", kind="status", states=("DISABLED", "ENABLED")),
        P("RESET_CNT", "Reset count", kind="counter"),
        P("EDAC_ERR_CNT", "Memory error count", kind="counter"),
        P("OBT_DRIFT", "On-board time drift", "ms", lo=-1000, hi=1000),
        P("SW_MODE", "Software mode", kind="status", states=("BOOT", "SAFE", "NOMINAL")),
        P("TC_ACC_CNT", "Accepted telecommand count", kind="counter"),
        P("TC_REJ_CNT", "Rejected telecommand count", kind="counter"),
        P("EVT_LAST_ID", "Last event identifier", kind="counter"),
        P("EVT_CNT", "Event count", kind="counter"),
        P("RAIL_V_5V", "5 V rail voltage", "V", lo=0, hi=6, limits=(4.75, 5.25)),
        P("HK_ENA_CNT", "Enabled housekeeping report count", kind="counter"),
    ),
    args=(
        A(
            "SID",
            "Housekeeping structure identifier, 1 to 32",
            lo="1",
            hi="32",
            typical="1",
            phrase="structure 1",
        ),
        A(
            "PAR_ID",
            "On-board parameter identifier",
            ptc=3,
            pfc=14,
            lo="0",
            hi="16777215",
            typical="3090",
        ),
        A("PAR_VAL", "Parameter value", ptc=5, pfc=1, lo="-1e9", hi="1e9", typical="1.0"),
    ),
    tcs=(
        C(
            "OBC_HK_ENABLE",
            "Enable a housekeeping report",
            ("SID",),
            service=(3, 5),
            status="HK_ENA_CNT",
        ),
        C(
            "OBC_HK_DISABLE",
            "Disable a housekeeping report",
            ("SID",),
            service=(3, 6),
            status="HK_ENA_CNT",
        ),
        C("OBC_CONN_TEST", "Perform a connection test", service=(17, 1), status="TC_ACC_CNT"),
        C("OBC_PAR_REPORT", "Report on-board parameter values", ("PAR_ID",), service=(20, 1)),
        C(
            "OBC_PAR_SET",
            "Set an on-board parameter value",
            ("PAR_ID", "PAR_VAL"),
            service=(20, 3),
            critical=True,
        ),
    ),
    fops=(
        Fop(
            "Housekeeping report recovery",
            "re-enable a housekeeping report after a software reset.",
            ("SW_MODE", "is", "NOMINAL"),
            (
                Step(
                    "Check the software",
                    (("verify", "SW_MODE", "==", '"NOMINAL"'), ("get", "RESET_CNT", "resets")),
                ),
                Step("Test the link", (("send", "OBC_CONN_TEST", {}, ""), ("wait", 2))),
                Step(
                    "Enable the report",
                    (
                        ("send", "OBC_HK_ENABLE", {"SID": "1"}, "structure 1"),
                        ("wait", 10),
                        ("verify", "HK_ENA_CNT", ">", "0"),
                    ),
                ),
            ),
        ),
    ),
    notes=(
        "After a reset, ⟦RESET_CNT:mn⟧ increases and every housekeeping report except the "
        "⟦OBC:hk⟧ packet is disabled until ⟦OBC_HK_ENABLE:id⟧ is sent.",
        "Watch ⟦TC_REJ_CNT:id⟧ during a pass; a rising count means telecommands fail acceptance.",
    ),
)

COM = Sub(
    "COM",
    "Communications",
    "communications",
    "runs the S-band receiver and transmitter and selects the antenna",
    8,
    (("RX", "receiver"), ("TX", "transmitter"), ("XPD", "transponder"), ("ANT", "antenna")),
    params=(
        P("RX_LOCK", "Receiver lock", kind="status", states=LOCK),
        P("RX_AGC", "Receiver signal level", "dBm", lo=-140, hi=-40, cal="log"),
        P("RX_SNR", "Receiver signal-to-noise ratio", "dB", lo=0, hi=40),
        P("TX_STAT", "Transmitter status", kind="status", states=ONOFF),
        P("TX_PWR", "Transmitter output power", "W", lo=0, hi=10, limits=(1.0, 8.0)),
        P(
            "TX_TEMP",
            "Transmitter temperature",
            "degC",
            lo=-40,
            hi=85,
            limits=(-10.0, 55.0),
            cal="poly",
        ),
        P("TX_RATE", "Downlink rate", "kbps", lo=0, hi=2048),
        P("XPD_MODE", "Transponder mode", kind="status", states=("STANDBY", "RANGING", "DATA")),
        P("RX_FREQ_ERR", "Receiver frequency offset", "Hz", lo=-50000, hi=50000),
        P("ANT_SEL", "Antenna selection", kind="status", states=("FORE", "AFT")),
        P("TX_I", "Transmitter current", "A", lo=0, hi=3),
        P("RX_TEMP", "Receiver temperature", "degC", lo=-40, hi=85, cal="poly"),
        P("FRAME_CNT", "Transmitted frame count", kind="counter"),
    ),
    args=(
        A("TX_RATE_SEL", "Downlink rate: 1 low, 2 high", typical="2", phrase="high rate"),
        A(
            "XPD_MODE_REQ",
            "Requested transponder mode: 1 standby, 2 ranging, 3 data",
            lo="1",
            hi="3",
            typical="3",
            phrase="data",
        ),
        A("ANT_ID", "Antenna: 1 fore, 2 aft", typical="1", phrase="fore antenna"),
    ),
    tcs=(
        C(
            "COM_TX_ON",
            "Switch the transmitter on",
            ("TX_RATE_SEL",),
            status="TX_STAT",
            expect="ON",
        ),
        C("COM_TX_OFF", "Switch the transmitter off", status="TX_STAT", expect="OFF"),
        C(
            "COM_XPD_MODE_SET",
            "Change the transponder mode",
            ("XPD_MODE_REQ",),
            status="XPD_MODE",
            expect="DATA",
        ),
        C(
            "COM_ANT_SELECT",
            "Select the active antenna",
            ("ANT_ID",),
            status="ANT_SEL",
            expect="FORE",
        ),
        C("COM_RX_RESET", "Reset the receiver", status="RX_LOCK"),
    ),
    fops=(
        Fop(
            "Downlink start",
            "start the high-rate downlink at the beginning of a pass.",
            ("RX_LOCK", "is", "LOCKED"),
            (
                Step("Check the uplink", (("verify", "RX_LOCK", "==", '"LOCKED"'),)),
                Step(
                    "Switch the transmitter on",
                    (
                        ("send", "COM_TX_ON", {"TX_RATE_SEL": "2"}, "high rate"),
                        ("wait", 5),
                        ("verify", "TX_STAT", "==", '"ON"'),
                        ("verify", "TX_PWR", ">", "1.0"),
                    ),
                ),
            ),
        ),
    ),
    notes=(
        "Switch the transmitter off with ⟦COM_TX_OFF:mn⟧ at the end of every pass; "
        "⟦TX_TEMP:mn⟧ rises by about 10 degC per hour of transmission.",
    ),
)

PLD = Sub(
    "PLD",
    "Payload",
    "payload",
    "operates the camera, its cooler and the image store",
    16,
    (("CAM", "camera"), ("FPA", "focal plane"), ("COOLER", "cooler"), ("STORE", "image store")),
    params=(
        P("CAM_STAT", "Camera status", kind="status", states=ONOFF),
        P("CAM_MODE", "Camera mode", kind="status", states=("STANDBY", "IMAGING", "CALIBRATION")),
        P(
            "FPA_TEMP",
            "Focal plane temperature",
            "degC",
            lo=-60,
            hi=40,
            limits=(-35.0, -15.0),
            cal="poly",
        ),
        P("CAM_I", "Camera current", "A", lo=0, hi=4),
        P("CAM_V", "Camera supply voltage", "V", lo=0, hi=32),
        P("IMG_CNT", "Image count", kind="counter"),
        P("EXP_TIME", "Exposure time", "ms", lo=0, hi=1000),
        P("COOLER_STAT", "Cooler status", kind="status", states=ONOFF),
        P("COOLER_PWR", "Cooler power", "W", lo=0, hi=20),
        P("STORE_FILL", "Image store fill level", "%", lo=0, hi=100, limits=(0.0, 90.0)),
        P("OPT_TEMP", "Optics temperature", "degC", lo=-40, hi=60, cal="poly"),
        P("SHUTTER_STAT", "Shutter status", kind="status", states=("CLOSED", "OPEN")),
        P("CMP_RATIO", "Compression ratio", lo=1, hi=20),
    ),
    args=(
        A(
            "CAM_MODE_REQ",
            "Requested camera mode: 1 standby, 2 imaging, 3 calibration",
            lo="1",
            hi="3",
            typical="2",
            phrase="imaging",
        ),
        A(
            "EXP_MS",
            "Exposure time, 1 to 1000 ms",
            ptc=3,
            pfc=12,
            unit="ms",
            lo="1",
            hi="1000",
            typical="20",
            phrase="20 ms",
        ),
        A("IMG_N", "Number of images, 1 to 100", lo="1", hi="100", typical="10"),
    ),
    tcs=(
        C("PLD_CAM_ON", "Switch the camera on", ("CAM_MODE_REQ",), status="CAM_STAT", expect="ON"),
        C("PLD_CAM_OFF", "Switch the camera off", status="CAM_STAT", expect="OFF"),
        C("PLD_IMG_TAKE", "Take a series of images", ("EXP_MS", "IMG_N"), status="IMG_CNT"),
        C("PLD_COOLER_ON", "Switch the focal plane cooler on", status="COOLER_STAT", expect="ON"),
        C("PLD_STORE_CLEAR", "Clear the image store", critical=True, status="STORE_FILL"),
    ),
    fops=(
        Fop(
            "Imaging session",
            "cool the focal plane and take a series of images.",
            ("STORE_FILL", "below", "90 %"),
            (
                Step(
                    "Cool the focal plane",
                    (
                        ("send", "PLD_COOLER_ON", {}, ""),
                        ("wait", 600),
                        ("verify", "FPA_TEMP", "<", "-15.0"),
                    ),
                ),
                Step(
                    "Switch the camera on",
                    (
                        ("send", "PLD_CAM_ON", {"CAM_MODE_REQ": "2"}, "imaging"),
                        ("wait", 5),
                        ("verify", "CAM_STAT", "==", '"ON"'),
                    ),
                ),
                Step(
                    "Take the images",
                    (
                        ("send", "PLD_IMG_TAKE", {"EXP_MS": "20", "IMG_N": "10"}, "20 ms"),
                        ("wait", 30),
                        ("get", "IMG_CNT", "images"),
                    ),
                ),
            ),
        ),
    ),
    notes=(
        "Images are only usable once ⟦FPA_TEMP:mn⟧ is below -15 degC; allow ten minutes after "
        "⟦PLD_COOLER_ON:id⟧.",
        "Clear the image store with ⟦PLD_STORE_CLEAR:mn⟧ only after the ground confirms the "
        "downlink of every image.",
    ),
)

# Extra subsystems for the medium and large sizes: generated items only.
EXTRA = (
    Sub(
        "PRP",
        "Propulsion",
        "propulsion",
        "controls the thrusters and the propellant tank",
        16,
        (("THR", "thruster"), ("TANK", "tank"), ("VLV", "valve"), ("CAT", "catalyst bed")),
    ),
    Sub(
        "MMU",
        "Mass memory",
        "mass memory",
        "stores science and housekeeping data",
        16,
        (("PART", "partition"), ("SCRUB", "scrubber"), ("BANK", "memory bank")),
    ),
    Sub(
        "GNS",
        "GNSS receiver",
        "GNSS receiver",
        "provides position, velocity and time",
        8,
        (("GNS", "receiver"), ("ANTG", "GNSS antenna"), ("CLK", "clock")),
    ),
    Sub(
        "SAD",
        "Solar array drive",
        "solar array drive",
        "rotates the solar arrays towards the sun",
        16,
        (("SADM", "drive mechanism"), ("POT", "potentiometer"), ("MOT", "motor")),
    ),
    Sub(
        "RWA",
        "Reaction wheels",
        "reaction wheel",
        "drives the reaction wheel assembly",
        4,
        (("WHL", "wheel"), ("DRV", "wheel drive"), ("TACH", "tachometer")),
    ),
    Sub(
        "MTQ",
        "Magnetorquers",
        "magnetorquer",
        "drives the three magnetorquer rods",
        8,
        (("ROD", "rod"), ("MAG", "magnetometer"), ("MDRV", "rod driver")),
    ),
    Sub(
        "STR",
        "Star tracker",
        "star tracker",
        "computes attitude from star images",
        4,
        (("OPTH", "optical head"), ("PROC", "processing unit"), ("BAFF", "baffle")),
    ),
    Sub(
        "CAM",
        "Camera",
        "camera",
        "runs the secondary camera",
        16,
        (("DET", "detector"), ("LENS", "lens"), ("FW", "filter wheel")),
    ),
)

SUBSYSTEMS = (PWR, TCS, AOC, OBC, COM, PLD, *EXTRA)

# Measures for generated parameters: (code, name, unit, kind, lo, hi, cal)
MEASURES = (
    ("V", "voltage", "V", "analogue", 0.0, 40.0, "lin"),
    ("I", "current", "A", "analogue", 0.0, 5.0, "lin"),
    ("TEMP", "temperature", "degC", "analogue", -40.0, 85.0, "poly"),
    ("STAT", "status", "", "status", 0.0, 1.0, "lin"),
    ("PWR", "power", "W", "analogue", 0.0, 50.0, "lin"),
    ("CNT", "event count", "", "counter", 0.0, 0.0, "lin"),
    ("ERR", "error count", "", "counter", 0.0, 0.0, "lin"),
)
