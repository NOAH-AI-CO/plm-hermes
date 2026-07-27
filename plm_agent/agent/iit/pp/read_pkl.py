import pickle
from agent.iit.pp.prompt_v2 import list_of_formal_sections, list_of_scientific_sections
from collections import defaultdict

def read_pkl(pkl_file):
    with open(pkl_file, 'rb') as f:
        obj = pickle.load(f)
    return obj

def read_formal_classification_results():
    _results = read_pkl('/Users/andy/repos/NoahAgent/noah_agent/classification_results_formal.pkl')

    cnt = defaultdict(int)
    other_cnt = defaultdict(int)
    for l in _results:
        for item in l:
            if isinstance(item, str):
                continue
            idx, _cls = item
            for k in sorted(list_of_formal_sections, reverse=True):
                if _cls.startswith(k):
                    cnt[k] += 1
                    break
            else:
                other_cnt[_cls] += 1
    # for key in cnt.keys():
    #     print(key, cnt[key])
    for key in other_cnt.keys():
        print(key, other_cnt[key])

def read_scientific_classification_results():
    _results = read_pkl('/Users/andy/repos/NoahAgent/noah_agent/classification_results_scientific.pkl')

    cnt = defaultdict(int)
    other_cnt = defaultdict(int)
    for l in _results:
        for item in l:
            if isinstance(item, str):
                continue
            idx, _cls = item
            for k in sorted(list_of_scientific_sections, reverse=True):
                if _cls.startswith(k):
                    cnt[k] += 1
                    break
            else:
                other_cnt[_cls] += 1
    # for key in cnt.keys():
    #     print(key, cnt[key])
    # for key in other_cnt.keys():
    #     print(key, other_cnt[key])
        
read_formal_classification_results()