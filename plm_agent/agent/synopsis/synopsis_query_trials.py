import os
import re
import logging
import elasticsearch
from typing import Union
from dotenv import load_dotenv
from collections import Counter, defaultdict
import sqlalchemy as sa
import sqlalchemy.orm as orm
from sqlalchemy.ext.automap import automap_base, generate_relationship
from typing import TypedDict, Union, List
load_dotenv()


logger = logging.getLogger(__name__)


class Intervention(TypedDict):
    type: str
    description: str



def inclusion_criteria_numbers(criteria_string):
    inclusion_criteria_match = re.search(
        'Inclusion Criteria:(.+?)(Exclusion Criteria:|$)',
        criteria_string, re.DOTALL | re.IGNORECASE
    )

    if inclusion_criteria_match:
        line_match = re.compile(r'\*\s.+')
        inclusion_criteria_lines = [
            a.strip()
            for a in inclusion_criteria_match.group(1).split('\n')
            if line_match.match(a.strip())
        ]
        return len(inclusion_criteria_lines)
    else:
        return 0


def indication_query(indication, query_type='should'):
    query_dict = {
        'bool': {
            query_type: [
                {
                    'match': {
                        'protocolSection.conditionsModule.conditions': {
                            'query': indication,
                            'operator': 'AND'
                        }
                    }
                }
            ],
        }
    }
    return query_dict


def title_query(query, operator='OR', weight=0.8):
    query_dict = {
        'bool': {
            'should': [
                {
                    'match': {
                        'protocolSection.identificationModule.officialTitle': {
                            'query': query,
                            'boost': weight,
                            'operator': operator
                        }
                    }
                },
                {
                    'match': {
                        'protocolSection.identificationModule.briefTitle': {
                            'query': query,
                            'boost': weight,
                            'operator': operator
                        }
                    }
                }
            ]
        }
    }
    return query_dict


def description_query(query, operator='OR', weight=0.8):
    query_dict = {
        'bool': {
            'should': [
                {
                    'match': {
                        'protocolSection.descriptionModule.briefSummary': {
                            'query': query,
                            'boost': weight,
                            'operator': operator
                        }
                    }
                },
                {
                    'match': {
                        'protocolSection.descriptionModule.detailedDescription': {
                            'query': query,
                            'boost': weight,
                            'operator': operator
                        }
                    }
                }
            ]
        }
    }
    return query_dict


def treatment_line_query(line, weight=0.4):
    '''
    value of line should be one of: first-line, second-line, later-line, rr
    - first-line：First-Line Treatment, Newly Diagnosed, Treatment-Naïve, Initial Therapy, De Novo
    - second-line：Second-Line Treatment, Post First-Line Therapy
    - later-line：Later-Line Treatment, Advanced, Multiple Prior Lines of Therapy
    - rr：Relapsed/Refractory (R/R), Recurrent, Progressive Disease
    '''
    line_values = {
        'first-line': [
            'First-Line Treatment', 'Newly Diagnosed', 'Treatment-Naïve', 'Initial Therapy', 'De Novo'
        ],
        'second-line': [
            'Second-Line Treatment', 'Post First-Line Therapy'
        ],
        'later-line': [
            'Later-Line Treatment', 'Advanced', 'Multiple Prior Lines of Therapy'
        ],
        'rr': [
            'Relapsed/Refractory', '(R/R)', 'Recurrent', 'Progressive Disease'
        ]
    }
    if line not in line_values:
        raise ValueError(
            'line should be one of: [{}]'.format(', '.join(line_values.keys()))
        )
    else:
        pass
    query_dict = {
        'bool': {
            'should': []
        }
    }
    for lv in line_values[line]:
        q = title_query(query=lv, operator='AND', weight=weight)
        query_dict['bool']['should'].extend(q['bool']['should'])
    return query_dict


def health_condition_query(condition, weight=0.3):
    '''
    value of conditon: Healthy Volunteers, HIV-positive, Diabetic, Hypertensive, Obese, Hepatic/Renal Impairment, Liver/Kidney Dysfunction
    '''
        # 'Healthy Volunteers', 'HIV-positive', 'Diabetic',
        # 'Hypertensive', 'Obese', 'Hepatic/Renal Impairment', 'Liver/Kidney Dysfunction'
    valid_conditions = {
        'healthy volunteers': 'Healthy Volunteers',
        'hiv-positive': 'HIV-positive',
        'diabetic': 'Diabetic',
        'hypertensive': 'Hypertensive',
        'obese': 'Obese',
        'hepatic/renal impairment': 'Hepatic/Renal Impairment',
        'liver/kidney dysfunction': 'Liver/Kidney Dysfunction'
    }

    if condition not in valid_conditions:
        raise ValueError(
            'condition should be one of: [{}]'.format(', '.join(valid_conditions.values()))
        )
    else:
        pass
    query_dict = {
        'bool': {
            'should': [
            ]
        }
    }
    q = title_query(query=valid_conditions[condition],
                    operator='AND', weight=weight)
    query_dict['bool']['should'].extend(q['bool']['should'])
    return query_dict


