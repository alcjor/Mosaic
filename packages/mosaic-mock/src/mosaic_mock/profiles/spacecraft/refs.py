"""References to mission objects, as `Ref` pieces and as template tokens.

What the pack makes linkable decides the ``match`` of each reference (02 § 3):
IDs of PCF/CCF/CPC, mnemonics of PCF/CCF and packet names are exact; long descriptions
and argument mnemonics are not surface forms, so they are ``fuzzy_only``.
"""

from __future__ import annotations

import re

from mosaic_mock.engine.text import Ref, Text, parse_tokens, tok
from mosaic_mock.profiles.spacecraft.world import Arg, Mission, Packet, Param, Tc

Obj = Param | Tc | Arg | Packet
VOCAB_TOKEN = re.compile(r"⟦([A-Z0-9_]+):([a-z]+)⟧")


def item_of(o: Obj) -> str:
    return o.item.ref


class Refs:
    def __init__(self, mission: Mission) -> None:
        self.m = mission
        self.by_item: dict[str, Obj] = {}
        for s in mission.subs:
            for o in (*s.params, *s.args, *s.tcs):
                self.by_item[item_of(o)] = o
        for pk in mission.packets:
            self.by_item[item_of(pk)] = pk

    # pieces ------------------------------------------------------------------------------

    def id(self, o: Param | Tc | Arg, role: str) -> Ref:
        return Ref(item_of(o), o.id, role, "exact", "id")

    def mn(self, o: Obj, role: str) -> Ref:
        if isinstance(o, Packet):
            return Ref(item_of(o), o.name, role, "exact", "mn")
        match = "fuzzy_only" if isinstance(o, Arg) else "exact"
        return Ref(item_of(o), o.mn, role, match, "mn")

    def ld(self, o: Param | Tc | Arg, role: str = "mentions", lower: bool = False) -> Ref:
        text = f"{o.ld[0].lower()}{o.ld[1:]}" if lower else o.ld
        return Ref(item_of(o), text, role, "fuzzy_only", "ld")

    def resolve(self, item: str, form: str, role: str = "mentions") -> Ref:
        o = self.by_item[item]
        if form == "id":
            assert not isinstance(o, Packet)
            return self.id(o, role)
        if form == "mn":
            return self.mn(o, role)
        if form in ("ld", "ldl"):
            assert not isinstance(o, Packet)
            return self.ld(o, role, lower=form == "ldl")
        raise ValueError(f"unknown reference form {form!r}")

    # templates ---------------------------------------------------------------------------

    def helpers(self) -> dict[str, object]:
        """Functions templates call to write a reference as a protected token."""
        return {
            "id": lambda o: tok(item_of(o), "id"),
            "mn": lambda o: tok(item_of(o), "mn"),
            "ld": lambda o: tok(item_of(o), "ld"),
            "ldl": lambda o: tok(item_of(o), "ldl"),
        }

    def parse(self, s: str, role: str = "mentions") -> Text:
        return parse_tokens(s, lambda item, form: self.resolve(item, form, role))

    def vocab_tokens(self, s: str) -> str:
        """Turn vocabulary placeholders (``⟦BAT_V_MAIN:mn⟧``, ``⟦OBC:hk⟧``) into item tokens."""

        def sub(m: re.Match[str]) -> str:
            name, form = m.group(1), m.group(2)
            if form == "hk":
                sub_m = next(s for s in self.m.subs if s.code == name)
                return tok(item_of(sub_m.hk[0]), "mn")
            return tok(item_of(self.m.by_mn[name]), form)

        return VOCAB_TOKEN.sub(sub, s)
