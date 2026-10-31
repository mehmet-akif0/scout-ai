"""Catalog, evidence, analysis publication, watchlists and offline bulk intake."""
import csv
import io
from datetime import date
import streamlit as st
from catalog import SECTIONS, HEADINGS, LABELS, MODELS, read_csv, map_csv
from storage import FIELDS


def done(message):
    st.session_state['notice'] = message
    st.rerun()


def claim_form(key, sources, previous=None):
    previous = previous or {}
    text = st.text_area('Text', value=previous.get('text', ''), key=key + '_text')
    label = st.selectbox('Evidence label', LABELS, index=LABELS.index(previous.get('label', 'Analyst interpretation')), key=key + '_label')
    lookup = {s['id']: s for s in sources}
    selected = st.multiselect('Supporting sources', list(lookup), default=previous.get('sources', []), format_func=lambda i: f"#{i} · {lookup[i]['origin']} · {lookup[i]['url']}", key=key + '_sources')
    basis = st.text_area('Corroboration basis', value=previous.get('basis', ''), help='Required for independent corroboration. Explain how the independent evidence supports this claim.', key=key + '_basis')
    return dict(text=text, label=label, sources=selected, basis=basis)


def show_claim(claim, sources):
    st.text(claim['text'])
    st.caption(claim['label'])
    if claim.get('basis'):
        st.text('Supporting basis: ' + claim['basis'])
    lookup = {s['id']: s for s in sources}
    for source_id in claim.get('sources', []):
        source = lookup.get(source_id)
        if source:
            st.write(source['url'])
            st.caption(f"{source['origin']} · Published: {source['published_on'] or 'Unknown'} · Accessed: {source['accessed_on']}")
            if source['note']:
                st.text(source['note'])


def detail(cat, company, reader=False):
    sid = company['id']
    st.header(company['name'])
    st.caption(f"{company['research_status']} · Company #{sid}")
    st.write('Direct detail address:')
    st.code(f'?view=reader&startup={sid}', language=None)
    st.caption('Append this query to the app address to open this company directly. Reader mode is a display option, not access control.')
    sources = cat.sources(sid)
    facts = cat.facts(sid)
    for section in SECTIONS:
        with st.expander(section, expanded=section == 'Overview'):
            if section == 'Overview':
                for label, field in [('Description', 'description'), ('Website', 'website'), ('Sector', 'sector'), ('Headquarters country', 'country'), ('Investment stage', 'stage')]:
                    st.text(f"{label}: {company[field] or 'Unknown'}")
                st.caption('Basic company fields are unverified user-entered information. Add sourced claims below for evidence.')
            if section == 'Founders':
                st.text(company['founders'] or 'Not researched')
            if section == 'Business Model':
                st.text(company['business_model'])
            selected_facts = [f for f in facts if f['section'] == section]
            if not selected_facts:
                st.caption('Not researched')
            for fact in selected_facts:
                show_claim(fact['content'], sources)
    st.subheader('Analyses')
    published = cat.analyses(sid, reader=True)
    if not published:
        st.info('No published analyses. Not researched.')
    for version in published:
        with st.expander(f"{version['title']} · {version['analyzed_on']} · v{version['version']} · Published"):
            for heading in HEADINGS:
                st.markdown('**' + heading + '**')
                claim = version['content'].get(heading)
                if claim and claim.get('text', '').strip():
                    show_claim(claim, sources)
                else:
                    st.caption('Not researched')
    if reader:
        return
    st.info('Local administration: no login or real user authorization is implemented. Publishing changes only in-app content visibility.')
    with st.expander('Manage company metadata'):
        with st.form(f'metadata_{sid}'):
            model = st.selectbox('Company business model', MODELS, index=MODELS.index(company['business_model']))
            research = st.selectbox('Research status', ['Not researched', 'In progress', 'Researched'], index=['Not researched', 'In progress', 'Researched'].index(company['research_status']))
            if st.form_submit_button('Save metadata'):
                cat.details(sid, model, research)
                done('Company metadata saved.')
    with st.expander('Add evidence source'):
        with st.form(f'source_{sid}', clear_on_submit=True):
            url = st.text_input('Evidence source URL')
            known_date = st.checkbox('Publication date is known')
            published_on = st.date_input('Source publication date', value=date.today())
            accessed_on = st.date_input('Access date', value=date.today())
            origin = st.selectbox('Source origin', ['Company', 'Independent', 'Other'])
            note = st.text_area('Source note', help='Describe the provenance. Independent is a manual classification, not automated verification.')
            if st.form_submit_button('Add source'):
                try:
                    cat.source(sid, url, published_on.isoformat() if known_date else '', accessed_on.isoformat(), origin, note)
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    done('Source saved.')
        for source in sources:
            st.text(f"#{source['id']} · {source['url']} · {source['origin']} · Published {source['published_on'] or 'Unknown'} · Accessed {source['accessed_on']}")
    with st.expander('Add or edit sourced company information'):
        fact_lookup = {f['id']: f for f in facts}
        selected = st.selectbox('Company information entry', [0, *fact_lookup], format_func=lambda i: 'New claim' if i == 0 else f"#{i} · {fact_lookup[i]['section']}")
        previous = fact_lookup.get(selected)
        with st.form(f'fact_{sid}_{selected}'):
            section = st.selectbox('Company section', SECTIONS, index=SECTIONS.index(previous['section']) if previous else 0)
            claim = claim_form(f'fact_{sid}_{selected}', sources, previous['content'] if previous else None)
            if st.form_submit_button('Save company information'):
                try:
                    cat.fact(sid, section, claim, selected or None)
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    done('Company information saved.')
    with st.expander('Write or edit an analysis'):
        versions = {v['id']: v for v in cat.analyses(sid)}
        selected = st.selectbox('Analysis version to edit', [0, *versions], format_func=lambda i: 'New dated analysis' if i == 0 else f"{versions[i]['title']} · series {versions[i]['series_id']} · v{versions[i]['version']} · {versions[i]['status']}")
        previous = versions.get(selected)
        if previous and previous['status'] == 'Published':
            st.warning('Saving edits creates a new Draft version. The published version stays unchanged.')
        with st.form(f'analysis_{sid}_{selected}'):
            title = st.text_input('Analysis title', value=previous['title'] if previous else '')
            day = st.date_input('Analysis date', value=date.fromisoformat(previous['analyzed_on']) if previous else date.today())
            content = {}
            for heading in HEADINGS:
                st.markdown('**' + heading + '**')
                content[heading] = claim_form(f'analysis_{sid}_{selected}_{heading}', sources, previous['content'].get(heading) if previous else None)
            if st.form_submit_button('Save draft'):
                try:
                    cat.analysis(sid, title, day.isoformat(), content, selected or None)
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    done('Draft saved. Reader view still shows only the latest published version.')
        if previous and previous['status'] == 'Draft':
            st.caption('Publish uses the saved draft. Save any form edits first.')
            if st.button('Publish saved draft', key=f'publish_{selected}'):
                try:
                    cat.publish(sid, selected)
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    done('Analysis published inside the app. No internet deployment performed.')


