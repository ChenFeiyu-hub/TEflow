# GitHub repository and release process

Repository: [ChenFeiyu-hub/TEflow](https://github.com/ChenFeiyu-hub/TEflow). **1.0.0** is the single-species public interface milestone. Citation author Feiyu Chen and ORCID are confirmed in `CITATION.cff`. Upstream publications/licenses remain separate. No DOI or PyPI publication is assumed.

The current **1.1.0rc1** candidate packages TIR-Learner v4 CPU with an explicit v3 backup. Use [its validation record](TEST_STATUS_v1.1.md) and [server feedback review](TIR4_SERVER_REVIEW_2026-11-08_zh.md). Bounded target-server adapter acceptance passed on 2026-11-08; distinguish it from the earlier experimental whole-genome completion and from a future genome run through the production adapter. The GitHub source includes the subsequent evidence in its validation metadata; the delivered rc1 archive remains an unchanged snapshot. Use the Git commit to identify the source revision. The earlier multi-species “1.1” plan is still future work.

Use this directory as the repository root, not the surrounding research workspace. Source includes code, recipes, small fixtures, documentation and CI; exclude genomes, feedback archives, databases, containers, installed environments and run state. Historical repair documents are references. New installation follows `INSTALL.md`; TIR backend acceptance follows `SERVER_TIR4_v1.1_zh.md`.

Release checklist:

1. Review the complete file list, secret/private-data exclusions, naming, author metadata and version. Preserve old frozen source/configurations and output directories.
2. Run portable units and Linux scheduler fixtures, including failure, scoped cancellation/resume, branch concurrency and explicit result selection. Build wheel/sdist; test the installed wheel outside the checkout and compare payload bytes. See `TEST_STATUS_v1.1.md` for completed checks and remaining evidence gaps.
3. Synchronize the reviewed source with GitHub and inspect Actions for the exact uploaded commit. A workflow file alone is not evidence of a successful remote run. CI builds distributions; it does not publish releases or PyPI packages automatically.
4. Tag only the intended tested commit. Any later code/recipe change requires its own validation and version/run compatibility decision. Keep release notes clear about real-genome evidence versus mocks.

The optional source inventory lists paths/sizes only; it is not a checksum gate. The production memory monitor does not enforce cgroups, and independent roots are not a host-wide scheduler. Historic systemd B2 success and unproven strict B3/logout are separate evidence sets. No production hard-limit or multi-species capability is certified by GitHub CI.

The next biological evidence should come from audits/reference replays and additional species under a separate validation plan. A first GitHub release does not require rerunning the completed Arabidopsis genome analysis.
