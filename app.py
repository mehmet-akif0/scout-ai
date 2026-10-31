"""ScoutAI: a personal startup scouting workspace."""
import streamlit as st
from storage import Store, STATUSES, STAGES, export_csv
from profiles import Profiles, ASSESSMENT_STATES
from profile_ui import manage_profiles, assessment_editor

st.set_page_config(page_title='ScoutAI | Startup scouting', page_icon='🔎', layout='wide')
store = Store()
profiles = Profiles(store)
st.title('ScoutAI')
st.caption('Your personal startup scouting workspace. Research thoughtfully. Keep everything in one place.')

if notice := st.session_state.pop('notice', None):
    st.success(notice)

rows = store.list()
with st.sidebar:
    st.header('Startup radar')
    st.caption('Private by default on your local machine. No external APIs or AI connections.')
    profile_lookup = {p['id']: p for p in profiles.list()}
    profile_options = [0, *profile_lookup]
    if st.session_state.get('active_profile_selector') not in profile_options:
        st.session_state.pop('active_profile_selector', None)
    active_profile = st.selectbox('Active Scouting Profile', profile_options, key='active_profile_selector', index=profile_options.index(profiles.active_id() or 0), format_func=lambda i: 'No active profile' if i == 0 else f"{profile_lookup[i]['name']} · #{i}")
    active_profile = active_profile or None
    if active_profile != profiles.active_id():
        profiles.activate(active_profile)
    assessment_filter = st.selectbox('Filter by profile assessment', ['All assessments', *ASSESSMENT_STATES], disabled=active_profile is None)
    query = st.text_input('Search company name', placeholder='Search your startups…')
    sector = st.selectbox('Filter by sector', ['All sectors'] + sorted({r['sector'] for r in rows if r['sector']}))
    stage = st.selectbox('Filter by stage', ['All stages', *STAGES])
    status = st.selectbox('Filter by status', ['All statuses', *STATUSES])

metrics = st.columns(4)
for col, label, value in zip(metrics, ['Total startups', 'Researching', 'Shortlisted', 'New'], [len(rows), *[sum(r['status'] == s for r in rows) for s in ('Researching', 'Shortlisted', 'New')]]):
    col.metric(label, value)

filtered = store.list(query, '' if sector == 'All sectors' else sector,
                      '' if stage == 'All stages' else stage, '' if status == 'All statuses' else status)
if active_profile is not None and assessment_filter != 'All assessments':
    filtered = [r for r in filtered if profiles.state(active_profile, r['id']) == assessment_filter]
list_tab, add_tab, profiles_tab = st.tabs(['Browse & edit', 'Add startup', 'Scouting Profiles'])
with profiles_tab:
    manage_profiles(profiles)


def editor(record=None):
    record = record or {}
    key = str(record.get('id', 'new'))
    with st.form('editor_' + key, clear_on_submit=not bool(record)):
        left, right = st.columns(2)
        name = left.text_input('Company name *', key=key + '_name', value=record.get('name', ''), max_chars=20000)
        website = right.text_input('Website', key=key + '_website', value=record.get('website', ''), placeholder='https://example.com', max_chars=20000)
        founders = left.text_input('Founders', key=key + '_founders', value=record.get('founders', ''), max_chars=20000)
        sector_value = right.text_input('Sector', key=key + '_sector', value=record.get('sector', ''), placeholder='e.g. Fintech', max_chars=20000)
        country = left.text_input('Country', key=key + '_country', value=record.get('country', ''), max_chars=20000)
        stage_value = right.selectbox('Investment stage', STAGES, key=key + '_stage', index=STAGES.index(record.get('stage', 'Unknown')))
        status_value = left.selectbox('Status', STATUSES, key=key + '_status', index=STATUSES.index(record.get('status', 'New')))
        description = st.text_area('Short description', key=key + '_description', value=record.get('description', ''), max_chars=20000)
        sources = st.text_area('Source links', key=key + '_sources', value=record.get('sources', ''), help='One http:// or https:// URL per line.', max_chars=20000)
        notes = st.text_area('Personal notes', key=key + '_notes', value=record.get('notes', ''), max_chars=20000)
        submitted = st.form_submit_button('Save changes' if record else 'Add startup', type='primary')
    if submitted:
        try:
            store.save(dict(name=name, website=website, founders=founders, sector=sector_value,
                            country=country, stage=stage_value, status=status_value,
                            description=description, sources=sources, notes=notes), record.get('id'))
        except ValueError as exc:
            st.error(str(exc))
        else:
            st.session_state['notice'] = 'Startup updated.' if record else 'Startup added.'
            st.rerun()

with add_tab:
    st.subheader('Add a startup')
    st.caption('* Company name is required. All other details can be filled in later.')
    editor()

with list_tab:
    st.subheader('Your discovery list')
    st.caption(f'{len(filtered)} of {len(rows)} startups · newest first')
    st.download_button('Export filtered list as CSV', export_csv(filtered), file_name='scoutai-startups.csv', mime='text/csv', disabled=not filtered)
    if not rows:
        st.info('Your workspace is empty. Open “Add startup” to add your first company. No demo data is loaded.')
    elif not filtered:
        st.info('No startups match your search and filters. Try changing them in the sidebar.')
    else:
        st.dataframe([{ 'Company': r['name'], 'Sector': r['sector'], 'Country': r['country'], 'Stage': r['stage'], 'Status': r['status'], 'Profile assessment': profiles.state(active_profile, r['id']) if active_profile else 'No active profile'} for r in filtered], hide_index=True, width='stretch')
        ids = [r['id'] for r in filtered]
        lookup = {r['id']: r for r in filtered}
        selected = st.selectbox('Select a startup to view or edit', ids, format_func=lambda value: f"{lookup[value]['name']} · #{value}")
        record = lookup[selected]
        st.caption(f"Added: {record['created_at']} UTC · Updated: {record['updated_at']} UTC")
        editor(record)
        assessment_editor(profiles, active_profile, selected)
        with st.expander('Delete startup'):
            st.warning('Deletion is permanent. Export your records first if you need a backup.')
            confirmation = st.checkbox('I understand. Delete this startup permanently.', key=f'confirm_{selected}')
            if st.button('Delete startup', disabled=not confirmation, key=f'delete_{selected}'):
                try:
                    store.delete(selected)
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    st.session_state['notice'] = 'Startup deleted.'
                    st.rerun()

st.divider()
st.caption('ScoutAI · Personal research, stored locally in SQLite · No automated AI analysis')