def catalog_view(cat, reader=False):
    st.subheader('Startup catalog')
    rows = cat.companies()
    cols = st.columns(5)
    query = cols[0].text_input('Catalog company search')
    sector = cols[1].selectbox('Catalog sector', ['Any', *sorted({r['sector'] or 'Unknown' for r in rows})])
    country = cols[2].selectbox('Headquarters country', ['Any', *sorted({r['country'] or 'Unknown' for r in rows})])
    stage = cols[3].selectbox('Catalog investment stage', ['Any', *sorted({r['stage'] for r in rows})])
    model = cols[4].selectbox('Catalog business model', ['Any', *MODELS])
    lists = {r['id']: r for r in cat.lists()}
    selected_list = st.selectbox('Catalog watchlist', [0, *lists], format_func=lambda i: 'All companies' if i == 0 else lists[i]['name'])
    members = {r['startup_id'] for r in cat.rows('SELECT startup_id FROM watchlist_members WHERE list_id=?', (selected_list,))}
    filtered = [r for r in rows if query.casefold() in r['name'].casefold() and
        (sector == 'Any' or (r['sector'] or 'Unknown') == sector) and
        (country == 'Any' or (r['country'] or 'Unknown') == country) and
        (stage == 'Any' or r['stage'] == stage) and (model == 'Any' or r['business_model'] == model) and
        (not selected_list or r['id'] in members)]
    st.caption(f'{len(filtered)} companies · missing information is never invented')
    for offset in range(0, len(filtered), 3):
        for column, company in zip(st.columns(3), filtered[offset:offset + 3]):
            with column.container(border=True):
                st.subheader(company['name'])
                st.text(f"{company['sector'] or 'Unknown'} · {company['country'] or 'Unknown'}")
                st.caption(f"{company['stage']} · {company['business_model']} · {company['research_status']}")
                st.text(company['description'][:240] or 'Not researched')
                st.link_button('Open company details', f"?view={'reader' if reader else 'admin'}&startup={company['id']}")
    if not filtered:
        st.info('No companies match. Add a startup or use Bulk Import in local administration.')
    raw_id = st.query_params.get('startup', '')
    selected_company = next((r for r in rows if str(r['id']) == raw_id), None)
    if raw_id and not selected_company:
        st.warning('Company not found. It may have been deleted.')
    options = [0, *[r['id'] for r in rows]]
    lookup = {r['id']: r for r in rows}
    sid = st.selectbox('Open company details', options, key='catalog_detail_selector', index=options.index(selected_company['id']) if selected_company else 0, format_func=lambda i: 'Choose a company' if i == 0 else f"{lookup[i]['name']} · #{i}")
    if sid:
        detail(cat, lookup[sid], reader)


