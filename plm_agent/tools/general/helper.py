def turncate_dict(d, max_length: int = 500):
    if isinstance(d, dict):
        res = {}
        for key, value in d.items():
            res[key] = turncate_dict(value, max_length)
    
    elif isinstance(d, list):
        res = []
        for item in d:
            res.append(turncate_dict(item, max_length))
    
    elif isinstance(d, str):
        res = d[:max_length] + '...' if len(d) > max_length else d
    
    else:
        res = d

    return res
    
def main():
    data = {
        "name": "用户资料",
        "info": {
            "id": 12345,
            "username": "test_user",
            "description": "这是一个非常长的描述，将被截断处理" * 5,
            "settings": {
                "theme": "dark",
                "notifications": True,
                "privacy": {
                    "public_profile": False,
                    "show_email": False
                }
            }
        },
        "posts": ["很长的帖子内容" * 10, "另一个帖子"]
    }

    turncated_data = turncate_dict(data)
    print(turncated_data)

if __name__ == "__main__":
    main()

