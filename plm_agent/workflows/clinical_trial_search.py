from typing import List
import asyncio
import elasticsearch
from elasticsearch import AsyncElasticsearch

from utils.core.elasticsearch_client import ElasticsearchClientSingleton


def nct_id_query(nct_ids, query_type='should'):
    queries = {'bool': {query_type: list()}}

    if 'should' in  queries:
        queries['bool']['minimum_should_match'] = 1
    else:
        pass
    for nct_id in nct_ids:
        queries['bool']['should'].append(
            {
                'match': {
                    'nct_id': {
                        'query': nct_id,
                        'operator': 'AND'
                    }
                }
            }
        )
    return queries


def indication_query(indications):
    queries = {'bool': {'should': list(), 'minimum_should_match': 1}}
    for indication in indications:
        queries['bool']['should'].extend(
            [
                {'match': {'indication.llt.en': {'query': indication, 'operator': 'AND'}}},
                {'match': {'indication.pt.en': {'query': indication, 'operator': 'AND'}}},
                {'match': {'indication.hlt.en': {'query': indication, 'operator': 'AND'}}},
                {'match': {'indication.hlgt.en': {'query': indication, 'operator': 'AND'}}},
                {'match': {'indication.soc.en': {'query': indication, 'operator': 'AND'}}}
            ]
        )
    return queries


def drug_name_query(drug_names, query_type='should'):
    queries = {'bool': {query_type: list()}}
    if 'should' in queries['bool']:
        queries['bool']['minimum_should_match'] = 1
    else:
        pass
    for name in drug_names:
        queries['bool'][query_type].append(
            {
                'bool': {
                    'should': [
                        {
                            'match': {
                                'drug.name': {
                                    'query': name,
                                    'operator': 'AND'
                                }
                            }
                        },
                        {
                            'match': {
                                'drug.generic_name': {
                                    'query': name,
                                    'operator': 'AND'
                                }
                            }
                        },
                        {
                            'match': {
                                'drug.other_names': {
                                    'query': name,
                                    'operator': 'AND'
                                }
                            }
                        }
                    ],
                    'minimum_should_match': 1
                }
            }
        )
    return queries


def drug_feature_term_query(drug_features):
    queries = list()
    for feature in drug_features:
        queries.append(
            {
                'term': {
                    'drug.feature.keyword': feature
                }
            }
        )
    return queries


def drug_modality_level_2_term_query(drug_modalities):
    queries = list()
    for modality in drug_modalities:
        queries.extend([
            # {
            #     'term': {
            #         'drug.modality.level_1.en.keyword': modality
            #     }
            # },
            {
                'term': {
                    'drug.modality.level_2.en.keyword': modality
                }
            }
        ])
    return queries


def administration_route_term_query(administration_routes):
    queries = list()
    for ar in administration_routes:
        queries.append(
            {
                'term': {
                    'drug.administration_route.keyword': ar
                }
            }
        )
    return queries


def target_query(targets, query_type='should'):
    queries = {'bool': {query_type: list()}}
    if 'should' in queries['bool']:
        queries['bool']['minimum_should_match'] = 1
    else:
        pass
    for target in targets:
        queries['bool'][query_type].append(
            {
                'bool': {
                    'should': [
                        {
                            'match': {
                                'target.name': {
                                    'query': target,
                                    'operator': 'AND'
                                }
                            }
                        },
                        {
                            'match': {
                                'target.symbol': {
                                    'query': target,
                                    'operator': 'AND'
                                }
                            }
                        }
                    ],
                    'minimum_should_match': 1
                }
            }
        )
    return queries


def company_name_query(company_names):
    queries = {
        'bool': {
            'should': list(),
            'minimum_should_match': 1
        }
    }
    for name in company_names:
        queries['bool']['should'].append(
            {
                'match': {
                    'company.name': {
                        'query': name,
                        'operator': 'AND'
                    }
                }
            }
        )
    return queries


def phase_query(phases, query_type='should'):
    queries = {
        'bool': {
            query_type: list()
        }
    }
    if 'should' in queries['bool']:
        queries['bool']['minimum_should_match'] = 1
    else:
        pass
    for phase in phases:
        queries['bool'][query_type].append(
            {
                'match': {
                    'design.phases': {
                        'query': phase,
                        'operator': 'AND'
                    }
                }
            }
        )
    return queries


def location_query(locations, query_type='should'):
    queries = {
        'bool': {
            query_type: list()
        }
    }
    if 'should' in queries['bool']:
        queries['bool']['minimum_should_match'] = 1
    else:
        pass
    for loc in locations:
        queries['bool'][query_type].append(
            {
                'match': {
                    'location.region': {
                        'query': loc,
                        'operator': 'AND'
                    }
                }
            }
        )
    return queries