def age_query(age, weight=0.2):
    '''
    age should be one of: [CHILD, ADULT, OLDER_ADULT]
    '''
    valid_ages = ['CHILD', 'ADULT', 'OLDER_ADULT']
    if age not in valid_ages:
        raise ValueError(
            'age should be one of: [{}]'.format(', '.join(valid_ages))
        )
    else:
        pass
    query_dict = {
        'bool': {
            'should': [
                {
                    'match': {
                        'protocolSection.eligibilityModule.stdAges': {
                            'query': age,
                            'boost': weight
                        }
                    }
                }
            ],
        }
    }

    return query_dict


def only_age_query(age):
    '''
    age should be one of: [CHILD, ADULT, OLDER_ADULT]

    return the docs with only the age group
    '''
    valid_ages = ['CHILD', 'ADULT', 'OLDER_ADULT']
    if age not in valid_ages:
        raise ValueError(
            'age should be one of: [{}]'.format(', '.join(valid_ages))
        )
    else:
        pass
    must_not = ' '.join(set(valid_ages) - set([age]))
    query_dict = {
        'bool': {
            'must': [
                {
                    'match': {
                        'protocolSection.eligibilityModule.stdAges': {
                            'query': age
                        }
                    }
                }
            ],
            'must_not': [
                {
                    'match': {
                        'protocolSection.eligibilityModule.stdAges': {
                            'query': must_not,
                            'operator': 'OR'
                        }
                    }
                }
            ]
        }
    }

    return query_dict


def sex_query(sex, weight=0.3):
    '''
    sex should be one of: [FEMALE, MALE, ALL]
    '''
    valid_value = ['FEMALE', 'MALE', 'ALL']
    if sex in ['BOTH']:
        sex = 'ALL'
    else:
        pass
    if sex not in valid_value:
        raise ValueError(
            'sex should be one of: [{}]'.format(', '.join(valid_value))
        )
    else:
        pass
    query_dict = {
        'bool': {
            'should': [
                {
                    'match': {
                        'protocolSection.eligibilityModule.sex': {
                            'query': sex,
                            'boost': weight
                        }
                    }
                }
            ],
        }
    }
    return query_dict


def phase_query(phase):
    '''
    - 1: PHASE1
    - 1/2: PHASE1 & PHASE2
    - 2: PHASE2
    - 2/3: PHASE2 & PHASE3
    - 3: PHASE3
    - 4: PHASE4
    - not_123: Not PHASE1, PHASE2, PHASE3, EARLY_PHASE1
    '''
    if phase == '1':
        query_dict = {
            'bool': {
                'must': [
                    {
                        'match': {
                            'protocolSection.designModule.phases': {
                                'query': 'PHASE1'
                            }
                        }
                    }
                ],
                'must_not': [
                    {
                        'match': {
                            'protocolSection.designModule.phases': {
                                'query': 'PHASE2'
                            }
                        }
                    }
                ]
            }
        }
    elif phase == '1/2':
        query_dict = {
            'bool': {
                'must': [
                    {
                        'match': {
                            'protocolSection.designModule.phases': {
                                'query': 'PHASE1 PHASE2',
                                'operator': 'AND'
                            }
                        }
                    }
                ],
            }
        }
    elif phase == '2':
        query_dict = {
            'bool': {
                'must': [
                    {
                        'match': {
                            'protocolSection.designModule.phases': {
                                'query': 'PHASE2'
                            }
                        }
                    }
                ],
                'must_not': [
                    {
                        'match': {
                            'protocolSection.designModule.phases': {
                                'query': 'PHASE1 PHASE3',
                                'operator': 'OR'
                            }
                        },
                    }
                ]
            }
        }
    elif phase == '2/3':
        query_dict = {
            'bool': {
                'must': [
                    {
                        'match': {
                            'protocolSection.designModule.phases': {
                                'query': 'PHASE2 PHASE3',
                                'operator': 'AND'
                            }
                        }
                    }
                ],
            }
        }
    elif phase == '3':
        query_dict = {
            'bool': {
                'must': [
                    {
                        'match': {
                            'protocolSection.designModule.phases': {
                                'query': 'PHASE3'
                            }
                        }
                    }
                ],
                'must_not': [
                    {
                        'match': {
                            'protocolSection.designModule.phases': {
                                'query': 'PHASE2'
                            }
                        }
                    }
                ]
            }
        }
    elif phase == '4':
        query_dict = {
            'bool': {
                'must': [
                    {
                        'match': {
                            'protocolSection.designModule.phases': {
                                'query': 'PHASE4'
                            }
                        }
                    }
                ],
            }
        }
    elif phase == 'not_123':
        query_dict = {
            'bool': {
                'must_not': [
                    {
                        'terms': {
                            'protocolSection.designModule.phases.keyword': [
                                'PHASE1', 'PHASE2', 'PHASE3', 'EARLY_PHASE1'
                            ]
                        }
                    }
                ],
            }
        }
    else:
        raise ValueError('phase should be one of: [1, 1/2, 2, 2/3, 3, 4, not_123]')
    return query_dict


