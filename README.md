# PyRefMan

PyRefMan is a Python-based reference manager that automates bibliography handling. Paste supported source URLs into your text, and PyRefMan will fetch metadata, format inline citations, and generate a reference list.

<img height="500px" alt="image" src="https://github.com/user-attachments/assets/541b7927-a4fd-49ea-ad8c-2f87434aa404" />


## Overview

PyRefMan supports a simple workflow:

- Paste text containing bracketed URLs (e.g., `[url]` OR `[url1, url2]` OR `[url1] [url2]`)
- Run the app
- Let PyRefMan collect reference metadata
- Receive formatted citations and a generated bibliography

## Installation

### Option 1: Download ZIP
1. Open the repository page.
2. Click `Code` → `Download ZIP`.
3. Extract the archive.

### Option 2: Clone with Git
```
git clone https://github.com/aaltulea/pyrefman.git
````

### Run the application
From the project folder:

- Windows: `start-pyrefman-windows.bat`
- macOS: `start-pyrefman-mac.command`
- Linux: `start-pyrefman-linux.sh`

## First Run

On first launch, the setup will:

- Create a local Python virtual environment
- Install dependencies (including Playwright)
- Download a local Pandoc build (if available)

This may take a few minutes. If prompted by your firewall, allow access. Network-dependent steps are retried for up to 5 minutes.

## Usage

### Input Format

PyRefMan expects reference URLs in brackets:

```text
[https://pubmed.ncbi.nlm.nih.gov/11111111/]
````

Grouped citations:

```text
[https://pubmed.ncbi.nlm.nih.gov/11111111/], [https://pubmed.ncbi.nlm.nih.gov/22222222/]
```

or:

```text
[https://pubmed.ncbi.nlm.nih.gov/11111111/, https://pubmed.ncbi.nlm.nih.gov/22222222/]
```

## Example input text


<details>
  <summary>Click here to expand</summary>

  Cellular senescence is a stress-induced state of stable cell cycle arrest triggered by factors such as DNA damage, telomere attrition, and oncogenic signaling, in which cells remain metabolically active and undergo functional changes that contribute to deleterious effects, with the arrest primarily mediated by tumor suppressor pathways including p53/p21 and p16 [[https://pubmed.ncbi.nlm.nih.gov/33855023/](https://pubmed.ncbi.nlm.nih.gov/33855023/)] [[https://pubmed.ncbi.nlm.nih.gov/20078217/](https://pubmed.ncbi.nlm.nih.gov/20078217/)] [[https://pubmed.ncbi.nlm.nih.gov/34663974/](https://pubmed.ncbi.nlm.nih.gov/34663974/)].


</details>


## Supported Sources

* PubMed e.g., `[https://pubmed.ncbi.nlm.nih.gov/11111111/]`
* bioRxiv e.g., `[https://www.biorxiv.org/content/10.64898/2026.04.20.719538v1]`
* NCBI GEO e.g., `[https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE157563]`
* DOI link e.g., `[https://doi.org/10.1038/s43587-026-01097-z]`

## Workflow

1. Create your document (Google Docs or any word processor).

   **Google Docs notes:**

   * Press space after typing a URL so it becomes a clickable hyperlink.
   * Non-hyperlinked URLs are not processed.
   * Set document access to “Anyone with the link can view,” or export it and use a local file.

2. Launch PyRefMan using the platform script.

3. Select an input source:

   * Local file
   * Google Docs URL
   * Pasted plain text or Markdown

4. Choose output location and reference style.

5. Run the app. Keep the browser window open during processing.

6. Open the generated output.

## Notes

* Supports plain text and Markdown.
* Non-Markdown local files are converted via Pandoc (formatting and images may be lost).
* Output formats: Markdown and Word (DOCX).
* Optional CSV mapping file can be generated.

## Contributing

Pull requests are welcome, especially:

* Additional reference styles
* New supported sources
* UI improvements
* Platform-specific enhancements


