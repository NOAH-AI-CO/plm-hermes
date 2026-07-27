from utils.sql_client import get_connection_user, text
import logging

logger = logging.getLogger(__name__)

class PromptFetcher:
    _instance = None
    prompt_dict = {}
    prompts_to_fetch = []
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(PromptFetcher, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if not hasattr(self, '_initialized') or not self._initialized:
            print('initing PromptFetcher')
            self.prompts_to_fetch = ['DEBUG', 'PROMPT']
            self.fetch_all()
            self._initialized = True
        
    def fetch_all(self):
        try:
            with get_connection_user() as conn:
                result = conn.execute(text(f"""SELECT prompt_list FROM "Config_activeprompts" LIMIT 1"""))
                prompt_list = result.scalar()
            self.prompts_to_fetch = prompt_list or []
            logger.info(f"Fetched prompt list: {self.prompts_to_fetch}")
        except Exception as e:
            logger.info(f"Error fetching prompt list: {e}")
        for p in self.prompts_to_fetch:
            self.fetch(p)
            
    def update_list(self, prompt_list):
        prev_prompts = self.prompts_to_fetch
        self.prompts_to_fetch = prompt_list
        for p in self.prompts_to_fetch:
            if p not in prev_prompts:
                self.fetch(p)
        logger.info(f"Updated prompt list: {self.prompts_to_fetch}")
            
    def fetch(self, name: str):
        try:
            with get_connection_user() as conn:
                result = conn.execute(text(f"""SELECT content FROM "PromptPlayground_prompt" WHERE name='{name}' AND revision=-1 LIMIT 1"""))
                prompt_content = result.scalar()
                if prompt_content:
                    self.prompt_dict[name] = prompt_content
        except Exception as e:
            logger.info(f"Error fetching prompt '{name}': {e}")
        
    def get(self, name: str, default=None):
        if name not in self.prompts_to_fetch:
            return default
        if name not in self.prompt_dict:
            logger.info(f"Prompt '{name}' not found in cache, using default value.")
            return default
        return self.prompt_dict.get(name, default)
    
    def print_all(self):
        for name, content in self.prompt_dict.items():
            print(f"{name}: {content}")