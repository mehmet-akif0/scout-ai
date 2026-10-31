"""Source-aware KPI cards, period charts, cohort evidence and manual/CSV entry."""
import csv
import json
from datetime import date
import altair as alt
import pandas as pd
import streamlit as st
from metrics import Metrics, FIELDS, LABELS, FREQUENCIES, SCENARIOS, AVAILABILITY, RECIPES, calculate, chart_groups
from catalog import read_csv, map_csv


def chart_frame(group):
    # One plotted point per actual observation: no resampling, averaging or zero filling.
    points=[]
    for r in group['rows']:
        points.append(dict(ID=r['id'],Date=r['period_end'],Value=float(r['value']),Name=r['name'],Unit=r['unit'],Currency=r['currency'],
            Period=r['period_start']+' → '+r['period_end'],Scenario=r['scenario'],Scope=r['scope'],Definition=r['definition'],
            Source=r['source_ref'],Accessed=r['accessed_on'],Formula=r['formula'],Conflict=(r['period_start'],r['period_end']) in group['conflicts']))
    return pd.DataFrame(points)


def dashboard(metrics,sid,prefix='dashboard'):
    rows=metrics.observations(sid)
    relevance=metrics.applicability(sid)
    stale=[r for r in rows if r.get('inputs_stale')]
    for r in stale:
        st.warning(f"Calculated measurement #{r['id']} ({r['name']}) references superseded inputs. It is retained as history and withheld from current charts; recalculate with current inputs.")
        with st.expander(f"Historical calculation #{r['id']}"):st.json(r)
    active=[r for r in rows if relevance.get(r['metric_key'],True) and not r.get('inputs_stale')]
    if not active:
        st.info('Insufficient data. Add dated, sourced measurements and choose relevant metrics. No company figures or benchmarks are invented.')
    na=[key for key,value in relevance.items() if not value]
    if na:st.caption('N/A for this company: '+', '.join(na))
    unknown=[r for r in active if r['availability']!='Known']
    for r in unknown:st.caption(f"{r['name']}: {r['availability']} · {r['period_end']} · {r['source_ref']}")
    groups=chart_groups(active)
    for n,group in enumerate(groups):
        first=group['rows'][0]
        with st.expander(f"{first['name']} · {first['scenario']} · {first['currency'] or first['unit']} · {first['scope']}",expanded=True):
            st.caption(f"{first['definition']} · {first['frequency']} · basis {first['basis']} · cohort {first['cohort'] or 'not specified'}")
            if group['conflicts']:
                st.warning('Conflicting values for the same period and definition. All sources are shown; no average is calculated.')
            frame=chart_frame(group)
            if len(group['rows'])==1:
                r=first
                st.metric(r['name'],f"{r['value']} {r['currency'] or r['unit']}",help=f"{r['period_start']} to {r['period_end']} · {r['source_ref']}")
                st.caption(f"Dated KPI: {r['period_end']} · {r['scenario']}")
            else:
                # Point-only time series deliberately avoids connecting across unknown/missing periods.
                chart=alt.Chart(frame).mark_point(filled=True,size=90,shape='circle' if first['scenario']=='Actual' else 'diamond').encode(
                    x=alt.X('Date:T',title='Measurement / period end date'),
                    y=alt.Y('Value:Q',title=f"{first['name']} ({first['currency'] or first['unit']})",scale=alt.Scale(zero=False)),
                    color=alt.Color('Scenario:N',scale=alt.Scale(domain=['Actual','Forecast','Target'],range=['#28684c','#c27a20','#6952a0'])),
                    tooltip=[alt.Tooltip('ID:Q'),alt.Tooltip('Value:Q'),*['Name:N','Period:N','Unit:N','Currency:N','Scenario:N','Definition:N','Scope:N','Source:N','Accessed:N','Formula:N','Conflict:N']])
                st.altair_chart(chart,use_container_width=True,key=f'{prefix}_{sid}_series_{n}')
                st.caption('Observed points only; no values or connecting lines are invented for missing periods. Forecast/Target use diamond markers and separate scenario groups.')
            st.dataframe(frame,hide_index=True,width='stretch')
            with st.expander('Sources, definitions and calculation inputs'):
                for r in group['rows']:
                    st.json(r)
    funding=[r for r in active if r['metric_key']=='funding_round' and r['availability']=='Known']
    if funding:
        st.markdown('**Funding timeline — round amounts, not valuation**')
        for r in sorted(funding,key=lambda r:r['period_end']):
            st.text(f"{r['period_end']} · {r['round_name'] or 'Round not specified'} · {r['value']} {r['currency']} · {r['scenario']} · {r['source_ref']}")
    cohorts=[r for r in active if r['metric_key']=='cohort_retention' and r['availability']=='Known' and r['scenario']=='Actual' and r['cohort'] and r['cohort_age'] is not None]
    if cohorts:
        compatible={}
        for r in cohorts:
            key=(r['definition'],r['scope'],r['frequency'],r['basis'],r['unit'],r['cohort_age_unit'])
            compatible.setdefault(key,[]).append(r)
        for n,(key,values) in enumerate(compatible.items()):
            cells={}
            for r in values:cells.setdefault((r['cohort'],r['cohort_age']),[]).append(r)
            if any(len(rs)>1 for rs in cells.values()):
                st.warning('Cohort heatmap withheld: multiple measurements exist for a cohort/age cell. Review sources or correct superseded values.')
                continue
            st.markdown('**Observed cohort retention**')
            data=pd.DataFrame([dict(Cohort=r['cohort'],Age=r['cohort_age'],Retention=float(r['value']),Source=r['source_ref'],Date=r['period_end'],Definition=r['definition'],Scope=r['scope'],Accessed=r['accessed_on']) for r in values])
            heat=alt.Chart(data).mark_rect().encode(x=alt.X('Age:O',title=f'Cohort age ({key[5]})'),y='Cohort:N',color=alt.Color('Retention:Q',title='Retention (%)',scale=alt.Scale(domain=[0,100])),tooltip=['Cohort:N','Age:O','Retention:Q','Source:N','Date:N','Definition:N','Scope:N','Accessed:N'])
            st.caption('Scope: '+key[1]+' · frequency: '+key[2]+' · actual observed cells only; missing cells remain blank.')
            st.altair_chart(heat,use_container_width=True,key=f'{prefix}_{sid}_cohort_{n}')
    else:st.caption('Cohort heatmap: Insufficient data. Needs actual cohort_retention observations with named cohort, explicit age, scope and percentage.')


