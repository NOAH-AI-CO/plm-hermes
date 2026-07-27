import re
import copy
import logging
import asyncio
import time
from enum import Enum

from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Any, Optional
from pydantic import BaseModel, Field

from tools.core.base_tool import BaseTool
from utils.standardize.database_tool_standardizer import DatabaseToolStandardizer, StandardizeProtocol
from utils.catalyst.retrieve import get_catalyst_list
from workflows.drug_compete import drug_compete
from workflows.clinical_trial_result_comparison import compare_clinical_trial_results

logger = logging.getLogger(__name__)


class PHASES(Enum):
    r"Clinical drug or treatment phases"
    I = "I"
    II = "II"
    III = "III"
    IV = "IV"
    PRECLINICAL = "Preclinical"
    OTHERS = "Others"

class PHASES2(Enum):
    r"Clinical drug or treatment phases"
    PRECLINICAL = "Preclinical"
    IND = "IND"
    I = "I"
    II = "II"
    III = "III"
    SUSPENDED = "Suspended"
    BLA_NDA = "BLA/NDA"
    APPROVED = "Approved"
    IV = "IV"
    WITHDRAWN_FROM_MARKET = "Withdrawn from Market"
    INVESTIGATOR_INITIATED = "Investigator Initiated - phase unknown"    
    OTHERS = "Others"

class COUNTRY(Enum):
    r"Country"
    USA = 'USA'
    CHINA = 'China'
    JAPAN = 'Japan'
    UK = 'UK'
    FRANCE = 'France'
    Germany = 'Germany'
    ITALY = 'Italy'
    SPAIN = 'Spain'

class COUNTRY2(Enum):
    r"Country"
    USA = 'United States'
    CHINA = 'China'
    JAPAN = 'Japan'
    UK = 'United Kingdom'
    FRANCE = 'France'
    Germany = 'Germany'
    ITALY = 'Italy'
    SPAIN = 'Spain'

class DRUG_MODALITY(Enum):
    r"Drug modality types"
    STEROIDS = "Steroids"
    VACCINE = "Vaccine"
    ANTISENSE_RNA = "Antisense RNA"
    ANTIBODY_DRUG_CONJUGATES_ADCS = "Antibody-Drug Conjugates, ADCs"
    UNKNOWN = "Unknown"
    PROTEIN_DEGRADER = "Protein Degrader"
    MONOCLONAL_ANTIBODIES = "Monoclonal Antibodies"
    MRNA = "mRNA"
    OTHERS = "Others"
    CELL_BASED_THERAPIES = "Cell-based Therapies"
    IMAGING_AGENTS = "Imaging Agents"
    GENE_THERAPY = "Gene Therapy"
    MIRNA = "miRNA"
    POLYPEPTIDE = "Polypeptide"
    RECOMBINANT_PROTEINS = "Recombinant Proteins"
    SMALL_MOLECULE = "Small Molecule"
    SIRNA_RNAI = "siRNA/RNAi"
    TRISPECIFIC_ANTIBODIES = "Trispecific Antibodies"
    POLYCLONAL_ANTIBODIES = "Polyclonal Antibodies"
    BI_SPECIFIC_ANTIBODIES = "Bi-specific Antibodies"
    GLYCOCONJUGATES = "Glycoconjugates"
    RADIOPHARMACEUTICAL = "Radiopharmaceutical"
    NUCLEIC_ACID_BASED = "Nucleic Acid-based"
    CARBOHYDRATES = "Carbohydrates"

class DRUG_FEATURES(Enum):
    r"Drug feature types"
    FIVE_ZERO_FIVE_B_TWO = "505b2"
    BACTERIAL_PRODUCT = "Bacterial Product"
    BIOLOGIC = "Biologic"
    BIOSIMILAR = "Biosimilar"
    DEVICE = "Device"
    FIXED_DOSE_COMBINATION = "Fixed-Dose Combination"
    IMMUNO_ONCOLOGY = "Immuno-Oncology"
    NEW_MOLECULAR_ENTITY_NME = "New Molecular Entity (NME)"
    NON_NME = "Non-NME"
    PRECISION_MEDICINE = "Precision Medicine"
    REFORMULATION = "Reformulation"
    SPECIALTY_DRUG = "Specialty Drug"
    VIRAL = "Viral"

