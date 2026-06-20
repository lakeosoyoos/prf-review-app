"""Auto-build the lessor -> supporting-document index (PRF review Stage 5).

Replaces the hand-built CERT_DOCS mapping. Scans the supporting-document folders, assigns each
PDF to a roster lessor / related entity / public-land agency / tribe, and exposes a single
`DocIndex.lookup(owner_string, trs=...)` the deliverable builder uses to attach documents to a
location. Roster-driven (account_config.yaml) — no per-account hardcoding.

    from doc_index import DocIndex
    di = DocIndex.build(source_dirs=["/path/Supporting Lease Documents", "/path/AIP_Harvest"],
                        config="account_config.yaml",
                        agency_bundles={"WA DNR (state lease)": "GC DNR State Leases (bundle).pdf", ...})
    di.lookup("BIRCH LAND & TIMBER LTD")        -> ["gamble land and timber signed lease cert.pdf", ...]
    di.lookup("DNR-Red Ridge", trs=(31,25,33))  -> ["<recorded DNR lease for that section>.pdf"] or [bundle]
    di.write("extracted/doc_index.json")

Matching is intentionally conservative: a file is assigned to a roster name only when the name's
DISTINCTIVE tokens (generic words like LLC/RANCH/FARMS/LEASE dropped) appear in the normalized
filename, with a difflib ratio tiebreak. One lessor may own several files; all are returned.
"""
import os, re, sys, json, glob, difflib

sys.path.insert(0, os.path.dirname(__file__))
from name_match import OwnerClassifier, _norm  # reuse the roster classifier + normalizer

# Generic corporate suffixes + filename-noise words carry no identifying signal. NOTE we deliberately
# KEEP entity-type words (CATTLE, FARMS, RANCH, LAND, TIMBER, RESORT, FLATS...) because they
# distinguish look-alike rosters (Example Cattle vs Example Farms; Birch Land & Timber vs Birch Resort).
_STOP = {"LLC", "INC", "LP", "LTD", "CO", "COMPANY", "CORP", "THE", "AND", "OF", "A",
         "PROPERTIES", "PROPERTY", "ENTERPRISES", "ENTERPRISE", "PARTNERSHIP",
         "GROUP", "HOLDING", "HOLDINGS", "TRUST", "FAMILY",
         "SIGNED", "LEASE", "LEASES", "CERT", "CERTIFICATION", "CERTIFICATIONS",
         "LCF", "FORM", "PERMIT", "AGREEMENT", "DOC", "PDF"}
_AGENCY_KW = [  # filename keyword -> canonical agency label (matches name_match.GOV_TAGS labels)
    ("WDFW", "WA WDFW (state lease)"), ("FISH", "WA WDFW (state lease)"),
    ("USFS", "US Forest Service (permit)"), ("FOREST", "US Forest Service (permit)"), ("ONF", "US Forest Service (permit)"),
    ("BLM", "US BLM (federal permit)"), ("ALLOTMENT", "US BLM (federal permit)"),
    ("DNR", "WA DNR (state lease)"), ("NATURAL RESOURCES", "WA DNR (state lease)"),
    ("COLVILLE", "Tribal lease"), ("TRIBAL", "Tribal lease"), ("CTL", "Tribal lease"),
]


def _terms(s):
    """Distinctive comparable tokens from a name OR a filename, normalized the same way so
    'C & M', 'C&M' and 'c&m 1 ...' all reduce to {'CM'} and 'BIRCH LAND & TIMBER' to {'BIRCH'}."""
    n = _norm(s)
    n = re.sub(r"\b([A-Z])\s*&\s*([A-Z])\b", r"\1\2", n)   # glue single-letter initialisms: C & M -> CM
    n = n.replace("&", " ")
    n = re.sub(r"\b(19|20)\d{2}\b", " ", n)                 # strip years
    n = re.sub(r"\b\d+\b", " ", n)                          # strip bare numbers
    return [t for t in n.split() if t not in _STOP and len(t) >= 2]


def _norm_fn(path):
    return _terms(os.path.splitext(os.path.basename(path))[0])


def _name_tokens(name):
    return _terms(name)


def _score(name_toks, fn_toks):
    """Match a roster name against a filename's tokens. Returns (hits, coverage).
    hits = # of the name's distinctive tokens present (absolute specificity);
    coverage = hits / len(name_toks). Compare candidates by (hits, coverage) so a 2-token match
    (ABLE+BAKER) beats a 1-token match (ABLE) for the same file."""
    if not name_toks or not fn_toks:
        return (0, 0.0)
    fnset = set(fn_toks)
    hit = sum(1 for t in name_toks if t in fnset)
    return (hit, hit / len(name_toks))


