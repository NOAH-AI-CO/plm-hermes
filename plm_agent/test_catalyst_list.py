from utils.clinical_utils.clean_args_typesense import clean_args_typesense
from utils.catalyst.retrieve import get_catalyst_list

params = {'phases': ['I', 'II', 'III', 'IV', 'Preclinical', 'Others'], 'catalyst_type': ['PDUFA Approval', 'Top-Line Results', 'Trial Data Update'], 'indication_name': {'data': ['obesity', 'weight loss'], 'logic': 'or'}}
params = {'indication_name': {'data': ['obesity', 'weight loss'], 'logic': 'or'}}
params = clean_args_typesense(params)
params['custom_impact'] = True
params['details'] = True
res = get_catalyst_list(**params)
print(res)