from pyrefman.data import InlineReference
from pyrefman.sources.BioRxivSource import BioRxivSource
from pyrefman.sources.NCBIGeoSource import NCBIGeoSource
from pyrefman.sources.PubMedSource import PubMedSource
import traceback


class SourcesLooper:
    SOURCES = None

    def __init__(self, citations_dir):
        self.citations_dir = citations_dir
        self.SOURCES = [
            PubMedSource(citations_dir),
            BioRxivSource(citations_dir),
            NCBIGeoSource(citations_dir)
        ]

    def accepts(self, url):
        for source in self.SOURCES:
            if source.accepts(url):
                return True
        return False

    def fetch_references_from_repos(self, reference: "InlineReference"):
        for source in self.SOURCES:
            if source.accepts(reference.url):
                try:
                    nbib_output = source.download(reference)
                    if nbib_output:
                        reference.associate_nbib(nbib_output)
                except Exception:
                    traceback.print_exc()
                    print("[ERROR] Couldn't obtain reference information for ", reference)
