from typing import List

from json_repair import repair_json

from llm.azure_models import GPT4oWorkflow


async def gen_dose(doses: str):
    if not doses or len(doses) == 0:
        return ""
    model = GPT4oWorkflow()
    sys_prompt = """
    You are a clinical trial expert. You are given a list of arms for a clinical trial.
    You need to generate a summary of the arms. Reply with a json with the following format:
    [{
        "name": "LoDAC (Low Dose Cytarabine)",
        "dose": "130 mg",
        "frequency": "QD",
        "duration": "12 weeks",
        "how": "SC" or "IV"
    }, ...]
    # instructions:
    - use SC or IV to indicate how the drug is given
    - keep empty fields as ""
    """
    user_prompt = f"""
    {doses}
    """
    result = await model(sys_prompt, user_prompt)
    results = eval(repair_json(result.content))
    return "\n".join([f"- {result['name']} {result['dose']} {result['frequency']} {result['duration']} {result['how']}" for result in results])