def measurement_form(metrics,sid):
    definitions=metrics.definitions()
    rows=[r for r in metrics.observations(sid) if r['label']!='Calculated']
    st.caption('Correct a manual measurement by creating a new version. For a calculation, correct its inputs and recalculate instead.')
    edit=st.selectbox('Correct an existing measurement',[0,*[r['id'] for r in rows]],format_func=lambda i:'New measurement' if i==0 else next(f"#{i} · {r['name']} · {r['period_end']}" for r in rows if r['id']==i))
    old=next((r for r in rows if r['id']==edit),{})
    key=st.selectbox('Metric definition',list(definitions),index=list(definitions).index(old['metric_key']) if old else 0,format_func=lambda k:definitions[k]['name'])
    d=definitions[key]
    if old.get('metric_key')==key:d={**d,'name':old['name'],'definition':old['definition']}
    prefix=f'metric_entry_{sid}_{edit}_{key}'
    with st.form(prefix,clear_on_submit=not bool(edit)):
        st.caption(d['definition']+' · unit: '+d['unit'])
        value=st.text_input('Numeric value (blank for Unknown / N/A)',value=str(old.get('value') or '') if old.get('value') is None else str(old['value']))
        currency=st.text_input('Currency (three-letter code, currency units only)',value=old.get('currency',''))
        availability=st.selectbox('Data availability',AVAILABILITY,index=AVAILABILITY.index(old.get('availability','Known')))
        scenario=st.selectbox('Data type',SCENARIOS,index=SCENARIOS.index(old.get('scenario','Actual')))
        frequency=st.selectbox('Measurement frequency',FREQUENCIES,index=FREQUENCIES.index(old.get('frequency','Point')))
        start=st.date_input('Period start / measurement date',value=date.fromisoformat(old['period_start']) if old else date.today())
        end=st.date_input('Period end / measurement date',value=date.fromisoformat(old['period_end']) if old else date.today())
        scope=st.text_area('Scope and population definition',value=old.get('scope',''),help='Define customer/user, entity, included revenue/costs and any gross/net distinction. Must match exactly for calculations.')
        basis=st.selectbox('Gross / net basis',['Not specified','Gross','Net'],index=['Not specified','Gross','Net'].index(old.get('basis','Not specified')))
        cohort=st.text_input('Starting cohort identifier (if applicable)',value=old.get('cohort',''))
        age=st.text_input('Cohort age (optional nonnegative integer)',value=str(old['cohort_age']) if old.get('cohort_age') is not None else '')
        age_unit=st.selectbox('Cohort age units (when age is provided)',['months','weeks','days','years'],index=['months','weeks','days','years'].index(old.get('cohort_age_unit') or 'months'))
        label=st.selectbox('Metric evidence label',LABELS[:-1],index=LABELS[:-1].index(old['label']) if old.get('label') in LABELS[:-1] else 2)
        source=st.text_input('Source URL or document reference',value=old.get('source_ref',''))
        accessed=st.date_input('Source access date',value=date.fromisoformat(old['accessed_on']) if old else date.today())
        published=st.text_input('Source publication date (YYYY-MM-DD, blank if unknown)',value=old.get('published_on',''))
        corroboration=st.text_input('Independent supporting reference',value=old.get('corroboration_ref',''))
        explanation=st.text_area('Independent corroboration basis',value=old.get('corroboration_basis',''))
        round_name=st.text_input('Funding round name / valuation basis (if applicable)',value=old.get('round_name',''))
        notes=st.text_area('Measurement notes',value=old.get('notes',''))
        if st.form_submit_button('Save measurement'):
            try:
                _,created=metrics.add(sid,dict(metric_key=key,name=d['name'],definition=d['definition'],value=value,currency=currency,availability=availability,scenario=scenario,frequency=frequency,
                    period_start=start.isoformat(),period_end=end.isoformat(),scope=scope,basis=basis,cohort=cohort,cohort_age=age,cohort_age_unit=age_unit,label=label,
                    source_ref=source,accessed_on=accessed.isoformat(),published_on=published,corroboration_ref=corroboration,corroboration_basis=explanation,round_name=round_name,notes=notes),edit or None)
            except (ValueError,TypeError) as exc:st.error(str(exc))
            else:
                st.session_state['notice']='Measurement saved; historical records preserved.' if created else 'Identical measurement already exists; skipped.';st.rerun()


