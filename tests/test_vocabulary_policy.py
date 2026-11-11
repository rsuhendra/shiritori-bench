"""Regression tests for mixed standalone-noun/suffix JMdict senses."""
import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest
import xml.etree.ElementTree as ET

from shiritori_bench.referee import Referee

spec = importlib.util.spec_from_file_location('vocabulary_policy',
    Path(__file__).resolve().parents[1] / 'scripts/build_vocabulary.py')
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


def entry(senses):
    return ET.fromstring('<entry><ent_seq>1524860</ent_seq><k_ele><keb>枕</keb></k_ele>'
        '<r_ele><reb>まくら</reb><re_pri>ichi1</re_pri></r_ele>' + senses + '</entry>')


class VocabularyPolicyTests(unittest.TestCase):
    def test_mixed_noun_suffix_is_accepted(self):
        e = entry('<sense><pos>noun (common) (futsuumeishi)</pos>'
                  '<pos>noun, used as a suffix</pos><gloss>pillow</gloss></sense>')
        self.assertEqual(len(policy.eligible_senses(e, 'まくら', {'枕'})), 1)

    def test_suffix_only_is_still_excluded(self):
        e = entry('<sense><pos>noun, used as a suffix</pos><gloss>suffix</gloss></sense>')
        self.assertEqual(policy.eligible_senses(e, 'まくら', {'枕'}), [])

    def test_other_exclusions_are_unchanged(self):
        for label in ('archaic', 'obsolete', 'abbreviation', 'proper noun', 'prefix', 'counter'):
            e = entry('<sense><pos>noun (common) (futsuumeishi)</pos>'
                      '<pos>noun, used as a suffix</pos><misc>' + label + '</misc></sense>')
            self.assertEqual(policy.eligible_senses(e, 'まくら', {'枕'}), [])

    def test_pos_inheritance_and_reading_restrictions_preserved(self):
        e = entry('<sense><pos>noun (common) (futsuumeishi)</pos><pos>noun, used as a suffix</pos>'
                  '<stagr>other</stagr></sense><sense><gloss>pillow</gloss></sense>')
        self.assertEqual(len(policy.eligible_senses(e, 'まくら', {'枕'})), 1)

    def test_suffix_only_sense_does_not_inherit_previous_standalone_status(self):
        e = entry('<sense><pos>noun (common) (futsuumeishi)</pos></sense>'
                  '<sense><pos>noun, used as a suffix</pos></sense>')
        self.assertEqual(len(policy.eligible_senses(e, 'まくら', {'枕'})), 1)

    def test_built_database_accepts_makura_and_records_policy_version(self):
        with tempfile.TemporaryDirectory() as folder:
            source, database = Path(folder) / 'source.xml', Path(folder) / 'words.sqlite'
            root = ET.Element('JMdict')
            root.append(entry('<sense><pos>noun (common) (futsuumeishi)</pos>'
                              '<pos>noun, used as a suffix</pos><gloss>pillow</gloss></sense>'))
            ET.ElementTree(root).write(source, encoding='utf-8')
            for common_only in (False, True):
                policy.build(source, database, common_only=common_only)
                referee = Referee(str(database))
                try:
                    self.assertEqual(referee.validate('まくら', 'ま', set()).outcome, 'VALID')
                finally:
                    referee.close()
                with sqlite3.connect(database) as c:
                    self.assertEqual(c.execute("select value from metadata where key='filter_version'").fetchone()[0], 'noun-v3')
