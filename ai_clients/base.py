from abc import ABC, abstractmethod


class BaseAIClient(ABC):
    @abstractmethod
    def list_models(self):
        raise NotImplementedError

    @abstractmethod
    def generate(self, prompt, model=None):
        raise NotImplementedError
