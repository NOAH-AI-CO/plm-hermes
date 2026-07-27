import fitz
import os

def add_watermark(input_pdf_path, output_pdf_path=None, watermark_text="NOAH AGENT"):
    if output_pdf_path is None:
        base, ext = os.path.splitext(input_pdf_path)
        output_pdf_path = f"{base}_watermarked{ext}"

    try:
        doc = fitz.open(input_pdf_path)
    except Exception as e:
        print(f"Failed to open {input_pdf_path}: {e}")
        return

    print(f"Adding watermark to {input_pdf_path}...")
    
    for page in doc:
        # Center of the page
        center = page.rect.tl + page.rect.br
        center /= 2
        
        # We use insert_text with rotate parameter. 
        # To "center" it, we must estimate its size or just let it start near center.
        # A simple robust way for a watermark is to use drawing commands (draw_page) or insert_text.
        # fitz.TextWriter is suitable for precise placement, but insert_text is easier.
        
        # But 'insert_textbox' with rotation and align=1 (center) is the easiest way to center text in a rect.
        # We use the full page rect.
        
        try:
            page.insert_text(
                center,
                watermark_text,
                fontsize=80,
                color=(0.6, 0.6, 0.6),
                fill_opacity=0.3,
                rotate=45,
                align=1 # Warning: align might not be supported in all versions for insert_text.
                        # For insert_text, 'align' is not a standard param in older versions, 
                        # but let's assume recent pymupdf. 
                        # Actually, looking at docs, insert_text(point, text, ... rotate=...) 
                        # does not have align. 
            )
            # Since align is likely not supported in insert_text, let's use a workaround 
            # or `insert_textbox` if we trust it doesn't clip awkwardly.
            
            # Let's switch to insert_textbox with a slightly padded rect to avoid edge issues?
            # page.insert_textbox(page.rect, watermark_text, fontsize=80, 
            #                    color=(0.6, 0.6, 0.6), fill_opacity=0.3, rotate=45, align=1)
            
        except Exception:
            # Fallback or retry with text_box
            pass
            
    # Let's re-implement the loop with a more robust method: insert_textbox
    # Re-opening doc or just clearing loop above? No, I'll validly implement it below.
    pass

def add_watermark_v2(input_pdf_path, output_pdf_path=None, watermark_text="NOAH AGENT"):
    if output_pdf_path is None:
        base, ext = os.path.splitext(input_pdf_path)
        output_pdf_path = f"{base}_watermarked{ext}"

    doc = fitz.open(input_pdf_path)
    print(f"Opened {input_pdf_path}, pages: {len(doc)}")
    
    # Create a rotation matrix for 45 degrees
    # Use constructor as tested in debug
    mat = fitz.Matrix(45)
    
    for page_num, page in enumerate(doc):
        print(f"Processing page {page_num}")
        w = page.rect.width
        h = page.rect.height
        
        # Grid settings
        step_x = 200
        step_y = 200
        
        for x in range(50, int(w), step_x):
            for y in range(50, int(h), step_y):
                point = fitz.Point(x, y)
                
                try:
                    # Using morph for rotation, exactly as in debug script
                    rc = page.insert_text(
                        point,
                        watermark_text,
                        fontsize=30,
                        fontname="helv",
                        color=(0.7, 0.7, 0.7), # Light grey
                        fill_opacity=0.3, # Transparent
                        rotate=0,
                        morph=(point, mat),
                        overlay=True
                    )
                    # print(f"Inserted at {point}, result: {rc}")
                except Exception as e:
                    print(f"Error inserting text at {point}: {e}")

    doc.save(output_pdf_path)
    print(f"Saved: {output_pdf_path}")

if __name__ == "__main__":
    input_file = "/Users/andy/repos/NoahAgent/3col.pdf"
    if os.path.exists(input_file):
        add_watermark_v2(input_file)
    else:
        print(f"File not found: {input_file}")
