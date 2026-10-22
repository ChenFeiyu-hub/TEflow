"""Independent local boundary audit commands; no changes to annotation DAG."""
from .common import read_json
from .boundary_review import prepare, plan, execute, pack


def add_commands(sub):
    p=sub.add_parser('boundary-prepare',help='Freeze explicitly selected loci; no TE discovery')
    for key in ('genome','loci','output'): p.add_argument('--'+key,required=True)
    p.add_argument('--annotation'); p.add_argument('--tools',help='JSON of argv lists and optional expected_version')
    p.add_argument('--flank',type=int,default=500); p.add_argument('--terminal',type=int,default=100)
    p.add_argument('--msa-group',action='append',default=[])
    p.add_argument('--dust-sensitivity',action='store_true',help='Also run DUST-disabled diagnostic; does not change primary analysis')
    p.add_argument('--evidence',action='append',default=[],help='Hash an upstream selection evidence file')
    for name in ('boundary-plan','boundary-run','boundary-pack'):
        p=sub.add_parser(name); p.add_argument('--review',required=True)
        if name=='boundary-pack': p.add_argument('--output',required=True)
        else: p.add_argument('--threads',type=int,default=1)
        if name=='boundary-run': p.add_argument('--timeout',type=int,default=3600)


def dispatch(args):
    if args.action=='boundary-prepare':
        return prepare(args.genome,args.loci,args.output,args.annotation,args.flank,args.terminal,
                       read_json(args.tools) if args.tools else None,args.msa_group,args.evidence,args.dust_sensitivity)
    if args.action=='boundary-plan': return plan(args.review,args.threads)
    if args.action=='boundary-run': return execute(args.review,args.threads,args.timeout)
    if args.action=='boundary-pack': return pack(args.review,args.output)
