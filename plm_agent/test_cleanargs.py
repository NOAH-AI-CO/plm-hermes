from utils.clinical_utils.clean_args_typesense import clean_args_typesense
import requests

# params = {'phases': ['I', 'II', 'III', 'IV', 'Preclinical', 'Others'], 'catalyst_type': ['PDUFA Approval', 'Top-Line Results', 'Trial Data Update'], 'indication_name': {'data': ['obesity', 'weight loss'], 'logic': 'or'}}
params = {'indication_name': {'data': ['HR+ HER2- breast cancer', 'Hormone receptor positive HER2 negative breast cancer'], 'logic': 'or'}}
params = clean_args_typesense(params)
print(params)
# params['custom_impact'] = True
# params['details'] = True
# res = get_catalyst_list(**params)
# Call API to get disease name information
response = requests.get("http://116.204.105.10:7000/disease_name/?query=HR%2B%20HER2-%20breast%20cancer")
print("API Response:", response.status_code)
print(response.json())

# params['custom_impact'] = True
# params['details'] = True
# res = get_catalyst_list(**params)
# print(res)

