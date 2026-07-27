from typing import List

from sqlalchemy import text

from utils.sql_client import get_connection
from utils.core.timer import async_timer
from utils.clinical_utils.common import get_drug_ids, generate_conditions_and_params


async def drug_compete(
    drug_names:dict={},
    company:List[str]=[],
    target:dict={},
    drug_modality:dict={},
    drug_feature:dict={},
    route_of_administration:dict={},
    indication_name:List[str]=[],
    phase:List[str]=[],
    location:List[str]=[],
    top_n:int=30,
    page:int=1,
    unique_key:List[str]=[],
    exact_indication:bool=False,
    use_citeline:bool=True,
    id:List[str]=[],
    **kwargs
):
    drug_ids = await get_drug_ids(drug_names, use_citeline=use_citeline)
    filtering_params = {
        'id': drug_ids,
        'target': target,
        'companies': {'data': company, 'logic': 'or'},
        'drug_modality_mapping': drug_modality,
        'drug_feature': drug_feature,
        'route_of_administration': route_of_administration,
        'indication_tree': {'data':indication_name, 'logic': 'or'},
        'phase': phase,
        'location': location,
        'unique_key': unique_key or id
    }
    query_mapping = {
        'drug_modality': 'drug_modality_mapping',
        "drug_names": "id",
        "indication_name": "indication_tree",
        "company": "companies",
    }
    print("filtering_params", filtering_params)
    if exact_indication:
        filtering_params.pop('indication_tree')
        filtering_params['indication'] = indication_name
    conditions, params = generate_conditions_and_params(filtering_params)
    
    and_keys = []
    apply_not_fields = kwargs.get("apply_not_fields", [])
    apply_not_fields = set([query_mapping.get(k, k) for k in apply_not_fields])
    if "condition_or" in kwargs and kwargs["condition_or"]:
        or_keys = []
        # print('apply_not_fields', apply_not_fields)
        for c in conditions:
            for key in apply_not_fields:
                if c.startswith(key):
                    c = f"NOT {c}"
                    break
            for key in set(['id', 'indication_tree', 'companies', 'target', 'drug_modality_mapping', 'drug_feature', 'route_of_administration']) - apply_not_fields:
                if c.startswith(key):
                    or_keys.append(c)
                    break
            else:
                and_keys.append(c)
        where_clause = " OR ".join(or_keys) if or_keys else f"1=1"
        if and_keys:
            where_clause = " AND ".join(and_keys + [f"({where_clause})"])
    else:
        for c in conditions:
            for key in apply_not_fields:
                if c.startswith(key):
                    c = f"NOT {c}"
                    break
            and_keys.append(c)
        where_clause = " AND ".join(and_keys) if and_keys else f"1=1"
        
    selected = [
        # "id",
        "name",
        "other_names",
        "lead_company",
        "partner_companies",
        "target",
        "drug_modality",
        "drug_feature",
        "route_of_administration",
        "indication_mapping",
        "phase",
        "location",
        "unique_key as id",
    ]
    
    with get_connection() as conn:
        result = conn.execute(text(f"SELECT {','.join(selected)} FROM citeline_drug_info WHERE {where_clause} ORDER BY unique_key DESC LIMIT {top_n} OFFSET {(page-1)*top_n}"), params)
        results = result.fetchall()
    with get_connection() as conn:
        # Get total count
        count_result = conn.execute(text(f"SELECT COUNT(*) FROM citeline_drug_info WHERE {where_clause}"), params)
        total_count = count_result.scalar()
        
    selected[-1] = "id"
    json_results = [{k if k != 'indication_mapping' else 'indication': v for k, v in dict(zip(selected, row)).items()} for row in results]
    if total_count > 10000:
        total_count = 10000
    return {"results": json_results, "total_count": total_count}
    # return json_results
