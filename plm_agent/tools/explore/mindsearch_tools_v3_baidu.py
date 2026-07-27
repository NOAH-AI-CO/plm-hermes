import requests
import json

from config import api_config


def main():
        
    url = "https://qianfan.baidubce.com/v2/ai_search/web_search"
    
    payload = json.dumps({
        "messages": [
            {
                "role": "user",
                "content": "今天热点新闻"
            }
        ],
        "edition": "standard",
        "search_source": "baidu_search_v2",
        "search_recency_filter": "week"
    }, ensure_ascii=False)
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {api_config.BAIDU_QIANFAN_API_KEY}'
    }
    
    response = requests.request("POST", url, headers=headers, data=payload.encode("utf-8"))
    
    response.encoding = "utf-8"
    print(response.text)
    

if __name__ == '__main__':
    main()