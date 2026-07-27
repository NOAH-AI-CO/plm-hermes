from config import settings
from llm.ali_models import Qwen3, SiliconFlowQwen3
from llm.azure_models import GPT41, GPT5Mini, GPTo4Mini, GPTo3, GPT5, GPT52, GPT54
from llm.openai_models import Openaio4Mini, Openaio3, Openai5, Openai52
from llm.deepseek_models import DeepseekChat, DeepseekChatR1, SiliconflowDeepseekChat
from llm.gcp_models import Gemini25Flash, Gemini25Pro, ClaudeSonnet4, Gemini3Flash, Gemini31Pro
from llm.base_model import CompositeModel

class SlotFillingModels(CompositeModel):
    def __init__(self, **params) -> None:
        self.models = [GPTo4Mini(reasoning_effort='medium'), GPTo3(), DeepseekChat(**params), Qwen3(**params)]
        super().__init__()
        
class LowEffortSlotFillingModels(CompositeModel):
    def __init__(self, **params) -> None:
        self.models = [DeepseekChatR1(**params), DeepseekChat(**params)]
        super().__init__()
        
class DeepseekChatModels(CompositeModel):
    def __init__(self, **params) -> None:
        self.models = [DeepseekChat(**params), DeepseekChatR1(**params), DeepseekChat(**params), GPTo4Mini(reasoning_effort='low'), Qwen3(**params), GPTo3()]
        super().__init__()

class IDSelectionModels(CompositeModel):
    def __init__(self, **params) -> None:
        self.models = [DeepseekChat(**params), Openaio4Mini(), GPTo4Mini(), GPT41(),  
                      SiliconflowDeepseekChat(**params), Qwen3(**params)]
        super().__init__()
        
class GPT41Deepseek(CompositeModel):
    provider = "openai"
    
    models = [GPT41(), DeepseekChat()]

class Compositeo4mini(CompositeModel):
    
    provider = "azure_openai"
    models = [GPTo4Mini(reasoning_effort='medium'), Openaio4Mini(reasoning_effort='medium'), GPT41()]
    

class Compositeo3(CompositeModel):

    provider = "openai"
    
    def __init__(self):
        # 尝试初始化模型，跳过配置缺失的模型
        models = []
        for model_cls, model_name in [
            (lambda: GPTo3(), "GPTo3"),
            (lambda: Openaio3(), "Openaio3"),
            (lambda: GPT5(), "GPT5"),
            (lambda: GPT5Mini(), "GPT5Mini")
        ]:
            try:
                models.append(model_cls())
            except (KeyError, AttributeError) as e:
                print(f"⚠️  跳过模型 {model_name}: 配置缺失 ({e})")
        
        if not models:
            raise RuntimeError("Compositeo3: 没有可用的模型")
        
        self.models = models
        super().__init__()


class CompositeGPT5(CompositeModel):

    provider = "openai"
    
    def __init__(self):
        # 尝试初始化模型，跳过配置缺失的模型
        models = []
        for model_cls, model_name in [
            (lambda: GPT5(), "GPT5"),
            (lambda: GPT54(), "GPT54"),
            (lambda: Openai5(), "Openai5"),
            (lambda: GPTo3(), "GPTo3"),
            (lambda: GPT5Mini(), "GPT5Mini"),
            (lambda: GPT41(), "GPT41")
        ]:
            try:
                models.append(model_cls())
            except (KeyError, AttributeError) as e:
                print(f"⚠️  跳过模型 {model_name}: 配置缺失 ({e})")
        
        if not models:
            raise RuntimeError("CompositeGPT5: 没有可用的模型")
        
        self.models = models
        super().__init__()


class CompositeGPT5Mini(CompositeModel):

    provider = "openai"
    
    def __init__(self):
        # 尝试初始化模型，跳过配置缺失的模型
        models = []
        for model_cls, model_name in [
            (lambda: GPT5Mini(), "GPT5Mini"),
            (lambda: GPTo4Mini(), "GPTo4Mini"),
            (lambda: GPT41(), "GPT41")
        ]:
            try:
                models.append(model_cls())
            except (KeyError, AttributeError) as e:
                print(f"⚠️  跳过模型 {model_name}: 配置缺失 ({e})")
        
        if not models:
            raise RuntimeError("CompositeGPT5Mini: 没有可用的模型")
        
        self.models = models
        super().__init__() 


class CompositeHitlFinal(CompositeModel):

    provider = ""
    models = [Gemini25Pro(), Openaio3(), ClaudeSonnet4(), GPT41()]


class CompositeMindsearchFinal(CompositeModel):

    provider = ""
    models = [GPT41(), Gemini25Flash()]

class DeepseekClaude(CompositeModel):
    models = [ClaudeSonnet4(), Gemini25Flash()]
    
class Compositeo3Claude(CompositeModel):
    models = [Openaio3(), GPTo3(), Gemini25Pro(), ClaudeSonnet4(), GPT41()]
    
class MedicalPaperWritingModels(CompositeModel):
    models = [Gemini25Pro(), Gemini25Flash(), ClaudeSonnet4(), Openaio3(), GPTo4Mini()]
    
class SiliconflowQwen3Models(CompositeModel):
    models = [SiliconFlowQwen3(), Qwen3()]
    
class NSFCWritingModels(CompositeModel):
    models = [Qwen3(), Gemini25Pro(), Gemini25Flash(), SiliconFlowQwen3()]

class IITReviewModels(CompositeModel):
    models = [Gemini3Flash(), Gemini31Pro(), Gemini3Flash(), Gemini31Pro()]
    
class BetterIITReviewModels(CompositeModel):
    models = [Gemini31Pro(), Gemini3Flash(), Gemini31Pro(), Gemini3Flash()]

class EthicsReviewModels(CompositeModel):
    models = [Gemini31Pro(), Gemini3Flash(), Gemini31Pro()]

class BetterEthicsReviewModels(CompositeModel):
    models = [Gemini31Pro(), Gemini3Flash(), Gemini31Pro(), Gemini3Flash()]

class EthicsPolicyMetadataModels(CompositeModel):
    models = [Gemini3Flash(), Gemini31Pro(), Gemini3Flash()]

class JournalRecommendationModels(CompositeModel):
    models = [Gemini25Pro(), Gemini25Flash()]


class CompositeGPT52(CompositeModel):

    provider = "openai"

    def __init__(self):
        models = []
        for model_cls, model_name in [
            (lambda: GPT52(), "GPT52"),
            (lambda: GPT5(), "GPT5"),
            (lambda: Openai52(), "Openai52"),
            (lambda: Openai5(), "Openai5"),
            (lambda: GPT5Mini(), "GPT5Mini"),
        ]:
            try:
                models.append(model_cls())
            except (KeyError, AttributeError) as e:
                print(f"⚠️  跳过模型 {model_name}: 配置缺失 ({e})")

        if not models:
            raise RuntimeError("CompositeGPT52: 没有可用的模型")

        self.models = models
        super().__init__()