def masking_query(masking, weight=0.2):
    '''
    masking should be one of: [NONE, SINGLE, DOUBLE, TRIPLE, QUADRUPLE]
    - NONE - None (Open Label)
    - SINGLE - Single
    - DOUBLE - Double
    - TRIPLE - Triple
    - QUADRUPLE - Quadruple
    '''
    valid_value = ['NONE', 'SINGLE', 'DOUBLE', 'TRIPLE', 'QUADRUPLE']
    if masking not in valid_value:
        raise ValueError(
            'masking should be one of: [{}]'.format(', '.join(valid_value))
        )
    else:
        pass
    query_dict = {
        'bool': {
            'should': [
                {
                    'match': {
                        'protocolSection.designModule.designInfo.maskingInfo.masking': {
                            'query': masking,
                            'boost': weight
                            # 'operator': 'AND'
                        }
                    }
                }
            ]
        }
    }
    return query_dict


def study_type_query(study_type, weight=1.0):
    '''
    study type should be one of: [EXPANDED_ACCESS, INTERVENTIONAL, OBSERVATIONAL]
    '''
    valid_value = [
        'EXPANDED_ACCESS', 'INTERVENTIONAL', 'OBSERVATIONAL'
    ]
    if study_type not in valid_value:
        raise ValueError(
            'study_type should be one of: [{}]'.format(', '.join(valid_value))
        )
    else:
        pass
    query_dict = {
        'bool': {
            'must': [
                {
                    'match': {
                        'protocolSection.designModule.studyType': {
                            'query': study_type,
                            'boost': weight
                            # 'operator': 'AND'
                        }
                    }
                }
            ]
        }
    }
    return query_dict


def intervention_model_query(intervention, weight=0.2, query_type='should'):
    '''
    intervention should be one of: [SINGLE_GROUP, PARALLEL, CROSSOVER, FACTORIAL, SEQUENTIAL]
    - SINGLE_GROUP - Single Group Assignment
    - PARALLEL - Parallel Assignment
    - CROSSOVER - Crossover Assignment
    - FACTORIAL - Factorial Assignment
    - SEQUENTIAL - Sequential Assignment
    '''
    valid_value = [
        'SINGLE_GROUP', 'PARALLEL', 'CROSSOVER', 'FACTORIAL', 'SEQUENTIAL'
    ]
    if intervention not in valid_value:
        raise ValueError(
            'intervention should be one of: [{}]'.format(
                ', '.join(valid_value)
            )
        )
    else:
        pass
    query_dict = {
        'bool': {
            query_type: [
                {
                    'match': {
                        'protocolSection.designModule.designInfo.interventionModel': {
                            'query': intervention,
                            'boost': weight
                            # 'operator': 'AND'
                        }
                    }
                }
            ]
        }
    }
    return query_dict


def observational_model_query(observational_model, weight=1.0, query_type='should'):
    '''
    observational model should be one of: [
        COHORT, CASE_CONTROL, CASE_ONLY, OTHER,
        ECOLOGIC_OR_COMMUNITY, CASE_CROSSOVER, DEFINED_POPULATION,
        FAMILY_BASED, NATURAL_HISTORY
    ]
    '''
    valid_value = [
        'COHORT', 'CASE_CONTROL', 'CASE_ONLY', 'OTHER',
        'ECOLOGIC_OR_COMMUNITY', 'CASE_CROSSOVER', 'DEFINED_POPULATION',
        'FAMILY_BASED', 'NATURAL_HISTORY'
    ]
    if observational_model not in valid_value:
        raise ValueError(
            'observational_model should be one of: [{}]'.format(
                ', '.join(valid_value)
            )
        )
    else:
        pass
    query_dict = {
        'bool': {
            query_type: [
                {
                    'match': {
                        'protocolSection.designModule.designInfo.observationalModel': {
                            'query': observational_model,
                            'boost': weight
                            # 'operator': 'AND'
                        }
                    }
                }
            ]
        }
    }
    return query_dict


def time_perspective_query(time_perspective, weight=1.0, query_type='should'):
    '''
    time perspective should be one of: [
        PROSPECTIVE, RETROSPECTIVE, CROSS_SECTIONAL, OTHER
    ]
    '''
    valid_value = [
        'PROSPECTIVE', 'RETROSPECTIVE', 'CROSS_SECTIONAL', 'OTHER'
    ]
    if time_perspective not in valid_value:
        raise ValueError(
            'time_perspective should be one of: [{}]'.format(
                ', '.join(valid_value)
            )
        )
    else:
        pass
    query_dict = {
        'bool': {
            query_type: [
                {
                    'match': {
                        'protocolSection.designModule.designInfo.timePerspective': {
                            'query': time_perspective,
                            'boost': weight
                            # 'operator': 'AND'
                        }
                    }
                }
            ]
        }
    }
    return query_dict


