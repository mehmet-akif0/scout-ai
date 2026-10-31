"""Explicit paid research controls, persistent progress and opt-in review."""
import json
from dataclasses import asdict
import streamlit as st
from research import ResearchQueue
from research_provider import Limits, ResearchError, api_key
from research_worker import start_worker, recover_if_idle
from profiles import Profiles
from metrics import Metrics, approve_metric_proposals
from catalog_ui import done


def research_view(cat, active_profile):
    st.subheader('AI Research')
    queue=ResearchQueue(cat.store)
    recover_if_idle(queue)  # Reclassify orphaned work only under the worker's exclusive lock.
    try:
        limits=Limits.environment()
    except ResearchError as exc:
        st.error(str(exc)); return
    configured=bool(api_key())
    if not configured:
        st.warning('Research is not configured: add SCOUTAI_AI_API_KEY on the server for api.openai.com (OpenAI Responses API + web search). Manual features still work. No live research has been performed by this screen.')
    st.write('Provider: OpenAI Responses API with built-in web search. No Crunchbase connection is configured.')
    st.caption('This sends company URLs, optional supplied text and active profile criteria to OpenAI. Model tokens and web search may be billed. No reliable cost estimate is available; no amount is invented.')
    st.json(asdict(limits))
    companies={c['id']:c for c in cat.companies()}
    company_options = [0,*companies]
    requested = next((i for i in companies if str(i) == st.query_params.get('startup')),0)
    selected=st.selectbox('Company to research', company_options, index=company_options.index(requested), format_func=lambda i: 'Choose a company' if i==0 else f"#{i} · {companies[i]['name']}")
    website=st.text_input('Research website URL', value=companies[selected]['website'] if selected else '', help='Public http(s) URL only; private/local networks and nonstandard ports are rejected.')
    extras=st.text_area('Optional additional source URLs', help='One public http(s) URL per line; actual tool-retrieved evidence is still required.')
    context=st.text_area('Optional research context', max_chars=20000, help='Treated as untrusted data, not instructions. Do not include secrets or sensitive personal information.')
    fresh=st.checkbox('Force fresh research (bypass cache; may incur new charges)')
    saved=[r['startup_id'] for r in cat.rows('SELECT * FROM research_selection ORDER BY position')]
    st.write(f'Saved ordered selection: {len(saved)} companies. Maximum batch: {limits.batch}.')
    st.caption(f'At most {len(saved)*(limits.retries+1)} API attempts for this saved batch; up to {len(saved)*(limits.retries+1)*limits.tool_calls} web tool calls across attempts. Actual usage can be lower.')
    if saved:
        st.dataframe([dict(Position=n+1,Company=companies[sid]['name'],Website=companies[sid]['website'] or 'Missing URL') for n,sid in enumerate(saved) if sid in companies],hide_index=True)
    st.caption('Per company: at most configured tool calls and retained sources, bounded output tokens, timeout per API attempt and limited retries. Cache hits may avoid calls. Pending work can be stopped; a Running request finishes. Retries after ambiguous network failure may cost again.')
    consent=st.checkbox('I understand paid APIs may be used and have reviewed the companies and limits.')
    def enqueue(ids, override=None):
        try:
            jobs=queue.enqueue(ids,limits,website=override,extra_urls=[u.strip() for u in extras.splitlines() if u.strip()],extra_text=context,profile_id=active_profile,fresh=fresh)
            start_worker(queue)
        except (ResearchError,ValueError) as exc:
            st.error(str(exc))
        else:
            done(f'Research queued or cached: {len(jobs)} companies. Refresh progress to see results; no automatic publishing.')
    if st.button('Research startup',disabled=not (configured and consent and selected and website)):
        enqueue([selected],website)
    if st.button('Research selected',disabled=not (configured and consent and saved and len(saved)<=limits.batch)):
        enqueue(saved)
    st.subheader('Research queue')
    jobs=queue.jobs()
    counts={s:sum(j['status']==s for j in jobs) for s in ('Pending','Running','Completed','Failed')}
    st.write(counts)
    if jobs:
        terminal=counts['Completed']+counts['Failed']
        st.progress(terminal/len(jobs),text=f'{terminal} of {len(jobs)} jobs finished or stopped')
        st.dataframe([dict(Job=j['id'],Company=j['name'],Status=j['status'],Attempts=j['attempts'],Stopped=bool(j['stopped']),Error=j['error']) for j in jobs],hide_index=True,width='stretch')
    if st.button('Refresh progress'):
        st.rerun()
    if st.button('Stop pending jobs',disabled=counts['Pending']==0):
        queue.stop_pending(); done('Pending jobs stopped. A running request is not interrupted.')
    failed={j['id']:j for j in jobs if j['status']=='Failed'}
    retry=st.selectbox('Failed job to retry',[0,*failed],format_func=lambda i:'Choose a failed job' if i==0 else f"#{i} · {failed[i]['name']}")
    if st.button('Retry failed job',disabled=not(configured and consent and retry)):
        queue.retry(retry); start_worker(queue); done('Job queued for retry. A saved validated response will be reused if available.')
    if st.button('Resume pending jobs',disabled=not(configured and consent and counts['Pending'])):
        start_worker(queue); done('Worker requested. Jobs run sequentially; refresh progress.')
    completed={j['id']:j for j in jobs if j['status']=='Completed'}
    review=st.selectbox('Research result to review',[0,*completed],format_func=lambda i:'Choose completed research' if i==0 else f"#{i} · {completed[i]['name']}")
    if not review:
        return
    job=completed[review]
    metadata=cat.rows('SELECT * FROM ai_analysis_metadata WHERE analysis_id=?',(job['analysis_id'],))
    if metadata:
        meta=metadata[0]
        st.caption(f"AI-generated · {meta['researched_on']} · model {meta['model']} · Draft analysis #{job['analysis_id']}")
        st.write('Review and publish the draft under Startup catalog → company details → Write or edit an analysis.')
        st.json(json.loads(meta['identity']))
        conflicts=json.loads(meta['conflicts'])
        if conflicts:
            st.warning('Sources conflict. Review before saving company information or publishing.')
            st.json(conflicts)
        st.markdown('**Profile suggestions (not saved manual assessments)**')
        snapshot=json.loads(meta['profile_snapshot'])
        if snapshot:
            current=Profiles(cat.store).get(snapshot['id'])
            st.caption(f"Captured profile: {snapshot['name']} · criteria version {snapshot['revision']}")
            if not current or current['revision'] != snapshot['revision']:
                st.warning('Profile changed or was deleted. These suggestions require a fresh review.')
            st.json(json.loads(meta['profile_suggestions']))
        else:
            st.caption('No active profile was captured.')
    proposals=cat.rows("SELECT * FROM research_proposals WHERE job_id=? AND state='Pending'",(review,))
    company=next(c for c in cat.companies() if c['id']==job['startup_id'])
    st.markdown('**Proposed company updates — nothing is applied automatically**')
    st.dataframe([dict(ID=p['id'],Field=p['field'],Current=company.get(p['field'],'See current sourced section'),Proposed=p['value'],Sources=p['sources'],Reason=p['reason']) for p in proposals],hide_index=True)
    chosen=st.multiselect('Select proposed changes to save',[p['id'] for p in proposals],format_func=lambda i:next(p['field'] for p in proposals if p['id']==i))
    confirm=st.checkbox('I reviewed the selected sources and approve replacing the shown company fields or adding the selected section claims.')
    if st.button('Apply selected proposals',disabled=not(chosen and confirm)):
        queue.apply_proposals(review,chosen); done('Only selected proposals were saved. Published analyses and profile assessments were not changed.')

    st.markdown('**AI metric proposals — separate from approved measurements**')
    pending_metrics=cat.rows("SELECT * FROM ai_metric_proposals WHERE job_id=? AND state='Pending'",(review,))
    for item in pending_metrics:
        st.json(dict(proposal_id=item['id'],measurement=json.loads(item['payload'])))
    selected_metrics=st.multiselect('Metric proposals to approve',[p['id'] for p in pending_metrics])
    confirm_metrics=st.checkbox('I reviewed metric values, units, dates, definitions and sources. Save selected proposals as observations; do not replace existing approved metrics.')
    if st.button('Approve metric proposals',disabled=not(selected_metrics and confirm_metrics)):
        try:approve_metric_proposals(Metrics(cat.store),review,selected_metrics)
        except ValueError as exc:st.error(str(exc))
        else:done('Approved metric observations saved. Existing metrics and published analysis evidence were not changed.')
