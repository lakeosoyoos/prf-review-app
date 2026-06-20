"""Roster-driven owner/lessor classification (PRF review Stage 4).

Why this exists: generic token matching fails in both directions in this domain.
  - OVER-match: tokens like ETAL, LAKE, BEAR, LAND, MOUNTAIN matched unrelated owners and once
    inflated "controlled acreage" from ~122k to 669k acres before being caught by a smell test.
  - UNDER-match: short/initialed lessors ("C & M I LLC", "J & J", "TJF", "BHP") tokenize to
    nothing and false-flag covered ground as uncovered.
The fix is a curated per-account roster (account_config.yaml) compiled into explicit regexes.

    from name_match import OwnerClassifier
    oc = OwnerClassifier.from_config("account_config.yaml")
    oc.classify("DNR-Red Ridge")        -> ("gov_lease", "WA DNR (state lease)")
    oc.classify("BIRCH LAND & TIMBER")  -> ("lessor", "BIRCH LAND & TIMBER")
    oc.classify("SMITH, RANDOM")         -> ("none", None)
"""
import re

GOV_TAGS = [  # agency prefixes/markers; county layers often tag leased ground "BLM-<lessee>"
    (r'\bBLM\b', "US BLM (federal permit)"),
    (r'\bUSFS\b|\bFOREST SERVICE\b|\bONF\b|\bUSDA\b', "US Forest Service (permit)"),
    (r'\bWDFW\b|FISH (AND|&) WILDLIFE', "WA WDFW (state lease)"),
    (r'\bDNR\b|NATURAL RESOURCES', "WA DNR (state lease)"),
    (r'\bUSA\b|UNITED STATES', "Federal (USA)"),
]
TRIBAL = re.compile(r'TRIBAL|COLVILLE|CONFEDERATED TRIBES')
PRIVATE_TAG = re.compile(r'PRIVATE LEASE')


def _norm(s):
    s = re.sub(r'[^A-Z0-9& ]', ' ', (s or '').upper())
    return re.sub(r'\s+', ' ', s.replace(' AND ', ' & ')).strip()


def _alias_regex(names):
    """Compile exact-ish alias patterns. Multi-word aliases match as phrases; single distinctive
    words (>=4 chars) as word-bounded tokens. Ampersand initialisms kept literal."""
    parts = []
    for n in names or []:
        n = _norm(n)
        if not n:
            continue
        if '&' in n or ' ' in n:
            parts.append(re.escape(n).replace(r'\ ', r'\s+'))
        elif len(n) >= 4:
            parts.append(r'\b' + re.escape(n) + r'\b')
        else:  # short token like TJF/BHP — require word boundaries
            parts.append(r'\b' + re.escape(n) + r'\b')
    return re.compile('|'.join(parts)) if parts else None


class OwnerClassifier:
    def __init__(self, insured_aliases, related, lessors, short_names=()):
        self.re_insured = _alias_regex(insured_aliases)
        self.re_related = _alias_regex(related)
        self.re_lessor = _alias_regex(list(lessors or []) + list(short_names or []))

    @classmethod
    def from_config(cls, path):
        import yaml
        with open(path) as f:
            cfg = yaml.safe_load(f)
        e = cfg.get("entities", {})
        return cls(e.get("insured_aliases"), e.get("related"),
                   e.get("lessors"), e.get("short_names"))

    def classify(self, owner):
        """-> (kind, label). kind in: fee_insured, fee_related, lessor, gov_lease, tribal,
        private_tag, none. Gov tags on an insured/related name still classify gov_lease
        (the tag means leased public ground, not fee)."""
        o = _norm(owner)
        if not o:
            return ("none", None)
        for pat, label in GOV_TAGS:
            if re.search(pat, o):
                return ("gov_lease", label)
        if TRIBAL.search(o):
            return ("tribal", "Tribal lease")
        if PRIVATE_TAG.search(o):
            return ("private_tag", "Private lease (tagged)")
        if self.re_insured and self.re_insured.search(o):
            return ("fee_insured", owner)
        if self.re_related and self.re_related.search(o):
            return ("fee_related", owner)
        if self.re_lessor and self.re_lessor.search(o):
            return ("lessor", owner)
        return ("none", None)

    def controlled(self, owner):
        return self.classify(owner)[0] != "none"


if __name__ == "__main__":
    oc = OwnerClassifier(["EXAMPLE CATTLE"], ["EXAMPLE FARMS", "SUMMIT HOLDING"],
                         ["BIRCH", "CEDAR"], ["TJF", "C & M", "J & J"])
    for t in ["DNR-Red Ridge", "BIRCH LAND & TIMBER LTD", "C & M I LLC",
              "TJF PROPERTIES LLC", "BEAR LAKE ESTATES", "SMITH ETAL, JOHN"]:
        print(f"  {t!r:34} -> {oc.classify(t)}")
