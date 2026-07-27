from agent.example_agent.example_agent import WeatherAgent, ChatAgent
from agent.explore.mindsearch_clinical_guidance_agent import MindSearchClinicalGuideline
from agent.explore.mindsearch_hitl_agent import MindSearchPatentHitlAgent
from agent.explore.mindsearch_hitl_agent import MindSearchFinanceHitlAgent, MindSearchSandboxHitlAgent
from agent.explore.mindsearch_agent_v3_china import MindSearchChinaAgent, MindSearchChinaGPTAgent
from agent.explore.mindsearch_agent_v3_pubmed import MindSearchPubMedHitlAgent
from agent.explore.mindsearch_agent_v3_1 import MindSearchAgentV3_1
from agent.explore.mindsearch_refer_agent_v3 import MindSearchReferAgentV3, MindSearchReferChinaAgent
from agent.explore.mindsearch_agent_v3_image import MindSearchImageGenerationAgent
from agent.catalyst.follow_up import CatalystFollowUpAgent
from agent.investment.report import InvestmentReportAgent
from agent.workflow.title_gen import WorkflowTitleGenAgent
from agent.workflow.evidence_title_gen import EvidenceTitleGenAgent
from agent.catalyst.technical_analysis import TechnicalAnalysisAgent
from agent.human_in_loop.planning_v5 import PlanningAgent
from agent.synopsis.report_gen_v2 import SynopsisAgentV2
from agent.synopsis.report_gen_roche import SynopsisAgentV2 as SynopsisAgentV2Roche
from agent.explore.mindsearch_rewrite_agent_v4 import MindSearchRewriteAgentV4
from agent.policy.policy import PolicyAgentV2
from agent.journal_recommendation.journal_recommendation_agent_v2 import JournalRecommendationAgentV2
from agent.policy.drug_policy import DrugPolicyAgent
from agent.nsfc.nsfc_writing_agent_v2 import NSFCAgentPhaseOne, NSFCAgentPhaseTwo
from agent.nsfc.v3 import NSFCAgentV3PhaseOne, NSFCAgentV3PhaseTwo
from agent.article_writing import ArticleRewritingAgent, ArticleEditingAgent
from agent.iit.core.iit_review_agent import IITAgent
from agent.xl_rag.rag_server import XLRagServer
from agent.bp.multi_llm import MultiLLMAgent
from agent.ppt.core import PPTXAgent
from agent.writing import WritingAgent

agent_routing = {
    "weather":  WeatherAgent,
    "chat": ChatAgent,
    "technical_analysis": TechnicalAnalysisAgent,
    "catalyst_follow_up": CatalystFollowUpAgent,
    "investment_report": InvestmentReportAgent,
    "synopsis": SynopsisAgentV2Roche,
    "synopsis_p13": SynopsisAgentV2,
    "policy": PolicyAgentV2,
    "workflow_title_gen": WorkflowTitleGenAgent,
    "evidence_title_gen": EvidenceTitleGenAgent,
    "planning": PlanningAgent,
    "article_nsfc_writing": NSFCAgentPhaseOne,
    "article_nsfc_writing_phase_2": NSFCAgentPhaseTwo,
    # To switch to V3:
    # "article_nsfc_writing": NSFCAgentV3PhaseOne,
    # "article_nsfc_writing_phase_2": NSFCAgentV3PhaseTwo,
    "article_editing": ArticleEditingAgent,
    "article_rewriting": ArticleRewritingAgent,
    "mindsearch": MindSearchAgentV3_1,
    "mindsearchofficialsite": MindSearchAgentV3_1,
    "mindsearchrefer": MindSearchReferAgentV3,
    "mindsearchworkflowrefer": MindSearchReferAgentV3,
    "mindsearchclinicalguideline": MindSearchClinicalGuideline,
    "mindsearchpubmed": MindSearchPubMedHitlAgent,
    "mindsearchrewrite": MindSearchRewriteAgentV4,
    "mindsearchfinance": MindSearchFinanceHitlAgent,
    "mindsearchpatent": MindSearchPatentHitlAgent,
    "journal_recommendation": JournalRecommendationAgentV2,
    "drug_policy": DrugPolicyAgent,
    "mindsearchofficialsitechina": MindSearchChinaGPTAgent,
    "mindsearchworkflowreferchina": MindSearchReferChinaAgent,
    "iit_review": IITAgent,
    "xl_rag": XLRagServer,
    "gemini": MultiLLMAgent,
    "multi-llm": MultiLLMAgent,
    "pptx": PPTXAgent,
    "mindsearchsandbox": MindSearchSandboxHitlAgent,
    "mindsearchimagegeneration": MindSearchImageGenerationAgent,
    "general_writing": WritingAgent,
}
