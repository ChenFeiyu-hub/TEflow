"""Portable files, strict configuration and content fingerprints."""
from __future__ import annotations
import csv
import gzip
import hashlib
import json
import os
import re
import tempfile
import sqlite3
import warnings
from datetime import datetime, timezone
from pathlib import Path

DNA = frozenset("ACGTRYSWKMBDHVN")
ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")


class WorkflowError(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


_FILE_HASHES = {}
HASH_METRICS = dict(bytes_read=0, memory_hits=0, disk_hits=0)


def file_stamp(path):
    s = Path(path).stat()
    return dict(size=s.st_size,mtime_ns=s.st_mtime_ns,ctime_ns=s.st_ctime_ns,device=s.st_dev,inode=s.st_ino)


def sha256(path):
    """Internal identity, cached by file metadata; not a release/upload acceptance gate.

    The optional local SQLite cache is a performance cache, not an adversarial
    integrity guarantee. Downloads use their independently pinned checksums.
    """
    path = str(Path(path).resolve())
    stamp = file_stamp(path)
    key = json.dumps([path,stamp],sort_keys=True)
    if key in _FILE_HASHES:
        HASH_METRICS['memory_hits'] += 1
        return _FILE_HASHES[key]
    cache = os.environ.get('TEFLOW_IDENTITY_CACHE') if stamp['size'] >= 1024*1024 else None
    db = None
    if cache:
        try:
            Path(cache).parent.mkdir(parents=True,exist_ok=True)
            db = sqlite3.connect(cache,timeout=1)
            db.execute('CREATE TABLE IF NOT EXISTS identity_cache (key TEXT PRIMARY KEY, digest TEXT NOT NULL)')
            row = db.execute('SELECT digest FROM identity_cache WHERE key=?',(key,)).fetchone()
            if row and isinstance(row[0], str) and re.fullmatch(r'[0-9a-f]{64}', row[0]):
                db.close()
                HASH_METRICS['disk_hits'] += 1
                _FILE_HASHES[key] = row[0]
                return row[0]
        except (sqlite3.Error, OSError) as exc:
            if db: db.close()
            db = None
            warnings.warn('Identity cache unavailable; reading file directly: ' + str(exc), RuntimeWarning)
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(1024 * 1024), b""):
                HASH_METRICS['bytes_read'] += len(block)
                h.update(block)
        if file_stamp(path) != stamp:
            raise WorkflowError('File changed while reading identity: '+path)
        value = h.hexdigest()
        _FILE_HASHES[key] = value
        if db:
            try:
                db.execute('INSERT OR REPLACE INTO identity_cache VALUES (?,?)',(key,value)); db.commit()
            except sqlite3.Error as exc:
                warnings.warn('Identity cache write failed; computed identity retained: ' + str(exc), RuntimeWarning)
        return value
    finally:
        if db: db.close()


def digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, allow_nan=False)
            f.write("\n")
        os.replace(tmp, path)
    finally:
        if Path(tmp).exists():
            Path(tmp).unlink()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def text_open(path):
    return gzip.open(path, "rt", encoding="utf-8-sig") if str(path).endswith(".gz") else open(path, encoding="utf-8-sig")


def fasta(path, allow_empty=False):
    seen, key, chunks = set(), None, []
    with text_open(path) as f:
        for line_no, raw in enumerate(f, 1):
            line = raw.strip()
            if not line:
                continue
            if line.startswith(">"):
                if key is not None:
                    if not chunks:
                        raise WorkflowError(f"Empty FASTA record: {key}")
                    yield key, "".join(chunks)
                fields = line[1:].split()
                if not fields or fields[0] in seen:
                    raise WorkflowError(f"Empty/duplicate FASTA ID at {path}:{line_no}")
                key, chunks = fields[0], []
                seen.add(key)
            else:
                if key is None or not set(line.upper()) <= DNA:
                    raise WorkflowError(f"Invalid DNA FASTA at {path}:{line_no}")
                chunks.append(line)
    if key is not None:
        if not chunks:
            raise WorkflowError(f"Empty FASTA record: {key}")
        yield key, "".join(chunks)
    elif not allow_empty:
        raise WorkflowError(f"No FASTA records: {path}")


def fasta_write_record(f, name, seq):
    f.write(">" + name + "\n")
    for i in range(0, len(seq), 80):
        f.write(seq[i:i + 80] + "\n")


def table(path, rows, fields):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fields, delimiter="\t", lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def source_fingerprint():
    from .assets import recipe_files
    root = Path(__file__).parent
    hashes = {p.relative_to(root).as_posix(): sha256(p) for p in sorted(root.rglob("*.py"))
              if "_assets" not in p.relative_to(root).parts}
    hashes.update({name: sha256(p) for name, p in recipe_files().items()})
    return digest(hashes)


