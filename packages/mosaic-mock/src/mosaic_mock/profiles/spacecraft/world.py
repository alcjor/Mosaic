"""Build the DEMOSAT-1 world: SRDB items and the mission model the renderers use."""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from mosaic_mock.engine.generate import SizeSpec
from mosaic_mock.engine.rng import Rng
from mosaic_mock.engine.world import Item, World
from mosaic_mock.profiles.spacecraft import vocab
from mosaic_mock.profiles.spacecraft.srdb_columns import key_of
from mosaic_mock.profiles.spacecraft.vocab import MEASURES, A, C, Fop, P, Step, Sub

HK_START_BYTE = 16


@dataclass
class Param:
    item: Item
    sub: SubM
    mn: str
    ld: str
    unit: str
    kind: str
    states: tuple[str, ...]

    @property
    def id(self) -> str:
        return self.item.key


@dataclass
class Arg:
    item: Item
    sub: SubM
    mn: str
    ld: str
    unit: str
    lo: str
    hi: str
    ptc: int
    pfc: int
    typical: str
    phrase: str

    @property
    def id(self) -> str:
        return self.item.key


@dataclass
class Tc:
    item: Item
    sub: SubM
    mn: str
    ld: str
    args: list[Arg]
    service: tuple[int, int]
    critical: bool
    status: Param | None
    expect: str | None
    code: int  # the on-board enum value

    @property
    def id(self) -> str:
        return self.item.key


@dataclass
class Packet:
    item: Item
    name: str
    spid: int
    apid: int
    service: tuple[int, int]
    descr: str
    sub: SubM | None
    fields: list[tuple[Param, int, int]] = field(default_factory=list)  # (param, byte, bit)


@dataclass
class FopM:
    number: str  # FOP-PWR-001
    file: str  # fops/fop_pwr_001.py
    spec: Fop
    sub: SubM


@dataclass
class SubM:
    spec: Sub
    index: int
    params: list[Param] = field(default_factory=list)
    args: list[Arg] = field(default_factory=list)
    tcs: list[Tc] = field(default_factory=list)
    hk: list[Packet] = field(default_factory=list)
    fops: list[FopM] = field(default_factory=list)

    @property
    def code(self) -> str:
        return self.spec.code

    @property
    def apid(self) -> int:
        return 0x101 + self.index


@dataclass
class Mission:
    subs: list[SubM]
    packets: list[Packet]
    by_mn: dict[str, Param | Arg | Tc]
    c_files: int

    @property
    def params(self) -> list[Param]:
        return [p for s in self.subs for p in s.params]

    @property
    def tcs(self) -> list[Tc]:
        return [t for s in self.subs for t in s.tcs]

    @property
    def fops(self) -> list[FopM]:
        return [f for s in self.subs for f in s.fops]


def fmt(x: float) -> str:
    return f"{x:.6g}"


