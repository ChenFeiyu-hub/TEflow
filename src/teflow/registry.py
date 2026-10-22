"""Declarative branch dependencies and execution hints, shared by plan and adapters."""
from dataclasses import dataclass


@dataclass(frozen=True)
class BranchSpec:
    name: str
    library_stage: str
    rm_stage: str
    prefix: str
    requires: tuple = ()
    library_parents: tuple = ()
    tools: tuple = ()


BRANCH_SPECS = (
    BranchSpec('edta','edta','rm_edta','E',tools=('edta',)),
    BranchSpec('edta_tetrimmer','tetrimmer','rm_refined','T',('edta',),('edta',),('tetrimmer',)),
    BranchSpec('heliano','heliano','rm_heliano','H',('edta',),('edta','qc_edta'),('heliano','heliano_cons')),
    BranchSpec('hite','hite','rm_hite','I',tools=('hite',)),
    BranchSpec('edta_plus_heliano','edta_plus_heliano','rm_edta_plus_heliano','EH',('edta','heliano'),('edta','heliano','qc_heliano')),
    BranchSpec('reference_only','reference_only','rm_reference_only','R'),
    BranchSpec('reference_plus_edta','reference_plus_edta','rm_reference_plus_edta','RE',('reference_only','edta'),('reference_only','edta')),
)
BRANCH_BY_NAME = {b.name:b for b in BRANCH_SPECS}
TOOL_PROBES = {
    'edta': (['--help'], (0,1)), 'tetrimmer': (['--version'], (0,)),
    'repeatmasker': (['-v'], (0,)), 'trf': (['-v'], (0,1,255)),
    'dustmasker': (['-version'], (0,)), 'heliano': (['-v'], (0,)),
    'heliano_cons': (['-v'], (0,)), 'hite': (['--help'], (0,)),
    'diamond': (['version'], (0,)), 'hmmscan': (['-h'], (0,)),
}


def stage_kind(stage):
    if stage in ('prepared', 'tracks'): return stage
    if stage.startswith('export'): return 'export'
    if stage.startswith('qc_'): return 'qc'
    if stage.startswith('rm_'): return 'repeatmasker'
    if stage in ('edta','tetrimmer','heliano','hite'): return stage
    return 'assembly'
