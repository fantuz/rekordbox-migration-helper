"""Exercise Hot Cue Bank links in a disposable encrypted Backup Library export."""
from contextlib import closing
import json
from pathlib import Path
from unittest import TestCase
import zipfile

from engine import open_master
from native_export import export_native, mutable_copy, rewrite_archive
import test_export_verification as fixtures


class HotCueBankExportTests(TestCase):
    decisions = {'a~b': {'action': 'merge', 'keeper': 'a'}}

    def setUp(self):
        self.fixture = fixtures.IndependentExportTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()

    def add_banks(self, *, row=None, mirror=None, same_pad=False, same_position=False, cache_only=False):
        fixture = self.fixture
        with closing(mutable_copy(fixture.master)) as db:
            db.executescript("""
                CREATE TABLE djmdSongHotCueBanklist(
                    ID TEXT, HotCueBanklistID TEXT, ContentID TEXT, CueID TEXT, rb_local_deleted INTEGER);
                CREATE TABLE hotCueBanklistCue(
                    ID TEXT, HotCueBanklistID TEXT, Cues TEXT, rb_local_deleted INTEGER);
            """)
            if row:
                db.execute("INSERT INTO djmdSongHotCueBanklist VALUES ('link','bank',?,?,?)", row)
            if mirror:
                db.execute("INSERT INTO hotCueBanklistCue VALUES ('mirror','bank',?,?)", mirror)
            if cache_only:
                db.execute("DELETE FROM djmdCue WHERE ID='cue-b'")
            if same_pad:
                # A manual donor cue on pad A can replace an automatic keeper cue at
                # another time, or lend its label to the keeper cue at the same time.
                fixture.catalog.cues['a'][0]['Comment'] = 'CUE(Auto)'
                fixture.catalog.cues['b'][0]['Kind'] = 1
                if same_position:
                    fixture.catalog.cues['b'][0]['InMsec'] = fixture.catalog.cues['a'][0]['InMsec']
                for identity, cues in fixture.catalog.cues.items():
                    cue = cues[0]
                    db.execute('UPDATE djmdCue SET Kind=?, InMsec=?, Comment=? WHERE ID=?',
                               (cue['Kind'], cue['InMsec'], cue['Comment'], cue['ID']))
                    db.execute('UPDATE contentCue SET Cues=? WHERE ContentID=?', (json.dumps(cues), identity))
            db.commit()
        updated = fixture.root / 'with-banks.zip'
        rewrite_archive(fixture.backup, updated, {'master.db': fixture.master}, lambda *_: None)
        updated.replace(fixture.backup)
        self.source_bytes = fixture.backup.read_bytes(), fixture.xml.read_bytes()

    def assert_held(self, kind='zip'):
        with self.assertRaisesRegex(ValueError, 'Hot Cue Bank'):
            self.fixture.prepare(kind, self.decisions)
        self.assertEqual(list((self.fixture.root / 'exports').iterdir()), [])
        self.assertEqual(self.source_bytes, (self.fixture.backup.read_bytes(), self.fixture.xml.read_bytes()))

    def test_bank_with_retiring_content_id_holds_native_export(self):
        self.add_banks(row=('b', None, 0))
        self.assert_held()

    def test_bank_with_only_reassigned_cue_id_holds_both_exports_atomically(self):
        self.add_banks(row=(None, 'cue-b', 0))
        self.assert_held('pair')

    def test_serialized_bank_can_reference_remapped_cue_without_active_bank_row(self):
        self.add_banks(row=(None, 'cue-b', 1), mirror=('[{"CueID":"cue-b"}]', 0))
        self.assert_held()

    def test_serialized_bank_can_reference_retired_keeper_cue(self):
        self.add_banks(mirror=('[{"ContentID":"a","CueID":"cue-a"}]', 0), same_pad=True)
        self.assert_held()

    def test_recovered_label_of_retained_keeper_cue_needs_bank_review(self):
        self.add_banks(mirror=('[{"CueID":"cue-a","Comment":"CUE(Auto)"}]', 0),
                       same_pad=True, same_position=True)
        self.assert_held()

    def test_source_cue_missing_from_review_cannot_be_retired_while_linked(self):
        self.fixture.catalog.cues['a'].clear()
        self.add_banks(row=(None, 'cue-a', 0))
        self.assert_held()

    def test_only_native_cache_can_establish_orphan_bank_owner(self):
        self.fixture.catalog.cues['b'].clear()
        self.add_banks(mirror=('[{"CueID":"cue-b"}]', 0), cache_only=True)
        self.assert_held()

    def test_invalid_live_mirror_holds_native_merge_but_allows_xml(self):
        self.add_banks(mirror=('{bad json', 0))
        self.assert_held()
        result = self.fixture.prepare('xml', self.decisions)
        self.assertEqual(result['validation']['independent_verification']['status'], 'passed')

    def test_no_duplicate_decision_allows_normal_metadata_copy(self):
        self.add_banks(row=('b', 'cue-b', 0), mirror=('[{"CueID":"cue-b"}]', 0))
        result = self.fixture.prepare('zip')
        self.assertEqual(result['validation']['independent_verification']['status'], 'passed')
        self.assertEqual(self.source_bytes, (self.fixture.backup.read_bytes(), self.fixture.xml.read_bytes()))

    def test_independent_verifier_rejects_an_altered_active_bank_mirror(self):
        self.add_banks(mirror=('[{"CueID":"cue-a"}]', 0))

        def alter_bank(catalog, decisions, relocations, output, progress):
            report = export_native(catalog, decisions, relocations, output, progress)
            changed = self.fixture.root / 'mutated.db'
            with zipfile.ZipFile(output) as archive:
                changed.write_bytes(archive.read('master.db'))
            with closing(mutable_copy(changed)) as db:
                db.execute("UPDATE hotCueBanklistCue SET Cues='[]' WHERE ID='mirror'")
                db.commit()
            rewritten = self.fixture.root / 'mutated.zip'
            rewrite_archive(output, rewritten, {'master.db': changed}, progress)
            rewritten.replace(output)
            return report

        with self.assertRaisesRegex(ValueError, 'Independent ZIP verification'):
            self.fixture.prepare('zip', self.decisions, native_writer=alter_bank)
        self.assertEqual(list((self.fixture.root / 'exports').iterdir()), [])
        self.assertEqual(self.source_bytes, (self.fixture.backup.read_bytes(), self.fixture.xml.read_bytes()))

    def test_unchanged_keeper_cue_and_inactive_donor_mirror_are_preserved(self):
        self.add_banks(row=('a', 'cue-a', 0), mirror=('[{"CueID":"cue-b"}]', 1))
        result = self.fixture.prepare('zip', self.decisions)
        self.assertEqual(result['validation']['independent_verification']['status'], 'passed')
        copied_db = self.fixture.root / 'checked.db'
        with zipfile.ZipFile(Path(result['directory']) / 'edited-library.zip') as archive:
            copied_db.write_bytes(archive.read('master.db'))
        with closing(open_master(copied_db)) as db:
            self.assertEqual(db.execute('SELECT ContentID,CueID FROM djmdSongHotCueBanklist').fetchone(),
                             ('a', 'cue-a'))
            self.assertEqual(db.execute('SELECT Cues,rb_local_deleted FROM hotCueBanklistCue').fetchone(),
                             ('[{"CueID":"cue-b"}]', 1))
        self.assertEqual(self.source_bytes, (self.fixture.backup.read_bytes(), self.fixture.xml.read_bytes()))
