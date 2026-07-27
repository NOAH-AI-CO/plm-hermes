import asyncio

from utils.sql_client import get_connection
from sqlalchemy import text


async def get_drug_ids(drug_names: dict = {}, use_citeline: bool = False):
    if type(drug_names) == list:
        drug_names = {'data': drug_names, 'logic': 'or'}
    if not drug_names or len(drug_names['data']) == 0:
        return []

    table_name = "biomedtracker_drug_name" if not use_citeline else "citeline_drug_name"

    def _query():
        with get_connection() as conn:
            results = []
            for drug_name in drug_names['data']:
                rows = conn.execute(
                    text(f"SELECT drug_id FROM {table_name} WHERE lower(name) = lower(:drug_name)"),
                    {"drug_name": drug_name}
                ).fetchall()
                results.append(rows)
            return results

    results = await asyncio.to_thread(_query)
    results = [result for result in results if result and len(result) > 0]
    if not results:
        return ['-1']
    ret = []
    for result in results:
        for r in result:
            ret.extend([r[0]])
    return list(set(ret)) if ret else ['-1']

async def get_target_names(target_names: dict = {}):
    if not target_names or len(target_names['data']) == 0:
        return {}

    def _query():
        with get_connection() as conn:
            results = []
            for target_name in target_names['data']:
                rows = conn.execute(
                    text("SELECT name FROM entrez_gene_symbol WHERE lower(symbol) = lower(:target_name)"),
                    {"target_name": target_name}
                ).fetchall()
                results.append(rows)
            return results

    results = await asyncio.to_thread(_query)
    results = [result for result in results if result and len(result) > 0]
    if not results:
        return {}
    ret = []
    for result in results:
        for r in result:
            ret.extend([r[0]])
    ret = list(set(ret)) if ret else ['-1']
    return {'data': ret, 'logic': target_names['logic']}

async def get_indication_mapped(indication_names: list = []):
    if not indication_names or len(indication_names) == 0:
        return []

    def _query():
        with get_connection() as conn:
            results = []
            for indication_name in indication_names:
                rows = conn.execute(
                    text("SELECT indication_mapping FROM biomedtracker_drug_info WHERE lower(indication) = lower(:indication_name) LIMIT 1"),
                    {"indication_name": indication_name}
                ).fetchall()
                results.append(rows)
            return results

    results = await asyncio.to_thread(_query)
    results = [result for result in results if result and len(result) > 0]
    if not results:
        return ['-1']
    ret = []
    for result in results:
        for r in result:
            ret.extend([r[0]])
    return list(ret) if ret else ['-1']

def generate_conditions_and_params(params_dict: dict):
    conditions = []
    params = {}
    for key, value in params_dict.items():
        if value:
            if isinstance(value, (str,int)):
                conditions.append(f"{key} = :{key}")
                params[key] = value
            elif isinstance(value, (list, tuple)):
                conditions.append(f"{key} = ANY(:{key})")
                params[key] = value
            elif isinstance(value, dict):
                data = value.get('data', [])
                logic = value.get('logic', 'or').lower()
                if data:
                    if logic == 'and':
                        conditions.append(f"{key}::text[] @> :{key}")
                    elif logic == 'or':
                        conditions.append(f"{key}::text[] && :{key}")
                    elif logic == 'not':
                        conditions.append(f"NOT ({key}::text[] && :{key})")
                    params[key] = data
    return conditions, params