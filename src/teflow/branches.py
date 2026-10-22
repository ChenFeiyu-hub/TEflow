"""Explicit, versioned branch graph. No discovery algorithm is implemented here."""
from .common import WorkflowError
from .registry import BRANCH_SPECS, BRANCH_BY_NAME

BRANCHES = {b.name:(b.library_stage, b.rm_stage, b.prefix) for b in BRANCH_SPECS}
DEFAULT_BRANCHES = list(BRANCHES)[:5]
HELIANO_DEFAULTS = dict(window=10000, domain_distance=2500, terminal_distance=0,
                        insertion_site_hle1=1, insertion_site_hle2=1, terminal_identity=100,
                        flank_similarity=0.5, pvalue=1e-5, bitscore=32, nearest=False,
                        library_mode="native_representatives")
HITE_DEFAULTS = dict(use_HybridLTR=1, use_NeuralTE=1, min_TE_len=80,
                     chrom_seg_length=1000000, remove_nested=1)


def enabled(c):
    if c.get("schema_version", 1) == 1:
        return ["edta", "edta_tetrimmer"]
    return [b for b in BRANCHES if c["branches"].get(b, {}).get("enabled", False)]


def options(c, branch):
    defaults = HELIANO_DEFAULTS if branch == "heliano" else HITE_DEFAULTS if branch == "hite" else {}
    return dict(defaults, **c.get("branches", {}).get(branch, {}).get("parameters", {}))


def validate(c):
    branches = c.get("branches")
    if not isinstance(branches, dict) or set(branches) - BRANCHES.keys():
        raise WorkflowError("schema 2 requires an explicit supported branches object")
    for name, value in branches.items():
        if not isinstance(value, dict) or set(value) - {"enabled", "parameters"} or type(value.get("enabled")) is not bool:
            raise WorkflowError("Each branch needs a boolean enabled and optional parameters: " + name)
        pars = value.get("parameters", {})
        allowed = HELIANO_DEFAULTS if name == "heliano" else HITE_DEFAULTS if name == "hite" else {}
        if not isinstance(pars, dict) or set(pars) - allowed.keys():
            raise WorkflowError("Unsupported branch parameters: " + name)
    names = set(enabled(c))
    if not names:
        raise WorkflowError("Enable at least one branch")
    requires = {b.name:set(b.requires) for b in BRANCH_SPECS}
    for branch in names:
        if requires.get(branch, set()) - names:
            raise WorkflowError("Missing enabled parent branch for " + branch)
    h = options(c, "heliano")
    for key in ("window", "domain_distance", "terminal_distance"):
        if type(h[key]) is not int or h[key] < (1 if key != "terminal_distance" else 0):
            raise WorkflowError("Invalid HELIANO " + key)
    if any(h[k] not in (0, 1) for k in ("insertion_site_hle1", "insertion_site_hle2")) or h["terminal_identity"] not in (80, 90, 100) or h["flank_similarity"] not in (0.4, 0.5, 0.6, 0.7):
        raise WorkflowError("Invalid HELIANO categorical parameter")
    if type(h["pvalue"]) not in (float,int) or not 0 < h["pvalue"] <= 1 or type(h["bitscore"]) is not int or not 30 <= h["bitscore"] < 55 or type(h["nearest"]) is not bool:
        raise WorkflowError("Invalid HELIANO score/pvalue/nearest")
    if h["library_mode"] not in ("native_representatives", "official_consensus"):
        raise WorkflowError("Unknown HELIANO library_mode")
    hi = options(c, "hite")
    if any(type(v) is not int or v not in (0, 1) for k, v in hi.items() if k in ("use_HybridLTR", "use_NeuralTE", "remove_nested")) or any(type(hi[k]) is not int or hi[k] < 1 for k in ("min_TE_len", "chrom_seg_length")):
        raise WorkflowError("Invalid HiTE parameters")
    for s in c["samples"]:
        if "reference_only" in names and not s.get("reference_library"):
            raise WorkflowError("reference_only requires sample.reference_library")
    qc = c.get("qc", {})
    if not isinstance(qc,dict) or set(qc) - {"host_proteins", "te_proteins", "pfam", "evalue"}:
        raise WorkflowError("Unknown QC option")
    if type(qc.get("pfam", False)) is not bool or type(qc.get("evalue",1e-5)) not in (int,float) or not 0 < qc.get("evalue", 1e-5) <= 1:
        raise WorkflowError("Invalid QC evidence parameters")
    if qc.get("host_proteins") == "derived" and any(not (s.get("cds") or s.get("derive_cds")) for s in c["samples"]):
        raise WorkflowError("Derived host protein QC requires CDS for every sample")
    ev = c.get("evaluation", {})
    if not isinstance(ev,dict) or set(ev) - {"promoter_analysis", "promoter_upstream", "promoter_near", "widths", "reference_features", "reference_class_attribute"}:
        raise WorkflowError("Unknown evaluation option")
    if type(ev.get("promoter_analysis", True)) is not bool:
        raise WorkflowError("evaluation.promoter_analysis must be boolean")
    u, n = ev.get("promoter_upstream", 1500), ev.get("promoter_near", 500)
    if type(u) is not int or type(n) is not int or not 0 < n <= u:
        raise WorkflowError("Invalid promoter windows")
    widths = ev.get("widths", list(range(4, 21)))
    if not isinstance(widths,list) or not widths or any(type(w) is not int or w < 1 for w in widths) or len(set(widths)) != len(widths):
        raise WorkflowError("Evaluation widths must be unique positive integers")
    if "reference_features" in ev and (not isinstance(ev["reference_features"],list) or not ev["reference_features"] or any(not isinstance(x,str) or not x for x in ev["reference_features"])):
        raise WorkflowError("reference_features must be a nonempty list of feature types")
    if "reference_class_attribute" in ev and (not isinstance(ev["reference_class_attribute"],str) or not ev["reference_class_attribute"]):
        raise WorkflowError("reference_class_attribute must be a nonempty string")


