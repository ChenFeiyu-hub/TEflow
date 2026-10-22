"""Versioned vocabulary normalization; never reclassifies a sequence or filters a family."""
from .common import WorkflowError

MAPPING_VERSION = '0.3'
# Explicit aliases, with a delimiter boundary for subfamilies. Codes are withheld
# where this vocabulary does not establish a Wicker code.
RULES = (
    ('DNA', ('DTA', 'hAT'), 'TIR', 'DTA'),
    ('DNA', ('DTC', 'CMC', 'CACTA', 'En-Spm'), 'TIR', 'DTC'),
    ('DNA', ('DTH', 'PIF', 'Harbinger', 'Tourist'), 'TIR', 'DTH'),
    ('DNA', ('DTM', 'MULE', 'Mutator'), 'TIR', 'DTM'),
    ('DNA', ('DTT', 'TcMar', 'Tc1', 'Mariner', 'Stowaway'), 'TIR', 'DTT'),
    ('DNA', ('DTE', 'Merlin'), 'TIR', 'DTE'),
    ('DNA', ('DTR', 'Transib'), 'TIR', 'DTR'),
    ('DNA', ('DTP', 'P'), 'TIR', 'DTP'),
    ('DNA', ('DTB', 'PiggyBac'), 'TIR', 'DTB'),
    ('DNA', ('DTX', 'Kolobok', 'Sola', 'Zisupton', 'Academ', 'Ginger',
             'Novosib', 'IS3EU', 'Dada', 'Zator'), 'TIR', 'DTX'),
    ('DNA', ('Crypton',), 'Crypton', 'DYC'),
    ('DNA', ('Maverick', 'Polinton'), 'Maverick', 'DMM'),
    ('DNA', ('Helitron', 'Helentron'), 'Helitron', 'DHH'),
    ('LTR', ('Copia',), 'LTR', 'RLC'),
    ('LTR', ('Gypsy',), 'LTR', 'RLG'),
    ('LTR', ('Pao', 'Bel-Pao'), 'LTR', 'RLB'),
    ('LTR', ('ERV', 'ERV1', 'ERV2', 'ERV3', 'ERVL', 'ERVK', 'ERVL-MaLR'), 'LTR', 'RLE'),
    ('LTR', ('Unknown',), 'LTR', 'RLX'),
    ('LTR', ('DIRS',), 'DIRS', 'RYD'),
    ('LTR', ('Ngaro',), 'DIRS', 'RYN'),
    ('LTR', ('Caulimovirus',), 'pararetrovirus', ''),
    ('LINE', ('L1',), 'LINE', 'RIL'),
    ('LINE', ('RTE',), 'LINE', 'RIT'),
    ('LINE', ('Jockey',), 'LINE', 'RIJ'),
    ('LINE', ('I',), 'LINE', 'RII'),
    ('LINE', ('R2',), 'LINE', 'RIR'),
    ('LINE', ('Unknown',), 'LINE', 'RIX'),
    ('LINE', ('Penelope',), 'PLE', 'RPP'),
    ('SINE', ('tRNA',), 'SINE', 'RST'),
    ('SINE', ('7SL',), 'SINE', 'RSL'),
    ('SINE', ('5S',), 'SINE', 'RSS'),
    ('SINE', ('Unknown',), 'SINE', 'RSX'),
    ('PLE', ('Penelope',), 'PLE', 'RPP'),
)
TE_ROOTS = {'dna', 'mite', 'ltr', 'line', 'sine', 'rc', 'retroposon', 'ple', 'dirs',
            'crypton', 'replitron', 'maverick', 'penelope', 'helitron', 'helentron'}
NON_TE = {'simple_repeat', 'low_complexity', 'satellite', 'rrna', 'trna', 'rna', 'scrna', 'snrna', 'srprna'}
UNKNOWN = {'unknown', 'unclassified', 'unspecified'}


def _matches(value, alias):
    value, alias = value.casefold(), alias.casefold()
    return value == alias or any(value.startswith(alias + sep) for sep in ('-', '/', '_'))


def classify(raw):
    clean = raw.strip().rstrip('?')
    root, _, sub = clean.partition('/')
    root_key = root.casefold().rstrip('?')
    result = dict(mapping_version=MAPPING_VERSION, classification_uncertain='?' in raw,
                  structural_label='MITE' if root_key == 'mite' else '',
                  order='', superfamily_code='', mapping_status='mapped')
    if root_key in UNKNOWN:
        return dict(result, tier='unknown', standard_class='unknown')
    if root_key in NON_TE:
        return dict(result, tier='non_te', standard_class='non_te')
    if root_key not in TE_ROOTS:
        raise WorkflowError('Unrecognized classification root (not biological Unknown): ' + raw)
    if root_key in ('rc', 'helitron', 'helentron'):
        return dict(result, tier='te', standard_class='HLE', order='Helitron', superfamily_code='DHH')
    matched = []
    for category, aliases, order, code in RULES:
        if category.casefold() == ('dna' if root_key == 'mite' else root_key) and any(_matches(sub, a) for a in aliases):
            matched.append((order, code))
    # Multiple aliases within an order can legitimately match a more specific label.
    if len(set(matched)) > 1:
        raise WorkflowError('Ambiguous classification mapping: ' + raw)
    order, code = matched[0] if matched else ('TIR' if root_key == 'mite' else root.upper(), '')
    category = ('HLE' if order == 'Helitron' else
                'TIR_MITE' if root_key == 'mite' or (root_key == 'dna' and order == 'TIR') else
                'DNA_other' if root_key == 'dna' else root.upper())
    return dict(result, tier='te', standard_class=category, order=order, superfamily_code=code,
                mapping_status='mapped' if matched or root_key == 'mite' else 'root_only')


def tier(raw):
    return classify(raw)['tier']


def standard_class(raw):
    return classify(raw)['standard_class']