class ROUTE_OF_ADMINISTRATION(Enum):
    r"Route of administration types"
    INTRAARTERIAL = "Intraarterial"
    INTRAURETHRAL = "Intraurethral"
    INHALED = "Inhaled"
    INTRANASAL = "Intranasal"
    SUBCUTANEOUS_SQ_UNSPECIFIED = "Subcutaneous (SQ) - Unspecified"
    TRANSDERMAL = "Transdermal"
    INTRAOCULAR_SUBRETINAL_SUBCONJUNCTIVAL = "Intraocular/Subretinal/Subconjunctival"
    SUBCUTANEOUS_SQ_INJECTION = "Subcutaneous (SQ) Injection"
    INTRAUTERINE = "Intrauterine"
    INTRALYMPHATIC = "Intralymphatic"
    INTRADISCAL = "Intradiscal"
    INTRA_AMNIOTIC = "Intra-amniotic"
    INTRATHECAL = "Intrathecal"
    INTRACEREBRAL_CEREBROVENTRICULAR = "Intracerebral/cerebroventricular"
    INTRAMUSCULAR_IM = "Intramuscular (IM)"
    INTRAARTICULAR = "Intraarticular"
    INTRACOCHELEAR = "Intracochlear"
    SURGICAL_IMPLANTATION = "Surgical Implantation"
    HEMOPERFUSION = "Hemoperfusion"
    SUBCUTANEOUS_SQ_INFUSION = "Subcutaneous (SQ) Infusion"
    INTRAVITREAL = "Intravitreal"
    INTRAVENOUS_IV = "Intravenous (IV)"
    ORAL_PO = "Oral (PO)"
    INTRADERMAL = "Intradermal"
    PERCUTANEOUS_CATHETER_INJECTION = "Percutaneous Catheter/Injection"
    INTRANODAL = "Intranodal"
    INTRAVESICAL = "Intravesical"
    INTRACAMERAL = "Intracameral"
    INTRATYMPANIC = "Intratympanic"
    INTRATUMORAL = "Intratumoral"
    SUBLINGUAL_SL_ORAL_TRANSMUCOSAL = "Sublingual (SL)/Oral Transmucosal"
    INTRAVAGINAL = "Intravaginal"
    N_A = "N/A"
    RECTAL = "Rectal"
    INTRACAVITARY = "Intracavitary"
    INTRA_CISTERNA_MAGNA_ICM_INJECTION = "Intra-Cisterna Magna (ICM) Injection"
    INJECTABLE_UNSPECIFIED = "Injectable - Unspecified"
    INTRATRACHEAL = "Intratracheal"
    TOPICAL = "Topical"
    INSTILLATION = "Instillation"
    INTRAINTESTINAL = "Intraintestinal"
    SUBMUCOSAL = "Submucosal"


class MedicalCommonFieldList(Enum):
    INDICATION_NAME = "indication_name"
    COMPANY = "company"
    TARGET = "target"
    PHASE = "phase"
    DRUG_MODALITY = "drug_modality"
    DRUG_FEATURE = "drug_feature"
    ROUTE_OF_ADMINISTRATION = "route_of_administration"

class ClinicalResultsFieldList(Enum):
    DRUG_NAME = "drug_name"
    NCTIDS = "nctids"
    LOCATIONS = "locations"
    INDICATION_NAME = MedicalCommonFieldList.INDICATION_NAME.value
    COMPANY = MedicalCommonFieldList.COMPANY.value
    TARGET = MedicalCommonFieldList.TARGET.value
    PHASE = MedicalCommonFieldList.PHASE.value
    DRUG_MODALITY = MedicalCommonFieldList.DRUG_MODALITY.value
    DRUG_FEATURE = MedicalCommonFieldList.DRUG_FEATURE.value
    ROUTE_OF_ADMINISTRATION = MedicalCommonFieldList.ROUTE_OF_ADMINISTRATION.value

