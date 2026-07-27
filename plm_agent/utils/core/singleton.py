from abc import ABC, abstractmethod

class Singleton(ABC):

    @classmethod
    @abstractmethod
    def get_client(cls):
        pass

    @classmethod
    @abstractmethod
    def get_asyncclient(cls):
        pass

    @classmethod
    @abstractmethod
    def initialize(cls):
        pass

    @classmethod
    @abstractmethod
    def cleanup(cls):
        pass

    @classmethod
    @abstractmethod
    def reset(cls):
        pass
