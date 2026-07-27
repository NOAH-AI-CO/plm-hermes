import os
import json
import datetime
import concurrent.futures
import urllib.request
from google import genai
from google.genai import types
from google.genai.types import HttpOptions

# Setup GCP credentials and environment variables
gcp_key_path = "/Users/andy/repos/NoahAgent/noah_agent/gcp_key.json"
if not os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', ''):
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = gcp_key_path

os.environ['GOOGLE_CLOUD_PROJECT'] = "noahai-440408"
os.environ['GOOGLE_CLOUD_LOCATION'] = "global"
os.environ['GOOGLE_GENAI_USE_VERTEXAI'] = "true"

# Initialize the Gemini client
client = genai.Client(http_options=HttpOptions(api_version="v1"))

def resolve_true_url(vertex_url: str) -> str:
    """Attempts to resolve the vertex grounding API redirect URL to its true destination."""
    try:
        req = urllib.request.Request(vertex_url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.url
    except Exception:
        return vertex_url

def add_citations(response) -> str:
    text = response.text
    if not response.candidates or not response.candidates[0].grounding_metadata:
        return text

    supports = response.candidates[0].grounding_metadata.grounding_supports
    chunks = response.candidates[0].grounding_metadata.grounding_chunks

    if not supports or not chunks:
        return text

    # Sort supports by end_index in descending order to avoid shifting issues when inserting.
    sorted_supports = sorted(supports, key=lambda s: s.segment.end_index, reverse=True)

    used_chunk_indices = set()

    for support in sorted_supports:
        end_index = support.segment.end_index
        if support.grounding_chunk_indices:
            # Create clean inline citation string like [1][2] instead of putting the full URL inline
            citation_links = []
            for i in support.grounding_chunk_indices:
                if i < len(chunks):
                    citation_links.append(f"[{i + 1}]")
                    used_chunk_indices.add(i)

            citation_string = "".join(citation_links)
            text = text[:end_index] + citation_string + text[end_index:]

    if used_chunk_indices:
        text += "\n\n### References\n"
        for i in sorted(list(used_chunk_indices)):
            uri = chunks[i].web.uri
            true_uri = resolve_true_url(uri)
            title = chunks[i].web.title if getattr(chunks[i].web, 'title', None) else true_uri
            text += f"{i + 1}. [{title}]({true_uri})\n"

    return text

def _search_and_summarize(query: str) -> str:
    current_date = datetime.datetime.now().strftime('%Y-%m-%d')
    enhanced_query = f"{query}\nCurrent date: {current_date}. Try to search for latest data."
    grounding_tool = types.Tool(google_search=types.GoogleSearch())
    config = types.GenerateContentConfig(
        tools=[grounding_tool],
        temperature=0.0
    )
    try:
        response = client.models.generate_content(
            model="gemini-3.1-pro-preview",
            contents=enhanced_query,
            config=config,
        )
        return add_citations(response)
    except Exception as e:
        return f"Error during search for '{query}': {e}"


def deep_research(query: str, max_turns: int = 3) -> str:
    """
    Performs deep research using Gemini 3.1 Pro and the Google Search grounding tool over multiple turns.
    """
    gathered_info = []

    for turn in range(1, max_turns + 1):
        print(f"Turn {turn}: Evaluating gathered information...")
        context_str = "\n\n".join(gathered_info) if gathered_info else "None"
        
        current_date_str = datetime.datetime.now().strftime('%Y-%m-%d')

        # LLM call to formulate queries for missing info
        eval_prompt = (
            f"Original user query: {query}\n\n"
            f"Current date: {current_date_str}\n"
            "Always use the current date to determine what 'recent' or 'latest' means. "
            f"Information gathered so far:\n{context_str}\n\n"
            "Analyze the gathered information against the original query. "
            "Does the gathered information fully answer the query?\n"
            "If yes, output an empty JSON list: []\n"
            "If no, output a JSON list of strings containing specific search queries needed to find the missing information. "
            "If 'Information gathered so far' is 'None', break down the original user query into an initial list of parallel subqueries.\n"
            "Output ONLY valid JSON, e.g., [\"query 1\", \"query 2\"]."
        )

        try:
            eval_response = client.models.generate_content(
                model="gemini-3.1-pro-preview",
                contents=eval_prompt,
                config=types.GenerateContentConfig(temperature=0.0)
            )
            
            # Parse JSON out of response
            text = eval_response.text.strip()
            if text.startswith("```json"):
                text = text[7:-3].strip()
            elif text.startswith("```"):
                text = text[3:-3].strip()
            
            missing_queries = json.loads(text)
        except Exception as e:
            print(f"Error evaluating missing queries: {e}")
            break

        if not isinstance(missing_queries, list) or len(missing_queries) == 0:
            print("No further information needed. All aspects answered.")
            break

        print(f"Missing information identified. Running parallel searches for: {missing_queries}")

        # Call Gemini Search in parallel for missing queries
        new_info = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(missing_queries)) as executor:
            future_to_query = {executor.submit(_search_and_summarize, mq): mq for mq in missing_queries}
            for future in concurrent.futures.as_completed(future_to_query):
                mq = future_to_query[future]
                try:
                    res = future.result()
                    new_info.append(f"Follow-up Query: {mq}\nResult:\n{res}")
                except Exception as e:
                    new_info.append(f"Follow-up Query: {mq}\nError: {e}")

        # Append to our gathered context
        gathered_info.extend(new_info)

    # Final synthesis
    print("Synthesizing final answer...")
    final_context = "\n\n".join(gathered_info)
    final_prompt = (
        f"Original user query: {query}\n\n"
        f"All gathered information across multiple search turns (with inline citations like [1]):\n{final_context}\n\n"
        "Based on all the gathered information above, provide a comprehensive, well-structured final answer to the original query. "
        "CRITICAL: Be sure to include the numeric inline citations (e.g., [1], [2]) directly in your final answer text corresponding to the sources. "
        "ALSO, at the very end of your response, add a \
\
### References\
 section that lists all the cited sources with their URLs formatting as \
1. [Title](URL)\
."
    )

    final_response = client.models.generate_content(
        model="gemini-3.1-pro-preview",
        contents=final_prompt,
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            temperature=0.0
        )
    )

    return add_citations(final_response)

if __name__ == "__main__":
    result = deep_research("Opdivo，Balversa，Keytruda，Padcev，VesiGel ，Bavencio，Jelmyto这几个药的最近的年销售额和历史的峰值销售额是多少？其中在bladder cancer这个疾病上的销售额又是多少？需要包含每个药的情况")
    print(result)
