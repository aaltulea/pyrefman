import re
from pathlib import Path
from typing import List, Dict, Any, Union


class NBIBParser:
    """
       Parse an NBIB/NLM record into a dict whose keys are the exact tags found in the input.
       - Continuation lines (lines that don't start with a tag) are appended to the previous tag's value.
       - Repeated tags become lists of values (preserves order).
       - No custom/grouping keys are added; output keys are exactly the tags present in the NBIB.
    """

    @staticmethod
    def parse(input) -> Dict[str, Any]:
        if isinstance(input, str):
            nbib_text = input
        elif isinstance(input, Path):
            nbib_text = input.read_text(encoding="utf-8")
        else:
            raise TypeError(f"Input must be a string or Path object. Got {type(input)} instead.")

        tag_re = re.compile(r"^([A-Z0-9\-]+)\s*-\s*(.*)$")

        def _norm(s: str) -> str:
            return re.sub(r"\s+", " ", s.strip())

        parsed: Dict[str, Union[str, List[str]]] = {}
        last_tag: Union[str, None] = None

        for raw in nbib_text.splitlines():
            if not raw:
                continue
            m = tag_re.match(raw)
            if m:
                tag = m.group(1)
                val = _norm(m.group(2))
                last_tag = tag
                if tag in parsed:
                    if isinstance(parsed[tag], list):
                        parsed[tag].append(val)
                    else:
                        parsed[tag] = [parsed[tag], val]
                else:
                    parsed[tag] = val
            else:
                # continuation line — append to last_tag's most recent value
                if last_tag is None:
                    continue
                cont = _norm(raw)
                cur = parsed.get(last_tag)
                if isinstance(cur, list):
                    cur[-1] = f"{cur[-1]} {cont}"
                else:
                    parsed[last_tag] = f"{cur} {cont}"

        # Final normalization: ensure strings are normalized and lists' elements are normalized
        for k, v in list(parsed.items()):
            if isinstance(v, list):
                parsed[k] = [_norm(x) for x in v]
            else:
                parsed[k] = _norm(v)

        return parsed

