from abc import abstractmethod, ABC

from pyrefman.data.InlineReference import InlineReference


# Abstract base for reference sources
class ReferencesSource(ABC):
    def __init__(self, citations_dir):
        self.driver = None
        self.citations_dir = citations_dir

    @abstractmethod
    def accepts(self, url: str) -> bool:
        pass

    @abstractmethod
    def download(self, reference: InlineReference) -> bool:
        pass
