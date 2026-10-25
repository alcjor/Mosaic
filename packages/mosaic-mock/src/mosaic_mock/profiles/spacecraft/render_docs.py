"""Renderers for documents: the SW ICD (HTML) and the SW user manual (.docx and PDF)."""

from __future__ import annotations

from collections.abc import Sequence

from mosaic_mock.engine.generate import RenderContext
from mosaic_mock.engine.model import Artifact, Document, Para, Section, Table
from mosaic_mock.engine.text import Piece, Styled, Text, tok
from mosaic_mock.profiles.spacecraft.refs import Refs, item_of
from mosaic_mock.profiles.spacecraft.render_code import mission
from mosaic_mock.profiles.spacecraft.world import Mission, Param, SubM, Tc

MISSION = "DEMOSAT-1"
FIRST_APP_CHAPTER = 4

PUS_SERVICES = (
    ("1", "1 to 8", "Request verification", "Acceptance and execution reports"),
    ("3", "5, 6", "Housekeeping", "Enable and disable a report"),
    ("3", "25", "Housekeeping", "Housekeeping parameter report"),
    ("5", "1, 4", "Event reporting", "Informative and high-severity events"),
    ("8", "1", "Function management", "Perform a function of an application"),
    ("17", "1", "Test", "Connection test"),
    ("20", "1, 3", "Parameter management", "Report and set on-board parameters"),
)

ACRONYMS = (
    ("APID", "Application process identifier"),
    ("FOP", "Flight operations procedure"),
    ("HK", "Housekeeping"),
    ("ICD", "Interface control document"),
    ("PUS", "Packet utilisation standard"),
    ("SCSW", "Spacecraft software"),
    ("SPID", "Packet identifier in the reference database"),
    ("SRDB", "Satellite reference database"),
    ("SUM", "Software user manual"),
    ("TC", "Telecommand"),
    ("TM", "Telemetry"),
)


def _offset(byte: int, bit: int) -> str:
    return f"{byte}.{bit}" if bit else str(byte)


def _join(parts: list[Text], sep: str = ", ", last: str = " and ") -> Text:
    out: Text = []
    for i, p in enumerate(parts):
        if i:
            out.append(last if i == len(parts) - 1 else sep)
        out += p
    return out


def _token_list(items: Sequence[str], last: str = " and ") -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + last + items[-1]


def _has_limits(ctx: RenderContext, p: Param) -> bool:
    return ctx.world.has(f"OCF/{p.id}")


class IcdRenderer:
    name = "icd_html"

    def render(self, ctx: RenderContext) -> Sequence[Artifact]:
        m = mission(ctx)
        refs = Refs(m)
        tg = ctx.textgen
        doc = Document("icd/scsw_icd", ("html",), f"{MISSION} SCSW interface control document")
        doc.front.append(Para([f"Document {MISSION}-SCSW-ICD, issue 2.0."]))
        tm = Section("1", ["TM packets"], 1, [Para([tg.render("icd_tm_intro.j2")])])
        for k, pk in enumerate(m.packets, 1):
            title: Text = [
                refs.mn(pk, "describes"),
                f", SPID {pk.spid}, APID 0x{pk.apid:03X}, PUS ({pk.service[0]},{pk.service[1]})",
            ]
            rows = [
                [
                    [_offset(b, bit)],
                    [refs.id(p, "describes")],
                    [refs.mn(p, "describes")],
                    [f"{p.item.attrs['PCF_PTC']}/{p.item.attrs['PCF_PFC']}"],
                    [refs.ld(p)],
                ]
                for p, b, bit in pk.fields
            ]
            tm.children.append(
                Section(
                    f"1.{k}",
                    title,
                    2,
                    [
                        Para([f"{pk.descr}."]),
                        Table(["Offset", "Parameter", "Mnemonic", "PTC/PFC", "Description"], rows),
                    ],
                )
            )
        tc_sec = Section("2", ["Telecommands"], 1, [Para([tg.render("icd_tc_intro.j2")])])
        for k, tc in enumerate(m.tcs, 1):
            blocks: list = [
                Para(
                    [
                        f"PUS ({tc.service[0]},{tc.service[1]}), APID 0x{tc.sub.apid:03X}. ",
                        refs.ld(tc),
                        ".",
                    ]
                )
            ]
            if tc.critical:
                blocks.append(
                    Para([Styled("Critical command:", "b"), " it needs an arm and fire sequence."])
                )
            if tc.args:
                rows = [
                    [
                        [str(i)],
                        [refs.id(a, "describes")],
                        [f"{a.ptc}/{a.pfc}"],
                        [f"{a.lo} to {a.hi}" + (f" {a.unit}" if a.unit else "")],
                        [refs.ld(a)],
                    ]
                    for i, a in enumerate(tc.args, 1)
                ]
                blocks.append(Table(["Position", "Argument", "Type", "Range", "Description"], rows))
            else:
                blocks.append(Para(["No arguments."]))
            tc_sec.children.append(
                Section(
                    f"2.{k}", [refs.id(tc, "describes"), " ", refs.mn(tc, "describes")], 2, blocks
                )
            )
        doc.sections = [tm, tc_sec]
        return [doc]