async def clinical_trial_search(indication: List[str]=[],
                                company: List[str]=[],
                                target: dict={},
                                drug_name: dict={},
                                drug_modality: dict={},
                                drug_feature: dict={},
                                route_of_administration: dict={},
                                nctids: List[str]=[],
                                phase: List[str]=[],
                                locations: dict={},
                                id: List[int]=[],
                                from_n: int=0,
                                size: int=10,
                                es_url: str='',
                                es_username: str='',
                                es_password: str=''):

    # make queries
    queries = {
        'bool': {
            'should': list(),
            'must': list(),
            'must_not': list(),
            'filter': list()
        }
    }
    # id
    if len(id):
        queries['ids'] = {'values': id}
    else:
        pass

    # indication
    if len(indication):
        indication_q = indication_query(indication)
        queries['bool']['filter'].append(indication_q)
    else:
        pass
    # company
    if len(company):
        company_q = company_name_query(company)
        queries['bool']['filter'].append(company_q)
    else:
        pass
    # target
    if len(target.get('data', [])):
        if target['logic'] == 'or':
            target_q = target_query(target['data'], query_type='should')
            queries['bool']['filter'].append(target_q)
        elif target['logic'] == 'and':
            target_q = target_query(target['data'], query_type='must')
            queries['bool']['must'].extend(target_q['bool']['must'])
        elif target['logic'] == 'not':
            target_q = target_query(target['data'], query_type='should')
            queries['bool']['must_not'].extend(
                target_q['bool']['should']
            )
        else:
            pass
    else:
        pass
    # drug
    if len(drug_name.get('data', [])):
        if drug_name['logic'] == 'or':
            drug_name_q = drug_name_query(drug_name['data'], query_type='should')
            queries['bool']['filter'].append(drug_name_q)
        elif drug_name['logic'] == 'and':
            drug_name_q = drug_name_query(drug_name['data'], query_type='must')
            queries['bool']['must'].extend(drug_name_q['bool']['must'])
        elif drug_name['logic'] == 'not':
            drug_name_q = drug_name_query(drug_name['data'], query_type='should')
            queries['bool']['must_not'].extend(drug_name_q['bool']['should'])
        else:
            pass
    else:
        pass
    # drug_modality
    if len(drug_modality.get('data', [])):
        if drug_modality['logic'] == 'or':
            modality_q = drug_modality_level_2_term_query(drug_modality['data'])
            queries['bool']['filter'].append(
                {
                    'bool': {
                        'should': modality_q,
                        'minimum_should_match': 1
                    }
                }
            )
        elif drug_modality['logic'] == 'and':
            modality_q = drug_modality_level_2_term_query(drug_modality['data'])
            queries['bool']['must'].extend(modality_q)
        elif drug_modality['logic'] == 'not':
            modality_q = drug_modality_level_2_term_query(drug_modality['data'])
            queries['bool']['must_not'].extend(modality_q)
        else:
            pass
    else:
        pass
    # drug_feature
    if len(drug_feature.get('data', [])):
        if drug_feature['logic'] == 'or':
            feature_q = drug_feature_term_query(drug_feature['data'])
            queries['bool']['filter'].append(
                {
                    'bool': {
                        'should': feature_q,
                        'minimum_should_match': 1
                    }
                }
            )
        elif drug_feature['logic'] == 'and':
            feature_q = drug_feature_term_query(drug_feature['data'])
            queries['bool']['must'].extend(feature_q)
        elif drug_feature['logic'] == 'not':
            feature_q = drug_feature_term_query(drug_feature['data'])
            queries['bool']['must_not'].extend(feature_q)
        else:
            pass
    else:
        pass
    # route_of_administration
    if len(route_of_administration.get('data', [])):
        if route_of_administration['logic'] == 'or':
            ar_q = administration_route_term_query(
                route_of_administration['data']
            )
            queries['bool']['filter'].append(
                {
                    'bool': {
                        'should': ar_q,
                        'minimum_should_match': 1
                    }
                }
            )
        elif route_of_administration['logic'] == 'and':
            ar_q = administration_route_term_query(
                route_of_administration['data']
            )
            queries['bool']['must'].extend(ar_q)
        elif route_of_administration['logic'] == 'not':
            ar_q = administration_route_term_query(
                route_of_administration['data']
            )
            queries['bool']['must_not'].extend(ar_q)
        else:
            pass
    else:
        pass
    # nct_id
    if len(nctids):
        nct_q = nct_id_query(nctids, query_type='should')
        queries['bool']['filter'].append(nct_q)
    else:
        pass
    # phase
    phase_mapping = {
        'I': 'PHASE1', 'II': 'PHASE2', 'III': 'PHASE3', 'IV': 'PHASE4'
    }
    converted_phases = list()
    for p in phase:
        if p in phase_mapping:
            converted_phases.append(phase_mapping[p])
        else:
            pass
    if len(converted_phases):
        phase_q = phase_query(converted_phases, query_type='should')
        queries['bool']['filter'].append(phase_q)
    else:
        pass
    # location
    if len(locations.get('data', [])):
        if locations['logic'] == 'or':
            loc_q = location_query(locations['data'], query_type='should')
            queries['bool']['filter'].append(loc_q)
        elif locations['logic'] == 'and':
            loc_q = location_query(locations['data'], query_type='must')
            queries['bool']['must'].extend(loc_q['bool']['must'])
        elif drug_name['logic'] == 'not':
            loc_q = location_query(locations['data'], query_type='should')
            queries['bool']['must_not'].extend(loc_q['bool']['should'])
        else:
            pass
    else:
        pass

    # make query body
    if 'ids' in queries:
        query_body = {
            'query': {'ids': queries['ids']}
        }
    else:
        query_body = {
            'query': queries,
            'size': size if size else 10
        }
        if from_n:
            query_body['from'] = from_n
        else:
            pass
    # search
    if es_url:
        es_client = AsyncElasticsearch(
            hosts=es_url,
            basic_auth=(es_username, es_password)
        )
    else:
        es_client = ElasticsearchClientSingleton.get_asyncclient()

    result = await es_client.search(
        index='noah-tool-clinical_trial',
        body=query_body
    )
    try:
        total_count = result['hits']['total']['value']
    except KeyError:
        total_count = 0
    datalist = [a['_source'] for a in result['hits']['hits']]
    return {'results': datalist, 'total_count': total_count}
