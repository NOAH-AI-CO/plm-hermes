---
name: attachment
description: "Download and parse attachment URLs (PDF / DOCX / XLSX / CSV / images). Returns text previews and sandbox blob paths."
---

# Attachment skill

## ``attachment_download``

Pass up to 10 URLs. Each file is downloaded in parallel, parsed, and
returned with:

- ``filename``
- ``type`` — ``pdf`` / ``docx`` / ``xlsx`` / ``csv`` / ``image`` / ``other``
- ``success`` — bool
- ``blob_path`` — a path usable inside the sandbox for further processing
- ``text_preview`` — first 500 chars of extracted text
- ``data_description`` — for tabular files, a shape/columns summary
- ``error`` — non-empty when ``success`` is false

```json
{
  "urls": [
    "https://example.com/paper.pdf",
    "https://example.com/data.xlsx"
  ],
  "explanation": "reading user uploads"
}
```

## When to pair with ``run_in_sandbox``

If the preview isn't enough:

1. Call ``attachment_download`` to get ``blob_path``.
2. Call ``run_in_sandbox`` with Python code that reads the blob, e.g.
   ```python
   import pdfplumber
   with pdfplumber.open("<blob_path>") as pdf:
       for page in pdf.pages[:10]:
           print(page.extract_text())
   ```
3. For spreadsheets, use ``pandas.read_excel(blob_path)`` or
   ``pandas.read_csv(blob_path)``.

## Limits

- Max 10 URLs per call. Batch your requests if the user shared more.
- Images are saved to the blob but not OCR'd automatically — use
  ``pytesseract`` inside the sandbox when OCR is needed.
- PDFs with scanned pages (image-only) need OCR; text-only PDFs are
  extracted directly.
