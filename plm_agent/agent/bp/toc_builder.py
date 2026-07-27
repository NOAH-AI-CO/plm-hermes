from io import BytesIO
import pypdf
import os
import tiktoken
# from agent.iit.v3.guidelines.es_indexing import client
import asyncio
import time
from google.genai import types

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

toc_builder_schema = {
    "type": "STRING",
}

llm_client = genai.Client(http_options=HttpOptions(api_version="v1"))

async def build_toc(toc, idx, page_text, total_pages):
    page_text_formatted = "\n\n".join(f"<Actual Page Number {i + 1}> Content:\n{page_text}\n</Actual Page Number {i + 1}>" for i, page_text in enumerate(page_text, idx))
    
    prompt = f"""You are a specialized document indexing agent. Your task is to build a precise Table of Contents (TOC) for a business plan.
You are receiving the document content in batches.

Total Pages in Document: {total_pages}

<Current TOC State>
{toc}
</Current TOC State>

<New Content to Analyze>
{page_text_formatted}
</New Content to Analyze>

Task:
1. Analyze the text in <New Content to Analyze> to identify structural headings (names of sections, chapters, or subsections).
2. Append any NEW headings found to the <Current TOC State>. Include sections like the title page and abstract if they appear.
3. Assign page numbers based ONLY on the tags <Actual Page Number X> wrapping the content. Do not trust page numbers printed within the text itself.
4. Ignore non-structural text such as running headers, footers, or body paragraphs.
5. If the document itself contains a "Table of Contents" page, IGNORE it. Do not extract entries from a pre-existing TOC text; only extract headings from the actual content sections.

Output Format:
Return the fully updated TOC as a single string with the following hierarchy:
1. Section Title - Page Number
    1.1 Subsection Title - Page Number

Constraints:
- Keep the TOC concise.
- Preserve the existing structure in <Current TOC State>.
- If no new sections are found in this batch, return the <Current TOC State> unchanged.
"""
    response = await llm_client.aio.models.generate_content(
        model="gemini-3-flash-preview",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=toc_builder_schema,
            temperature=0,
            thinking_config=types.ThinkingConfig(thinking_level="minimal")
        ),
    )
    
    toc_content = json.loads(response.text)
    return toc_content

def pdf_to_text(pdf_stream, by_page=False):
    text = ""    
    try:
        pdf_reader = pypdf.PdfReader(pdf_stream)
        page_no = len(pdf_reader.pages)
        if page_no > 600:
            raise ValueError("PDF has too many pages (>600). Please upload a smaller file.")

        if by_page:
            pages_text = []
            for page_num in range(page_no):
                page = pdf_reader.pages[page_num]
                page_text = page.extract_text()
                pages_text.append(page_text)
            g_count = str(pages_text).count('/G')
            if g_count*2 / len(str(pages_text)) > 0.1:
                raise ValueError("/G error")
            return pages_text

        for page_num in range(page_no):
            page = pdf_reader.pages[page_num]
            text += page.extract_text()
        return text
    except Exception as e:
        raise ValueError(f"Failed to extract text from PDF: {e}")

# file_content_bytes = None
# with open("/Users/andy/repos/NoahAgent/noah_agent/agent/iit/ca_man.pdf", "rb") as file:
#     file_content_bytes = file.read()
# buf = BytesIO(file_content_bytes)
# text = pdf_to_text(buf, by_page=True)

def get_batches(text, max_tokens=20000):
    doc_tokens = 0
    batches = []
    last_idx = 0
    encoding = tiktoken.get_encoding("cl100k_base") 
    # total_tokens = sum(len(encoding.encode(doc)) for doc in text)
    # print(f"Total tokens in document: {total_tokens}")
    for idx, doc in enumerate(text):
        tokens = encoding.encode(doc)
        doc_tokens += len(tokens)
        if doc_tokens > max_tokens:
            docs = text[last_idx:idx]
            batches.append((last_idx,docs))
            last_idx = idx
            # print(f"Created batch ending at page {idx}, batch tokens: {doc_tokens - len(tokens)}")
            doc_tokens = len(tokens)
    if doc_tokens > 0:
        docs = text[last_idx:len(text)]
        batches.append((last_idx, docs))
        # print(f"Created batch ending at page {len(text)}, batch tokens: {doc_tokens}")
    return batches

def get_batches_by_size(text, batch_size=10):
    formal_batches = []
    for i in range(0, len(text), batch_size):
        formal_batches.append((i, text[i:i + batch_size]))
        
async def _run(path="/Users/andy/repos/NoahAgent/noah_agent/agent/iit/csco-bc.json"):
    import json
    toc = ""
    text = None
    
    file_content_bytes = None
    with open(path, "rb") as file:
        file_content_bytes = file.read()
    buf = BytesIO(file_content_bytes)
    text = pdf_to_text(buf, by_page=True)

    # with open(path, "rb") as f:
    #     text = json.load(f)
    #     print("Loaded JSON with", len(text), "pages")
    batches = get_batches(text, max_tokens=30000)
    for i, batch in batches:
        print(f"Batch starting at page {i + 1} with {len(batch)} pages")
        
    
async def pages_to_toc(pages):
    try:
        toc = ""
        batches = get_batches(pages, max_tokens=30000)
        for i, batch in batches:
            toc = await build_toc(toc, i, batch, len(pages))
            print(f"--- TOC after processing pages {i + 1} to {i + len(batch)} ---")
            print(toc)
        return toc
    except Exception as e:
        # client.update_by_query(index="guidelines", body={"script": {"source": "ctx._source.remove('toc')", "lang": "painless"}, "query": {"term": {"id": obj['data']['id']}}})
        with open('toc_building_errors.txt', 'a') as f:
            f.write(f"Error processing pages: {e}\n")
        print(f"Error processing pages: {e}")
        
if __name__ == "__main__":
    # with open("/Users/andy/Downloads/02.2022-165-内科, 毕锡文2.临床研究方案及其修正案 copy.pdf", "rb") as file:
    #     file_content_bytes = file.read()
    # buf = BytesIO(file_content_bytes)
    # text = pdf_to_text(buf, by_page=True)
    start = time.time()
    # toc = asyncio.run(_run("/Users/andy/Downloads/02.2022-165-内科, 毕锡文2.临床研究方案及其修正案 copy.pdf"))
    toc = asyncio.run(_run('/Users/andy/Downloads/gender-analysis-barriers-immunization-indonesia(1).pdf'))
    # print("Final TOC Output:\n", toc)
    end = time.time()
    print(f"Time taken: {end - start} seconds")
    

    

