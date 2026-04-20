# PyRefMan

PyRefMan is a Python-based reference manager that automates bibliography handling. Paste supported source URLs into your text, and PyRefMan will fetch metadata, format inline citations, and generate a reference list.

## Overview

PyRefMan supports a simple workflow:

- Paste text containing bracketed URLs (e.g., `[url]`, `[url1, url2]`, or `[url1] [url2]`)
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

git clone <repository-url>

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

### Supported Sources

* PubMed
* bioRxiv

### Workflow

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