class DrugCompetitionLandscapeFieldList(Enum):
    DRUG_NAMES = "drug_names"
    LOCATION = "location"
    PHASE = "phase"
    INDICATION_NAME = MedicalCommonFieldList.INDICATION_NAME.value
    COMPANY = MedicalCommonFieldList.COMPANY.value
    TARGET = MedicalCommonFieldList.TARGET.value
    DRUG_MODALITY = MedicalCommonFieldList.DRUG_MODALITY.value
    DRUG_FEATURE = MedicalCommonFieldList.DRUG_FEATURE.value
    ROUTE_OF_ADMINISTRATION = MedicalCommonFieldList.ROUTE_OF_ADMINISTRATION.value

class CatalystTypes(Enum):
    PDUFA_APPROVAL="PDUFA Approval"
    TOP_LINE_RESULTS="Top-Line Results"
    TRAIL_DATA_UPDATE="Trial Data Update"

class CatalystSearchFieldList(Enum):
    PHASES="phases"
    INDICATION_NAME="indication_name"
    COMPANY="company"
    DRUG_NAME="drug_name"
    CATALYST_TYPE="catalyst_type"


class CatalystEventQueryInputSchema(BaseModel):
    thought_process: str = Field(
        description='The step by step explanation of why triggering this query.')
    phases: List[PHASES2] = Field(
        default=None,
        description="List of phases. Can be empty."
    )
    indication_name: List[str] = Field(
        default=None,
        description="List of english indication names (translate to english if in other languages), include other english names of same indication to increase query success rate. Can be empty."
    )
    company: List[str] = Field(
        default=None,
        description="Company names (english). Can be empty."
    )
    drug_name: List[str] = Field(
        default=None,
        description="Drug name and logical operation in query (english). Can be empty."
    )
    catalyst_type: List[CatalystTypes] = Field(
        default=None,
        description="Catalyst type. Can be empty."
    )
    apply_not_fields: List[CatalystSearchFieldList] = Field(
        default=None,
        description="List of fields to apply NOT operation on. Can be empty."
    )
    date_range: List[str] = Field(
        default=None,
        description='Date range contains start date time and end date time, i.e. ["2025-06-23T16:00:00.000Z", "2025-07-20T16:00:00.000Z"], must contains two date time, the end date could be current. Can be empty'
    )
    page: int = Field(
        default=1,
        description="Current database paging position."
    )

class DatabaseQuery(BaseTool):
    name: str = 'DatabaseQuery'
    standardizer_client: DatabaseToolStandardizer = DatabaseToolStandardizer()

    def standardizer(self, **kwarg) -> tuple[dict, bool]:
        res = {}
        fails = []
        standardization = False
        for key, value in kwarg.items():
            if key in self.keys and len(value) > 0:
                meta = self.keys[key]
                function = meta['function']
                method = getattr(self.standardizer_client, function)
                res[key] = set()
                for item in value:
                    query_input = copy.deepcopy(meta)
                    query_input.pop('function')
                    query_input['query'] = item
                    result = method(**query_input)
                    if result:
                        if query_input.get('verbose', False):
                            # TODO support verbose
                            pass
                        else:
                            res[key].add(result)
                        standardization = True
                    else:
                        fails.append(item)
                res[key] = list(res[key])
            else:
                if key not in ['thought_process']:
                    res[key] = value
        logger.info(f'{self.name} result: {res} failed normailized key: {fails}')
        return res, standardization


class CatalystEventsDatabaseQuery(DatabaseQuery):
    name: str = 'CatalystEventsDatabaseQuery'
    description: str = 'Performs a database search to retrieve catalyst events based on specified keywords.'
    input_schema: BaseModel = CatalystEventQueryInputSchema
    strict: bool = True

    keys: dict = {
        'indication_name': {
            'function': 'indication',
            'protocol': StandardizeProtocol.BMT,
        },
        'drug_name': {
            'function': 'drug_name',
            'protocol': StandardizeProtocol.BMT,
        },
        'company': {
            'function': 'company',
            'protocol': StandardizeProtocol.BMT,
        },
        'target': {
            'function': 'target',
            'protocol': StandardizeProtocol.BMT,
        }
    }

    async def run(self, **kwarg):
        params, standardization = self.standardizer(**kwarg)

        yield {
            "function": self.name,
            "params": kwarg,
            "result": {},
            "function_params": params,
            "standardization": standardization,
        }


