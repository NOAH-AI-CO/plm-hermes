import os

from llm.gcp_models import Gemini31Pro, Gemini3Flash
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 拼接出 gcp_key.json 的绝对路径
gcp_key_path = os.path.join(BASE_DIR, "gcp_key.json")

os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = gcp_key_path

# from llm.deepseek_models import DeepseekChat
from llm.deepseek_models import DeepseekChat
# from tools.human_in_loop.planning.schema import *


kwargs = {'tools': [{'type': 'function', 'function': {'name': 'drug_competition_landscape_input_schema_cn', 'description': 'Schema for drug_competition_landscape_input_schema_cn', 'parameters': {'type': 'object', 'properties': {'question': {'type': ['string', 'null'], 'description': '获取查询结果后代表用户提出的问题'}, 'indication_name': {'type': ['array', 'null'], 'items': {'type': ['string', 'null'], 'description': 'List of english indication names (translate to english if in other languages), include alt names of same indication to increase query success rate'}}, 'company': {'type': ['array', 'null'], 'items': {'type': ['string', 'null'], 'description': 'Company names in english (translate to english if in other languages)'}}, 'target': {'type': ['object', 'null'], 'properties': {'data': {'type': 'array', 'items': {'type': 'string', 'description': 'list of strings (english)'}}, 'logic': {'type': 'string', 'description': 'the logical operation to be performed in the query, can be one of and/or', 'enum': ['or', 'and']}}, 'required': ['data', 'logic'], 'additionalProperties': False}, 'phase': {'type': ['array', 'null'], 'items': {'type': ['string', 'null'], 'description': 'List of phases', 'enum': ['Preclinical', 'IND', 'I', 'II', 'III', 'Suspended', 'BLA/NDA', 'Approved', 'IV', 'Withdrawn from Market', 'Investigator Initiated - phase unknown', 'Unknown', 'Others']}}, 'drug_modality': {'type': ['object', 'null'], 'properties': {'data': {'type': 'array', 'items': {'type': 'string', 'description': 'list of strings', 'enum': ['Steroids', 'Vaccine', 'Antisense RNA', 'Antibody-Drug Conjugates, ADCs', 'Unknown', 'Protein Degrader', 'Monoclonal Antibodies', 'mRNA', 'Others', 'Cell-based Therapies', 'Imaging Agents', 'Gene Therapy', 'miRNA', 'Polypeptide', 'Recombinant Proteins', 'Small Molecule', 'siRNA/RNAi', 'Trispecific Antibodies', 'Polyclonal Antibodies', 'Bi-specific Antibodies', 'Glycoconjugates', 'Radiopharmaceutical']}}, 'logic': {'type': 'string', 'description': 'the logical operation to be performed in the query, can be one of and/or', 'enum': ['or', 'and']}}, 'required': ['data', 'logic'], 'additionalProperties': False}, 'drug_feature': {'type': ['object', 'null'], 'properties': {'data': {'type': 'array', 'items': {'type': 'string', 'description': 'list of strings', 'enum': ['Precision Medicine', 'Reformulation', 'Bacterial Product', '505b2', 'Immuno-Oncology', 'Biosimilar', 'Fixed-Dose Combination', 'Device', 'Non-NME', 'Specialty Drug', 'Viral', 'Biologic', 'New Molecular Entity (NME)']}}, 'logic': {'type': 'string', 'description': 'the logical operation to be performed in the query, can be one of and/or', 'enum': ['or', 'and']}}, 'required': ['data', 'logic'], 'additionalProperties': False}, 'route_of_administration': {'type': ['object', 'null'], 'properties': {'data': {'type': 'array', 'items': {'type': 'string', 'description': 'list of strings', 'enum': ['Inhaled', 'Intranasal', 'Transdermal', 'Intrathecal Injection', 'Intradermal Injection', 'Intraarticular Injection', 'Intraarterial Injection', 'Surgical Implantation', 'Subcutaneous Injection', 'Intraocular Injection', 'Intratumoral Injection', 'Intravenous (IV)', 'Intracavitary Injection', 'Oral (PO)', 'Intramuscular (IM) Injection', 'Percutaneous Catheter/Injection', 'Unknown', 'Intracerebral/cerebroventricular Injection', 'Others', 'Sublingual (SL)/Oral Transmucosal', 'Intravaginal', 'Rectal', 'Injectable (Others)', 'Intravesical Injection', 'Topical']}}, 'logic': {'type': 'string', 'description': 'the logical operation to be performed in the query, can be one of and/or', 'enum': ['or', 'and']}}, 'required': ['data', 'logic'], 'additionalProperties': False}, 'drug_names': {'type': ['object', 'null'], 'properties': {'data': {'type': 'array', 'items': {'type': 'string', 'description': 'list of strings (english)'}}, 'logic': {'type': 'string', 'description': 'the logical operation to be performed in the query, can be one of and/or', 'enum': ['or', 'and']}}, 'required': ['data', 'logic'], 'additionalProperties': False}, 'location': {'type': ['array', 'null'], 'items': {'type': ['string', 'null'], 'description': "List of locations (country, english), default to ['USA'] unless user specifies country, if user specifies global then ['USA', 'China', 'Japan', 'United Kingdom', 'France', 'Germany', 'Italy', 'Spain']"}}}, 'required': ['question', 'indication_name', 'company', 'target', 'phase', 'drug_modality', 'drug_feature', 'route_of_administration', 'drug_names', 'location'], 'additionalProperties': False}, 'strict': True}}], 'tool_choice': {'type': 'function', 'function': {'name': 'drug_competition_landscape_input_schema_cn'}}}

prompt = '''You are a clinical drug analyst. 
The user wants to query and analyze drug information with a focus on their competitive landscape using data from our database.
Your task is to help the user form query arguments according to the schema we provide you. 
Note: Try to not limit phases unless specified in user question. Leave query params empty if you are not sure about them.

Previous tool uses: ['Medical-Search']

The goal/reason for choosing this tool: 获取所有针对HR+HER2-乳腺癌的已获批和在研药物的详细信息，包括药物管线、作用机制和公司分布等。 (to answer the original user question: HR+HER2-乳腺癌的竞争格局，包括获批和在研的药物管线，重点药物的详细临床数据分析，未来的发展趋势，有潜力的创新项目等)'''

simple_test_prompt = "Tell a joke"

# llm = DeepseekChat()
llm = Gemini31Pro()

async def test():

    # response = await llm(user_prompt=simple_test_prompt, temperature=0.1, **kwargs)
    response = llm.stream_call(user_prompt=simple_test_prompt, temperature=0)
    # print("Response:", response)
    async for chunk in response:
        print("Chunk:", chunk)

if __name__ == "__main__":
    import asyncio

    asyncio.run(test())