def intervention_query(intervention_type, intervention_text=None,
                       query_weight=1.0, text_weight=0.5):
    '''
    query interventions
    '''
    valid_value = [
        'DRUG', 'OTHER', 'DEVICE', 'BEHAVIORAL', 'PROCEDURE',
        'BIOLOGICAL', 'DIAGNOSTIC_TEST', 'DIETARY_SUPPLEMENT',
        'RADIATION', 'COMBINATION_PRODUCT', 'GENETIC'
    ]
    if intervention_type not in valid_value:
        raise ValueError(
            'intervention_type should be one of: [{}]'.format(
                ', '.join(valid_value)
            )
        )
    else:
        pass
    query_dict = {
        'bool': {
            'should': [
                {
                    'match': {
                        'protocolSection.armsInterventionsModule.interventions.type': {
                            'query': intervention_type,
                            'boost': query_weight,
                            'operator': 'OR'
                        }
                    }
                }
            ]
        }
    }
    if intervention_text:
        query_dict['bool']['should'].append(
            {
                'match': {
                    'protocolSection.armsInterventionsModule.interventions.name': {
                        'query': intervention_text,
                        'boost': text_weight,
                        'operator': 'OR'
                    }
                }
            }
        )
        query_dict['bool']['should'].append(
            {
                'match': {
                    'protocolSection.armsInterventionsModule.interventions.description': {
                        'query': intervention_text,
                        'boost': text_weight,
                        'operator': 'OR'
                    }
                }
            }
        )
    else:
        pass
    return query_dict


def outcome_query(outcome, weight=0.3):
    '''
    including primaryOutcomes, secondaryOutcomes, and otherOutcomes
    '''
    query_dict = {
        'bool': {
            'should': [
                {
                    'multi_match': {
                        'query': outcome,
                        'fields': [
                            'protocolSection.outcomesModule.primaryOutcomes.measure^{}'.format(weight),
                            'protocolSection.outcomesModule.secondaryOutcomes.measure^{}'.format(weight),
                            'protocolSection.outcomesModule.otherOutcomes.measure^{}'.format(weight),
                            'protocolSection.outcomesModule.primaryOutcomes.description^{}'.format(weight),
                            'protocolSection.outcomesModule.secondaryOutcomes.description^{}'.format(weight),
                            'protocolSection.outcomesModule.otherOutcomes.description^{}'.format(weight),
                        ],
                    }
                }
            ]
        }
    }
    return query_dict


def location_query(location, weight=0.1):
    '''
    location should be one of [CN, US, EU, JP, Other]
    - CN: China, including HK, TW, MO
    - US: United Status
    - EU: European Union countries, including: AT, BE, BG, CY, CZ, DE, DK, EE, EL, ES, FI, FR, HR, HU, IE, IT, LT, LU, LV, MT, NL, PL, PT, RO, SE, SI, SK
    - JP: Japan
    - Other
    '''
    valid_location = ['CN', 'US', 'EU', 'JP', 'Other']
    if location not in valid_location:
        raise ValueError(
            'location should be one of: [{}]'.format(
                ', '.join(valid_location)
            )
        )
    else:
        pass
    query_dict = {
        'bool': {
            'should': list()
        }
    }
    if location == 'CN':
        query_dict['bool']['should'].append(
            {
                'match': {
                    'protocolSection.contactsLocationsModule.locations.country': {
                        'query': 'China Taiwan Hong Kong Macau',
                        'operator': 'OR',
                        'boost': weight
                    }
                }
            }
        )
    elif location == 'US':
        query_dict['bool']['should'].append(
            {
                'match': {
                    'protocolSection.contactsLocationsModule.locations.country': {
                        'query': 'United States',
                        'operator': 'AND',
                        'boost': weight
                    }
                }
            }
        )
    elif location == 'EU':
        query_dict['bool']['should'].append(
            {
                'match': {
                    'protocolSection.contactsLocationsModule.locations.country': {
                        'query': 'Austria Belgium Bulgaria Cyprus Czech Germany Denmark Estonia Greece Spain Finland France Croatia Hungary Ireland Italy Lithuania Luxembourg Latvia Malta Netherlands Poland Portugal Romania Sweden Slovenia Slovakia',
                        'operator': 'OR',
                        'boost': weight
                    }
                }
            }
        )
    elif location == 'JP':
        query_dict['bool']['should'].append(
            {
                'match': {
                    'protocolSection.contactsLocationsModule.locations.country': {
                        'query': 'Japan',
                        'operator': 'AND',
                        'boost': weight
                    }
                }
            }
        )
    else:
        raise ValueError(
            'location should be one of: [{}]'.format(', '.join(valid_location))
        )
    return query_dict