class ManualRenderer:
    name = "manual"

    def render(self, ctx: RenderContext) -> Sequence[Artifact]:
        m = mission(ctx)
        refs = Refs(m)
        doc = Document("sum/sum", ("docx", "pdf"), f"{MISSION} SW user manual")
        doc.front.append(Para([f"Document {MISSION}-SCSW-SUM, issue 1.2, {ctx.date.isoformat()}."]))
        doc.sections = [
            self._intro(ctx, m),
            self._overview(ctx, m, refs),
            self._services(m, refs),
            *[
                self._application(ctx, m, refs, s, FIRST_APP_CHAPTER + i)
                for i, s in enumerate(m.subs)
            ],
            Section(
                "A",
                ["Acronyms"],
                1,
                [Table(["Acronym", "Meaning"], [[[a], [b]] for a, b in ACRONYMS])],
            ),
        ]
        return [doc]

    @staticmethod
    def _prose(ctx: RenderContext, refs: Refs, template: str, **kw: object) -> list[Para]:
        paras = ctx.textgen.prose(template, **refs.helpers(), **kw)
        return [Para(refs.parse(p)) for p in paras]

    def _intro(self, ctx: RenderContext, m: Mission) -> Section:
        tg = ctx.textgen
        purpose = [Para([p]) for p in tg.prose("sum_purpose.j2", mission=MISSION)]
        scope = [Para([p]) for p in tg.prose("sum_scope.j2", version="3.1", n_apps=len(m.subs))]
        docs = [
            f"{MISSION}-SCSW-ICD issue 2.0, SCSW interface control document",
            f"{MISSION}-FOP issue 1.0, flight operations procedures",
            f"{MISSION}-SRDB version 1.2, satellite reference database",
        ]
        return Section(
            "1",
            ["Introduction"],
            1,
            [],
            [
                Section("1.1", ["Purpose"], 2, list(purpose)),
                Section("1.2", ["Scope"], 2, list(scope)),
                Section("1.3", ["Reference documents"], 2, [Para([d], "bullet") for d in docs]),
            ],
        )

    def _overview(self, ctx: RenderContext, m: Mission, refs: Refs) -> Section:
        apps = ", ".join(f"{s.spec.adj} ({s.code})" for s in m.subs)
        arch = [
            Para([p])
            for p in ctx.textgen.prose("sum_architecture.j2", n_apps=len(m.subs), app_list=apps)
        ]
        tcs = m.tcs
        critical = next((t for t in tcs if t.critical), None)
        handling = self._prose(ctx, refs, "sum_tc_handling.j2", example=tcs[0], critical=critical)
        hk = _token_list([tok(item_of(pk), "mn") for s in m.subs for pk in s.hk])
        housekeeping = self._prose(ctx, refs, "sum_housekeeping.j2", hk_list=hk)
        return Section(
            "2",
            ["SCSW overview"],
            1,
            [],
            [
                Section("2.1", ["Architecture"], 2, arch),
                Section("2.2", ["Telecommand handling"], 2, handling),
                Section("2.3", ["Housekeeping"], 2, housekeeping),
            ],
        )

    @staticmethod
    def _services(m: Mission, refs: Refs) -> Section:
        rows = [[[a], [b], [c], [d]] for a, b, c, d in PUS_SERVICES]
        events = [pk for pk in m.packets if pk.sub is None]
        ev_rows = [[[refs.mn(pk, "mentions")], [str(pk.service[1])], [pk.descr]] for pk in events]
        return Section(
            "3",
            ["PUS services"],
            1,
            [],
            [
                Section(
                    "3.1",
                    ["Services used"],
                    2,
                    [
                        Table(
                            ["Service", "Subtypes", "Name", "Used for"],
                            rows,
                            caption="Table 3-1 PUS services used",
                        ),
                    ],
                ),
                Section(
                    "3.2",
                    ["Event reporting"],
                    2,
                    [
                        Para(
                            [
                                "Events are reported in two packets, both sent by the on-board "
                                "computer application."
                            ]
                        ),
                        Table(
                            ["Packet", "Subtype", "Description"],
                            ev_rows,
                            caption="Table 3-2 Event packets",
                        ),
                    ],
                ),
            ],
        )

    def _application(
        self, ctx: RenderContext, m: Mission, refs: Refs, sub: SubM, n: int
    ) -> Section:
        analogue = [p for p in sub.params if p.kind == "analogue"]
        limited = next((p for p in analogue if _has_limits(ctx, p)), None)
        switchable = [t for t in sub.tcs if t.status is not None]
        t1 = switchable[0] if switchable else (sub.tcs[0] if sub.tcs else None)
        t2 = next((t for t in sub.tcs if t is not t1), None)
        event = next(pk for pk in m.packets if pk.name == "EVT_ALARM")
        hk = _token_list([tok(item_of(pk), "mn") for pk in sub.hk])
        overview = self._prose(
            ctx,
            refs,
            "sum_app_overview.j2",
            sub=sub,
            hk_list=hk,
            many_hk=len(sub.hk) > 1,
            a1=analogue[0] if analogue else None,
            a2=analogue[1] if len(analogue) > 1 else None,
            limited=limited,
            event=event,
            t1=t1,
            t2=t2,
            s1=t1.status if t1 else None,
        )
        tc_rows = [self._tc_row(refs, tc) for tc in sub.tcs]
        hk_intro: Text = ["The "]
        hk_intro += _join([[refs.mn(pk, "mentions")] for pk in sub.hk])
        hk_intro.append(
            " packets, PUS (3,25), carry the parameters below."
            if len(sub.hk) > 1
            else " packet, PUS (3,25), carries the parameters below."
        )
        hk_rows = [
            [[refs.id(p, "describes")], [refs.mn(p, "describes")], [p.unit], [refs.ld(p)]]
            for p in sub.params
        ]
        notes = self._notes(ctx, refs, sub, t1)
        procs = [Para([f"{f.number} {f.spec.title}"], "bullet") for f in sub.fops]
        if procs:
            notes += [Para([Styled("Related procedures:", "b")]), *procs]
        return Section(
            str(n),
            [f"{sub.spec.name} application ({sub.code})"],
            1,
            [],
            [
                Section(f"{n}.1", ["Overview"], 2, overview),
                Section(
                    f"{n}.2",
                    ["Telecommands"],
                    2,
                    [
                        Table(
                            ["TC", "Mnemonic", "Description", "Arguments"],
                            tc_rows,
                            caption=f"Table {n}-1 {sub.code} telecommands",
                        ),
                    ],
                ),
                Section(
                    f"{n}.3",
                    ["Housekeeping"],
                    2,
                    [
                        Para(hk_intro),
                        Table(
                            ["Parameter", "Mnemonic", "Unit", "Description"],
                            hk_rows,
                            caption=f"Table {n}-2 {sub.code} housekeeping parameters",
                        ),
                    ],
                ),
                Section(f"{n}.4", ["Operations notes"], 2, notes),
            ],
        )

    @staticmethod
    def _tc_row(refs: Refs, tc: Tc) -> list[Text]:
        args: Text = []
        for i, a in enumerate(tc.args):
            args += [", " if i else "", refs.id(a, "mentions"), " (", refs.mn(a, "mentions"), ")"]
        return [
            [refs.id(tc, "describes")],
            [refs.mn(tc, "describes")],
            [refs.ld(tc)],
            args or ["None"],
        ]

    def _notes(self, ctx: RenderContext, refs: Refs, sub: SubM, t1: Tc | None) -> list[Para]:
        if sub.spec.notes:
            out = []
            for note in sub.spec.notes:
                text = ctx.textgen.rewrite(refs.vocab_tokens(note))
                lead: list[Piece] = [Styled("Note:", "b"), " "]
                out.append(Para([*lead, *refs.parse(text)]))
            return out
        return self._prose(ctx, refs, "sum_app_notes.j2", t1=t1, s1=t1.status if t1 else None)
