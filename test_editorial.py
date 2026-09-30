import json
from unittest.mock import patch
import unittest
import test_studio as fixtures
from editorial import prepare, propose
import server as app


class EditorialTests(unittest.TestCase):
    setUp=fixtures.StudioTests.setUp
    tearDown=fixtures.StudioTests.tearDown
    text_book=fixtures.StudioTests.text_book
    def configured(self):
        s=self.s.make_source('Lecture attentive','Auteur','Document',[dict(text='Écouter les questions du lecteur avant de rédiger.',start=0,duration=0,page=2)])
        b=self.text_book();b['source_ids']=[s['id']];b['brief']={'intention':'Écrire un livre utile','reader':'Débutants'}
        return self.s.save_book(b),s

    def test_brief_and_sources_are_versioned_and_isolated(self):
        b,s=self.configured();self.assertEqual(self.s.book()['source_ids'],[s['id']])
        other=self.s.create_book({'title':'Autre'});self.assertNotIn('source_ids',other)
        paths={x['path'] for x in self.s.version(b['_revision'])['changes']};self.assertTrue({'brief','source_ids'}<=paths)

    def test_editorial_proposals_are_grounded_and_do_not_mutate_book(self):
        b,s=self.configured();before=self.s.book()
        result={'paragraphs':[{'text':'Commencer par écouter son lecteur.','evidence_ids':['E1']}],'questions':['Interroger plusieurs lecteurs.']}
        progress=[]
        with patch.object(app,'llm_request',return_value={'choices':[{'message':{'content':json.dumps(result)}}]}) as call:
            p=propose(self.s,{'book_id':b['_book_id'],'chapter_id':'chapter1','mode':'draft'},progress=lambda *x:progress.append(x))
        self.assertEqual(p['evidence'][0]['locator'],'p. 2');self.assertEqual(p['evidence'][0]['source_id'],s['id'])
        self.assertEqual(before,self.s.book());self.assertIn('Écouter les questions',call.call_args.args[1]['messages'][1]['content'])
        self.assertEqual([x[0] for x in progress],['prompt','generation','validation'])
        self.assertEqual(call.call_args.args[1]['max_tokens'],16000)
        self.assertEqual(call.call_args.args[1]['reasoning_effort'],'low')

    def test_background_editorial_job_keeps_result(self):
        b,_=self.configured();job=dict(id='job-test',book_id=b['_book_id'],status='queued',created=app.now())
        result={'mode':'plan','chapters':[]}
        try:
            app.EDITORIAL_JOBS[job['id']]=job
            with patch('editorial.propose',return_value=result):app.run_editorial_job(job,{'book_id':b['_book_id'],'mode':'plan'})
            self.assertEqual(job['status'],'finished');self.assertEqual(job['progress'],100);self.assertEqual(job['result'],result)
            self.assertEqual(app.public_editorial_job(job)['status'],'finished');self.assertNotIn('result',app.public_editorial_job(job))
            self.assertEqual(app.public_editorial_job(job,True)['result'],result)
        finally:
            app.EDITORIAL_JOBS.pop(job['id'],None)
            with app.connect() as c:c.execute("DELETE FROM settings WHERE id='editorial-job:job-test'")

    def test_hallucinated_or_missing_references_are_rejected(self):
        b,s=self.configured()
        for refs in (['E999'],[]):
            result={'paragraphs':[{'text':'Une affirmation','evidence_ids':refs}]}
            with patch.object(app,'llm_request',return_value={'choices':[{'message':{'content':json.dumps(result)}}]}):
                with self.assertRaises(ValueError):propose(self.s,{'book_id':b['_book_id'],'chapter_id':'chapter1','mode':'draft'})

    def test_prepare_requires_own_project_sources(self):
        self.configured();other=self.s.create_book({'title':'Autre'})
        with self.assertRaises(ValueError):prepare(self.s,{'book_id':other['_book_id']})

    def test_generated_block_sources_stay_out_of_the_reading(self):
        b,s=self.configured();b['chapters'][0]['blocks'][0]['source_ids']=[s['id']];b['chapters'][0]['blocks'][0]['text']='Un texte sourcé.'
        b=self.s.save_book(b);sections=self.s.book_sections(b)
        self.assertEqual([x['title'] for x in sections],['Commencer'])
        self.assertNotIn('Sources',sections[0]['blocks'][0]['text'])
        self.assertEqual(self.s.book(b['_book_id'])['chapters'][0]['blocks'][0]['source_ids'],[s['id']])