def make_query_body(indication: Union[str, List[str]] = None,
                    phase: str = None,
                    treatment_line: str = None,
                    treatment_line_weight: float = 0.4,
                    health_condition: str = None,
                    health_condition_weight: float = 0.3,
                    sex: str = None,
                    sex_weight: float = 0.3,
                    only_age: str = None,
                    age: str = None,
                    age_weight: float = 0.2,
                    study_type: str = None,
                    study_type_weight: float = 1.0,
                    intervention_model: str = None,
                    intervention_model_weight: float = 0.2,
                    intervention_model_query_type: str = 'should',
                    observational_model: str = None,
                    observational_model_weight: float = 1.0,
                    observational_model_query_type: str = 'should',
                    time_perspective: str = None,
                    time_perspective_weight: float = 1.0,
                    time_perspective_query_type: str = 'should',
                    intervention_type: Union[str, List[str]] = None,
                    intervention_text: Union[str, List[str]] = None,
                    intervention_type_weight: float = 1.0,
                    intervention_text_weight: float = 0.5,
                    masking: str = None,
                    masking_weight: float = 0.2,
                    outcome: Union[str, list] = None,
                    outcome_weight: float = 0.3,
                    location: str = None,
                    location_weight: float = 0.1,
                    title: str = None,
                    title_weight: float = 0.8,
                    description: str = None,
                    description_weight: float = 0.8,
                    size=500):
    query_info = dict()
    if indication and isinstance(indication, str):
        query_info['indication'] = indication_query(indication, query_type='must')
    elif indication and isinstance(indication, List):
        for i, indi in enumerate(indication):
            query_info['indication_{}'.format(i)] = indication_query(
                indi, query_type='should'
            )
    else:
        pass
    if phase:
        query_info['phase'] = phase_query(phase)
    else:
        pass
    if treatment_line:
        query_info['treatment_line'] = treatment_line_query(
            treatment_line.lower(),
            weight=treatment_line_weight
        )
    else:
        pass
    if health_condition:
        query_info['health_condition'] = health_condition_query(
            health_condition.lower(),
            weight=health_condition_weight
        )
    else:
        pass
    if only_age:
        query_info['age'] = only_age_query(only_age.upper())
    else:
        pass
    if age:
        query_info['age'] = age_query(age.upper(), weight=age_weight)
    else:
        pass
    if sex:
        query_info['sex'] = sex_query(
            sex.upper(),
            weight=sex_weight
        )
    else:
        pass
    if study_type:
        query_info['study_type'] = study_type_query(
            study_type.upper(),
            weight=study_type_weight,
        )
    else:
        pass
    if intervention_model:
        query_info['intervention_model'] = intervention_model_query(
            intervention_model.upper(),
            weight=intervention_model_weight,
            query_type=intervention_model_query_type
        )
    else:
        pass
    if observational_model:
        query_info['observational_model'] = observational_model_query(
            observational_model.upper(),
            weight=observational_model_weight,
            query_type=observational_model_query_type
        )
    else:
        pass
    if time_perspective:
        query_info['time_perspective'] = time_perspective_query(
            time_perspective.upper(),
            weight=time_perspective_weight,
            query_type=time_perspective_query_type
        )
    else:
        pass
    if intervention_type and isinstance(intervention_type, str):
        query_info['intervention'] = intervention_query(
            intervention_type=intervention_type,
            intervention_text=intervention_text,
            query_weight=intervention_type_weight,
            text_weight=intervention_text_weight,
        )
    elif intervention_type and isinstance(intervention_type, List):
        i_type_list = intervention_type
        if isinstance(intervention_text, list) and \
           (len(intervention_type) == len(intervention_text)):
            i_text_list = intervention_text
        else:
            i_text_list = [None] * len(i_type_list)
        for i, q in enumerate(zip(i_type_list, i_text_list)):
            query_info['intervention_{}'.format(i)] = intervention_query(
                intervention_type=q[0],
                intervention_text=q[1],
                query_weight=intervention_type_weight,
                text_weight=intervention_text_weight,
            )
    else:
        pass
    if masking:
        query_info['masking'] = masking_query(
            masking.upper(),
            weight=masking_weight
        )
    else:
        pass
    if outcome and isinstance(outcome, str):
        query_info['outcome'] = outcome_query(
            outcome,
            weight=outcome_weight
        )
    elif outcome and isinstance(outcome, List):
        for i, oc in enumerate(outcome):
            query_info['outcome_{}'.format(i)] = outcome_query(
                oc,
                weight=outcome_weight
            )
    else:
        pass
    if location:
        query_info['location'] = location_query(
            location,
            weight=location_weight
        )
    else:
        pass
    if title:
        query_info['title'] = title_query(
            query=title,
            weight=title_weight
        )
    else:
        pass
    if description:
        query_info['description'] = description_query(
            query=description,
            weight=description_weight
        )
    else:
        pass

    must = list()
    must_not = list()
    should = list()
    filters = list()

    for label, qd in query_info.items():
        if 'must' in qd['bool']:
            must.extend(qd['bool']['must'])
        else:
            pass
        if 'must_not' in qd['bool']:
            must_not.extend(qd['bool']['must_not'])
        else:
            pass
        if 'should' in qd['bool']:
            should.extend(qd['bool']['should'])
        else:
            pass
        if 'filter' in qd['bool']:
            filters.extend(qd['bool']['filter'])
        else:
            pass

    search_body = {
        'query': {
            'bool': dict()
        },
        'size': size,
    }
    if len(must):
        search_body['query']['bool']['must'] = must
    else:
        pass
    if len(must_not):
        search_body['query']['bool']['must_not'] = must_not
    else:
        pass
    if len(should):
        search_body['query']['bool']['should'] = should
    else:
        pass
    if len(filters):
        search_body['query']['bool']['filter'] = filters
    else:
        pass

    return search_body


def module_name_for_table(cls, tablename, table):
    if table.schema is not None:
        return f"{table.schema}"
    else:
        return "default"