def load_config(path):
    path = Path(path).resolve()
    c = read_json(path)
    required = {"schema_version", "run_id", "work_root", "results_root", "samples", "tools", "execution", "parameters"}
    if not isinstance(c, dict) or not required <= c.keys() or c["schema_version"] not in (1, 2):
        raise WorkflowError("Expected configuration schema_version=1 or 2 with all required fields")
    unknown = c.keys() - required - {"databases", "fixture_only", "description", "branches", "qc", "evaluation", "exports"}
    if c["schema_version"] == 1 and any(k in c for k in ("branches", "qc", "evaluation")):
        raise WorkflowError("Branch/QC options require an explicit migration to schema 2")
    if unknown:
        raise WorkflowError("Unknown configuration fields: " + ", ".join(sorted(unknown)))
    if not ID.fullmatch(c["run_id"]):
        raise WorkflowError("Unsafe run_id")
    def resolve(value):
        p = Path(value).expanduser()
        return str((path.parent / p).resolve()) if not p.is_absolute() else str(p.resolve())
    for key in ("work_root", "results_root"):
        c[key] = resolve(c[key])
    if c["work_root"] == c["results_root"]:
        raise WorkflowError("work_root and results_root must differ")
    ids = set()
    for s in c["samples"]:
        if not ID.fullmatch(s.get("id", "")) or s["id"] in ids:
            raise WorkflowError("Unsafe or duplicate sample ID")
        ids.add(s["id"])
        if s.get('taxon_group', 'plant') not in ('plant', 'metazoa', 'fungi', 'other'):
            raise WorkflowError('sample.taxon_group must be plant/metazoa/fungi/other')
        for k in ("genome", "annotation", "cds", "reference_library", "reference_te", "promoters_bed"):
            if s.get(k):
                s[k] = resolve(s[k])
        if not s.get("genome"):
            raise WorkflowError("Every sample needs a genome")
        if len(s.get("exclude_seqids", [])) != len(set(s.get("exclude_seqids", []))):
            raise WorkflowError("Duplicate exclude_seqids")
    if not ids:
        raise WorkflowError("No samples")
    exports = c.get('exports', {})
    policies = exports.get('softmask_policies', ['te_primary']) if isinstance(exports, dict) else None
    if (not isinstance(exports, dict) or set(exports) - {'softmask_policies'} or
        not isinstance(policies, list) or not policies or any(p not in ('te_primary', 'all_interspersed') for p in policies)
        or len(policies) != len(set(policies))):
        raise WorkflowError('exports.softmask_policies must be a unique nonempty list of te_primary/all_interspersed')
    e = c["execution"]
    if e.get("mode") not in ("local_check", "server", "fixture"):
        raise WorkflowError("execution.mode must be local_check/server/fixture")
    for k in ("threads", "mem_mb"):
        if type(e.get(k)) is not int or e[k] < 1:
            raise WorkflowError(f"execution.{k} must be a positive integer")
    if e["mode"] == "local_check" and e["threads"] > 2:
        raise WorkflowError("Local checking is limited to 2 workflow threads")
    if set(c["parameters"]) != {"max_divergence"} or not isinstance(c["parameters"]["max_divergence"], (int, float)) or not 0 <= c["parameters"]["max_divergence"] <= 100:
        raise WorkflowError("parameters currently accepts only max_divergence between 0 and 100")
    if set(e) - {"mode", "threads", "mem_mb", "stage_timeout_seconds", "scheduling"}:
        raise WorkflowError("Unknown execution option")
    if e.get("stage_timeout_seconds") is not None and (type(e["stage_timeout_seconds"]) is not int or e["stage_timeout_seconds"] < 1):
        raise WorkflowError("stage_timeout_seconds must be null or a positive integer")
    from .branches import validate, required_tools
    if c["schema_version"] == 2:
        validate(c)
        for k in ("host_proteins", "te_proteins"):
            if c.get("qc", {}).get(k) and c["qc"][k] != "derived":
                c["qc"][k] = resolve(c["qc"][k])
    from .resources import validate as validate_resources
    validate_resources(c)
    required_t = required_tools(c)
    if required_t - c["tools"].keys():
        raise WorkflowError("Missing tools for enabled branches: " + ", ".join(sorted(required_t - c["tools"].keys())))
    if c["schema_version"] == 1 and set(c["tools"]) != required_t:
        raise WorkflowError("Schema 1 defines exactly the five legacy tools")
    for key, t in c["tools"].items():
        if not isinstance(t.get("command"), list) or not t["command"] or not all(isinstance(x, str) and x for x in t["command"]):
            raise WorkflowError(f"{key}.command must be a nonempty argument array")
        if not t.get("expected_version"):
            raise WorkflowError(f"{key} needs expected_version")
        for k in ("source_root", "lock_file", "image"):
            if t.get(k):
                t[k] = resolve(t[k])
    if c.get("databases", {}).get("pfam_dir"):
        c["databases"]["pfam_dir"] = resolve(c["databases"]["pfam_dir"])
    for d in c.get("databases", {}).get("files", []):
        d["path"] = resolve(d["path"])
    c["_config_path"] = str(path)
    return c


def sample(c, sid):
    for s in c["samples"]:
        if s["id"] == sid:
            return s
    raise WorkflowError("Unknown sample: " + sid)


def work(c, sid):
    return Path(c["work_root"]) / c["run_id"] / sid


def results(c, sid):
    return Path(c["results_root"]) / c["run_id"] / sid


def biological_guard(c):
    if c["execution"]["mode"] != "server":
        raise WorkflowError("Production tools require execution.mode=server. Local checks do not launch EDTA.")
    if os.environ.get("TEFLOW_ALLOW_PRODUCTION") != "1":
        raise WorkflowError("Use teflow run --config CONFIG on the Linux server")
    paths = [c[k] for k in ("work_root", "results_root")]
    if c.get("databases", {}).get("pfam_dir"):
        paths.append(c["databases"]["pfam_dir"])
    for path in paths:
        if re.search(r"[\s;&|`$<>\"'()!?{}\[\]*^]", path):
            raise WorkflowError("Upstream tools need a work/results path without spaces or shell metacharacters")
    if c.get("fixture_only"):
        if sum(len(seq) for s in c["samples"] for _, seq in fasta(s["genome"])) > 100000:
            raise WorkflowError("Synthetic fixture mode is limited to 100 kb across all inputs")