def required_tools(c):
    if "schema_version" not in c:
        return set(c["tools"])
    names = set(enabled(c))
    tools = {"repeatmasker", "trf", "dustmasker"}
    for name in names:
        tools.update(BRANCH_BY_NAME[name].tools)
    if c.get("qc", {}).get("host_proteins") or c.get("qc", {}).get("te_proteins"):
        tools.add("diamond")
    if c.get("qc", {}).get("pfam"):
        tools.add("hmmscan")
    return tools


def graph(c):
    if c["schema_version"] == 1:
        return dict(edta=[], tetrimmer=["edta"], rm_edta=["edta"],
                    rm_refined=["tetrimmer"], tracks=[],
                    export=["edta", "tetrimmer", "rm_edta", "rm_refined", "tracks"])
    deps = {"tracks": []}
    parent = {b.library_stage:list(b.library_parents) for b in BRANCH_SPECS}
    for branch in enabled(c):
        lib, rm, _ = BRANCHES[branch]
        deps[lib] = parent[lib]
        deps["qc_" + branch] = [lib]
        deps[rm] = [lib]
        deps["export_" + branch] = [lib, rm, "qc_" + branch, "tracks"]
    deps["export"] = ["export_" + b for b in enabled(c)]
    return deps


def stage_branch(stage):
    for branch, (lib, rm, _) in BRANCHES.items():
        if stage in (lib, rm, "qc_" + branch, "export_" + branch):
            return branch
    return None


def stage_tools(c, stage):
    if stage.startswith("rm_"):
        return {"repeatmasker"}
    if stage == "tracks":
        return {"trf", "dustmasker"}
    if stage.startswith("qc_"):
        return required_tools(c) & {"diamond", "hmmscan"}
    return {"edta": {"edta"}, "tetrimmer": {"tetrimmer"},
            "heliano": {"heliano", "heliano_cons", "repeatmasker"}, "hite": {"hite"}}.get(stage, set())
