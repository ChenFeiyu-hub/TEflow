"""General genomic/reference summaries, with optional promoter opportunity analysis."""
import bisect
import csv
import itertools
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from .common import WorkflowError, fasta, table, read_json, write_json
from .formats import union, tier, standard_class, bed_write
from .inputs import annotation_rows
from .classification import classify, MAPPING_VERSION


def tsv(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


class IntervalIndex:
    def __init__(self, intervals):
        self.rows = defaultdict(list)
        for chrom, a, b in union(intervals):
            self.rows[chrom].append((a, b))
        self.ends = {c: [b for a, b in rows] for c, rows in self.rows.items()}

    def clip(self, chrom, a, b):
        rows = self.rows.get(chrom, [])
        i = bisect.bisect_right(self.ends.get(chrom, []), a)
        result = []
        while i < len(rows) and rows[i][0] < b:
            x, y = rows[i]
            if a < b:
                result.append((chrom, max(a, x), min(b, y)))
            i += 1
        return result


def intersect(a, b):
    index = IntervalIndex(b)
    return union(v for chrom, x, y in union(a) for v in index.clip(chrom, x, y))


def subtract(a, b):
    index = IntervalIndex(b)
    result = []
    for chrom, x, y in union(a):
        cursor = x
        for _, u, v in index.clip(chrom, x, y):
            if u > cursor:
                result.append((chrom, cursor, u))
            cursor = v
        if cursor < y:
            result.append((chrom, cursor, y))
    return result


def bp(intervals):
    return sum(b-a for _, a, b in union(intervals))


def bed(path):
    result = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip() and not line.startswith("#"):
                v = line.split()
                result.append((v[0], int(v[1]), int(v[2])))
    return union(result)


def promoter_windows(s, manifest, config):
    lengths = {r["original_id"]: r["length"] for r in manifest["sequences"] if r["included"]}
    windows, seen = [], set()
    if s.get("promoters_bed"):
        with open(s["promoters_bed"], encoding="utf-8") as f:
            for line in f:
                if not line.strip() or line.startswith("#"):
                    continue
                v = line.split()
                if len(v) < 6 or v[0] not in lengths or v[5] not in ("+", "-") or v[3] in seen:
                    raise WorkflowError("Promoter BED needs unique IDs, original seqids and BED6 strand")
                a, b = int(v[1]), int(v[2])
                if not 0 <= a <= b <= lengths[v[0]]:
                    raise WorkflowError("Promoter BED outside genome")
                seen.add(v[3]); windows.append(dict(seqid=v[0], start=a, end=b, gene_id=v[3], strand=v[5]))
        return windows, "supplied_frozen_BED6"
    if not s.get("annotation"):
        return [], "not_available"
    genes = {}
    for chrom, kind, a, b, strand, _, at in annotation_rows(s["annotation"]):
        if kind != "gene" or chrom not in lengths or strand not in ("+", "-"):
            continue
        gid = at.get("gene_id", at.get("ID"))
        if not gid or gid in genes:
            raise WorkflowError("Gene features need unique IDs for provisional promoters")
        genes[gid] = (chrom, a-1, b, strand)
    bodies = IntervalIndex((ch, a, b) for ch, a, b, _ in genes.values())
    upstream = config.get("promoter_upstream", 1500)
    for gid, (ch, a, b, strand) in sorted(genes.items()):
        lo, hi = (max(0, a-upstream), a) if strand == "+" else (b, min(lengths[ch], b+upstream))
        overlaps = bodies.clip(ch, lo, hi)
        if overlaps:
            if strand == "+":
                lo = max(y for _, x, y in overlaps)
            else:
                hi = min(x for _, x, y in overlaps)
        windows.append(dict(seqid=ch, start=lo, end=hi, gene_id=gid, strand=strand))
    return windows, "provisional_gene_boundary_TSS_neighbor_clipped; supply BED6 for a downstream coordinate protocol"


def scopes(s, manifest, config):
    genome = [(r["original_id"], 0, r["length"]) for r in manifest["sequences"] if r["included"]]
    if not config.get("promoter_analysis", True):
        return dict(selected_genome=genome), [], "disabled_explicitly"
    promoters, mode = promoter_windows(s, manifest, config)
    near, far = [], []
    distance = config.get("promoter_near", 500)
    for r in promoters:
        ch, a, b = r["seqid"], r["start"], r["end"]
        if r["strand"] == "+":
            z = max(a, b-distance); n, f = (ch, z, b), (ch, a, z)
        else:
            z = min(b, a+distance); n, f = (ch, a, z), (ch, z, b)
        if n[1] < n[2]: near.append(n)
        if f[1] < f[2]: far.append(f)
    areas = dict(selected_genome=genome, promoter_all=union((r["seqid"], r["start"], r["end"]) for r in promoters if r["start"] < r["end"]),
                 promoter_near=union(near), promoter_far=union(far))
    return areas, promoters, mode


def classification_inventory(library, fragments, output):
    families = defaultdict(set)
    for name, _ in fasta(library, allow_empty=True):
        fid, cls = name.split("#", 1); families[cls].add(fid)
    hits = defaultdict(list)
    for r in fragments:
        hits[r["classification"]].append(r)
    rows = []
    for cls in sorted(families.keys() | hits.keys()):
        selected = hits[cls]
        rows.append(dict(raw_classification=cls, standard_class=standard_class(cls), tier=tier(cls),
                         library_entries=len(families[cls]), hit_families=len({r["family_id"] for r in selected}),
                         fragments=len(selected), fragment_sum_bp=sum(int(r["end"])-int(r["start"]) for r in selected),
                         union_bp=bp((r["seqid"], int(r["start"]), int(r["end"])) for r in selected)))
        rows[-1].update(classify(cls))
    table(output, rows, ["raw_classification", "standard_class", "tier", "library_entries", "hit_families", "fragments", "fragment_sum_bp", "union_bp", "mapping_version",
                        'order', 'superfamily_code', 'classification_uncertain', 'structural_label', 'mapping_status'])


def reference_tracks(s, manifest, config):
    if not s.get("reference_te"):
        return None, dict(status="not_provided")
    lengths = {r["original_id"]: r["length"] for r in manifest["sequences"]}
    selected = {r["original_id"] for r in manifest["sequences"] if r["included"]}
    features = set(config.get("reference_features", ["transposable_element", "repeat_region"]))
    tracks = defaultdict(list); count = excluded = 0
    for chrom, kind, a, b, _, _, attrs in annotation_rows(s["reference_te"]):
        if kind not in features: continue
        if chrom not in lengths or b > lengths[chrom]:
            raise WorkflowError("TE reference does not match frozen genome coordinates")
        if chrom not in selected:
            excluded += 1; continue
        cls = attrs.get(config.get("reference_class_attribute", "Classification"), attrs.get("classification", ""))
        try:
            category = standard_class(cls) if cls else "unclassified_reference"
        except WorkflowError:
            category = "unmapped_reference"
        interval = (chrom, a-1, b)
        tracks["total_te"].append(interval); tracks[category].append(interval)
        count += 1
    if not count:
        raise WorkflowError("No selected TE reference features; check feature types and seqids")
    return {k: union(v) for k, v in tracks.items()}, dict(status="reference_agreement_only", features=count, excluded_features=excluded,
                                                          completeness="not_assumed", independence="not_assumed")


def prediction_tracks(fragments):
    result = defaultdict(list)
    for r in fragments:
        interval = (r["seqid"], int(r["start"]), int(r["end"]))
        category = standard_class(r["classification"])
        result[category].append(interval)
        if tier(r["classification"]) == "te":
            result["total_te"].append(interval)
    result.setdefault("total_te", [])
    return {k: union(v) for k, v in result.items()}


def branch_evaluation(c, s, prepared, dest, library):
    manifest = read_json(Path(prepared) / "manifest.json")
    config = c.get("evaluation", {})
    areas, promoters, promoter_mode = scopes(s, manifest, config)
    if config.get("promoter_analysis", True):
        table(dest / "promoters.tsv", promoters, ["seqid", "start", "end", "gene_id", "strand"])
    fragments = tsv(dest / "mask_sources.tsv")
    classification_inventory(library, fragments, dest / "classification_inventory.tsv")
    predicted = prediction_tracks(fragments)
    ref, refinfo = reference_tracks(s, manifest, config)
    rows = []
    for area, region in areas.items():
        for category in sorted(predicted.keys() | (ref.keys() if ref else set())):
            p = intersect(predicted.get(category, []), region)
            r = intersect(ref.get(category, []), region) if ref is not None else None
            p_bp = bp(p); r_bp = bp(r) if r is not None else None
            common = bp(intersect(p, r)) if r is not None else None
            rows.append(dict(region=area, category=category, region_bp=bp(region), predicted_bp=p_bp, reference_bp=r_bp,
                             shared_bp=common, reference_unmatched_prediction_bp=p_bp-common if common is not None else None,
                             reference_coverage=common/r_bp if r_bp else None,
                             prediction_inside_reference=common/p_bp if p_bp and common is not None else None))
    fields = ["region", "category", "region_bp", "predicted_bp", "reference_bp", "shared_bp", "reference_unmatched_prediction_bp", "reference_coverage", "prediction_inside_reference"]
    table(dest / "regional_evaluation.tsv", rows, fields)
    # Gene/CDS context is useful to genome annotation independently of promoters.
    context = {"gene_bodies": [], "CDS": [], "exons": []}
    if s.get("annotation"):
        selected = {r["original_id"] for r in manifest["sequences"] if r["included"]}
        names = {"gene": "gene_bodies", "CDS": "CDS", "exon": "exons"}
        for chrom, kind, a, b, *_ in annotation_rows(s["annotation"]):
            if chrom in selected and kind in names:
                context[names[kind]].append((chrom, a-1, b))
        table(dest / "gene_context_coverage.tsv",
              [dict(region=k, annotation_bp=bp(v), TE_overlap_bp=bp(intersect(v, predicted["total_te"])))
               for k, v in context.items()], ["region", "annotation_bp", "TE_overlap_bp"])
    if not config.get("promoter_analysis", True):
        summary = dict(reference=refinfo, promoter_analysis=False, promoter_mode=promoter_mode,
                       gene_context="descriptive_overlap_only" if s.get("annotation") else "not_provided",
                       family_recovery="not_evaluated_without_curated_consensus_benchmark", automatic_winner=False)
        write_json(dest / "evaluation.json", summary)
        return summary
    mapping = {r["alias"]: r["original_id"] for r in manifest["sequences"] if r["included"]}
    sequences = {mapping[n]: seq for n, seq in fasta(Path(prepared) / "genome.fa")}
    te, unknown = bed(dest / "te.mask.bed"), bed(dest / "repeat_unknown.bed")
    tr, dust = bed(dest / "tandem_repeat.bed"), bed(dest / "low_complexity.bed")
    policies = {"M0": [], "M1_TE": te, "M2_TE_unknown": te+unknown,
                "M3_TE_unknown_tandem_dust": te+unknown+tr+dust, "primary_repeat_TE_tandem_dust": te+tr+dust}
    indexes = {k: IntervalIndex(v) for k, v in policies.items()}
    widths = config.get("widths", list(range(4, 21)))
    def opportunity_rows():
        for r in promoters:
            chrom, a, b = r["seqid"], r["start"], r["end"]
            for policy, index in indexes.items():
                data = bytearray(sequences[chrom][a:b].upper(), "ascii")
                masked = index.clip(chrom, a, b)
                for _, x, y in masked:
                    data[x-a:y-a] = b"N" * (y-x)
                runs = [len(m.group()) for m in re.finditer(b"[ACGT]+", data)]
                yield dict(gene_id=r["gene_id"], seqid=chrom, start=a, end=b, policy=policy, length=b-a,
                           masked_bp=bp(masked), mask_fraction=bp(masked)/(b-a) if b>a else None,
                           **{f"valid_windows_w{w}": sum(max(0, n-w+1) for n in runs) for w in widths})
    table(dest / "promoter_opportunities.tsv", opportunity_rows(), ["gene_id", "seqid", "start", "end", "policy", "length", "masked_bp", "mask_fraction"] + [f"valid_windows_w{w}" for w in widths])
    summary = dict(reference=refinfo, promoters=len(promoters), promoter_mode=promoter_mode,
                   window_count="genomic positions; multiply by two only for strand-specific scoring opportunities",
                   family_recovery="not_evaluated_without_curated_consensus_benchmark", automatic_winner=False)
    write_json(dest / "evaluation.json", summary)
    return summary


def compare_branches(c, s, prepared, out, branches, sources=None):
    manifest = read_json(Path(prepared) / "manifest.json")
    areas, _, _ = scopes(s, manifest, c.get("evaluation", {}))
    sources = out if sources is None else Path(sources)
    tracks = {b: prediction_tracks(tsv(sources / b / "mask_sources.tsv")) for b in branches}
    rows = []
    differences = out / "differences"; differences.mkdir(exist_ok=True)
    for left, right in itertools.combinations(branches, 2):
        for region_name, region in areas.items():
            for category in sorted(tracks[left].keys() | tracks[right].keys()):
                a, b = (intersect(tracks[x].get(category, []), region) for x in (left, right))
                shared = bp(intersect(a, b)); au, bu = bp(a), bp(b)
                rows.append(dict(left=left, right=right, region=region_name, category=category,
                                 left_bp=au, right_bp=bu, shared_bp=shared, left_only_bp=au-shared,
                                 right_only_bp=bu-shared, jaccard=shared/(au+bu-shared) if au+bu-shared else None))
        a, b = tracks[left]["total_te"], tracks[right]["total_te"]
        bed_write(differences / f"{left}__vs__{right}.left_only.bed", subtract(a, b))
        bed_write(differences / f"{left}__vs__{right}.right_only.bed", subtract(b, a))
    table(out / "branch_discordance.tsv", rows, ["left", "right", "region", "category", "left_bp", "right_bp", "shared_bp", "left_only_bp", "right_only_bp", "jaccard"])
    layers = coverage_layers(sources, branches, output=out)
    result = dict(status="computed_awaiting_biological_review", branches=branches, selected_branch=None,
                  fixture_only=bool(c.get("fixture_only")), accuracy_claim=False,
                  interpretation="Pairwise reference/coverage differences are descriptive, not proof of accuracy or causal attribution")
    result.update(mapping_version=MAPPING_VERSION, coverage_layers=layers)
    write_json(out / "comparison.json", result)
    return result


def coverage_layers(out, branches, output=None):
    """Count unions, never sums of overlapping layers. Also works on old exports."""
    out = Path(out)
    rows = []
    tracks = dict(te='te.mask.bed', unknown='repeat_unknown.bed', non_te='non_te.bed',
                  tandem='tandem_repeat.bed', low_complexity='low_complexity.bed')
    for branch in branches:
        folder = out / branch
        qc = read_json(folder / 'qc.json')
        data = {k:bed(folder / name) for k,name in tracks.items()}
        row = dict(branch=branch, selected_genome_bp=qc['total_bp'], acgt_bp=qc['acgt_bp'])
        row.update({k+'_bp':bp(v) for k,v in data.items()})
        row['interspersed_incl_unknown_bp'] = bp(data['te'] + data['unknown'])
        row['repeat_mask_bp'] = bp(bed(folder/'repeat.mask.bed'))
        row['all_interspersed_mask_bp'] = bp(data['te'] + data['unknown'] + data['tandem'] + data['low_complexity'])
        for key,value in list(row.items()):
            if key.endswith('_bp') and key not in ('selected_genome_bp','acgt_bp'):
                row[key.removesuffix('_bp')+'_bp_per_acgt_bp'] = value / row['acgt_bp'] if row['acgt_bp'] else None
                row[key.removesuffix('_bp')+'_fraction_of_genome'] = value / row['selected_genome_bp'] if row['selected_genome_bp'] else None
        rows.append(row)
    if rows:
        table(Path(output or out)/'coverage_layers.tsv', rows, list(rows[0]))
    return rows