def calculations(metrics,sid):
    recipe=st.selectbox('Calculation',list(RECIPES))
    st.caption('No benchmark or good/bad threshold is inferred. Insufficient or incompatible inputs do not produce a number.')
    rows=metrics.observations(sid)
    inputs={}
    for role in RECIPES[recipe]:
        choices=[r for r in rows if r['availability']=='Known' and not r.get('inputs_stale') and (recipe=='Growth' or r['metric_key']==role)]
        lookup={r['id']:r for r in choices}
        selected=st.selectbox('Input: '+role,[0,*lookup],format_func=lambda i:'Select input' if not i else f"#{i} · {lookup[i]['name']} · {lookup[i]['value']} {lookup[i]['currency'] or lookup[i]['unit']} · {lookup[i]['period_start']} → {lookup[i]['period_end']} · {lookup[i]['scenario']}",key=f'calc_{sid}_{recipe}_{role}')
        if selected:inputs[role]=lookup[selected]
    try:result=calculate(recipe,inputs)
    except (ValueError,KeyError) as exc:st.info('Insufficient data / undefined: '+str(exc));return
    st.metric(result['name'],f"{result['value']} {result['currency'] or result['unit']}")
    st.json(result)
    if st.button('Save calculated measurement'):
        if result['metric_key'] not in metrics.definitions():metrics.define(result['metric_key'],result['name'],result['definition'],result['unit'])
        metrics.add(sid,result,calculated=True)
        st.session_state['notice']='Calculation saved with formula and immutable input snapshots.';st.rerun()