class CatalystEventsDatabaseQueryExecution(BaseTool):
    name: str = 'CatalystEventsDatabaseQueryExecution'
    description: str = 'Performs a database search with relevant standardization query params to retrieve catalyst events based on specified keywords.'
    input_schema: BaseModel = CatalystEventQueryInputSchema
    strict: bool = True

    async def run(self, **kwarg):
        params = copy.deepcopy(kwarg)
        params.pop('thought_process', None)
        nparams = {}

        nparams.update(params)
        nparams['custom_impact'] = True
        nparams['details'] = True
        nparams['top_n'] = 30
        logger.info(f"CatalystEvent query paramers {nparams}")
        try:
            result = get_catalyst_list(**nparams)
        except Exception as exc:
            logger.warning(f"Failed for get_catalyst_list query {nparams}: {exc}")
            result = []
        logger.info(f"CatalystEvent query count {len(result)}")
        # remove internal params
        nparams.pop('custom_impact', None)
        nparams.pop('details', None)
        nparams.pop('top_n', None)
        yield {
            "function": self.name,
            "params": kwarg,
            "result": {
                "results": result
            },
            "function_params": nparams,
        }


class ClinicalResultsQueryInputSchema(BaseModel):
    thought_process: str = Field(
        description='The step by step explanation of why triggering this query.')
    indication_name: List[str] = Field(
        default=None,
        description="List of english indication names (translate to english if in other languages), include other english names of same indication to increase query success rate. Can be empty."
    )
    company: List[str] = Field(
        default=None,
        description="Company names (english). Can be empty."
    )
    target: List[str] = Field(
        default=None,
        description="Target name and logical operation in query (english). Can be empty."
    )
    drug_name: List[str] = Field(
        default=None,
        description="Drug name and logical operation in query (english). Can be empty."
    )
    drug_modality: List[DRUG_MODALITY] = Field(
        default=None,
        description="List of drug modalities. Can be empty."
    )
    drug_feature: List[DRUG_FEATURES] = Field(
        default=None,
        description="List of drug features. Can be empty."
    )
    route_of_administration: List[ROUTE_OF_ADMINISTRATION] = Field(
        default=None,
        description="List of routes of administration. Can be empty."
    )
    nctids: List[str] = Field(
        default=None,
        description="List of NCTIDs, i.e. NCT00256152, NCT00256178. Can be empty."
    )
    phase: List[PHASES] = Field(
        default=None,
        description="List of phases. Can be empty."
    )
    locations: List[COUNTRY2] = Field(
        default=None,
        description="Locations in country (english) and logical operation in query. Can be empty."
    )


class ClinicalResultsDatabaseQuery(DatabaseQuery):
    name: str = 'ClinicalResultsDatabaseQuery'
    description: str = 'Performs a database search to retrieve clinical result based on specified keywords.'
    input_schema: BaseModel = ClinicalResultsQueryInputSchema
    strict: bool = True

    keys: dict = {
        'indication_name': {
            'function': 'indication',
            'protocol': StandardizeProtocol.NOAH,
        },
        'drug_name': {
            'function': 'drug_name',
            'protocol': StandardizeProtocol.BMT,
        },
        'company': {
            'function': 'company',
            'protocol': StandardizeProtocol.BMT,
        },
        'target': {
            'function': 'target',
            'protocol': StandardizeProtocol.BMT,
        }
    }

    async def run(self, **kwarg):
        params, standardization = self.standardizer(**kwarg)

        yield {
            "function": self.name,
            "params": kwarg,
            "result": {},
            "function_params": params,
            "standardization": standardization,
        }


class ClinicalResultsDatabaseQueryExecution(DatabaseQuery):
    name: str = 'ClinicalResultsDatabaseQueryExecution'
    description: str = 'Performs a database search with relevant standardization query params to retrieve clinical result based on specified keywords.'
    input_schema: BaseModel = ClinicalResultsQueryInputSchema
    strict: bool = True

    async def run(self, **kwarg):
        params = copy.deepcopy(kwarg)
        params.pop('thought_process', None)
        nparams = {}
        
        for k,v in compare_clinical_trial_results.__annotations__.items():
            if k in params:
                if isinstance(params[k], list) and v == dict:
                    nparams[k] = {'data': params[k], 'logic': 'or'}
                elif isinstance(params[k], dict) and v == list:
                    nparams[k] = params[k].get('data', params[k])
                else:
                    nparams[k] = params[k]

        nparams['top_n'] = 30
        logger.info(f"ClinicalResults query paramers {nparams}")
        try:
            result = await compare_clinical_trial_results(**nparams)
        except Exception as exc:
            logger.warning(f"Failed for compare_clinical_trial_results query {nparams}: {exc}")
            result = {}
        logger.info(f"Result total_count: {result.get('total_count', 0)}, count: {len(result.get('results', []))}")
        # remove internal params
        nparams.pop('top_n', None)
        yield {
            "function": self.name,
            "params": kwarg,
            "result": result,
            "function_params": nparams,
        }

    
