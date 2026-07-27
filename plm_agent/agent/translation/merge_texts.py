import os
import time


# 拼接出 gcp_key.json 的绝对路径
gcp_key_path = "/Users/andy/repos/NoahAgent/noah_agent/gcp_key.json"
if not os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', ''):
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = gcp_key_path

os.environ['GOOGLE_CLOUD_PROJECT'] = "noahai-440408"
os.environ['GOOGLE_CLOUD_LOCATION'] = "global"
os.environ['GOOGLE_GENAI_USE_VERTEXAI'] = "true"


from google import genai
from google.genai.types import HttpOptions
import json
        
client = genai.Client(http_options=HttpOptions(api_version="v1"))

# with open("/Users/andy/repos/NoahAgent/noah_agent/outputs3/iit2.json", "r") as f:
#     text = json.load(f)

text_merge_schema = {
    "type": "ARRAY",
    "items": {
        "type": "STRING",
    }
}


def merge(text):
    print("merging text:", text)
    response = client.models.generate_content(
        model="gemini-3-flash-preview",
        contents=f"{text}\n\n Help me merge the list of texts above that might have been separated by formatting, return the merged indices ranges('start-end' or single page num) of each consecutive section in a list:\n\n",
        config={
            "response_mime_type": "application/json",
            "response_schema": text_merge_schema,
            "temperature": 0,
        },
    )
    json_content = json.loads(response.text)
    return json_content

# response = client.models.generate_content(
#     model="gemini-3-flash-preview",
#     contents="Help me translate the following text from Chinese to English, maintain formatting if possible, only return the translation result:\n\n" + "".join(text[:5]),
#     config={
#         "temperature": 0,
#     },
# )

# translated = response.text
# with open("/Users/andy/repos/NoahAgent/noah_agent/outputs3/translated.md", "w") as f:
#     f.write(translated)

start = time.time()
translate_dict = {}
try:
    with open("translate.json", "r", encoding="utf-8") as f:
        translate_dict = json.load(f)
except FileNotFoundError:
    pass
    
# print("translate_dict", translate_dict)
orig_texts = list(translate_dict.keys())
orig_texts = [(text[:50] + '...' + text[-50:] if len(text) > 100 else text) for text in orig_texts]


ret = merge(str(orig_texts))

print("merge result:", ret)

end = time.time()
print(f"Time taken: {end - start} seconds")