def metrics_view(cat):
    st.subheader('Metrics & Analytics')
    metrics=Metrics(cat.store)
    companies={c['id']:c for c in cat.companies()}
    sid=st.selectbox('Metrics company',[0,*companies],format_func=lambda i:'Select company' if not i else companies[i]['name'])
    if not sid:return
    company=companies[sid]
    st.caption(f"Business model: {company['business_model']} · stage: {company['stage']}. Select relevant metrics for this company; no universal SaaS template is forced.")
    tabs=st.tabs(['Dashboard','Manual measurement','Metric CSV Import','Calculations','Relevance & definitions'])
    with tabs[0]:dashboard(metrics,sid)
    with tabs[1]:measurement_form(metrics,sid)
    with tabs[2]:
        st.caption('UTF-8 CSV. Required: metric_key, value (unless Unknown/N/A), period_start, period_end, scope, source_ref, accessed_on. Other columns can be mapped or use explicit defaults. Dates: YYYY-MM-DD. No currency conversion or merging.')
        upload=st.file_uploader('Upload metric CSV',type=['csv'])
        if upload:
            try:
                columns,rows=read_csv(upload.getvalue().decode('utf-8-sig'))
                mapping={}
                for field in FIELDS:
                    if field in ('inputs','formula'):continue
                    mapping[field]=st.selectbox('Metric CSV column: '+field,['(not mapped)',*columns],index=columns.index(field)+1 if field in columns else 0)
                incoming=map_csv(rows,mapping)
                preview=metrics.preview(sid,incoming)
                st.dataframe([dict(Row=r['row'],Action=r['action'],Error=r['error'],Warning=r.get('warning',''),Data=json.dumps(r['data'])) for r in preview],hide_index=True)
                confirm=st.checkbox('I reviewed metric rows, sources, errors and duplicates. Add valid observations without overwriting existing metrics.')
                if st.button('Import valid metric rows',disabled=not confirm):
                    counts=metrics.import_rows(sid,incoming);st.session_state['notice']=str(counts);st.rerun()
            except (ValueError,UnicodeError,csv.Error) as exc:st.error(str(exc))
    with tabs[3]:calculations(metrics,sid)
    with tabs[4]:
        definitions=metrics.definitions();relevance=metrics.applicability(sid)
        observed={r['metric_key'] for r in metrics.observations(sid)}
        default=[k for k in definitions if relevance.get(k,k in observed)]
        with st.form(f'metric_relevance_{sid}'):
            selected=st.multiselect('Relevant metrics (others become N/A for this company)',list(definitions),default=default,format_func=lambda k:definitions[k]['name'])
            if st.form_submit_button('Save metric relevance'):
                metrics.set_applicability(sid,selected);st.rerun()
        st.dataframe([dict(Metric_key=k,**v) for k,v in definitions.items()],hide_index=True,width='stretch')
        st.caption('Relevance is a human choice based on business model and stage. Unselected metrics are not failed metrics; existing observations remain stored.')
        with st.form('custom_metric'):
            key=st.text_input('Custom metric key (lowercase snake_case)');name=st.text_input('Custom metric name');definition=st.text_area('Custom metric definition');unit=st.text_input('Custom metric unit')
            if st.form_submit_button('Create metric definition'):
                try:metrics.define(key,name,definition,unit)
                except ValueError as exc:st.error(str(exc))
                else:st.rerun()