def get_result_summary(dbstring, nct_ids):
    engine = sa.create_engine(dbstring)
    try:
        NoahBase = automap_base()
        NoahBase.prepare(autoload_with=engine,
                         schema='noah',
                         modulename_for_table=module_name_for_table)

        table_outcome = NoahBase.metadata.tables['noah.clinical_trial_result_summary']

        outcomes = defaultdict(dict)
        with engine.connect() as conn:
            query = """
            SELECT cross.nct_id AS nct_id,
                   rs.noah_clinical_trial_id AS noah_id,
                   rs.design, rs.efficacy, rs.safety, rs.key_findings
            FROM crossdb.clinical_trial_noah_nct AS cross
            INNER JOIN noah.clinical_trial_result_summary AS rs
            ON rs.clinical_trial_id = cross.noah_clinical_trial_id
            WHERE cross.nct_id IN ({});
            """.format(','.join(["'{}'".format(a) for a in nct_ids]))
            cursor = conn.execute(sa.text(query))
            for a in cursor:
                outcomes[a[0]] = dict(zip(cursor.keys(), a))
        return outcomes
    finally:
        engine.dispose()


def get_brief_outcomes(dbstring, nct_ids):
    engine = sa.create_engine(dbstring)
    try:
        NoahBase = automap_base()
        NoahBase.prepare(autoload_with=engine,
                         schema='noah',
                         modulename_for_table=module_name_for_table)

        table_outcome = NoahBase.metadata.tables['noah.patch_clinical_trial_outcome']

        outcomes = defaultdict(list)
        with engine.connect() as conn:
            result_cursor = conn.execute(
                sa.select(table_outcome).where(table_outcome.c.nct_id.in_(nct_ids))
            )
            for a in result_cursor:
                outcomes[a[1]].append(
                    dict(zip(['id', 'nct_id', 'outcome', 'outcome_type'], a))
                )
        return outcomes
    finally:
        engine.dispose()


def format_trial_info(trial):
    simplified = dict()
    # id
    simplified['id'] = trial['id']
    simplified['identificationModule'] = trial['protocolSection']['identificationModule']
    # description
    simplified['description'] = trial['protocolSection'].get(
        'descriptionModule',
        {'detailedDescription': ''}
    ).get('detailedDescription', '')
    if not simplified['description']:
        simplified['description'] = trial['protocolSection'].get(
            'descriptionModule',
            {'briefSummary': ''}
        ).get('briefSummary', '')
    else:
        pass
    # location
    location_dict = {
        'CN': ['China', 'Taiwan', 'Hong Kong', 'Macau'],
        'US': ['United States'],
        'EU': ['Austria', 'Belgium', 'Bulgaria', 'Cyprus', 'Czech Republic', 'Germany',
               'Denmark', 'Estonia', 'Greece', 'Spain', 'Finland', 'France',
               'Croatia', 'Hungary', 'Ireland', 'Italy', 'Lithuania', 'Luxembourg',
               'Latvia', 'Malta', 'Netherlands', 'Poland', 'Portugal', 'Romania',
               'Sweden', 'Slovenia', 'Slovakia'],
        'JP': ['Japan']
    }
    location_2_group = dict()
    for k, v in location_dict.items():
        for name in v:
            location_2_group[name] = k

    if 'contactsLocationsModule' in trial['protocolSection']:
        if 'locations' in trial['protocolSection']['contactsLocationsModule']:
            locations = trial['protocolSection']['contactsLocationsModule']['locations']
        else:
            locations = list()
    else:
        locations = list()

    location_count = Counter()
    for loc in locations:
        country = loc.get('country', '')
        if country in location_2_group:
            location_count[location_2_group[country]] += 1
        else:
            location_count['Other'] += 1
    simplified['location'] = dict(location_count)
    # design
    simplified['designModule'] = trial['protocolSection'].get(
        'designModule', dict()
    )
    # eligibility
    simplified['eligibilityModule'] = trial['protocolSection'].get(
        'eligibilityModule', dict()
    )
    # status
    simplified['statusModule'] = trial['protocolSection'].get(
        'statusModule', dict()
    )
    # outcome
    original_outcome = trial['protocolSection'].get(
        'outcomesModule', dict()
    )
    outcome_measures = defaultdict(list)
    for key in original_outcome:
        for mvalue in original_outcome[key]:
            outcome_measures[key].append(mvalue.get('measure', ''))
    simplified['outcomesModule'] = outcome_measures
    # armsInterventionsModule
    simplified['armsInterventionsModule'] = trial['protocolSection'].get(
        'armsInterventionsModule', dict()
    )
    # sponsorCollaboratorsModule
    simplified['sponsorCollaboratorsModule'] = trial['protocolSection'].get(
        'sponsorCollaboratorsModule', dict()
    )
    # conditionsModule
    simplified['conditionsModule'] = trial['protocolSection'].get(
        'conditionsModule', dict()
    )

    return simplified


