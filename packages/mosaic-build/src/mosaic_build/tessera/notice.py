"""A tessera's notice, set in its import settings (plan M3.14; sections 3.2, 4.1, 7.2, 10).

The ``notice`` setting is the licence or confidentiality marking of the source, such as its
copyright line. The tessera's one source row holds it as written, ``header.settings`` records it,
and a mosaic copies it with the source (section 3.2) and lists it in its build report (section
7.2), so the marking is not lost (section 10). Without the setting the notice is NULL.
"""

__all__ = ["notice_problem"]


def notice_problem(notice: str | None) -> str | None:
    """Why the builder refuses ``notice``, or None when it takes it (None: no notice)."""
    if notice is None:
        return None
    if notice == "":
        return "notice is empty; leave the setting out for a source with no notice"
    if "\x00" in notice:
        return "notice contains U+0000, which text never holds (3.1)"
    for c in notice:
        if 0xD800 <= ord(c) <= 0xDFFF:
            return (
                f"notice contains the unpaired surrogate U+{ord(c):04X}, "
                f"which text cannot hold (3.1)"
            )
    return None
