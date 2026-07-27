from functools import reduce
from utils.retrievers.typesense_retriever import search_one_column, get_client

def clean_args_typesense(args: dict, citeline = False, tool = '') -> dict:
    if tool in ["Drug-Analysis"]:
        citeline = True
    client = get_client()
    map_dict = {"indication_name": "indication", "target": "target", "lead_company":"company", "company": "company", "drug_name": "drug"}
    if citeline:
        map_dict.update({"target": "citeline_target", "company":"citeline_company", "drug_name": "citeline_drug", "indication_name": "citeline_indication"})
    for key in map_dict.keys():
        if key in args and args[key]:
            new_data = set()
            if type(args[key]) == dict: 
                items = reduce(lambda x, y: x + y, [item.split('/') for item in args[key].get("data",[])], [])
                for item in set(items):
                    search_result = search_one_column(client=client, name=map_dict[key], query=item, num_typos=1)
                    if search_result:
                        new_data.add(search_result)
                    else:
                        pass
                args[key]["data"] = list(new_data)
            elif type(args[key]) == list:
                items = reduce(lambda x, y: x + y, [item.split('/') for item in args[key]], [])
                for item in items:
                    search_result = search_one_column(client=client, name=map_dict[key], query=item, num_typos=1)
                    if search_result:
                        new_data.add(search_result)
                    else:
                        pass
                args[key] = list(new_data)

    if tool == "Drug-Analysis":
        args['location'] = args.get('location', []) or ['USA', 'China', 'Japan', 'UK', 'France', 'Germany', 'Italy', 'Spain']
        # 替换 'united states' 为 'USA'，忽略大小写
        args['location'] = [
            'USA' if loc.lower() == 'united states' else loc for loc in args['location']
        ]

    for key in ['location', 'locations']:
        if args.get(key, []):
            location = args[key].copy()
            for l in location:
                if 'global' in l.lower() or 'world' in l.lower():
                    for country in ['USA', 'China', 'Japan', 'UK', 'France', 'Germany', 'Italy', 'Spain']:
                        if country not in args[key]:
                            args[key].append(country)
                    break
                if 'europe' in l.lower():
                    for country in ['Germany', 'France', 'Italy', 'Spain', 'UK']:
                        if country not in args[key]:
                            args[key].append(country)
                    break
    
    if tool == 'Clinical-Trial-Result-Analysis':
        if 'locations' in args and 'USA' in args['locations']:
            args['locations'] = [
                'United States' if loc.lower() == 'usa' else loc for loc in args['locations']
            ]
    
    return args


def main():
    # Drug-Analysis location
    #args = {'location': ['United States', 'China']}
    #res = clean_args_typesense(args=args, tool='Drug-Analysis')
    #print(res)

    # Global
    args = {'location': ['global']}
    res = clean_args_typesense(args=args, tool='Drug-Analysis')
    print(res)

    #args = {'locations': ['USA']}
    #res = clean_args_typesense(args=args, tool='Clinical-Trial-Result-Analysis')
    #print(res)

if __name__ == "__main__":
    main()

