"""Township-Range-Section parsing + instrument index (PRF review Stages 3-4).

Public/tribal grazing land is absent from assessor parcel layers; legals are the locator.
Parses the four formats seen in the field into (township, range, section) int tuples:

    parse_compact("031N-025E-0007")  -> (31, 25, 7)     # per-field FSA spreadsheet legal
    parse_map("31-25-07")            -> (31, 25, 7)     # county layer MAP field
    parse_prose(text)                -> [(T,R,S), ...]  # permits: "Sec 16; N1/2 of Sec 22 ... T21N R27E"
                                                        # tribal: "Section 35, Township 31 North, Range 25 East"

    idx = InstrumentIndex()
    idx.add_instrument(legal_text, label="WA DNR lease C1200B71 -> Gebbers Cattle Ltd")
    idx.lookup((31, 25, 31))  -> ["WA DNR lease C1200B71 -> Gebbers Cattle Ltd"]
"""
import re


def parse_compact(s):
    m = re.match(r'(\d{2,3})[NS]-(\d{2,3})[EW]-(\w+)', str(s or ''))
    if not m:
        return None
    sec = int(m.group(3)) if m.group(3).isdigit() else None  # e.g. "IA21" -> None
    return (int(m.group(1)), int(m.group(2)), sec)


def parse_map(s):
    m = re.match(r'(\d{1,2})-(\d{1,2})-(\d{1,3})', str(s or ''))
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def parse_prose(text):
    """All (T,R,S) tuples in prose legal text. Handles both orders:
    sections-then-township ('Sec 16 ... T21N R27E') and inline
    ('Section 35, Township 31 North, Range 25 East')."""
    out = []
    t = str(text or '')
    # inline: Section N, Township N North, Range N East
    for m in re.finditer(r'Section\s+(\d+)[^.;]*?Township\s+(\d+)\s*North[^.;]*?Range\s+(\d+)\s*East',
                         t, re.I | re.S):
        out.append((int(m.group(2)), int(m.group(3)), int(m.group(1))))
    # block: "<sections...> T31N R25E" — sections listed before the township-range
    for m in re.finditer(r'((?:Sec(?:tion)?s?\.?\s*\d+[^T]*?)+)T\s*(\d+)\s*N\b[, ]*R\s*(\d+)\s*E',
                         t, re.I):
        T, R = int(m.group(2)), int(m.group(3))
        for sm in re.finditer(r'Sec(?:tion)?s?\.?\s*(\d+)', m.group(1), re.I):
            tup = (T, R, int(sm.group(1)))
            if tup not in out:
                out.append(tup)
    return out


class InstrumentIndex:
    """(T,R,S) -> [instrument labels]. Build from extracted permits/tribal leases."""
    def __init__(self):
        self._idx = {}

    def add_instrument(self, legal_text, label):
        for k in parse_prose(legal_text):
            self._idx.setdefault(k, [])
            if label not in self._idx[k]:
                self._idx[k].append(label)

    def add_key(self, trs, label):
        if trs and trs[2] is not None:
            self._idx.setdefault(trs, [])
            if label not in self._idx[trs]:
                self._idx[trs].append(label)

    def lookup(self, trs):
        return self._idx.get(trs, []) if trs else []

    def __len__(self):
        return len(self._idx)


if __name__ == "__main__":
    assert parse_compact("031N-025E-0007") == (31, 25, 7)
    assert parse_compact("029N-023E-IA21") == (29, 23, None)
    assert parse_map("31-25-07") == (31, 25, 7)
    p = parse_prose("The E1/2 of Sec 16; N 1/2 of Sec 22, all in T21N R27E, W.M.")
    assert (21, 27, 16) in p and (21, 27, 22) in p, p
    q = parse_prose("the NE1/4SW1/4 of Section 35, Township 31 North, Range 25 East, Willamette Meridian")
    assert (31, 25, 35) in q, q
    print("trs_match self-tests OK")
