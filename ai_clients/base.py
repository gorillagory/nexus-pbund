from abc import ABC, abstractmethod


class BaseAIClient(ABC):
    @abstractmethod
    def list_models(self):
        raise NotImplementedError

    @abstractmethod
    def generate(self, prompt, model=None, timeout=None):
        raise NotImplementedError

    @abstractmethod
    def generate_stream(self, prompt, model=None, timeout=None):
        raise NotImplementedError
