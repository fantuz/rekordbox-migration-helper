"""Predefined journeys must name real tools and retain honest capability boundaries."""
import json
from pathlib import Path
import unittest
from journeys import new_plan,update_plan
from journey_templates import TEMPLATES
from documentation import FILES


class JourneyTemplateTests(unittest.TestCase):
    def test_all_guides_have_valid_targets_and_complete_translations(self):
        root=Path(__file__).parent;html=(root/'static/index.html').read_text(encoding='utf-8')
        messages=json.loads((root/'static/locales.json').read_text(encoding='utf-8'))['messages']
        self.assertEqual(len(TEMPLATES),8)
        for kind,template in TEMPLATES.items():
            self.assertIn(template['title'],messages);self.assertIn(template['note'],messages)
            self.assertEqual(len({s['id'] for s in template['steps']}),len(template['steps']))
            for step in template['steps']:
                self.assertIn(step['title'],messages)
                if step['view']:self.assertIn('id="view-'+step['view']+'"',html)
                if step['doc']:self.assertIn(step['doc'],FILES)
                if step['tab']:self.assertIn('data-lab-tab="'+step['tab']+'"',html)

    def test_guided_steps_cannot_claim_automatic_execution_or_foreign_steps(self):
        for kind,template in TEMPLATES.items():
            plan=new_plan(kind,'snapshot:synthetic')
            changed=update_plan(plan,{'step':template['steps'][0]['id'],'status':'confirmed'},lambda _:None)
            self.assertEqual(changed['steps'][template['steps'][0]['id']]['basis'],'user statement')
            self.assertEqual(plan['steps'],{})
            with self.assertRaises(ValueError):update_plan(plan,{'step':'not-in-this-guide','status':'confirmed'},lambda _:None)
            with self.assertRaises(ValueError):update_plan(plan,{'step':template['steps'][0]['id'],'status':'skipped'},lambda _:None)

    def test_reverse_migration_is_explicitly_external_and_sharing_excludes_audio(self):
        self.assertIn('not implemented',TEMPLATES['guide-serato-rb']['note'])
        self.assertIn('outside Workbench',TEMPLATES['guide-serato-rb']['note'])
        self.assertIn('audio files are not included',TEMPLATES['guide-sharing']['note'])

if __name__=='__main__':unittest.main()
