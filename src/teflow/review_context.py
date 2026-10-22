"""Annotation and locus evidence; no TE/gene truth labels are inferred here."""
from collections import defaultdict
from .common import WorkflowError, fasta_write_record, table
from .evaluation import bp, intersect, tsv
from .formats import union
from .inputs import annotation_rows
from .library_qc import revcomp


def annotation_models(path, genome):
    """Resolve GTF gene_id/transcript_id and GFF3 Parent chains, including isoforms."""
    genes, parents, cds, exons = {}, {}, [], []
    for chrom, kind, a, b, strand, phase, at in annotation_rows(path):
        if chrom not in genome.lengths or not 1 <= a <= b <= genome.lengths[chrom]:
            raise WorkflowError("Annotation coordinates do not match genome: " + chrom)
        rid = at.get("ID")
        if rid and at.get("Parent"): parents[rid] = at["Parent"].split(",")
        gid = at.get("gene_id") or (rid if kind in ("gene", "pseudogene") else None)
        if kind in ("gene", "pseudogene") and gid:
            if gid in genes: raise WorkflowError("Duplicate annotation gene ID: " + gid)
            genes[gid] = dict(gene_id=gid, seqid=chrom, start=a-1, end=b, strand=strand,
                              biotype=at.get("gene_biotype", at.get("gene_type", at.get("biotype", "unreported"))))
        if kind in ("CDS", "exon"):
            (cds if kind == "CDS" else exons).append((chrom, a-1, b, strand, at))
    def ancestors(node, seen=None):
        if node in genes: return {node}
        seen = set() if seen is None else set(seen)
        if node in seen: raise WorkflowError("Cycle in annotation parents: " + node)
        seen.add(node)
        return set().union(*(ancestors(p, seen) for p in parents.get(node, [])))
    coding, transcripts, exon_map = defaultdict(list), defaultdict(list), defaultdict(list)
    unresolved = 0
    for kind, entries in (("CDS", cds), ("exon", exons)):
        for chrom, a, b, strand, at in entries:
            tids = [at["transcript_id"]] if at.get("transcript_id") else at.get("Parent", "").split(",")
            gids = {at["gene_id"]} if at.get("gene_id") else set().union(*(ancestors(t) for t in tids))
            if not gids:
                unresolved += 1; continue
            for gid in gids:
                if gid not in genes:
                    genes[gid] = dict(gene_id=gid, seqid=chrom, start=a, end=b, strand=strand,
                                      biotype="inferred_extent_from_features")
                g = genes[gid]
                if g["seqid"] != chrom or g["strand"] != strand:
                    raise WorkflowError("Inconsistent gene coordinates: " + gid)
                g["start"] = min(g["start"], a); g["end"] = max(g["end"], b)
                if kind == "CDS": coding[gid].append((chrom, a, b))
                for tid in tids:
                    if kind == "CDS": transcripts[(gid, tid or "unreported")].append((chrom, a, b))
                    else: exon_map[(gid, tid or "unreported")].append((chrom, a, b))
    return dict(genes=genes, cds={k: union(v) for k, v in coding.items()},
                transcripts={k: union(v) for k, v in transcripts.items()},
                exons={k: union(v) for k, v in exon_map.items()}, unresolved_features=unresolved)


def native_loci(paths, selected, library, genome, aliases):
    """Trace exact/RC combined-library parents to HELIANO native representatives.

    A consensus-to-native subfamily relationship is not an exact locus mapping.
    Generic callers can supply native_loci.tsv with family_id/seqid/start/end/strand.
    """
    if paths.get("native_loci"):
        rows = tsv(paths["native_loci"])
    elif paths.get("native_sites") and paths.get("native_parents"):
        sites = {r["native_id"]: r for r in tsv(paths["native_sites"])}
        pmap = defaultdict(list)
        for r in tsv(paths["native_parents"]): pmap[r["family_id"]].append(r)
        parent_map = defaultdict(list)
        if paths.get("combined_parents"):
            for r in tsv(paths["combined_parents"]):
                if r["parent_branch"] == "heliano": parent_map[r["family_id"]].append(r["parent_family_id"])
        else:
            for fid in selected: parent_map[fid].append(fid)
        rows = []
        for fid in selected:
            for pid in parent_map[fid]:
                for r in pmap[pid]:
                    if r["relation"] != "native_sequence": continue
                    if r["native_id"] not in sites: raise WorkflowError("Native parent has no coordinate record")
                    site = sites[r["native_id"]]
                    rows.append(dict(site, family_id=fid, parent_family_id=pid))
    else:
        return []
    loci = []
    for row in rows:
        fid = row["family_id"]
        if fid not in selected: continue
        c = aliases.get(row["seqid"], row["seqid"]); a, b = int(row["start"]), int(row["end"])
        strand = row["strand"]
        if c not in genome.lengths or not 0 <= a < b <= genome.lengths[c] or strand not in ("+", "-"):
            raise WorkflowError("Invalid native locus: " + fid)
        seq = library[fid] if strand == "+" else revcomp(library[fid])
        if not any(x != "N" for x in seq):
            raise WorkflowError("Native locus has no non-N sequence to verify: " + fid)
        reference = genome[c][a:b]
        # Combined libraries may retain an RC-equivalent representative.
        matching = [s for s in (seq, revcomp(seq)) if len(s) == b-a and
                    all(x == "N" or x == y for x, y in zip(s, reference))]
        if not matching:
            raise WorkflowError("Native non-N sequence does not match frozen genome: " + fid)
        loci.append(dict(family_id=fid, seqid=c, start=a, end=b, strand=strand,
                         locus_id=f"native{len(loci)+1:05d}", source="verified_native_representative",
                         alignment_id="", native_id=row.get("native_id", ""), parent_family_id=row.get("parent_family_id", fid),
                         sequence_evidence="nonN_equal_reference_allowing_exact_RC_alias"))
    return loci