class DrugCompetitionQueryInputSchema(BaseModel):
    thought_process: str = Field(
        description='The step by step explanation of why triggering this query.')
    drug_names: List[str] = Field(
        default=None,
        description="Drug name and logical operation in query. Can be empty."
    )
    company: List[str] = Field(
        default=None,
        description="Company names (english). Can be empty."
    )
    target: List[str] = Field(
        default=None,
        description="Target name and logical operation in query (english). Can be empty."
    )
    drug_modality: List[DRUG_MODALITY] = Field(
        default=None,
        description="List of drug modalities. Can be empty."
    )
    drug_feature: List[DRUG_FEATURES] = Field(
        default=None,
        description="List of drug features. Can be empty."
    )
    route_of_administration: List[ROUTE_OF_ADMINISTRATION] = Field(
        default=None,
        description="List of routes of administration. Can be empty."
    )
    indication_name: List[str] = Field(
        default=None,
        description="List of english indication names (translate to english if in other languages), include other english names of same indication to increase query success rate. Can be empty."
    )
    phase: List[PHASES2] = Field(
        default=None,
        description="List of phases. Can be empty."
    )
    location: List[COUNTRY] = Field(
        default=None,
        description="List of phases. Can be empty."
    )
    page: int = Field(
        default=1,
        description="Current database paging position. Default is 1. Can be empty."
    )


class DrugCompetitionDatabaseQuery(DatabaseQuery):
    name: str = 'DrugCompetitionDatabaseQuery'
    description: str = 'Performs a database search to retrieve drug competition land scape based on specified keywords.'
    input_schema: BaseModel = DrugCompetitionQueryInputSchema
    strict: bool = True

    keys: dict = {
        'indication_name': {
            'function': 'indication',
        },
        'drug_names': {
            'function': 'drug_name',
        },
        'company': {
            'function': 'company',
        },
        'target': {
            'function': 'target',
        }
    }

    async def run(self, **kwarg):
        params, standardization = self.standardizer(**kwarg)

        yield {
            "function": self.name,
            "params": kwarg,
            "result": {},
            "function_params": params,
            "standardization": standardization,
        }


class DrugCompetitionDatabaseQueryExecution(BaseTool):
    name: str = 'DrugCompetitionDatabaseQueryExecution'
    description: str = 'Performs a database search with relevant standardization query params to retrieve drug competition land scape based on specified keywords.'
    input_schema: BaseModel = DrugCompetitionQueryInputSchema
    strict: bool = True

    async def run(self, **kwarg):
        params = copy.deepcopy(kwarg)
        params.pop('thought_process', None)
        nparams = {}
        
        for k,v in drug_compete.__annotations__.items():
            if k in params:
                if isinstance(params[k], list) and v == dict:
                    nparams[k] = {'data': params[k], 'logic': 'or'}
                elif isinstance(params[k], dict) and v == list:
                    nparams[k] = params[k].get('data', params[k])
                else:
                    nparams[k] = params[k]

        nparams['top_n'] = 100
        logger.info(f"DrugCompetition query paramers {nparams}")
        try:
            result = await drug_compete(**nparams)
        except Exception as exc:
            logger.warning(f"Failed for drug_compete query {nparams}: {exc}")
            result = {}
        logger.info(f"Result total_count: {result.get('total_count', 0)}, count: {len(result.get('results', []))}")
        # remove internal params
        nparams.pop('top_n', None)

        yield {
            "function": self.name,
            "params": kwarg,
            "result": result,
            "function_params": nparams
        }