def _split(total: int, n: int) -> list[int]:
    return [total // n + (1 if i < total % n else 0) for i in range(n)]


class _Builder:
    def __init__(self, rng: Rng, size: SizeSpec) -> None:
        self.rng = rng
        self.size = size
        self.world = World()
        self.naming = self.world.naming
        self.by_mn: dict[str, Param | Arg | Tc] = {}

    def add(self, table: str, attrs: dict[str, str]) -> Item:
        return self.world.add(Item(table, key_of(table, attrs), attrs))

    # --- parameters ---------------------------------------------------------------------

    def params(self, sub: SubM, target: int, r: random.Random) -> None:
        specs = list(sub.spec.params)
        specs += self._generated_params(sub.spec, max(0, target - len(specs)))
        txf: dict[tuple[str, ...], str] = {}
        for s in specs:
            pid = (
                f"{sub.code}T{s.num:04d}"
                if s.num is not None
                else self.naming.numbered_id(f"{sub.code}T", r)
            )
            self._param(sub, s, pid, txf, r)

    def _generated_params(self, sub: Sub, n: int) -> list[P]:
        out: list[P] = []
        inst = 1
        while len(out) < n:
            for dev, dname in sub.devices:
                for code, mname, unit, kind, lo, hi, cal in MEASURES:
                    if len(out) >= n:
                        break
                    suffix = "" if inst == 1 else f"_{inst}"
                    mn = self.naming.mnemonic(f"{dev}_{code}{suffix}")
                    ld = f"{dname.capitalize()} {mname}" + ("" if inst == 1 else f", unit {inst}")
                    states = vocab.ONOFF if kind == "status" else ()
                    out.append(P(mn, ld, unit, kind, states, lo, hi, None, cal))
            inst += 1
        return out

    def _param(self, sub: SubM, s: P, pid: str, txf: dict, r: random.Random) -> None:
        num = int(pid[-4:])
        attrs = {
            "PCF_NAME": pid,
            "PCF_DESCR": s.mn,
            "PCF_PID": str(int(f"{0x0C + sub.index:02X}{num:04d}", 16)),
            "PCF_UNIT": s.unit,
            "PCF_PTC": "2" if s.kind == "status" else ("4" if s.lo < 0 else "3"),
            "PCF_PFC": "8" if s.kind == "status" else "12",
            "PCF_CATEG": "S" if s.kind == "status" else "N",
            "PCF_NATUR": "R",
            "PCF_USCON": "N",
            "PCF_SUBSYS": sub.code,
            "PCF_CORR": "Y",
            "PCF_DARC": "0",
            "PCF_ENDIAN": "B",
            "PCF_LDESCR": s.ld,
        }
        item = self.add("PCF", attrs)
        p = Param(item, sub, s.mn, s.ld, s.unit, s.kind, s.states)
        sub.params.append(p)
        self.by_mn[s.mn] = p
        if s.kind == "status":
            states = s.states or vocab.ONOFF
            cal = txf.get(states)
            if cal is None:
                cal = f"T{sub.code}{len(txf) + 1:04d}"
                txf[states] = cal
                t = self.add(
                    "TXF",
                    {
                        "TXF_NUMBR": cal,
                        "TXF_DESCR": "/".join(states),
                        "TXF_RAWFMT": "U",
                        "TXF_NALIAS": str(len(states)),
                    },
                )
                for i, st in enumerate(states):
                    tp = self.add(
                        "TXP",
                        {"TXP_NUMBR": cal, "TXP_FROM": str(i), "TXP_TO": str(i), "TXP_ALTXT": st},
                    )
                    self.world.link("TXP_NUMBR", tp, t)
            attrs["PCF_CURTX"] = cal
            self.world.link("PCF_CURTX", item, self.world.get(f"TXF/{cal}"))
        elif s.kind == "analogue":
            attrs["PCF_CURTX"] = self._calibration(sub, s, num, item)
            attrs["PCF_DECIM"] = "2"
            limits = s.limits
            if limits is None and s.num is None and r.random() < 0.3:
                span = s.hi - s.lo
                limits = (s.lo + 0.1 * span, s.hi - 0.1 * span)
            if limits:
                self._limits(item, s, limits)

    def _calibration(self, sub: SubM, s: P, num: int, pcf: Item, suffix: str = "") -> str:
        lo, hi = s.lo, s.hi
        if s.cal == "poly":
            cid = f"M{sub.code}{num:04d}{suffix}"
            cal = self.add(
                "MCF",
                {
                    "MCF_IDENT": cid,
                    "MCF_DESCR": f"{s.mn} polynomial",
                    "MCF_POL1": fmt(lo),
                    "MCF_POL2": fmt((hi - lo) / 4095),
                },
            )
        elif s.cal == "log":
            cid = f"L{sub.code}{num:04d}{suffix}"
            cal = self.add(
                "LGF",
                {
                    "LGF_IDENT": cid,
                    "LGF_DESCR": f"{s.mn} logarithmic",
                    "LGF_POL1": fmt(lo),
                    "LGF_POL2": fmt((hi - lo) / 12),
                },
            )
        else:
            cid = f"C{sub.code}{num:04d}{suffix}"
            cal = self.add(
                "CAF",
                {
                    "CAF_NUMBR": cid,
                    "CAF_DESCR": f"{s.mn} linear",
                    "CAF_ENGFMT": "R",
                    "CAF_RAWFMT": "U",
                    "CAF_RADIX": "D",
                    "CAF_UNIT": s.unit,
                    "CAF_NCURVE": "2",
                    "CAF_INTER": "F",
                },
            )
            for x, y in ((0, lo), (4095, hi)):
                cap = self.add("CAP", {"CAP_NUMBR": cid, "CAP_XVALS": str(x), "CAP_YVALS": fmt(y)})
                self.world.link("CAP_NUMBR", cap, cal)
        if not suffix:
            self.world.link("PCF_CURTX", pcf, cal)
        return cid

    def _limits(self, pcf: Item, s: P, limits: tuple[float, float]) -> None:
        ocf = self.add(
            "OCF",
            {
                "OCF_NAME": pcf.key,
                "OCF_NBCHCK": "2",
                "OCF_NBOOL": "0",
                "OCF_INTER": "C",
                "OCF_CODIN": "R",
            },
        )
        self.world.link("OCF_NAME", ocf, pcf)
        margin = 0.1 * (s.hi - s.lo)
        for pos, kind, lo, hi in (
            (1, "S", *limits),
            (2, "H", limits[0] - margin, limits[1] + margin),
        ):
            ocp = self.add(
                "OCP",
                {
                    "OCP_NAME": pcf.key,
                    "OCP_POS": str(pos),
                    "OCP_TYPE": kind,
                    "OCP_LVALU": fmt(lo),
                    "OCP_HVALU": fmt(hi),
                },
            )
            self.world.link("OCP_NAME", ocp, ocf)

    # --- telecommands -------------------------------------------------------------------

    def telecommands(self, sub: SubM, target: int, r: random.Random) -> None:
        args = list(sub.spec.args)
        tcs = list(sub.spec.tcs)
        extra_args, extra_tcs = self._generated_tcs(sub, max(0, target - len(tcs)))
        args += extra_args
        tcs += extra_tcs
        for a in args:
            pname = (
                f"{sub.code}P{a.num:04d}"
                if a.num is not None
                else self.naming.numbered_id(f"{sub.code}P", r)
            )
            item = self.add(
                "CPC",
                {
                    "CPC_PNAME": pname,
                    "CPC_DESCR": a.mn,
                    "CPC_PTC": str(a.ptc),
                    "CPC_PFC": str(a.pfc),
                    "CPC_DISPFMT": "R" if a.ptc == 5 else "U",
                    "CPC_RADIX": "D",
                    "CPC_UNIT": a.unit,
                    "CPC_CATEG": "N",
                    "CPC_INTER": "R",
                    "CPC_DEFVAL": a.typical,
                    "CPC_CORR": "Y",
                    "CPC_DESCR2": a.ld,
                    "CPC_ENDIAN": "B",
                },
            )
            arg = Arg(item, sub, a.mn, a.ld, a.unit, a.lo, a.hi, a.ptc, a.pfc, a.typical, a.phrase)
            sub.args.append(arg)
            self.by_mn[a.mn] = arg
        for k, c in enumerate(tcs):
            cname = (
                f"{sub.code}C{c.num:04d}"
                if c.num is not None
                else self.naming.numbered_id(f"{sub.code}C", r)
            )
            targs = [a for a in (self.by_mn[x] for x in c.args) if isinstance(a, Arg)]
            item = self.add(
                "CCF",
                {
                    "CCF_CNAME": cname,
                    "CCF_DESCR": c.mn,
                    "CCF_DESCR2": c.ld,
                    "CCF_CRITICAL": "Y" if c.critical else "N",
                    "CCF_PKTID": "TCHDR",
                    "CCF_TYPE": str(c.service[0]),
                    "CCF_STYPE": str(c.service[1]),
                    "CCF_APID": str(sub.apid),
                    "CCF_NPARS": str(len(targs)),
                    "CCF_PLAN": "N",
                    "CCF_EXEC": "Y",
                    "CCF_ILSCOPE": "N",
                    "CCF_ILSTAGE": "C",
                    "CCF_SUBSYS": str(sub.index + 1),
                    "CCF_HIPRI": "N",
                    "CCF_ACK": "15",
                },
            )
            bit = 0
            for a in targs:
                width = 32 if a.ptc == 5 else (16 if a.pfc >= 12 else 8)
                cdf = self.add(
                    "CDF",
                    {
                        "CDF_CNAME": cname,
                        "CDF_ELTYPE": "E",
                        "CDF_DESCR": a.mn,
                        "CDF_ELLEN": str(width),
                        "CDF_BIT": str(bit),
                        "CDF_GRPSIZE": "0",
                        "CDF_PNAME": a.id,
                        "CDF_INTER": "R",
                    },
                )
                self.world.link("CDF_CNAME", cdf, item)
                self.world.link("CDF_PNAME", cdf, a.item)
                bit += width
            status = self.by_mn.get(c.status) if c.status else None
            assert status is None or isinstance(status, Param)
            tc = Tc(
                item,
                sub,
                c.mn,
                c.ld,
                targs,
                c.service,
                c.critical,
                status,
                c.expect,
                ((sub.index + 1) << 8) | (k + 1),
            )
            sub.tcs.append(tc)
            self.by_mn[c.mn] = tc

    def _generated_tcs(self, sub: SubM, n: int) -> tuple[list[A], list[C]]:
        args: list[A] = []
        tcs: list[C] = []
        inst = 1
        while len(tcs) < n:
            for dev, dname in sub.spec.devices:
                sfx = "" if inst == 1 else str(inst)
                stat = next((p.mn for p in sub.params if p.mn.startswith(f"{dev}_STAT")), None)
                mode = A(
                    self.naming.mnemonic(f"{dev}{sfx}_MODE_SEL"),
                    f"{dname.capitalize()} mode: 1 low, 2 high",
                    typical="1",
                    phrase="low mode",
                )
                lim_lo = A(
                    self.naming.mnemonic(f"{dev}{sfx}_LIM_LO"),
                    f"{dname.capitalize()} lower limit",
                    ptc=5,
                    pfc=1,
                    lo="-1e3",
                    hi="1e3",
                    typical="10.0",
                )
                lim_hi = A(
                    self.naming.mnemonic(f"{dev}{sfx}_LIM_HI"),
                    f"{dname.capitalize()} upper limit",
                    ptc=5,
                    pfc=1,
                    lo="-1e3",
                    hi="1e3",
                    typical="90.0",
                )
                args += [mode, lim_lo, lim_hi]
                unit = f" unit {inst}" if inst > 1 else ""
                for c in (
                    C(
                        self.naming.mnemonic(f"{sub.code}_{dev}{sfx}_ON"),
                        f"Switch the {dname}{unit} on",
                        (mode.mn,),
                        status=stat,
                        expect="ON" if stat else None,
                    ),
                    C(
                        self.naming.mnemonic(f"{sub.code}_{dev}{sfx}_OFF"),
                        f"Switch the {dname}{unit} off",
                        status=stat,
                        expect="OFF" if stat else None,
                    ),
                    C(
                        self.naming.mnemonic(f"{sub.code}_SET_{dev}{sfx}_LIM"),
                        f"Set the {dname}{unit} limits",
                        (lim_lo.mn, lim_hi.mn),
                    ),
                    C(
                        self.naming.mnemonic(f"{sub.code}_{dev}{sfx}_RESET"),
                        f"Reset the {dname}{unit}",
                    ),
                ):
                    if len(tcs) < n:
                        tcs.append(c)
            inst += 1
        used = {a for c in tcs for a in c.args}
        return [a for a in args if a.mn in used], tcs

    # --- packets ------------------------------------------------------------------------

    def packets(self, mission_subs: list[SubM], n_packets: int) -> list[Packet]:
        n_events = 2
        per_sub = _split(max(len(mission_subs), n_packets - n_events), len(mission_subs))
        out: list[Packet] = []
        spid = 1001
        for sub, n_hk in zip(mission_subs, per_sub, strict=True):
            sizes = _split(len(sub.params), min(n_hk, len(sub.params)))
            start = 0
            for k, size in enumerate(sizes):
                name = f"{sub.code}_HK" if len(sizes) == 1 else f"{sub.code}_HK{k + 1}"
                self.naming.register(name, guard=False)
                pk = self._packet(
                    name=name,
                    spid=spid,
                    apid=sub.apid,
                    svc=(3, 25),
                    pi1=len(out) + 1,
                    descr=f"{sub.spec.name} housekeeping, every {sub.spec.period} s",
                    sub=sub,
                )
                self._layout(pk, sub.params[start : start + size])
                sub.hk.append(pk)
                out.append(pk)
                start += size
                spid += 1
        obc = next((s for s in mission_subs if s.code == "OBC"), mission_subs[0])
        evt_params = [p for p in obc.params if p.mn in ("EVT_LAST_ID", "EVT_CNT")] or obc.params[:2]
        for k, (name, st, descr) in enumerate(
            (
                ("EVT_INFO", 1, "Informative event report"),
                ("EVT_ALARM", 4, "High-severity event report"),
            )
        ):
            self.naming.register(name, guard=False)
            pk = self._packet(
                name=name, spid=2001 + k, apid=obc.apid, svc=(5, st), pi1=st, descr=descr, sub=None
            )
            self._layout(pk, evt_params)
            out.append(pk)
        return out

    def _packet(
        self,
        *,
        name: str,
        spid: int,
        apid: int,
        svc: tuple[int, int],
        pi1: int,
        descr: str,
        sub: SubM | None,
    ) -> Packet:
        item = self.add(
            "PID",
            {
                "PID_TYPE": str(svc[0]),
                "PID_STYPE": str(svc[1]),
                "PID_APID": str(apid),
                "PID_PI1_VAL": str(pi1),
                "PID_SPID": str(spid),
                "PID_DESCR": descr,
                "PID_TPSD": "-1",
                "PID_DFHSIZE": "10",
                "PID_TIME": "N",
                "PID_VALID": "Y",
                "PID_CHECK": "0",
                "PID_EVENT": "N",
            },
        )
        return Packet(item, name, spid, apid, svc, descr, sub)

    def _layout(self, pk: Packet, params: list[Param]) -> None:
        byte = HK_START_BYTE
        for p in params:
            plf = self.add(
                "PLF",
                {
                    "PLF_NAME": p.id,
                    "PLF_SPID": str(pk.spid),
                    "PLF_OFFBY": str(byte),
                    "PLF_OFFBI": "0",
                },
            )
            self.world.link("PLF_NAME", plf, p.item)
            self.world.link("PLF_SPID", plf, pk.item)
            pk.fields.append((p, byte, 0))
            byte += 1 if p.kind == "status" else 2
        tpcf = self.add(
            "TPCF", {"TPCF_SPID": str(pk.spid), "TPCF_NAME": pk.name, "TPCF_SIZE": str(byte)}
        )
        self.world.link("TPCF_SPID", tpcf, pk.item)

    # --- procedures ---------------------------------------------------------------------

    def fops(self, subs: list[SubM], target: int) -> None:
        per_sub = _split(max(target, len(subs)), len(subs))
        for sub, n in zip(subs, per_sub, strict=True):
            specs = list(sub.spec.fops)
            k = 0
            switchable = [t for t in sub.tcs if t.status is not None and t.expect]
            analogue = [p for p in sub.params if p.kind == "analogue"]
            while len(specs) < n and switchable and analogue:
                tc = switchable[k % len(switchable)]
                pre = analogue[k % len(analogue)]
                specs.append(_generated_fop(tc, pre))
                k += 1
            for i, spec in enumerate(specs[:n], 1):
                number = f"FOP-{sub.code}-{i:03d}"
                sub.fops.append(FopM(number, f"fops/fop_{sub.code.lower()}_{i:03d}.py", spec, sub))


def _generated_fop(tc: Tc, pre: Param) -> Fop:
    assert tc.status is not None
    send = ("send", tc.mn, {a.mn: a.typical for a in tc.args}, tc.args[0].phrase if tc.args else "")
    return Fop(
        tc.ld,
        f"{tc.ld[0].lower()}{tc.ld[1:]} during routine operations.",
        (pre.mn, "above", f"{fmt(0.0)} {pre.unit}".strip()),
        (
            Step(f"Check {pre.ld[0].lower()}{pre.ld[1:]}", (("verify", pre.mn, ">", "0.0"),)),
            Step(tc.ld, (send, ("wait", 5), ("verify", tc.status.mn, "==", f'"{tc.expect}"'))),
        ),
    )


def _reserve_curated(b: _Builder, specs: tuple[Sub, ...]) -> None:
    """Register every curated mnemonic and fixed ID before any random ID is drawn."""
    for sub in specs:
        for mn in [p.mn for p in sub.params] + [a.mn for a in sub.args] + [c.mn for c in sub.tcs]:
            b.naming.register(mn, guard=False)
        for letter, nums in (
            ("T", [p.num for p in sub.params]),
            ("P", [a.num for a in sub.args]),
            ("C", [c.num for c in sub.tcs]),
        ):
            for n in nums:
                if n is not None:
                    b.naming.register(f"{sub.code}{letter}{n:04d}")


def build_world(rng: Rng, size: SizeSpec) -> World:
    b = _Builder(rng, size)
    specs = vocab.SUBSYSTEMS[: size["subsystems"]]
    subs = [SubM(s, i) for i, s in enumerate(specs)]
    _reserve_curated(b, specs)
    r = rng.stream("ids")
    for sub, n in zip(subs, _split(size["parameters"], len(subs)), strict=True):
        b.params(sub, n, r)
    for sub, n in zip(subs, _split(size["telecommands"], len(subs)), strict=True):
        b.telecommands(sub, n, r)
    packets = b.packets(subs, size["packets"])
    # Calibration selection: the solar array current changes calibration in boost mode.
    sa, bcr = b.by_mn.get("SA_I_TOTAL"), b.by_mn.get("BCR_MODE")
    if isinstance(sa, Param) and isinstance(bcr, Param):
        spec = next(p for p in sa.sub.spec.params if p.mn == "SA_I_TOTAL")
        alt = b._calibration(sa.sub, spec, int(sa.id[-4:]), sa.item, suffix="B")
        for pos, val, sel in ((1, "1", sa.item.attrs["PCF_CURTX"]), (2, "2", alt)):
            cur = b.add(
                "CUR",
                {
                    "CUR_PNAME": sa.id,
                    "CUR_POS": str(pos),
                    "CUR_RLCHK": bcr.id,
                    "CUR_VALPAR": val,
                    "CUR_SELECT": sel,
                },
            )
            b.world.link("CUR_PNAME", cur, sa.item)
            b.world.link("CUR_RLCHK", cur, bcr.item)
    for svc in sorted({pk.service for pk in packets}):
        b.add(
            "PIC",
            {
                "PIC_TYPE": str(svc[0]),
                "PIC_STYPE": str(svc[1]),
                "PIC_PI1_OFF": "10",
                "PIC_PI1_WID": "8" if svc[0] == 3 else "16",
                "PIC_PI2_OFF": "-1",
                "PIC_PI2_WID": "0",
            },
        )
    b.add(
        "VDF",
        {
            "VDF_NAME": "DMSAT1",
            "VDF_COMMENT": "DEMOSAT-1 mock database",
            "VDF_DOMAINID": "1",
            "VDF_RELEASE": "1",
            "VDF_ISSUE": "2",
        },
    )
    b.fops(subs, size["fops"])
    b.world.meta["mission"] = Mission(subs, packets, b.by_mn, size["c_files"])
    return b.world
