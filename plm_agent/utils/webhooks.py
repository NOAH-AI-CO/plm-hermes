import requests
from config import settings

def call_feishu_clinical_result_webhook(error: str):
    try:
        fs_webhook_url = settings.FEISHU_WEBHOOK_URL
        requests.post(fs_webhook_url, 
                      json = {"error": str(error)},
                      timeout=3)
    except:
        print("Failed to send error message to Feishu")
        pass