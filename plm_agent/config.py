from datetime import datetime
import json
import os
import random
from copy import deepcopy

class MetaConfig(dict):
    """
    A dictionary-like configuration class with attribute-style access.

    Inherited from dictionary, this class provides methods for accessing and modifying
    dictionary items using attributes and methods.
    """

    def __init__(self, *args, **kwargs):
        """
        Initialize class instance.

        Args:
            *args: Variable length argument list.
            **kwargs: Arbitrary keyword arguments.
        """
        super().__init__(*args, **kwargs)

    def __getitem__(self, key):
        """
        Get the value for the specified key.

        If the value contains '||', it will randomly select one of the split values.

        Args:
            key (str): The key to retrieve from the dictionary.

        Returns:
            str: The corresponding value, or a randomly selected value if '||' is found.

        Raises:
            AttributeError: If the key does not exist in the dictionary.
        """
        val = dict.__getitem__(self, key)
        if isinstance(val, str) and "||" in val:
            return random.choice(val.split("||"))
        return val

    def __getattr__(self, key: str):
        try:
            return self[key]
        except KeyError:
            if os.getenv("NOAH_LENIENT_CONFIG"):
                return ""
            raise AttributeError(key)

    def to_dict(self, safe=False):
        """
        Convert the MetaConfig object to dictionary.

        Args:
            safe (bool, optional): If True, 'api_keys' will be excluded from the output.
                Default is False.

        Returns:
            dict: Dictionary representation of the instance.
        """
        if safe:
            right_value = deepcopy(self)
            right_value.pop("api_keys", "")
            return right_value
        else:
            return self

    def reload(self, config_file='api.json'):
        """
        Load configuration data from json file and environment variables. And also update
        the ARGS with new data.

        Args:
            config_file (str, optional): Path to the json configuration file.
                Default is 'api.json'.
        """
        config_file = os.getenv('CONFIG_FILE', config_file)
        print('---config file---\n'+str(config_file))
        new_config = json.load(open(config_file, 'r', encoding="utf-8"))
        self.clear()
        self.update(new_config)

    @staticmethod
    def get_default_config(config_file='api.json'):
        """
        Get default configuration data from given file through environment variable.

        Args:
            sconfig_file (str, optional): Path to the json configuration file.
                Default is 'api.json'.

        Returns:
            MetaConfig: An instance of MetaConfig with loaded configuration data.
        """
        try:
            config_file = os.getenv('CONFIG_FILE', config_file)
            print('---read config file:'+str(config_file))
            cfg = json.load(open(config_file, 'r', encoding="utf-8"))
        except Exception as e:
            cfg = {}
            print(e)
        return MetaConfig(**cfg)

print(f"Current datetime: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
api_config = MetaConfig.get_default_config("api.json")
settings = MetaConfig.get_default_config("setting_test.json")
