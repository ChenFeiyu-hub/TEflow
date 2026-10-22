import json
from pathlib import Path
import unittest
from teflow.branches import graph, required_tools, stage_tools


class GoldenBranchContracts(unittest.TestCase):
    def test_pre_v06_branch_and_tool_contracts(self):
        cases = json.loads((Path(__file__).parent/'golden/branch_contracts_v050.json').read_text())
        for row in cases:
            c = row['config']
            with self.subTest(config=c):
                self.assertEqual(graph(c), row['graph'])
                self.assertEqual(sorted(required_tools(c)), row['tools'])
                self.assertEqual({s:sorted(stage_tools(c,s)) for s in graph(c)}, row['stage_tools'])
