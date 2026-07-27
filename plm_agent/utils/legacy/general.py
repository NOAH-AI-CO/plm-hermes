import re
from pygtrans import Translate  # Google translate API
import logging
import random


def translate_to_english(str):
    """
    Translate a string to English. Called by the function score_pi.

    Parameters:
    str (str): The string to be translated.

    Returns:
    translated_str (str): The translated string.
    """

    client = Translate()
    translated_str = client.translate(str, target="en")

    return translated_str.translatedText


def remove_html_tags(text):
    return re.sub(r'<.*?>', '', text)


def is_english_regex(text):
    return bool(re.match(r'^[a-zA-Z\s]+$', text))


aws_regions = ['us-west-2', 'us-east-1']
aws_anthropic_models = ('anthropic.claude-3-5-sonnet-20240620-v1:0', 'anthropic.claude-3-sonnet-20240229-v1:0', 'anthropic.claude-3-haiku-20240307-v1:0', 'anthropic.claude-3-opus-20240229-v1:0')
    
def retry_aws(obj, func, *args, **kwargs):
    param_model = kwargs.get('model')
    if param_model in aws_anthropic_models:
        reordered_models = (param_model,) + tuple((model,) for model in aws_anthropic_models if model != param_model)
    else:
        reordered_models = aws_anthropic_models
    # print('reordered_models:', list(reordered_models))
    for model in reordered_models:
        kwargs['model'] = model
        random.shuffle(aws_regions)
        for region in aws_regions:
            try:
                obj.aws_region = region
                obj.base_url = f"https://bedrock-runtime.{region}.amazonaws.com"
                res = func(*args, **kwargs)
                return res
            except Exception as e:
                print(e)
                logging.debug(f"retry_aws failed on region {region}: {e}")