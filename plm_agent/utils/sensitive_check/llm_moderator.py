from llm.gcp_models import CompositeClaude

async def topic_filter(content: str):
    """
      - content: 需要审核的文本内容
    返回: is_blocked bool
    """
    if not content or not isinstance(content, str) or not content.strip():
        raise Exception({'error': 'content参数是必需的，且必须是非空字符串'})
    
    llm = CompositeClaude()
    prompt = """You are a content moderator for a medical research platform. Your task is to determine if the provided content is appropriate for our medical research platform.

BLOCK content if it contains:
1. Non-medical topics (entertainment, sports, general news, technology unrelated to medicine, etc.)
2. Political content (elections, political parties, government policies, political figures, political opinions)
3. Inappropriate content (violence, harassment, illegal activities, adult content)

ALLOW content if it relates to:
1. Medical research and scientific studies
2. Drug development and clinical trials
3. Disease mechanisms and pathology
4. Medical technology and devices
5. Healthcare system analysis (non-political aspects)
6. Epidemiology and public health research
7. Pharmaceutical industry analysis
8. Medical education and training
9. Asking for medical advice

Note: If previous answer is provided as context, being unrelevant to current user prompt is ok as long as both previous and current content are appropriate seperately.

Respond with only one of these options:
- "ALLOW" - if the content is appropriate for our medical research platform
- "BLOCK" - if the content should be blocked

Content to evaluate: {content}

Decision:"""
    
    result = await llm(user_prompt=prompt.format(content=content), temperature=0)
    
    print("Moderation result:", result)
    if hasattr(result, 'text'):
        result = result.text
    if not isinstance(result, str):
        result = str(result)
    
    # Parse the response to determine if content should be blocked
    decision = result.strip()
    if decision not in ["ALLOW", "BLOCK"]:
        if decision.startswith("BLOCK"):
            decision = "BLOCK"
        elif "ALLOW" in decision:
            decision = "ALLOW"
        else:
            decision = "BLOCK"
    is_blocked = decision == "BLOCK"
    
    result = {
        "is_blocked": is_blocked,
        "decision": decision,
        "message": "Content blocked" if is_blocked else "Content allowed"
    }
    return is_blocked
        

async def political_topic_filter(content: str):
    """
      - content: 需要审核的文本内容
    返回: is_blocked bool
    """
    if not content or not isinstance(content, str) or not content.strip():
        raise Exception({'error': 'content参数是必需的，且必须是非空字符串'})
    
    llm = CompositeClaude()
    prompt = """You are a content moderator for an online research platform. Your task is to determine if the provided content is appropriate for our medical research platform.

BLOCK content if it contains sensitive political/historical content, especially those related to the Chinese government.

ALLOW content otherwise.

Note: If previous answer is provided as context, being unrelevant to current user prompt is ok as long as both previous and current content are appropriate seperately.

Respond with only one of these options:
- "BLOCK" - if the content should be blocked
- "ALLOW" - if the content is otherwise appropriate

Content to evaluate: {content}

Decision:"""
    
    result = await llm(user_prompt=prompt.format(content=content), temperature=0)
    
    print("Moderation result:", result)
    if isinstance(result, list) and result:
        result = result[0]
    if hasattr(result, 'text'):
        result = result.text
    if not isinstance(result, str):
        result = str(result)
    
    # Parse the response to determine if content should be blocked
    decision = result.strip()
    if decision not in ["ALLOW", "BLOCK"]:
        if decision.startswith("BLOCK"):
            decision = "BLOCK"
        elif "ALLOW" in decision:
            decision = "ALLOW"
        else:
            decision = "ALLOW"
    is_blocked = decision == "BLOCK"
    
    result = {
        "is_blocked": is_blocked,
        "decision": decision,
        "message": "Content blocked" if is_blocked else "Content allowed"
    }
    return is_blocked
        