def execute_search(es_url,
                   es_username,
                   es_password,
                   index,
                   search_body):
    es_client = elasticsearch.Elasticsearch(
        hosts=es_url,
        basic_auth=(es_username, es_password)
    )
    try:
        search_result = es_client.search(
            index=index,
            body=search_body
        )
    except Exception as e:
        logger.warning(e, 'failed retrying')
        es_client = elasticsearch.Elasticsearch(
            hosts=es_url,
            basic_auth=(es_username, es_password)
        )
        search_result = es_client.search(
            index=index,
            body=search_body
        )
    return search_result


def search_trials(indication: str = None,
                  phase: str = None,
                  treatment_line: str = None,
                  health_condition: str = None,
                  sex: str = None,
                  age: str = None,
                  intervention_model: str = None,
                  masking: str = None,
                  outcome: str = None,
                  location: str = None,
                  **kwargs):
    es_url = os.getenv('ES_URL')
    es_username = os.getenv('ES_USERNAME')
    es_password = os.getenv('ES_PASSWORD')
    dbstring = os.getenv('DB_STRING_GOLDEN')
    # first search
    search_body = make_query_body(indication=indication,
                                  phase=phase,
                                  treatment_line=treatment_line,
                                  health_condition=health_condition,
                                  health_condition_weight=0.3,
                                  sex=sex,
                                  sex_weight=0.3,
                                  only_age=age,
                                  intervention_model=intervention_model,
                                  intervention_model_weight=0.2,
                                  masking=masking,
                                  masking_weight=0.2,
                                  outcome=outcome,
                                  outcome_weight=0.3,
                                  location=location,
                                  location_weight=0.1)
    search_result = execute_search(es_url=es_url,
                                   es_username=es_username,
                                   es_password=es_password,
                                   index='clinicaltrials.gov-clinical_trial',
                                   search_body=search_body)
    hits = search_result['hits']['hits']
    ids_have = [a['_id'] for a in hits]
    # check numbers
    if len(hits) <= 10:
        if phase in ['1/2', '2/3']:
            phases = phase.split('/')
            for p in phases:
                search_body = make_query_body(indication=indication,
                                              phase=p,
                                              treatment_line=treatment_line,
                                              health_condition=health_condition,
                                              health_condition_weight=0.3,
                                              sex=sex,
                                              sex_weight=0.3,
                                              age=age,
                                              intervention_model=intervention_model,
                                              intervention_model_weight=0.2,
                                              masking=masking,
                                              masking_weight=0.2,
                                              outcome=outcome,
                                              outcome_weight=0.3,
                                              location=location,
                                              location_weight=0.1)
                search_result = execute_search(es_url=es_url,
                                               es_username=es_username,
                                               es_password=es_password,
                                               index='clinicaltrials.gov-clinical_trial',
                                               search_body=search_body)
                for hit in search_result['hits']['hits']:
                    if hit['_id'] not in ids_have:
                        hits.append(hit)
                        ids_have.append(hit['_id'])
                    else:
                        pass
        else:
            search_body = make_query_body(indication=indication,
                                          phase=phase,
                                          treatment_line=treatment_line,
                                          health_condition=health_condition,
                                          health_condition_weight=0.3,
                                          sex=sex,
                                          sex_weight=0.3,
                                          age=age)
            search_result = execute_search(es_url=es_url,
                                           es_username=es_username,
                                           es_password=es_password,
                                           index='clinicaltrials.gov-clinical_trial',
                                           search_body=search_body)
            for hit in search_result['hits']['hits']:
                if hit['_id'] not in ids_have:
                    hits.append(hit)
                    ids_have.append(hit['_id'])
                else:
                    pass
    elif len(hits) > 50:
        old_hits = hits
        hits = list()
        for hit in old_hits:
            criteria_string = hit['_source'].get(
                'protocolSection', {}
            ).get('eligibilityModule', {}).get('eligibilityCriteria', '')
            line_num = inclusion_criteria_numbers(criteria_string)
            if line_num >= 8:
                hits.append(hit)
            else:
                pass
    else:
        # hits 数量在 [10, 50] 之间直接作为结果
        pass
    # format trial dict
    trials = [format_trial_info(hit['_source']) for hit in hits]
    # brief outcome
    if dbstring:
        nct_ids = [trial['identificationModule']['nctId'] for trial in trials]
        brief_measures_dict = get_brief_outcomes(
            dbstring=dbstring,
            nct_ids=nct_ids
        )
        for i, trial in enumerate(trials):
            nct_id = trial['identificationModule']['nctId']
            if nct_id in brief_measures_dict:
                measures_list = brief_measures_dict[nct_id]
                brief_measures = defaultdict(list)
                for mvalue in measures_list:
                    brief_measures[mvalue['outcome_type']].append(
                        mvalue['outcome']
                    )
                if len(brief_measures):
                    trials[i]['outcomesModule'] = brief_measures
                else:
                    pass
        else:
            pass
    else:
        pass

    logger.debug("len(trials): {}".format(len(trials)))
    return trials, kwargs


