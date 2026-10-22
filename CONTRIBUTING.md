# Contributing

Read [EXTENDING](docs/EXTENDING.md) before changing adapters or data contracts. Use a focused branch and describe the concrete behavior change, its evidence, validation scope and compatibility implications.

```bash
python -m pip install '.[dev]'
python -m unittest discover -s tests -v
# Linux: actual scheduler with mock upstream tools
python -m pip install '.[engine]'
python tests/integration_cli.py
python tests/integration_v02.py
python -m build
python -m twine check dist/*
```

Tests must not require private data, large downloads or whole-genome discovery. Add a small fixture that exercises the affected contract rather than asserting implementation details. Tests that invoke real tools must be explicit and document required versions. Keep full alignments, genomes, databases, containers, environment directories and local configuration outside Git.

Preserve old frozen runs. Do not relax hashes, remove failure evidence, change a tool version requirement to hide an error, or treat a valid empty discovery result as a crash. Changing workflow recipes changes the source fingerprint and requires a new run. Cite published methods and respect their licenses separately from this wrapper's MIT license.

Issue reports should contain package/tool versions, command, observed/expected behavior and a minimal log excerpt. A compact `pack-feedback` archive is useful after reviewing paths, IDs and logs for sharing suitability. Release preparation is described in [GITHUB_RELEASE](docs/GITHUB_RELEASE.md).
