---
name: attachment-download
description: "Download and parse attachments (PDF/Excel/CSV/Word/Image) from URLs. Returns content preview and blob paths."
---

# Attachment Download

## Usage
```bash
attachment-download '{"urls": ["https://example.com/file.pdf"]}'
```

## Parameters
| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| urls | list[str] | Yes | - | List of attachment URLs (max 10) |

## Output
For each file:
- Filename and file type
- blob_path (use in sandbox for further processing)
- Content preview (text extracted from the file)
- Data description (structure summary for tabular data)

## Supported File Types
- PDF: Text extraction
- Excel (.xlsx, .xls): Table data preview
- CSV: Table data preview
- Word (.docx, .doc): Text extraction
- Image (.jpg, .png, etc.): Saved to blob for sandbox processing

## Example
```bash
attachment-download '{"urls": ["https://example.com/paper.pdf", "https://example.com/data.xlsx"]}'
```

## Notes
- Files are downloaded in parallel
- For Excel/CSV files needing computation, use the blob_path in sandbox
- Maximum 10 URLs per request
