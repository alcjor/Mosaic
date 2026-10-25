"""Renderers for line-oriented artifacts: SRDB tables, FOPs (Python) and SCSW code (C)."""

from __future__ import annotations

from collections.abc import Sequence

from mosaic_mock.engine.generate import RenderContext
from mosaic_mock.engine.model import Artifact, LinesFile, Scope, TableFile
from mosaic_mock.engine.text import Piece, plain
from mosaic_mock.engine.world import Item
from mosaic_mock.profiles.spacecraft.refs import Refs
from mosaic_mock.profiles.spacecraft.srdb_columns import TABLE_ORDER, row_of
from mosaic_mock.profiles.spacecraft.world import FopM, Mission, Param, SubM, Tc

COMMENT_COL = 42
CODE_ROOT = "scsw/"


def mission(ctx: RenderContext) -> Mission:
    return ctx.world.meta["mission"]


class SrdbRenderer:
    name = "scos_tables"

    def render(self, ctx: RenderContext) -> Sequence[Artifact]:
        out = []
        for table in TABLE_ORDER:
            rows = [row_of(table, i.attrs) for i in ctx.world.of_type(table)]
            if rows:
                out.append(TableFile(f"srdb/{table.lower()}.dat", table, rows))
        return out


# --- FOPs ---------------------------------------------------------------------------------


def _with_comment(code: Sequence[Piece], comment: Sequence[Piece]) -> list[Piece]:
    pad = max(2, COMMENT_COL - len(plain(code)))
    return [*code, " " * pad, "# ", *comment]


def render_fop(f: FopM, refs: Refs) -> LinesFile:
    m = refs.m
    spec = f.spec
    lf = LinesFile(f.file)
    lf.add(f'"""{f.number} {spec.title}')
    lf.add("")
    lf.add(f"Purpose: {spec.purpose}")
    pre = m.by_mn[spec.pre[0]]
    assert isinstance(pre, Param)
    lf.add(
        "Preconditions: ",
        refs.mn(pre, "mentions"),
        " (",
        refs.id(pre, "mentions"),
        f") {spec.pre[1]} {spec.pre[2]}.",
    )
    lf.add('"""')
    kinds = {a[0] for s in spec.steps for a in s.actions}
    names = ["step"] + [
        fn
        for kind, fn in (
            ("send", "send_tc"),
            ("verify", "verify_tm"),
            ("get", "get_tm"),
            ("wait", "wait"),
        )
        if kind in kinds
    ]
    lf.add(f"from demoproc import {', '.join(names)}")
    for n, step in enumerate(spec.steps, 1):
        lf.add("")
        lf.add("")
        first = lf.add(f'@step({n}, "{step.title}")')
        lf.add(f"def step_{n}():")
        for action in step.actions:
            kind = action[0]
            if kind == "wait":
                lf.add(f"    wait({action[1]})")
            elif kind == "verify":
                p = m.by_mn[action[1]]
                assert isinstance(p, Param)
                code = ['    verify_tm("', refs.id(p, "reads"), f'", "{action[2]}", {action[3]})']
                lf.add(*_with_comment(code, [refs.mn(p, "mentions")]))
            elif kind == "get":
                p = m.by_mn[action[1]]
                assert isinstance(p, Param)
                code = [f'    {action[2]} = get_tm("', refs.id(p, "reads"), '")']
                lf.add(*_with_comment(code, [refs.mn(p, "mentions")]))
            elif kind == "send":
                tc = m.by_mn[action[1]]
                assert isinstance(tc, Tc)
                code: list[Piece] = ['    send_tc("', refs.id(tc, "sends"), '"']
                for arg_mn, value in action[2].items():
                    arg = m.by_mn[arg_mn]
                    code += [", ", refs.id(arg, "sets"), f"={value}"]
                code.append(")")
                comment: list[Piece] = [refs.mn(tc, "mentions")]
                if action[3]:
                    comment.append(f", {action[3]}")
                lf.add(*_with_comment(code, comment))
        lf.scopes.append(Scope(f"step={n}", first, len(lf.lines) - 1))
    return lf


class FopRenderer:
    name = "fops"

    def render(self, ctx: RenderContext) -> Sequence[Artifact]:
        refs = Refs(mission(ctx))
        return [render_fop(f, refs) for f in mission(ctx).fops]


# --- C code -------------------------------------------------------------------------------


