"""English profile management and per-company manual assessment UI."""
import hashlib
from datetime import date
import streamlit as st
from profiles import PRIORITIES, RESULTS

BUILTINS = {
    'sectors': ('Target sectors', 'List the sectors you want to research.'),
    'headquarters': ('Target headquarters countries / regions', 'Company headquarters location, not founder origin or nationality.'),
    'stages': ('Target investment stages', 'List the investment stages relevant to this profile.'),
    'excluded_companies': ('Excluded companies', 'Companies to exclude; manually assess whether the company is excluded.'),
    'excluded_investors': ('Excluded investors', 'Investors to exclude; manually assess the company’s investor relationships.'),
}


def manage_profiles(profiles):
    st.subheader('Scouting Profiles')
    st.write('Define your own research lens. Company facts remain shared; assessments belong to one profile only.')
    st.caption('Blank fields impose no restriction. For exclusion criteria, “Meets” means the company passes the exclusion rule. No automatic matching is performed.')
    all_profiles = profiles.list()
    lookup = {p['id']: p for p in all_profiles}
    chosen = st.selectbox('Profile to manage', [0, *lookup], key='manage_profile', format_func=lambda i: 'Create a new profile' if i == 0 else f"{lookup[i]['name']} · #{i}")
    profile = lookup.get(chosen)
    revision = profile['revision'] if profile else 0
    prefix = f'profile_{chosen}_{revision}'
    criteria = {c['key']: c for c in profile['criteria']} if profile else {}
    with st.form(prefix):
        name = st.text_input('Profile name', key=prefix + '_name', value=profile['name'] if profile else '', max_chars=200)
        values = []
        for key, (label, help_text) in BUILTINS.items():
            col, priority_col = st.columns([3, 1])
            previous = criteria.get(key, {})
            value = col.text_area(label, key=prefix + key + '_value', value=previous.get('value', ''), help=help_text)
            priority = priority_col.selectbox(label + ' priority', PRIORITIES, key=prefix + key + '_priority', index=PRIORITIES.index(previous.get('priority', 'Preferred')))
            values.append(dict(key=key, label=label, value=value, priority=priority))
        models = ('Any', 'B2B', 'B2C', 'B2B2C')
        old_model = criteria.get('business_model', {})
        model = st.selectbox('Business model', models, key=prefix + '_model', index=models.index(old_model.get('value', 'Any')))
        model_priority = st.selectbox('Business model priority', PRIORITIES, key=prefix + '_model_priority', index=PRIORITIES.index(old_model.get('priority', 'Preferred')))
        values.append(dict(key='business_model', label='Business model', value='' if model == 'Any' else model, priority=model_priority))
        st.markdown('**Custom criteria**')
        st.caption('Add rows with a criterion name, a target or rule, and its priority. Empty rules are ignored.')
        custom = [dict(Name=c['label'], Rule=c['value'], Priority=c['priority']) for c in criteria.values() if c['key'].startswith('custom_')]
        import pandas as pd
        custom_rows = st.data_editor(pd.DataFrame(custom, columns=['Name', 'Rule', 'Priority']), num_rows='dynamic', hide_index=True,
            column_config={'Priority': st.column_config.SelectboxColumn(options=list(PRIORITIES), default='Preferred', required=True)}, key=prefix + '_custom')
        submitted = st.form_submit_button('Save profile', type='primary')
    if submitted:
        try:
            for row in custom_rows.fillna('').to_dict('records'):
                label, rule = row['Name'].strip(), row['Rule'].strip()
                if not rule:
                    continue
                values.append(dict(key='custom_' + hashlib.sha256(label.casefold().encode()).hexdigest(), label=label, value=rule, priority=row['Priority'] or 'Preferred'))
            profiles.save(name, values, chosen or None)
        except ValueError as exc:
            st.error(str(exc))
        else:
            st.session_state['notice'] = 'Profile saved. Select it in the sidebar to assess startups.'
            st.rerun()
    if profile:
        st.caption(f"Criteria version: {revision}. Changing criteria requires a fresh review; renaming alone does not.")
        confirm = st.checkbox('Delete this profile and its assessments; keep all startups.', key=f'delete_profile_confirm_{chosen}')
        if st.button('Delete profile', disabled=not confirm):
            profiles.delete(chosen)
            st.session_state['notice'] = 'Profile deleted. Startup records were preserved.'
            st.rerun()


def assessment_editor(profiles, profile_id, startup_id):
    st.subheader('Profile assessment')
    profile = profiles.get(profile_id)
    if not profile:
        st.info('Select an active Scouting Profile in the sidebar to assess this company.')
        return
    state = profiles.state(profile_id, startup_id)
    st.write(f"**{profile['name']}** · {state}")
    history = profiles.history(profile_id, startup_id)
    if state == 'Review needed':
        st.warning('Criteria have changed. Previous results are historical, not current. Review every current criterion before saving.')
    elif state == 'Not evaluated':
        st.info('This startup has not been evaluated for this profile.')
    current = history[0]['responses'] if history and history[0]['revision'] == profile['revision'] else {}
    if profile['criteria']:
        responses = {}
        prefix = f"assessment_{profile_id}_{startup_id}_{profile['revision']}"
        st.caption('Manual assessment only. Unknown is not a failure. Preferred misses never automatically exclude a company. Summary labels refer only to this profile, not an investment recommendation.')
        with st.form(prefix):
            for criterion in profile['criteria']:
                key = criterion['key']
                prior = current.get(key, {})
                st.markdown(f"**{criterion['label']} · {criterion['priority']}**")
                st.text(criterion['value'])
                result = st.selectbox('Result', RESULTS, index=RESULTS.index(prior.get('result', 'Unknown')), key=prefix + key + '_result')
                rationale = st.text_area('Rationale', prior.get('rationale', ''), key=prefix + key + '_rationale')
                source = st.text_input('Source URL', prior.get('source', ''), key=prefix + key + '_source')
                day = st.date_input('Assessment date', value=date.fromisoformat(prior['date']) if prior else date.today(), key=prefix + key + '_date')
                responses[key] = dict(result=result, rationale=rationale, source=source, date=day.isoformat())
            submitted = st.form_submit_button('Save assessment', type='primary')
        if submitted:
            try:
                profiles.assess(profile_id, startup_id, profile['revision'], responses)
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.session_state['notice'] = 'Assessment saved for this profile.'
                st.rerun()
    else:
        st.info('This profile has no restrictions. Add criteria in Scouting Profiles before assessing.')
    if history:
        with st.expander('Saved assessment history'):
            for version in history:
                st.markdown(f"**Criteria version {version['revision']}**" + (' (historical)' if version['revision'] != profile['revision'] else ' (current)'))
                for criterion in version['criteria']:
                    response = version['responses'][criterion['key']]
                    st.text(f"{criterion['label']} ({criterion['priority']}): {criterion['value']}")
                    st.text(f"{response['result']} · {response['date']}\n{response['rationale']}\n{response['source']}")
