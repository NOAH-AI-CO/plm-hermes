'''
managing streaming messages
'''
import re

def filter_score(text):
    '''
    将 text 中的 score 过滤掉， pattern 为 <function_quality_score>3</function_quality_score>， 其中的3可以为任何数字, 将html标签及中间的数字均过滤掉
    如果pattern已经单独占据了一行(该行除了pattern没有其余内容)， 那去除pattern的同时，也去除该行
    '''

    pattern = r'<function_quality_score>\d+</function_quality_score>'
    text = re.sub(pattern, '', text)

    # 去除标签后， 可能导致空行增加；将两个及以上的空行， 替换为两个空行（自然换行 + 1个空行）
    text = re.sub(r'\n{2,}', '\n\n', text)

    return text


def filte_tag(text, tag_text):
    '''
    将 text 中 的tag_text过滤.
    e.g. filte both <think> and </think> if tag_text is 'think' 
    '''

    list_tag = [f'<{tag_text}>', f'</{tag_text}>']
    for t in list_tag:
        text = text.replace(t, '')

    return text 


def func_post_message(content, type, status, memory):
    '''
    post process of message from llms
    '''

    # 分析content 内容， 根据内容的label进行处理， 按照需要增加 think, result 等类型标签
    '''
    if status == 'DONE':
        if type == 'CONTENT':
            print('result:\n')
            content = filte_tag(content, 'result')
    elif status == 'CONTINUE':
        if type == 'CONTENT':
            print('think:\n')
            content = filte_tag(content, 'think')
    else:
        pass 
    '''

    # 以上代码从分支的角度， 可能存在 result 中有 think 或者 think 中有 result 的情况。 
    # 故使用以下代码进行兜底， 无论如何都会过滤掉 think 和 result
    content = filte_tag(content, 'result')
    content = filte_tag(content, 'think')
    content = filte_tag(content, 'function_results_reflection')
    content = filte_tag(content, 'function_quality_reflection')
    # 过滤 score
    content = filter_score(content)

    # 过滤 function_results_reflection_score

    # 过滤

    return {
            "content":content, 
            "type":type, 
            "status":status, 
            "memory":memory
    }