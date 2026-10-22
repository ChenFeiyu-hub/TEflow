"""Distinguish an immutable image release label from its CLI version banner."""
from pathlib import Path
from .common import WorkflowError, sha256

ZENODO_SHA256 = "4776bd6a1c0d8797f0e1e5febe385b157fb36a5de0615b2b7f8818672de74e55"
ZENODO_SIZE = 3674533888
ZENODO_URL = "https://zenodo.org/records/15734031"


def identity_for_digest(path, size, checksum):
    identity = dict(path=str(Path(path).resolve()), bytes=size, sha256=checksum,
                    recognized=False)
    if checksum == ZENODO_SHA256 and size == ZENODO_SIZE:
        identity.update(recognized=True, source=ZENODO_URL,
                        release_label="3.3.3", reported_version="3.3.2",
                        version_note="Official Zenodo image release label differs from CLI banner",
                        source_comparison_scope="Only main.py was compared with Git tag v.3.3.3; it differs solely in version_num. Whole-image source equivalence is not established.")
    return identity


def inspect_image(path, require_known=False):
    path = Path(path).resolve()
    if not path.is_file():
        raise WorkflowError("HiTE image is missing: " + str(path))
    info = identity_for_digest(path, path.stat().st_size, sha256(path))
    if require_known and not info["recognized"]:
        raise WorkflowError("This repair accepts only the verified Zenodo SIF; image checksum/size differs")
    return info


def provenance(c):
    tool = c["tools"]["hite"]
    return dict(cli_version=tool["expected_version"],
                image_identity=tool.get("image_identity"),
                version_basis="configured CLI version checked by doctor; image bytes locked by freeze")