def demo_sample_text() -> str:
    return '''
PMID- 37118429
OWN - NLM
STAT- MEDLINE
DCOM- 20230501
LR  - 20250204
IS  - 2662-8465 (Electronic)
IS  - 2662-8465 (Linking)
VI  - 3
IP  - 3
DP  - 2023 Mar
TI  - Heterochronic parabiosis reprograms the mouse brain transcriptome by shifting 
      aging signatures in multiple cell types.
PG  - 327-345
LID - 10.1038/s43587-023-00373-6 [doi]
AB  - Aging is a complex process involving transcriptomic changes associated with 
      deterioration across multiple tissues and organs, including the brain. Recent 
      studies using heterochronic parabiosis have shown that various aspects of 
      aging-associated decline are modifiable or even reversible. To better understand 
      how this occurs, we performed single-cell transcriptomic profiling of young and 
      old mouse brains after parabiosis. For each cell type, we cataloged alterations 
      in gene expression, molecular pathways, transcriptional networks, ligand-receptor 
      interactions and senescence status. Our analyses identified gene signatures, 
      demonstrating that heterochronic parabiosis regulates several hallmarks of aging 
      in a cell-type-specific manner. Brain endothelial cells were found to be 
      especially malleable to this intervention, exhibiting dynamic transcriptional 
      changes that affect vascular structure and function. These findings suggest new 
      strategies for slowing deterioration and driving regeneration in the aging brain 
      through approaches that do not rely on disease-specific mechanisms or actions of 
      individual circulating factors.
CI  - © 2023. The Author(s).
FAU - Ximerakis, Methodios
AU  - Ximerakis M
AUID- ORCID: 0000-0002-2815-7558
AD  - Department of Stem Cell and Regenerative Biology, Harvard University, Cambridge, 
      MA, USA. methodiosximerakis@gmail.com.
AD  - Harvard Stem Cell Institute, Cambridge, MA, USA. methodiosximerakis@gmail.com.
AD  - Stanley Center for Psychiatric Research, Broad Institute of MIT and Harvard, 
      Cambridge, MA, USA. methodiosximerakis@gmail.com.
FAU - Holton, Kristina M
AU  - Holton KM
AD  - Department of Stem Cell and Regenerative Biology, Harvard University, Cambridge, 
      MA, USA.
AD  - Harvard Stem Cell Institute, Cambridge, MA, USA.
AD  - Stanley Center for Psychiatric Research, Broad Institute of MIT and Harvard, 
      Cambridge, MA, USA.
FAU - Giadone, Richard M
AU  - Giadone RM
AUID- ORCID: 0000-0003-4523-3062
AD  - Department of Stem Cell and Regenerative Biology, Harvard University, Cambridge, 
      MA, USA.
AD  - Harvard Stem Cell Institute, Cambridge, MA, USA.
FAU - Ozek, Ceren
AU  - Ozek C
AD  - Department of Stem Cell and Regenerative Biology, Harvard University, Cambridge, 
      MA, USA.
AD  - Harvard Stem Cell Institute, Cambridge, MA, USA.
FAU - Saxena, Monika
AU  - Saxena M
AD  - Department of Stem Cell and Regenerative Biology, Harvard University, Cambridge, 
      MA, USA.
AD  - Harvard Stem Cell Institute, Cambridge, MA, USA.
FAU - Santiago, Samara
AU  - Santiago S
AUID- ORCID: 0000-0002-9502-7104
AD  - Department of Stem Cell and Regenerative Biology, Harvard University, Cambridge, 
      MA, USA.
AD  - Harvard Stem Cell Institute, Cambridge, MA, USA.
FAU - Adiconis, Xian
AU  - Adiconis X
AD  - Stanley Center for Psychiatric Research, Broad Institute of MIT and Harvard, 
      Cambridge, MA, USA.
AD  - Klarman Cell Observatory, Broad Institute of MIT and Harvard, Cambridge, MA, USA.
FAU - Dionne, Danielle
AU  - Dionne D
AD  - Klarman Cell Observatory, Broad Institute of MIT and Harvard, Cambridge, MA, USA.
FAU - Nguyen, Lan
AU  - Nguyen L
AD  - Klarman Cell Observatory, Broad Institute of MIT and Harvard, Cambridge, MA, USA.
FAU - Shah, Kavya M
AU  - Shah KM
AUID- ORCID: 0000-0002-8722-4095
AD  - Department of Stem Cell and Regenerative Biology, Harvard University, Cambridge, 
      MA, USA.
AD  - Harvard Stem Cell Institute, Cambridge, MA, USA.
FAU - Goldstein, Jill M
AU  - Goldstein JM
AD  - Department of Stem Cell and Regenerative Biology, Harvard University, Cambridge, 
      MA, USA.
AD  - Harvard Stem Cell Institute, Cambridge, MA, USA.
FAU - Gasperini, Caterina
AU  - Gasperini C
AD  - Department of Stem Cell and Regenerative Biology, Harvard University, Cambridge, 
      MA, USA.
AD  - Harvard Stem Cell Institute, Cambridge, MA, USA.
FAU - Gampierakis, Ioannis A
AU  - Gampierakis IA
AD  - Department of Stem Cell and Regenerative Biology, Harvard University, Cambridge, 
      MA, USA.
AD  - Harvard Stem Cell Institute, Cambridge, MA, USA.
FAU - Lipnick, Scott L
AU  - Lipnick SL
AD  - Department of Stem Cell and Regenerative Biology, Harvard University, Cambridge, 
      MA, USA.
AD  - Harvard Stem Cell Institute, Cambridge, MA, USA.
AD  - Stanley Center for Psychiatric Research, Broad Institute of MIT and Harvard, 
      Cambridge, MA, USA.
FAU - Simmons, Sean K
AU  - Simmons SK
AD  - Stanley Center for Psychiatric Research, Broad Institute of MIT and Harvard, 
      Cambridge, MA, USA.
AD  - Klarman Cell Observatory, Broad Institute of MIT and Harvard, Cambridge, MA, USA.
FAU - Buchanan, Sean M
AU  - Buchanan SM
AD  - Department of Stem Cell and Regenerative Biology, Harvard University, Cambridge, 
      MA, USA.
AD  - Harvard Stem Cell Institute, Cambridge, MA, USA.
FAU - Wagers, Amy J
AU  - Wagers AJ
AD  - Department of Stem Cell and Regenerative Biology, Harvard University, Cambridge, 
      MA, USA.
AD  - Harvard Stem Cell Institute, Cambridge, MA, USA.
AD  - Joslin Diabetes Center, Boston, MA, USA.
AD  - Paul F. Glenn Center for the Biology of Aging, Harvard Medical School, Boston, 
      MA, USA.
FAU - Regev, Aviv
AU  - Regev A
AUID- ORCID: 0000-0003-3293-3158
AD  - Klarman Cell Observatory, Broad Institute of MIT and Harvard, Cambridge, MA, USA.
AD  - Howard Hughes Medical Institute, Koch Institute of Integrative Cancer Research, 
      Department of Biology, Massachusetts Institute of Technology, Cambridge, MA, USA.
FAU - Levin, Joshua Z
AU  - Levin JZ
AUID- ORCID: 0000-0002-0170-3598
AD  - Stanley Center for Psychiatric Research, Broad Institute of MIT and Harvard, 
      Cambridge, MA, USA.
AD  - Klarman Cell Observatory, Broad Institute of MIT and Harvard, Cambridge, MA, USA.
FAU - Rubin, Lee L
AU  - Rubin LL
AUID- ORCID: 0000-0002-8658-841X
AD  - Department of Stem Cell and Regenerative Biology, Harvard University, Cambridge, 
      MA, USA. lee_rubin@harvard.edu.
AD  - Harvard Stem Cell Institute, Cambridge, MA, USA. lee_rubin@harvard.edu.
AD  - Stanley Center for Psychiatric Research, Broad Institute of MIT and Harvard, 
      Cambridge, MA, USA. lee_rubin@harvard.edu.
LA  - eng
GR  - T32 NS007433/NS/NINDS NIH HHS/United States
GR  - RF1 NS117407/NS/NINDS NIH HHS/United States
GR  - T32 DK007529/DK/NIDDK NIH HHS/United States
GR  - R01 AG072086/AG/NIA NIH HHS/United States
GR  - R01 NS117407/NS/NINDS NIH HHS/United States
PT  - Journal Article
PT  - Research Support, N.I.H., Extramural
PT  - Research Support, Non-U.S. Gov't
DEP - 20230309
PL  - United States
TA  - Nat Aging
JT  - Nature aging
JID - 101773306
SB  - IM
EIN - Nat Aging. 2025 Feb;5(2):333. doi: 10.1038/s43587-025-00804-6. PMID: 39881191
MH  - Animals
MH  - Mice
MH  - *Transcriptome/genetics
MH  - *Endothelial Cells
MH  - Aging/genetics
MH  - Parabiosis
MH  - Brain
PMC - PMC10154248
COIS- L.L.R. is a founder of Elevian, Rejuveron and Vesalius Therapeutics, a member of 
      their scientific advisory boards and a private equity shareholder. All are 
      interested in formulating approaches intended to treat diseases of the nervous 
      system and other tissues. He is also on the advisory board of Alkahest, a Grifols 
      company, focused on the plasma proteome. None of these companies provided any 
      financial support for the work in this paper. A.J.W. is a scientific advisor for 
      Kate Therapeutics and Frequency Therapeutics, and is a founder of Elevian, Inc. 
      and a member of their scientific advisory board and shareholder. Elevian, Inc. 
      also provides sponsored research to the Wagers lab. A.R. is a founder and equity 
      holder of Celsius Therapeutics, an equity holder in Immunitas Therapeutics and 
      until 31 August 2020 was a SAB member of Syros Pharmaceuticals, Neogene 
      Therapeutics, Asimov and Thermo Fisher Scientific. From 1 August 2020, A.R. has 
      been an employee of Genentech, a member of the Roche Group. M.X. has been an 
      employee of Merck & Co. since August 2020. The remaining authors declare no 
      competing interests.
EDAT- 2023/04/29 06:04
MHDA- 2023/05/01 06:42
PMCR- 2023/03/09
CRDT- 2023/04/28 23:41
PHST- 2022/05/19 00:00 [received]
PHST- 2023/01/30 00:00 [accepted]
PHST- 2023/05/01 06:42 [medline]
PHST- 2023/04/29 06:04 [pubmed]
PHST- 2023/04/28 23:41 [entrez]
PHST- 2023/03/09 00:00 [pmc-release]
AID - 10.1038/s43587-023-00373-6 [pii]
AID - 373 [pii]
AID - 10.1038/s43587-023-00373-6 [doi]
PST - ppublish
SO  - Nat Aging. 2023 Mar;3(3):327-345. doi: 10.1038/s43587-023-00373-6. Epub 2023 Mar 
      9.

'''.strip()


def run_demo(printer=None):
    if printer is None:
        from pprint import pprint as printer

    proc = NBIBParser()
    parsed = proc.parse(demo_sample_text())
    printer(parsed)
    return parsed


if __name__ == '__main__':
    run_demo()