def search_trials_phase4(study_type: str=None,
                         indication: Union[str, List[str]] = None,
                         phase: str = '4',
                         treatment_line: str = None,
                         health_condition: str = None,
                         sex: str = None,
                         age: str = None,
                         interventions: List[Intervention] = None,
                         masking: str = None,
                         outcome: Union[str, list] = None,
                         location: str = None,
                         **kwargs):
    es_url = os.getenv('ES_URL')
    es_username = os.getenv('ES_USERNAME')
    es_password = os.getenv('ES_PASSWORD')
    dbstring = os.getenv('DB_STRING_GOLDEN')
    # converts
    # specific phase query for phase4
    if phase == '4':
        phase = 'not_123'
    else:
        pass
    # study_type mapping
    if study_type and (study_type in ['PROSPECTIVE_COHORT', 'RETROSPECTIVE_COHORT', 'DUAL_COHORT'] or study_type.endswith('_COHORT')):
        study_type = 'COHORT'
    else:
        pass
    # intervention list to intervention_type and intervention_text
    intervention_type_list = []
    intervention_text_list = []
    if interventions:
        # intervention must have a type
        intervention_type_list.extend([
            a.get('type', '') for a in interventions if a.get('type')
        ])
        intervention_text_list.extend([
            a.get('description', '') for a in interventions if a.get('type')
        ])
    else:
        pass
    # first search
    if study_type in [
        'COHORT', 'CASE_CONTROL'
    ]:
        search_body = make_query_body(indication=indication,
                                      phase=None,
                                      treatment_line=treatment_line,
                                      health_condition=health_condition,
                                      health_condition_weight=0.3,
                                      sex=sex,
                                      sex_weight=0.1,
                                      age=age,
                                      age_weight=0.2,
                                      study_type='OBSERVATIONAL',
                                      study_type_weight=1.0,
                                      observational_model=study_type,
                                      observational_model_weight=1.0,
                                      observational_model_query_type='must',
                                      intervention_type=intervention_type_list,
                                      intervention_text=intervention_text_list,
                                      intervention_type_weight=1.0,
                                      intervention_text_weight=0.5,
                                      masking=masking,
                                      masking_weight=0.2,
                                      outcome=outcome,
                                      outcome_weight=0.3,
                                      location=location,
                                      location_weight=0.1,
                                      size=100)
    elif study_type == 'CROSS_SECTIONAL':
        search_body = make_query_body(indication=indication,
                                      phase=phase,
                                      treatment_line=treatment_line,
                                      health_condition=health_condition,
                                      health_condition_weight=0.3,
                                      sex=sex,
                                      sex_weight=0.3,
                                      age=age,
                                      age_weight=0.2,
                                      study_type='OBSERVATIONAL',
                                      study_type_weight=1.0,
                                      time_perspective=study_type,
                                      time_perspective_weight=1.0,
                                      intervention_type=intervention_type_list,
                                      intervention_text=intervention_text_list,
                                      intervention_type_weight=1.0,
                                      intervention_text_weight=0.5,
                                      masking=masking,
                                      masking_weight=0.2,
                                      outcome=outcome,
                                      outcome_weight=0.3,
                                      location=location,
                                      location_weight=0.1,
                                      title='cross-sectional',
                                      title_weight=1.0,
                                      description='cross-sectional',
                                      description_weight=1.0,
                                      size=100)
    elif study_type in [
            'SINGLE_GROUP', 'PARALLEL', 'CROSSOVER', 'FACTORIAL', 'SEQUENTIAL'
    ]:
        search_body = make_query_body(indication=indication,
                                      phase=phase,
                                      treatment_line=treatment_line,
                                      health_condition=health_condition,
                                      health_condition_weight=0.3,
                                      sex=sex,
                                      sex_weight=0.3,
                                      age=age,
                                      age_weight=0.2,
                                      study_type='INTERVENTIONAL',
                                      study_type_weight=1.0,
                                      intervention_model=study_type,
                                      intervention_model_weight=1.0,
                                      intervention_model_query_type='must',
                                      intervention_type=intervention_type_list,
                                      intervention_text=intervention_text_list,
                                      intervention_type_weight=1.0,
                                      intervention_text_weight=0.5,
                                      masking=masking,
                                      masking_weight=0.2,
                                      outcome=outcome,
                                      outcome_weight=0.3,
                                      location=location,
                                      location_weight=0.1,
                                      size=100)
    else:
        search_body = make_query_body(indication=indication,
                                      phase=phase,
                                      treatment_line=treatment_line,
                                      health_condition=health_condition,
                                      health_condition_weight=0.3,
                                      sex=sex,
                                      sex_weight=0.3,
                                      age=age,
                                      age_weight=0.2,
                                      intervention_type=intervention_type_list,
                                      intervention_text=intervention_text_list,
                                      intervention_type_weight=1.0,
                                      intervention_text_weight=0.5,
                                      masking=masking,
                                      masking_weight=0.2,
                                      outcome=outcome,
                                      outcome_weight=0.3,
                                      location=location,
                                      location_weight=0.1,
                                      size=100)
    search_result = execute_search(es_url=es_url,
                                   es_username=es_username,
                                   es_password=es_password,
                                   index='clinicaltrials.gov-clinical_trial',
                                   search_body=search_body)
    hits = search_result['hits']['hits']
    ids_have = [a['_id'] for a in hits]
    # format trial dict
    trials = [format_trial_info(hit['_source']) for hit in hits]
    return trials, kwargs