def watchlists_view(cat):
    st.subheader('Watchlists')
    lookup = {r['id']: r for r in cat.lists()}
    selected = st.selectbox('Manage watchlist', [0, *lookup], key='manage_watchlist', format_func=lambda i: 'Create a new list' if i == 0 else lookup[i]['name'])
    companies = {r['id']: r for r in cat.companies()}
    members = [r['startup_id'] for r in cat.rows('SELECT startup_id FROM watchlist_members WHERE list_id=?', (selected,))]
    with st.form(f'watchlist_{selected}'):
        name = st.text_input('List name', value=lookup[selected]['name'] if selected else '')
        chosen = st.multiselect('Companies in list', list(companies), key=f'watchlist_members_{selected}', default=members, format_func=lambda i: f"{companies[i]['name']} · #{i}")
        if st.form_submit_button('Save watchlist'):
            try:
                list_id = cat.save_list(name, selected or None)
                cat.set_members(list_id, chosen)
            except ValueError as exc:
                st.error(str(exc))
            else:
                done('Watchlist saved.')
    if selected:
        confirm = st.checkbox('Delete this list only; keep its companies.')
        if st.button('Delete watchlist', disabled=not confirm):
            cat.execute('DELETE FROM watchlists WHERE id=?', (selected,))
            done('Watchlist deleted; companies preserved.')


def bulk_import_view(cat):
    st.subheader('Bulk Import')
    st.caption('Offline intake only: no websites are fetched. All added records start as Not researched. Existing records are never updated. Bare domains need an explicit https:// prefix.')
    mode = st.radio('Import method', ['CSV upload', 'Website URLs'])
    incoming = []
    if mode == 'CSV upload':
        upload = st.file_uploader('Upload UTF-8 CSV', type=['csv'])
        if upload:
            try:
                text = upload.getvalue().decode('utf-8-sig')
                columns, raw = read_csv(text)
                mapping = {}
                for field in (*FIELDS, 'business_model'):
                    mapping[field] = st.selectbox('CSV column for ' + field, ['(not mapped)', *columns], index=columns.index(field) + 1 if field in columns else 0)
                incoming = map_csv(raw, mapping)
            except (UnicodeError, csv.Error, ValueError) as exc:
                st.error(str(exc))
                return
    else:
        urls = st.text_area('One company website URL per line', placeholder='https://company.example')
        incoming = [dict(website=line.strip()) for line in urls.splitlines() if line.strip()]
    if len(incoming) > 5000:
        st.error('Import at most 5,000 rows at a time.')
        return
    if incoming:
        preview = cat.prepare_import(incoming)
        st.dataframe([dict(Row=r['row'], Company=r['item']['name'], Website=r['item']['website'], Action=r['action'], Reason=r['reason']) for r in preview], hide_index=True, width='stretch')
        st.caption('Domains are compared as exact normalized hosts, ignoring www, case, paths, and trailing dots. Subdomains remain separate. Equal names without matching domains are never merged. Identical name-only import rows are skipped on repeat.')
        st.write({key: sum(r['action'] == key for r in preview) for key in ('Add', 'Skip', 'Error')})
        confirm = st.checkbox('I reviewed the preview. Add valid new rows and skip duplicates and errors.')
        if st.button('Import valid rows', disabled=not confirm):
            counts = cat.import_rows(incoming)
            done(f"Import complete: {counts['added']} added, {counts['skipped']} skipped, {counts['errors']} errors.")
    st.divider()
    st.markdown('**Prepare a future research selection**')
    companies = {r['id']: r for r in cat.companies()}
    saved = [r['startup_id'] for r in cat.rows('SELECT * FROM research_selection ORDER BY position')]
    chosen = st.multiselect('Startups for future research (selection order)', list(companies), default=saved, format_func=lambda i: f"#{i} · {companies[i]['name']} · {companies[i]['research_status']}", key='future_research_selection')
    if st.button('Save research selection'):
        cat.select_for_research(chosen)
        done('Ordered selection saved. No AI research was started.')
    st.caption('Preparation only: stable startup IDs and ordered selection are stored for a later research phase. No AI jobs, web requests, or automatic research run here.')
