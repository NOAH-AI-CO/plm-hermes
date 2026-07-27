from enum import IntEnum, Enum
from pydantic import BaseModel, Field
from typing import Optional

from agent.core.schema import BaseResponse


class ProcessingType(IntEnum):
    UNKNOWN = 0
    PROCESSING = 1
    RESPONSING = 2
    DONE = 3
    REWRITE = 4
    THOUGHT = 5
    CONTENT = 6
    RESPONSEDONE = 7
    FOLLOWUPQUESTION = 8
    THINKING = 9
    FAILED = 10
    

class SearchType(IntEnum):
    ASSISTANT = -3
    HELPER = -2
    DISABLE = -1
    UNKNOWN = 0
    WEB = 1
    PUBMED = 2
    NEWS = 3
    PATENT = 4
    STOCKPRICES = 5
    CODEGENERATION = 6
    CODEEXECUTION = 7
    FILEMANAGEMENT = 8
    CODEREVIEW = 9
    ATTACHEMNT = 10
    DRUG_MANUAL = 11
    CLINICAL_GUIDELINE = 12
    CLINICAL_TRIAL = 13

class WebSearchLink(BaseModel):
    id: int = 0
    url: str
    summ: str
    title: str
    reason: str = ""
    is_open: bool = False
    content: str = ""
    site_name: str = ""
    pubmed_id: str = "" # page's pubmed id
    pmc: str = ""
    pmcid: str = ""
    pii: str = ""
    cite_score: str = "" # page published journal infactor score
    issn: str = "" # page issn code
    full_journal_name: str = ""
    nlm_id: str = ""
    essn: str = ""
    pub_date: str = "" # page published time
    score: str = "0" # page score indicate the degree of page importantance
    type: SearchType = SearchType.WEB
    doi: str = ""
    author: str = ""
    patent_id: str = ""
    attachment_id: str = ""
    citation: dict = {}  # Vancouver citation format: {"txt": "...", "bib": "..."}
    

class WebSearchSubject(str, Enum):
    UNKNOWN = 'unknown'
    TREATMENT = 'treatment'
    MEDICINE = 'medicine'
    DISEASE = 'disease'
    COMPANY = 'company'
    NEWS = 'news'
    CODE = 'code'

class WebSearchRegion(str, Enum):
    r"""Web search engine region."""
    GLOBAL = 'global'
    CHINA = 'china'
    JAPAN = 'japan'
    ARAB = 'arab'


class SearchEngine(str, Enum):
    r"""Web search engine."""
    WEB = 'web'
    NEWS = 'news'
    PATENT = 'patent'
    MEDICAL = 'medical'


class SearchNode(BaseModel):
    id: int = 0
    search_type: SearchType = SearchType.UNKNOWN
    query: str = ""
    key_word: str = ""
    thought_process: str = ""
    subject: WebSearchSubject = WebSearchSubject.UNKNOWN
    search_results: list = []
    children: list = []
    source: list = [] # search results source merge, i.e. merge same web search domain
    summary: str = ""
    attachments_key: str = ""
    region: WebSearchRegion = WebSearchRegion.GLOBAL
    processing_type: ProcessingType = ProcessingType.UNKNOWN

    def add_child(self, child):
        if not isinstance(child, SearchNode):
            raise ValueError('Child must be an instance of SearchNode')
        if child not in self.children:
            self.children.append(child)
    
    def add_search_result(self, search_result: WebSearchLink):
        self.search_results.append(search_result)


class MindSearchResponse(BaseResponse):
    processing_type: ProcessingType = ProcessingType.UNKNOWN
    search_graph: SearchNode = None
    followup_questions: list[str] = []
    content: str = ""
    role: str = "assistant"
    raw_data: dict = {}
    files: list = []
    folders: list = []
