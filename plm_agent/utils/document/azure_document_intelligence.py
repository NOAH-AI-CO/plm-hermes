from azure.core.credentials import AzureKeyCredential
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import DocumentAnalysisFeature, AnalyzeResult

from config import api_config

# https://learn.microsoft.com/en-us/python/api/overview/azure/ai-documentintelligence-readme?view=azure-python


class AzureDocumentParser:
    
    document_intelligence_client = DocumentIntelligenceClient(endpoint=api_config.AZURE_DOCUMENT_INTELLIGENC_ENDPOINT,
                                                              credential=AzureKeyCredential(api_config.AZURE_DOCUMENT_INTELLIGENC_KEY))


    def analyze_read(self, file_path: str) -> AnalyzeResult:
        with open(file_path, "rb") as f:
            poller = self.document_intelligence_client.begin_analyze_document(
                "prebuilt-read",
                body=f,
                features=[DocumentAnalysisFeature.STYLE_FONT],
            )
        result: AnalyzeResult = poller.result()
        return result

    def analyze_layout(self, file_path: str) -> AnalyzeResult:
        r"""
        This method is very expansive. Be careful use it only when you really need.
        """
        with open(file_path, "rb") as f:
            poller = self.document_intelligence_client.begin_analyze_document(
                "prebuilt-layout",
                body=f)
        result: AnalyzeResult = poller.result()
        return result

