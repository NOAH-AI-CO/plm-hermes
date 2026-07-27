import fitz # PyMuPDF

def classify_pdf(pdf_path):
    doc = fitz.open(pdf_path)
    check_pages = min(5, len(doc))
    
    has_text_count = 0
    no_text_count = 0
    for p in range(check_pages): 
        page = doc[p]

        # Example using page methods:
        images = page.get_images()
        # if images:
            # print(f"Page {p+1} contains images ({len(images)} found).")

        text = page.get_text("text")
        if len(text.strip()) > 10:
            # print(f"Page {p+1} contains searchable text.")
            has_text_count += 1

        if not images and len(text.strip()) <= 10:
            # print(f"Page {p+1} is likely blank or entirely image-based without embedded text info.")
            no_text_count += 1
    if has_text_count >= 0.2 * check_pages:
        return True
    return False