def locus_context(loci, genome, annotation, output, flank):
    model = annotation_models(annotation, genome) if annotation else None
    genes = list(model["genes"].values()) if model else []
    gene_rows, tx_rows, contexts = [], [], []
    family_dir = output / "boundary_inputs"; family_dir.mkdir()
    family_paths = {}
    with (output / "locus_flanks.fa").open("w", encoding="ascii") as handle:
        for locus in loci:
            c, a, b = locus["seqid"], locus["start"], locus["end"]
            lo, hi = max(0, a-flank), min(genome.lengths[c], b+flank)
            sequence = genome[c][lo:hi]
            if locus["strand"] == "-": sequence = revcomp(sequence)
            fasta_write_record(handle, locus["locus_id"], sequence)
            # Numeric filenames avoid using caller-supplied family IDs as paths.
            fid = locus["family_id"]
            if fid not in family_paths: family_paths[fid] = family_dir / f"family{len(family_paths)+1:05d}.fa"
            with family_paths[fid].open("a", encoding="ascii") as family_file:
                fasta_write_record(family_file, locus["locus_id"], sequence)
            span = [(c, a, b)]; overlapping = [g for g in genes if g["seqid"] == c and g["start"] < b and g["end"] > a]
            contained, cds_union = [], []
            for g in overlapping:
                gid = g["gene_id"]; coding = model["cds"].get(gid, [])
                overlap = intersect(span, coding); cds_union.extend(overlap)
                full = bool(coding) and bp(overlap) == bp(coding)
                if full: contained.append(gid)
                gene_rows.append(dict(locus_id=locus["locus_id"], family_id=locus["family_id"], **g,
                                      gene_CDS_bp=bp(coding), overlapping_CDS_bp=bp(overlap), contains_entire_annotated_CDS_union=full))
                for (gene, tid), tx in model["transcripts"].items():
                    if gene != gid: continue
                    ov = bp(intersect(tx, span))
                    tx_rows.append(dict(locus_id=locus["locus_id"], family_id=locus["family_id"], gene_id=gid,
                                        transcript_id=tid, transcript_CDS_bp=bp(tx), overlapping_CDS_bp=ov,
                                        CDS_segments=len(tx), exon_segments=len(model["exons"].get((gene, tid), [])),
                                        contains_entire_annotated_CDS=bool(tx) and ov == bp(tx)))
            contexts.append(dict(locus, extracted_start=lo, extracted_end=hi, requested_flank=flank,
                                 left_flank_available=a-lo, right_flank_available=hi-b, fasta_orientation="locus_strand",
                                 overlapping_genes=";".join(g["gene_id"] for g in overlapping) if model else "not_evaluated",
                                 overlapping_CDS_union_bp=bp(cds_union) if model else None,
                                 genes_with_entire_CDS_union=";".join(contained) if model else "not_evaluated",
                                 annotation_status="provided_descriptive_only" if model else "not_provided"))
    fields = ["locus_id", "family_id", "source", "seqid", "start", "end", "strand", "native_id", "parent_family_id",
              "alignment_id", "sequence_evidence", "extracted_start", "extracted_end", "requested_flank", "left_flank_available",
              "right_flank_available", "fasta_orientation", "overlapping_genes", "overlapping_CDS_union_bp",
              "genes_with_entire_CDS_union", "annotation_status"]
    table(output / "loci.tsv", contexts, fields)
    table(output / "locus_genes.tsv", gene_rows, ["locus_id", "family_id", "gene_id", "seqid", "start", "end", "strand", "biotype",
          "gene_CDS_bp", "overlapping_CDS_bp", "contains_entire_annotated_CDS_union"])
    table(output / "locus_transcripts.tsv", tx_rows, ["locus_id", "family_id", "gene_id", "transcript_id", "transcript_CDS_bp",
          "overlapping_CDS_bp", "CDS_segments", "exon_segments", "contains_entire_annotated_CDS"])
    table(output / "boundary_inputs.tsv", [dict(family_id=k, fasta=str(v.relative_to(output)).replace("\\", "/"),
          records=sum(r["family_id"] == k for r in loci), interpretation="local_alignment_input_not_validated_copy_boundaries")
          for k, v in family_paths.items()], ["family_id", "fasta", "records", "interpretation"])
    return dict(loci=len(loci), native_loci=sum(r["source"] == "verified_native_representative" for r in loci),
                annotation_status="provided" if model else "not_provided", unresolved_annotation_features=model["unresolved_features"] if model else None)