class DocIndex:
    def __init__(self, lessor_docs, agency_docs, tribal_docs, files, roster_names, oc,
                 unmatched_files=None, unmatched_names=None, agency_bundle=None, tribal_bundle=None):
        self.lessor_docs = lessor_docs          # {normalized roster name: [filenames]}
        self.agency_docs = agency_docs          # {agency label: [filenames]} (all keyword matches; fallback)
        self.agency_bundle = agency_bundle or {}  # {agency label: single canonical bundle filename}
        self.tribal_bundle = tribal_bundle      # single canonical tribal cert/bundle filename
        self.tribal_docs = tribal_docs          # [filenames]
        self.files = files                       # {filename: full source path}
        self.roster_names = roster_names         # [original roster names], for matching owner->name
        self.oc = oc
        self.unmatched_files = unmatched_files or []
        self.unmatched_names = unmatched_names or []
        # precompute name-token lists for owner->roster matching
        self._name_toks = {n: _name_tokens(n) for n in roster_names}

    # ---- build ----------------------------------------------------------------
    @classmethod
    def build(cls, source_dirs, config=None, oc=None, roster_names=None,
              agency_bundles=None, threshold=0.5):
        """Scan source_dirs for PDFs and assign each to a roster lessor / agency / tribe.
        Provide either `config` (path to account_config.yaml) or (`oc` + `roster_names`)."""
        if oc is None:
            oc = OwnerClassifier.from_config(config)
        if roster_names is None:
            import yaml
            e = yaml.safe_load(open(config)).get("entities", {})
            roster_names = (list(e.get("insured_aliases") or []) + list(e.get("related") or [])
                            + list(e.get("lessors") or []) + list(e.get("short_names") or []))
        files = {}
        for d in source_dirs:
            for p in glob.glob(os.path.join(d, "**", "*.pdf"), recursive=True):
                files.setdefault(os.path.basename(p), p)   # first wins on dup basenames

        lessor_docs, agency_docs, tribal_docs = {}, {}, []
        unmatched = []
        name_toks = {n: _name_tokens(n) for n in roster_names}
        for fn, path in sorted(files.items()):
            up = fn.upper()
            ag = next((lab for kw, lab in _AGENCY_KW if kw in up), None)
            if ag == "Tribal lease":
                tribal_docs.append(fn); continue
            if ag:
                agency_docs.setdefault(ag, [])
                if fn not in agency_docs[ag]:
                    agency_docs[ag].append(fn)
                continue
            ft = _norm_fn(fn)
            best, bn = (0, 0.0), None
            for n in roster_names:
                sc = _score(name_toks[n], ft)
                if sc > best:
                    best, bn = sc, n
            if bn and best[1] >= threshold:          # coverage gate
                key = _norm(bn)
                lessor_docs.setdefault(key, [])
                if fn not in lessor_docs[key]:
                    lessor_docs[key].append(fn)
            else:
                unmatched.append(fn)
        # record the canonical bundle filename per agency (lookup returns this, not every constituent)
        agency_bundle = {}
        for lab, bundle in (agency_bundles or {}).items():
            if bundle:
                agency_bundle[lab] = bundle
                agency_docs.setdefault(lab, [])
                if bundle not in agency_docs[lab]:
                    agency_docs[lab].insert(0, bundle)
        tribal_bundle = next((f for f in tribal_docs if "CERTIFICATION" in f.upper()),
                             tribal_docs[0] if tribal_docs else None)
        matched_names = {k for k in lessor_docs}
        unmatched_names = [n for n in roster_names if _norm(n) not in matched_names]
        return cls(lessor_docs, agency_docs, tribal_docs, files, roster_names, oc,
                   unmatched_files=unmatched, unmatched_names=unmatched_names,
                   agency_bundle=agency_bundle, tribal_bundle=tribal_bundle)

    # ---- lookup ---------------------------------------------------------------
    def lookup(self, owner, trs=None, recorded_by_trs=None):
        """Return supporting-document filename(s) for an owner string.
        recorded_by_trs: optional {(T,R,S): filename} of section-specific recorded permits/leases,
        which take precedence over a generic agency bundle."""
        kind, label = self.oc.classify(owner)
        if kind == "gov_lease":
            if recorded_by_trs and trs in recorded_by_trs:
                return [recorded_by_trs[trs]]          # section-specific recorded instrument wins
            if label in self.agency_bundle:
                return [self.agency_bundle[label]]     # else the one canonical agency bundle
            return list(self.agency_docs.get(label, []))
        if kind == "tribal":
            if recorded_by_trs and trs in recorded_by_trs:
                return [recorded_by_trs[trs]]
            return [self.tribal_bundle] if self.tribal_bundle else list(self.tribal_docs)
        if kind in ("lessor", "fee_related", "fee_insured", "private_tag"):
            # rank roster names this owner matches; return the best one that actually HAS docs
            # (so an alias like "BEAR MOUNTAIN" with no file falls back to "BEAR MTN" which has one).
            oset = set(_terms(owner))
            ranked = []
            for n, toks in self._name_toks.items():
                if not toks:
                    continue
                hit = sum(1 for t in toks if t in oset)
                cov = hit / len(toks)
                if cov >= 0.5:
                    ranked.append(((hit, cov), n))
            for _, n in sorted(ranked, reverse=True):
                docs = self.lessor_docs.get(_norm(n))
                if docs:
                    return list(docs)
        return []

    def write(self, path):
        out = {
            "lessor_docs": self.lessor_docs,
            "agency_docs": self.agency_docs,
            "tribal_docs": self.tribal_docs,
            "unmatched_files": self.unmatched_files,
            "unmatched_roster_names": self.unmatched_names,
            "n_files_indexed": len(self.files),
        }
        with open(path, "w") as f:
            json.dump(out, f, indent=2)
        return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Build the lessor->document index from supporting-doc folders.")
    ap.add_argument("config", help="path to account_config.yaml")
    ap.add_argument("source_dirs", nargs="+", help="folders to scan for supporting PDFs")
    ap.add_argument("-o", "--out", default="extracted/doc_index.json")
    a = ap.parse_args()
    di = DocIndex.build(a.source_dirs, config=a.config)
    rep = di.write(a.out)
    print(f"indexed {rep['n_files_indexed']} files -> {a.out}")
    print(f"  lessors matched: {len(rep['lessor_docs'])} | agencies: {list(rep['agency_docs'])} | tribal files: {len(rep['tribal_docs'])}")
    print(f"  unmatched files: {len(rep['unmatched_files'])} | unmatched roster names: {len(rep['unmatched_roster_names'])}")
    if rep["unmatched_files"]:
        print("  (unmatched files):", rep["unmatched_files"][:12])
