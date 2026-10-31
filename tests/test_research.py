"""Offline mock tests only. These fixtures are not live research findings."""
import copy
import json
import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
import requests
from catalog import Catalog, HEADINGS
from profiles import Profiles
from storage import Store
from research import ResearchQueue
from research_provider import Limits, ResearchError, OpenAIResearch, public_url
from research_worker import worker_lock, recover_if_idle
from test_profiles import criterion, response


def fixture(host='startup.example'):
    website='https://'+host
    claim=dict(text='Unknown',label='Analyst interpretation',sources=[],basis='')
    result=dict(identity=dict(domain=host,confirmed=True,rationale='Mock company domain and product match',sources=[website]),
        sources=[dict(url=website,published_on='',origin='Company',evidence_quote='Mock: a software product')],
        facts=[dict(section='Product',claim=dict(text='Mock product statement',label='Company claim',sources=[website],basis=''))],
        analysis={h:copy.deepcopy(claim) for h in HEADINGS},
        proposals=[dict(field='description',value='Mock proposed description',sources=[website],reason='Mock evidence')],conflicts=[],profile_suggestions=[])
    result['analysis'][HEADINGS[1]]=dict(text='Mock product analysis',label='Company claim',sources=[website],basis='')
    return dict(result=result,citations=[website],model='mock-model-not-live')

class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/'jobs.db')
        self.sid=self.store.save(dict(name='Mock startup',website='https://startup.example',stage='Unknown',status='New',description='Keep existing facts'))
        self.profiles=Profiles(self.store)
        self.pid=self.profiles.save('Preserve profile',[criterion()])
        self.profiles.assess(self.pid,self.sid,1,{'sector':response('Meets')})
        self.original=self.store.list()
        self.q=ResearchQueue(self.store)
        self.dns=patch('research.public_url',side_effect=lambda u:u)
        self.dns.start();self.addCleanup(self.dns.stop)
        self.provider=Mock()
        self.provider.run.return_value=fixture()
        self.factory=Mock(return_value=self.provider)

    def test_complete_job_sources_draft_preservation_and_retry_idempotence(self):
        job_id=self.q.enqueue([self.sid])[0]
        self.assertEqual(self.q.enqueue([self.sid]),[job_id])
        self.q.process_one(self.factory)
        job=self.q.jobs()[0]
        self.assertEqual(job['status'],'Completed')
        self.assertEqual(self.store.list(),self.original)
        self.assertEqual(self.profiles.state(self.pid,self.sid),'Meets required criteria')
        self.assertEqual(self.q.cat.analyses(self.sid,reader=True),[])
        analysis=self.q.cat.analyses(self.sid)[0]
        self.assertEqual(analysis['status'],'Draft')
        self.assertEqual(self.q.cat.sources(self.sid)[0]['published_on'],None)
        self.assertEqual(analysis['content'][HEADINGS[2]]['text'],'Unknown')
        self.q.retry(job_id)
        self.assertFalse(self.q.process_one(self.factory))
        self.assertEqual(len(self.q.cat.analyses(self.sid)),1)
        self.assertEqual(self.q.enqueue([self.sid]),[job_id])
        self.provider.run.assert_called_once()
        # Publication/editing preserves provenance without exposing profile suggestions in Reader.
        self.q.cat.publish(self.sid,analysis['id'])
        derived=self.q.cat.analysis(self.sid,'Human revised', '2026-10-31',analysis['content'],analysis['id'])
        metadata=self.q.cat.rows('SELECT * FROM ai_analysis_metadata WHERE analysis_id=?',(derived,))
        self.assertEqual(metadata[0]['model'],'mock-model-not-live')

    def test_failures_do_not_stop_next_company_and_restart_recovery(self):
        second=self.store.save(dict(name='Next',website='https://next.example',stage='Unknown',status='New'))
        ids=self.q.enqueue([self.sid,second])
        self.provider.run.side_effect=[ResearchError('Mock timeout'),fixture('next.example')]
        self.assertTrue(self.q.process_one(self.factory)); self.assertTrue(self.q.process_one(self.factory))
        statuses={j['id']:j['status'] for j in self.q.jobs()}
        self.assertEqual(statuses,{ids[0]:'Failed',ids[1]:'Completed'})
        self.q.retry(ids[0]); self.q.claim()
        with worker_lock(self.store.path) as acquired:
            self.assertTrue(acquired)
            self.assertFalse(recover_if_idle(self.q))
            self.assertEqual(next(j for j in self.q.jobs() if j['id']==ids[0])['status'],'Running')
        self.assertTrue(recover_if_idle(self.q))
        self.assertEqual(next(j for j in self.q.jobs() if j['id']==ids[0])['status'],'Failed')

    def test_stopping_pending_and_cached_response_retry_no_extra_api(self):
        jid=self.q.enqueue([self.sid])[0]
        self.q.stop_pending();self.assertFalse(self.q.process_one(self.factory))
        self.assertTrue(self.q.jobs()[0]['stopped'])
        self.q.retry(jid)
        with patch.object(self.q,'finish',side_effect=RuntimeError('Mock interruption before commit')):
            self.q.process_one(self.factory)
        self.assertEqual(self.q.jobs()[0]['status'],'Failed')
        self.q.retry(jid);self.q.process_one(self.factory)
        self.assertEqual(self.q.jobs()[0]['status'],'Completed')
        self.provider.run.assert_called_once()
        self.assertEqual(len(self.q.cat.analyses(self.sid)),1)

    def test_reject_unknown_identity_unretrieved_sources_and_uncorroborated(self):
        inputs=dict(website='https://startup.example',profile=None)
        for kind in ('identity','citations','factual','corroboration','conflict'):
            payload=fixture()
            if kind=='identity':payload['result']['identity']['domain']='namesake.example'
            if kind=='citations':payload['citations']=[]
            if kind=='factual':payload['result']['facts'][0]['claim']['sources']=[]
            if kind=='corroboration':payload['result']['facts'][0]['claim']['label']='Independently corroborated'
            if kind=='conflict':payload['result']['conflicts']=[dict(topic='Mock conflict',detail='Mock discrepancy',sources=['https://startup.example'])]
            with self.subTest(kind=kind),self.assertRaises(ResearchError):
                self.q.validate_payload(inputs,payload,Limits())

    def test_opt_in_proposals_and_profile_suggestions_separate(self):
        self.provider.run.return_value['result']['profile_suggestions']=[dict(key='sector',result='Unknown',rationale='Mock insufficient evidence',sources=[])]
        jid=self.q.enqueue([self.sid],profile_id=self.pid)[0]
        self.q.process_one(self.factory)
        proposals=self.q.cat.rows('SELECT * FROM research_proposals WHERE job_id=?',(jid,))
        desc=next(p for p in proposals if p['field']=='description')
        self.assertEqual(self.store.list(),self.original)
        self.q.apply_proposals(jid,[desc['id']])
        self.assertEqual(self.store.list()[0]['description'],'Mock proposed description')
        self.assertEqual(self.q.cat.facts(self.sid),[])
        section=next(p for p in proposals if p['field'].startswith('section:'))
        self.q.apply_proposals(jid,[section['id']]);self.q.apply_proposals(jid,[section['id']])
        self.assertEqual(len(self.q.cat.facts(self.sid)),1)
        self.assertEqual(self.profiles.state(self.pid,self.sid),'Meets required criteria')


    def test_existing_published_analysis_is_unchanged_and_cache_reused(self):
        content={HEADINGS[0]:dict(text='Original human interpretation',label='Analyst interpretation',sources=[])}
        manual=self.q.cat.analysis(self.sid,'Human memo','2026-10-30',content)
        self.q.cat.publish(self.sid,manual)
        original=self.q.cat.analyses(self.sid,reader=True)
        jid=self.q.enqueue([self.sid])[0]
        self.q.process_one(self.factory)
        self.assertEqual(self.q.cat.analyses(self.sid,reader=True),original)
        # A finished old job with a still-valid cache finalizes without another paid request.
        self.q.cat.execute("UPDATE research_jobs SET updated_at=datetime('now','-48 hours') WHERE id=?",(jid,))
        new=self.q.enqueue([self.sid])[0]
        self.assertNotEqual(new,jid)
        self.q.process_one(self.factory)
        self.provider.run.assert_called_once()
        self.assertEqual(self.q.cat.analyses(self.sid,reader=True),original)

