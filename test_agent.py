import json, unittest
from unittest.mock import patch
import test_studio as fixtures
import server as app
import agent


class AgentTests(unittest.TestCase):
    def setUp(self):
        fixtures.StudioTests.setUp(self);app.AGENT_JOBS.clear()
    def tearDown(self):
        app.AGENT_JOBS.clear();fixtures.StudioTests.tearDown(self)

    def test_agent_can_search_and_read_sources(self):
        source=self.s.make_source('Trouver son audience','Alice','Vidéo',[dict(start=12,duration=4,text='Interroger dix clients avant de définir son audience.')])
        found=agent.execute_tool(app,self.s,{'book_id':'book-main'},'search_sources',{'query':'audience clients'})
        self.assertEqual(found[0]['id'],source['id']);self.assertEqual(found[0]['passages'][0]['locator'],'00:12')
        read=agent.execute_tool(app,self.s,{'book_id':'book-main'},'read_source',{'source_id':source['id'],'query':'clients'})
        self.assertIn('dix clients',read['passages'][0]['text'])

    def test_write_action_requires_confirmation_and_versions_book(self):
        thread=agent.create_thread(app,self.s,{'book_id':'book-main'})
        result=agent.execute_tool(app,self.s,thread,'propose_create_chapter',{'title':'Comprendre son audience','purpose':'Partir du terrain'})
        agent.save_thread(app,thread);before=self.s.book()['_revision']
        self.assertEqual(result['status'],'pending_confirmation');self.assertEqual(self.s.book()['chapters'],[])
        applied=agent.apply_action(app,self.s,thread['id'],result['action_id'],True)
        self.assertNotEqual(applied['book']['_revision'],before);self.assertEqual(applied['book']['chapters'][0]['title'],'Comprendre son audience')
        self.assertEqual(agent.get_thread(app,thread['id'])['actions'][0]['status'],'applied')

    def test_agent_tag_action_requires_confirmation(self):
        source=self.s.make_source('Un vlog test','Alice','Vidéo',[dict(start=0,duration=2,text='Dans les coulisses.')])
        thread=agent.create_thread(app,self.s,{'book_id':'book-main'})
        result=agent.execute_tool(app,self.s,thread,'propose_tag_sources',{'source_ids':[source['id']],'tags':['Vlog','Facecam'],'mode':'add'})
        agent.save_thread(app,thread)
        self.assertEqual(app.get_source(source['id'])['annotation']['tags'],[])
        applied=agent.apply_action(app,self.s,thread['id'],result['action_id'],True)
        self.assertEqual(applied['tags']['count'],1)
        self.assertEqual(app.get_source(source['id'])['annotation']['tags'],['Vlog','Facecam'])

    def test_agent_tool_loop_persists_answer_and_trace(self):
        thread=agent.create_thread(app,self.s,{'book_id':'book-main'});thread['messages'].append(dict(id='u1',role='user',content='Quel est mon plan ?',created=app.now()));agent.save_thread(app,thread)
        replies=[
          {'choices':[{'message':{'content':'','tool_calls':[{'id':'call1','type':'function','function':{'name':'read_book','arguments':json.dumps({'book_id':'book-main'})}}]}}]},
          {'choices':[{'message':{'content':'Ton livre ne contient encore aucun chapitre.'}}]}
        ]
        job=dict(id='agent-job-test',thread_id=thread['id'],status='queued',created=app.now())
        try:
            with patch.object(app,'llm_request',side_effect=replies) as request:agent.run_job(app,self.s,app.AGENT_JOBS,job)
            saved=agent.get_thread(app,thread['id']);answer=saved['messages'][-1]
            self.assertEqual(job['status'],'finished');self.assertIn('aucun chapitre',answer['content']);self.assertEqual(answer['trace'][0]['tool'],'read_book')
            self.assertEqual(request.call_args_list[0].args[1]['reasoning_effort'],'none')
        finally:
            with app.connect() as c:c.execute("DELETE FROM settings WHERE id='agent-job:agent-job-test'")


if __name__=='__main__':unittest.main(verbosity=2)
