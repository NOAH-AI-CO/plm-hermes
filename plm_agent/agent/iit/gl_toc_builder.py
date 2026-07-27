from io import BytesIO
import pypdf
import os
import tiktoken
from agent.iit.v3.guidelines.es_indexing import client

# 拼接出 gcp_key.json 的绝对路径
gcp_key_path = "/Users/andy/repos/NoahAgent/noah_agent/gcp_key.json"
if not os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', ''):
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = gcp_key_path

from llm.deepseek_models import DeepseekChat
from llm.gcp_models import Gemini25Pro

toc_builder_prompt = """
Help me construct a table of contents for a clinical guideline document page by page. There are in total {total_pages} pages.
<TOC In Progress>
{toc}
</TOC In Progress>
<Next Pages>
{page_text}
</Next Pages>

Please update the <TOC In Progress> section with the new table of contents including the new page.
Table of contents should be simple and concise, only include main sections and subsections with page numbers.
Format the table of contents as follows:
1. Section Title - Page Number
    1.1 Subsection Title - Page Number
Use indentation to indicate subsections.
Output the TOC without any additional explanation.
Ignore the provided table of contents, as the page number might not match the actual file. Refer only to the <Actual Page Number> in the <Next Pages> section for page numbering.

"""

llm = Gemini25Pro()
# llm = DeepseekChat()

async def build_toc(toc, idx, page_text, total_pages):
    extra_body={
      'extra_body': {
        "google": {
          "thinking_config": {
            "thinking_budget": 1024,
          }
        }
      }
    }
    kwargs = {"extra_body": extra_body}
    # response = await llm(user_prompt=toc_builder_prompt, temperature=0.1, **kwargs)
    page_text = "\n\n".join(f"<Actual Page Number {i + 1}> Content:\n{page_text}\n</Actual Page Number {i + 1}>" for i, page_text in enumerate(page_text, idx))
    toc = (await llm(user_prompt=toc_builder_prompt.format(toc=toc, page_text=page_text, total_pages=total_pages), temperature=0, **kwargs))
    if hasattr(toc, 'content'):
        toc = toc.content
    return toc

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
    
async def _run():
    toc = ""
    text = None
    
    # file_content_bytes = None
    # with open("/Users/andy/repos/NoahAgent/noah_agent/agent/iit/ca_man.pdf", "rb") as file:
    #     file_content_bytes = file.read()
    # buf = BytesIO(file_content_bytes)
    # text = pdf_to_text(buf, by_page=True)

    with open("/Users/andy/repos/NoahAgent/noah_agent/agent/iit/csco-bc.json", "rb") as f:
        import json
        text = json.load(f)
        print("Loaded JSON with", len(text), "pages")
    batches = get_batches(text, max_tokens=20000)
    for i, batch in batches:
        print(f"Batch starting at page {i + 1} with {len(batch)} pages")
        
    for i, batch in batches:
        toc = await build_toc(toc, i, batch, len(text))
        print(f"--- TOC after processing pages {i + 1} to {i + len(batch)} ---")
        print(toc)
        
async def run_on_path(path, obj, use_ocr=False):
    from agent.iit.v3.guidelines.vllm_ocr import pdf_to_list 
    try:
        toc = ""
        text = None
        if not use_ocr:
            file_content_bytes = None
            with open(path, "rb") as file:
                file_content_bytes = file.read()
            buf = BytesIO(file_content_bytes)
            text = pdf_to_text(buf, by_page=True)
        else:
            text = pdf_to_list(path)
        client.update_by_query(index="guidelines", body={"script": {"source": "ctx._source.pages = params.pages", "lang": "painless", "params": {"pages": text}}, "query": {"term": {"id": obj['data']['id']}}})
        with open('updated_gl_ids_pages.txt', 'a') as f: 
            f.write(f"{obj['data']['id']} with {len(text)} pages\n")
        return
        with open('updated_gl_ids_debug.txt', 'a') as f: 
            f.write(f"Starting TOC building for {obj['data']['id']} with {len(text)} pages\n")
        print("Starting TOC building for", obj['data']['id'], "with", len(text), "pages")
        batches = get_batches(text, max_tokens=20000)
        for i, batch in batches:
            toc = await build_toc(toc, i, batch, len(text))
            
        # Now, the original update query should succeed
        client.update_by_query(index="guidelines", body={"script": {"source": "ctx._source.toc = params.toc", "lang": "painless", "params": {"toc": toc}}, "query": {"term": {"id": obj['data']['id']}}})
        with open('updated_gl_ids.txt', 'a') as f: 
            f.write(f"{obj['data']['id']}\n")
        with open('toc_outputs.txt', 'a') as f:
            f.write(f"ID: {obj['data']['id']}\nTOC:\n{toc}\n\n")
        toc = toc.replace("</TOC In Progress>", "").replace("<TOC In Progress>", "").strip()
        return toc
    except Exception as e:
        client.update_by_query(index="guidelines", body={"script": {"source": "ctx._source.remove('toc')", "lang": "painless"}, "query": {"term": {"id": obj['data']['id']}}})
        with open('updated_gl_ids.txt', 'a') as f:
            f.write(f"Error processing id: {obj['data']['id']} {path}: {e}\n")
        print(f"Error processing {path}: {e}")

async def run_on_pages(pages, id):
    try:
        toc = ""
        client.update_by_query(index="guidelines", body={"script": {"source": "ctx._source.pages = params.pages", "lang": "painless", "params": {"pages": pages}}, "query": {"term": {"id": id}}})
        with open('updated_gl_ids_pages_csco.txt', 'a') as f: 
            f.write(f"{id} with {len(pages)} pages\n")
        with open('updated_gl_ids_csco.txt', 'a') as f: 
            f.write(f"Starting TOC building for {id} with {len(pages)} pages\n")
        print("Starting TOC building for", id, "with", len(pages), "pages")
        batches = get_batches(pages, max_tokens=20000)
        for i, batch in batches:
            toc = await build_toc(toc, i, batch, len(pages))
            
        # Now, the original update query should succeed
        client.update_by_query(index="guidelines", body={"script": {"source": "ctx._source.toc = params.toc", "lang": "painless", "params": {"toc": toc}}, "query": {"term": {"id": id}}})
        with open('updated_gl_ids_csco.txt', 'a') as f: 
            f.write(f"{id}\n")
        with open('toc_outputs_csco.txt', 'a') as f:
            f.write(f"ID: {id}\nTOC:\n{toc}\n\n")
        return toc
    except Exception as e:
        # client.update_by_query(index="guidelines", body={"script": {"source": "ctx._source.remove('toc')", "lang": "painless"}, "query": {"term": {"id": obj['data']['id']}}})
        with open('updated_gl_ids_csco.txt', 'a') as f:
            f.write(f"Error processing id: {id}: {e}\n")
        print(f"Error processing {id}: {e}")
        
if __name__ == "__main__":
    import asyncio
    with open("/Users/andy/Downloads/医脉通/中国胰肾联合移植临床诊疗指南/中国胰肾联合移植临床诊疗指南.pdf", "rb") as file:
        file_content_bytes = file.read()
    buf = BytesIO(file_content_bytes)
    text = pdf_to_text(buf, by_page=True)
    g_count = str(text).count('/G')
    print(f"Number of '/G' appearances: {g_count}")
    print("Percetange of '/G' appearances:", g_count*2 / len(str(text)))
    