class ProviderTests(unittest.TestCase):
    def test_ssrf_private_dns_and_url_forms(self):
        for url in ('http://127.0.0.1','http://169.254.169.254/latest','http://10.0.0.1','http://[::1]','file:///etc/passwd','https://user:pass@public.example','https://public.example:8080','http://2130706433','http://server.local'):
            with self.subTest(url=url),self.assertRaises(ResearchError):public_url(url)
        with patch('socket.getaddrinfo',return_value=[(socket.AF_INET,0,0,'',('10.0.0.2',0))]):
            with self.assertRaises(ResearchError):public_url('https://rebinding.example')
        with patch('socket.getaddrinfo',return_value=[(socket.AF_INET,0,0,'',('8.8.8.8',0)),(socket.AF_INET,0,0,'',('127.0.0.1',0))]):
            with self.assertRaises(ResearchError):public_url('https://mixed.example')
        with patch('socket.getaddrinfo',return_value=[(socket.AF_INET,0,0,'',('8.8.8.8',0))]):
            self.assertEqual(public_url('https://public.example'),'https://public.example')

    def test_missing_credentials_no_http_call(self):
        post=Mock()
        with patch.dict(os.environ,{},clear=True),self.assertRaises(ResearchError):
            OpenAIResearch(post=post).run({'website':'https://startup.example'})
        post.assert_not_called()

    def test_bounded_api_retry_structured_sources_and_no_secrets_in_errors(self):
        data=fixture()
        output=dict(status='completed',model='mock-model',output=[
            dict(type='web_search_call',action=dict(sources=[dict(url='https://startup.example')])),
            dict(type='message',content=[dict(type='output_text',text=json.dumps(data['result']),annotations=[])])])
        post=Mock(side_effect=[Mock(status_code=429),Mock(status_code=200,json=lambda:output)])
        with patch.dict(os.environ,{'SCOUTAI_AI_API_KEY':'mock-not-a-real-key'}),patch('research_provider.public_url',side_effect=lambda u:u):
            result=OpenAIResearch(Limits(retries=1),post=post,sleeper=lambda _:None).run({'website':'https://startup.example'})
            self.assertEqual(result['citations'],['https://startup.example'])
            self.assertEqual(post.call_count,2)
            body=post.call_args.kwargs['json']
            self.assertEqual(body['max_tool_calls'],4)
            self.assertFalse(body['store'])
            failed=Mock(return_value=Mock(status_code=401))
            with self.assertRaisesRegex(ResearchError,'HTTP 401') as error:
                OpenAIResearch(post=failed).run({'website':'https://startup.example'})
            self.assertNotIn('mock-not-a-real-key',str(error.exception))

    def test_incomplete_response_never_becomes_result(self):
        post=Mock(return_value=Mock(status_code=200,json=lambda:dict(status='incomplete',output=[])))
        with patch.dict(os.environ,{'SCOUTAI_AI_API_KEY':'mock-key'}),patch('research_provider.public_url',side_effect=lambda u:u),self.assertRaises(ResearchError):
            OpenAIResearch(post=post).run({'website':'https://startup.example'})
