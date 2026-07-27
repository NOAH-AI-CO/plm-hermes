import json
from math import e, prod
def process_prob(response, details=False):
    """
    Separate the log probability into the probability and the sign.
    """
    message = response.choices[0].message.content
    if not response.choices[0].logprobs:
        return
    logprobs = response.choices[0].logprobs.content
    prob_map = map_probabilities_for_key_value_pair_v2(json.loads(message), logprobs)
    # for item in [(2.718281828459045 ** logprob_obj.logprob, logprob_obj.token) for logprob_obj in logprobs]:
    #     print(item)
    # probs = [2.718281828459045 ** logprob_obj.logprob for logprob_obj in logprobs]
    # print("probs", probs)
    logprob_sum = sum([logprob_obj.logprob for logprob_obj in logprobs])
    # return prod(probs)
    response.choices[0].logprobs = None
    msg_json = json.loads(response.choices[0].message.content)
    # confidences = {}
    msg_json['confidence'] = prod([v['confidence'] for v in prob_map.values()])
    if details:
        msg_json['probabilities'] = prob_map
    
    response.choices[0].message.content = json.dumps(msg_json)

def map_probabilities_for_key_value_pair_v2(obj, lp):
    results = {}
    idx = 0
    for k, v in obj.items():
        key_str = json.dumps({k: v}, separators=(',', ':'))
        # Identify relevant tokens for this segment
        relevant_probs = []
        match = 0
        cnt = 0
        for logprob_obj in lp[idx:]:
            cnt += 1
            if logprob_obj.token in key_str:
                relevant_probs.append(logprob_obj)
                match += 1
            else:
                if match:
                    break
        idx += cnt
        if relevant_probs:
            sum_val = 0
            n = len(relevant_probs) 
            for rp in relevant_probs:
                sum_val += rp.logprob
            if v:
                results[k] = {"value":v, "confidence":e ** (sum_val/n), 
                            #   "prob_prod":e ** sum_val
                              }
        if isinstance(v, dict):
            results[k]['detail'] = map_probabilities_for_key_value_pair_v2(v, relevant_probs)
    return results


# def map_probabilities_for_key_value_pairs_recurse(obj):
#     if isinstance(obj, dict):
#         for k, v in obj.items():
#             if isinstance(v, dict):
#                 map_probabilities_for_key_value_pairs_recurse(v)
#             elif isinstance(v, list):
#                 for item in v:
#                     map_probabilities_for_key_value_pairs_recurse(item)
#             else:
#                 print(k, v)
#     elif isinstance(obj, list):
#         for item in obj:
#             map_probabilities_for_key_value_pairs_recurse(item)
#     else:
#         print(obj)