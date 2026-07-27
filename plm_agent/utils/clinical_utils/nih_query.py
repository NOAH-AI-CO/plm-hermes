import logging
import requests
from utils.clinical_utils.nih_valid_values import (
    valid_Status,
    valid_Phase,
    valid_StudyType,
    valid_Sex,
    valid_LocationCountry
)

# https://clinicaltrials.gov/data-api/api
# https://clinicaltrials.gov/find-studies/constructing-complex-search-queries

# Queries
# https://clinicaltrials.gov/data-api/about-api/search-areas
#   query.cond: condition/disease
#   query.term: other
#   query.locn: location
#   query.titles: titles
#   query.intr: intervention/treatment/drug
#   query.id: NCT IDs

# Filters
# filter.* or postFilter.*, the postFilter will be applied after aggFilters.
# Without aggregation, they are the same.
#   filter.overallStatus: values are limited
#     example: [NOT_YET_RECRUITING, RECRUITING]
#     allowed values:
#       - ACTIVE_NOT_RECRUITING COMPLETED
#       - ENROLLING_BY_INVITATION
#       - NOT_YET_RECRUITING
#       - RECRUITING
#       - SUSPENDED
#       - TERMINATED
#       - WITHDRAWN
#       - AVAILABLE
#       - NO_LONGER_AVAILABLE
#       - TEMPORARILY_NOT_AVAILABLE
#       - APPROVED_FOR_MARKETING
#       - WITHHELD
#       - UNKNOWN
#   filter.advanced:
#     example: Phase: ARER[Phase]PHASE1 OR ARER[Phase]PHASE2

# Valid values
# LocationCountry:
#   - https://clinicaltrials.gov/api/v2/stats/field/values?fields=LocationCountry

def filter_field_status(status_list):
    # status: a list of
    # generate OR relationship of the status
    
    status_v = [s for s in status_list if s in valid_Status]
    text = '{}'.format(', '.join(status_v))
    return text


def advanced_filter_field_phases(phase_list):
    # phases: a list of phases: PHASE1, PHASE2, PHASE3, PHASE4
    # generate OR relationship of the phases
    text_list = list()

    for phase in phase_list:
        phase = phase.replace(' ', '').upper()
        if phase in valid_Phase:
            text_list.append('AREA[Phase]{}'.format(phase))
        else:
            pass

    return '(' + ' OR '.join(text_list) + ')'


def advanced_filter_field_study_type(type_list):
    text_list = list()

    for st in type_list:
        st = st.upper()
        if st in valid_StudyType:
            text_list.append('AREA[StudyType]{}'.format(st))
        else:
            pass

    return '(' + ' OR '.join(text_list) + ')'


def advanced_filter_field_gender(gender):
    gender = gender.upper()
    if gender in valid_Sex:
        return '(AREA[Sex]{})'.format(gender.upper())
    else:
        return ''


def advanced_filter_field_location(location_list):
    # https://clinicaltrials.gov/api/v2/stats/field/values?fields=LocationCountry
    # LocationCountry values
    text_list = list()

    for loc in location_list:
        if loc in valid_LocationCountry:
            text_list.append('AREA[LocationCountry]{}'.format(loc))
        else:
            pass

    return '(' + ' OR '.join(text_list) + ')'


def combine_advanced_filters(filters):
    return ' AND '.join(filters)    


def nih_query_clinical_trials(question='',
                              disease='',
                              sponsor='',
                              outcome='',
                              drugs=[],
                              ids=[],
                              filter_phases=[],
                              filter_gender='ALL',
                              filter_locations=[],
                              filter_status=[],
                              filter_study_types=[],
                              pagesize=5):
    # fields = ['NCTId', 'BriefTitle', 'Phase']
    url = 'https://clinicaltrials.gov/api/v2/studies'
    params = {
        'query.term': question,
        'query.cond': disease, # disease name
        'query.intr': ' OR '.join(drugs), # drug name
        'query.lead': sponsor, # lead sponsor
        'query.outc': outcome,
        'query.id': ','.join(ids),
        'pageSize': pagesize,
        'format': 'json',
        # 'fields': fields
    }
    # add filter of status
    if filter_status:
        params['filter.overallStatus'] = filter_field_status(filter_status)
    else:
        pass

    advanced_filters = list()
    # add filter of Phase
    if filter_phases:
        advanced_filters.append(
            advanced_filter_field_phases(filter_phases)
        )
    else:
        pass
    # add filter of study types
    if filter_study_types and isinstance(filter_study_types, list):
        advanced_filters.append(
            advanced_filter_field_study_type(filter_study_types)
        )
    else:
        pass
    # add filter of patient gender
    if filter_gender in ['MALE', 'FEMALE']:
        gender_filter_text = advanced_filter_field_gender(filter_gender)
        if gender_filter_text:
            advanced_filters.append(gender_filter_text)
        else:
            pass
    else:
        pass
    # add filter of locations
    if filter_locations and isinstance(filter_locations, list):
        location_filter_text = advanced_filter_field_location(
            filter_locations
        )
        advanced_filters.append(location_filter_text)
    else:
        pass

    params['filter.advanced'] = combine_advanced_filters(advanced_filters)
    
    # remove empty parameters
    empty_value_keys = list()
    for k in params:
        if not params[k]:
            empty_value_keys.append(k)
        else:
            pass

    for k in empty_value_keys:
        del params[k]

    if 'fields' in params:
        if isinstance(params['fields'], list):
            params['fields'] = '[' + ','.join(params['fields']) + ']'
        else:
            del params['fields']
    else:
        pass


    # Make a GET request to the API
    print(params)
    response = requests.get(url, params=params)
    results = list()
    if response.status_code == 200:
        content = response.json()
        # parse returned json
        for study in content['studies']:
            try:
                trial = study
                results.append(trial)
            except KeyError:
                pass
    else:
        pass

    return results