class _CFile:
    """A C file under construction that records its function definitions."""

    def __init__(self, path: str) -> None:
        self.lf = LinesFile(CODE_ROOT + path)
        self.rel = path
        self.functions: list[tuple[str, int, list[Tc]]] = []  # (name, first line idx, handled TCs)

    def add(self, *pieces: Piece) -> int:
        return self.lf.add(*pieces)

    def function(
        self, signature: str, body: Sequence[Sequence[Piece]], handles: list[Tc] | None = None
    ) -> None:
        name = signature.split("(", maxsplit=1)[0].rsplit(maxsplit=1)[-1].lstrip("*")
        first = self.add(signature)
        self.add("{")
        for line in body:
            self.add(*line)
        last = self.add("}")
        self.lf.scopes.append(Scope(f"function={name}", first, last))
        self.functions.append((name, first, handles or []))


def _pid_hex(p: Param) -> str:
    return f"0x{int(p.item.attrs['PCF_PID']):06X}"


class CodeRenderer:
    name = "c_code"

    def render(self, ctx: RenderContext) -> Sequence[Artifact]:
        m = mission(ctx)
        refs = Refs(m)
        files = [self._ids_h(m, refs), self._tc_ids_h(m, refs)]
        n_drivers = max(0, m.c_files - 2 - 2 * len(m.subs))
        per_sub = [
            n_drivers // len(m.subs) + (1 if i < n_drivers % len(m.subs) else 0)
            for i in range(len(m.subs))
        ]
        for sub, nd in zip(m.subs, per_sub, strict=True):
            files.append(self._app_h(sub))
            files.append(self._app_c(sub, refs))
            files += self._drivers(sub, nd, refs)
        for f in files:
            for name, first, handles in f.functions:
                fn = ctx.world.add(
                    Item(
                        "Function",
                        f"{f.rel}::{name}",
                        {"name": name, "file": f.rel, "line": str(first + 1)},
                    )
                )
                for tc in handles:
                    ctx.world.link("handles", fn, tc.item)
        return [f.lf for f in files]

    @staticmethod
    def _ids_h(m: Mission, refs: Refs) -> _CFile:
        f = _CFile("include/demosat_ids.h")
        f.add("/* demosat_ids.h - on-board parameter identifiers, generated from the SRDB */")
        f.add("#ifndef DEMOSAT_IDS_H")
        f.add("#define DEMOSAT_IDS_H")
        for sub in m.subs:
            f.add("")
            f.add(f"/* {sub.spec.name} application ({sub.code}) */")
            for p in sub.params:
                f.add(
                    "#define PARAM_",
                    refs.id(p, "defines_id"),
                    f" ({_pid_hex(p)}u) /* ",
                    refs.mn(p, "mentions"),
                    " */",
                )
        f.add("")
        f.add("#endif /* DEMOSAT_IDS_H */")
        return f

    @staticmethod
    def _tc_ids_h(m: Mission, refs: Refs) -> _CFile:
        f = _CFile("include/demosat_tc_ids.h")
        f.add("/* demosat_tc_ids.h - telecommand identifiers, generated from the SRDB */")
        f.add("#ifndef DEMOSAT_TC_IDS_H")
        f.add("#define DEMOSAT_TC_IDS_H")
        f.add("")
        f.add("typedef enum {")
        tcs = m.tcs
        for k, tc in enumerate(tcs):
            sep = "," if k < len(tcs) - 1 else " "
            f.add(
                "    TC_",
                refs.id(tc, "defines_id"),
                f" = 0x{tc.code:04X}u{sep}  /* ",
                refs.mn(tc, "mentions"),
                " */",
            )
        f.add("} tc_id_t;")
        f.add("")
        f.add("#endif /* DEMOSAT_TC_IDS_H */")
        return f

    @staticmethod
    def _app_h(sub: SubM) -> _CFile:
        lo, up = sub.code.lower(), sub.code
        f = _CFile(f"src/{lo}_app.h")
        f.add(f"/* {lo}_app.h - {sub.spec.adj} application ({up}) interface */")
        f.add(f"#ifndef {up}_APP_H")
        f.add(f"#define {up}_APP_H")
        f.add("")
        f.add('#include "demosat_tc_ids.h"')
        f.add('#include "scsw_types.h"')
        f.add("")
        f.add(f"#define {up}_OK (0)")
        f.add(f"#define {up}_ERR_RANGE (-1)")
        f.add(f"#define {up}_ERR_UNKNOWN_TC (-2)")
        f.add("")
        f.add(f"void {lo}_init(void);")
        f.add(f"int {lo}_tc_dispatch(tc_id_t tc_id, const tc_args_t *args);")
        f.add(f"void {lo}_hk_fill(hk_buf_t *buf);")
        f.add("")
        f.add(f"#endif /* {up}_APP_H */")
        return f

    @staticmethod
    def _app_c(sub: SubM, refs: Refs) -> _CFile:
        lo, up = sub.code.lower(), sub.code
        f = _CFile(f"src/{lo}_app.c")
        f.add(
            f"/* {lo}_app.c - {sub.spec.adj} application ({up}): telecommands and housekeeping */"
        )
        f.add('#include "demosat_ids.h"')
        f.add(f'#include "{lo}_app.h"')
        f.add("")
        f.add(f"static uint32_t {lo}_tc_count;")
        for tc in sub.tcs:
            f.add("")
            comment: list[Piece] = [
                "/* Handler for ",
                refs.id(tc, "mentions"),
                " (",
                refs.mn(tc, "mentions"),
                "): ",
                refs.ld(tc, lower=True),
                ".",
            ]
            if tc.args:
                comment.append(" Arguments: " if len(tc.args) > 1 else " Argument: ")
                for i, a in enumerate(tc.args):
                    comment += [", " if i else "", refs.id(a, "mentions")]
                comment.append(".")
            f.add(*comment, " */")
            if tc.args:
                body: list[list[Piece]] = [
                    ["    if (args == NULL) {"],
                    [f"        return {up}_ERR_RANGE;"],
                    ["    }"],
                    [f"    return drv_command(DEV_{up}, 0x{tc.code:04X}u, args);"],
                ]
            else:
                body = [
                    ["    (void)args;"],
                    [f"    return drv_command(DEV_{up}, 0x{tc.code:04X}u, NULL);"],
                ]
            f.function(f"static int {tc.mn.lower()}(const tc_args_t *args)", body)
        f.add("")
        f.add(f"/* Dispatch the telecommands addressed to the {sub.spec.adj} application. */")
        body = [[f"    {lo}_tc_count++;"], ["    switch (tc_id) {"]]
        for tc in sub.tcs:
            body.append(
                ["    case TC_", refs.id(tc, "handles"), ":   /* ", refs.mn(tc, "mentions"), " */"]
            )
            body.append([f"        return {tc.mn.lower()}(args);"])
        body += [["    default:"], [f"        return {up}_ERR_UNKNOWN_TC;"], ["    }"]]
        f.function(
            f"int {lo}_tc_dispatch(tc_id_t tc_id, const tc_args_t *args)",
            body,
            handles=list(sub.tcs),
        )
        f.add("")
        pk_comment: list[Piece] = ["/* Fill the "]
        for i, pk in enumerate(sub.hk):
            pk_comment += [" and " if i else "", refs.mn(pk, "mentions")]
        pk_comment.append(
            " packets, PUS (3,25). */" if len(sub.hk) > 1 else " packet, PUS (3,25). */"
        )
        f.add(*pk_comment)
        body = []
        for k, p in enumerate(sub.params):
            if p.kind == "status":
                code: list[Piece] = [
                    "    hk_put_u8(buf, PARAM_",
                    refs.id(p, "uses"),
                    f", drv_state(DEV_{up}, {k}u));",
                ]
            else:
                code = [
                    "    hk_put_u16(buf, PARAM_",
                    refs.id(p, "uses"),
                    f", adc_read(ADC_{up}_{k:02d}));",
                ]
            body.append([*code, "  /* ", refs.mn(p, "mentions"), " */"])
        f.function(f"void {lo}_hk_fill(hk_buf_t *buf)", body)
        f.add("")
        f.add(f"/* Initialise the {sub.spec.adj} application. */")
        f.function(f"void {lo}_init(void)", [[f"    {lo}_tc_count = 0u;"]])
        return f

    @staticmethod
    def _drivers(sub: SubM, n: int, refs: Refs) -> list[_CFile]:
        lo, up = sub.code.lower(), sub.code
        out = []
        chunk = max(1, -(-len(sub.params) // max(n, 1)))
        for k in range(n):
            params = sub.params[k * chunk : (k + 1) * chunk] or sub.params[:1]
            f = _CFile(f"src/{lo}_drv_{k + 1}.c")
            f.add(f"/* {lo}_drv_{k + 1}.c - {sub.spec.adj} drivers, part {k + 1} */")
            f.add('#include "demosat_ids.h"')
            f.add(f'#include "{lo}_app.h"')
            f.add("")
            comment: list[Piece] = ["/* Sample "]
            for i, p in enumerate(params[:3]):
                comment += [", " if i else "", refs.mn(p, "mentions")]
            comment.append(" and related channels. */" if len(params) > 3 else ". */")
            f.add(*comment)
            body = [
                [
                    "    hk_put_u16(buf, PARAM_",
                    refs.id(p, "uses"),
                    f", adc_read(ADC_{up}_{j:02d}));",
                ]
                for j, p in enumerate(params)
            ]
            f.function(f"void {lo}_drv_{k + 1}_sample(hk_buf_t *buf)", body)
            out.append(f)
        return out
