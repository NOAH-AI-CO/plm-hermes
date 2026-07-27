import io
from typing import Optional
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
import requests
from agent.iit.prompt.result_prompt import (
    formal_html_template,
    scientific_html_template
)

def convert_html_to_pdf(html_path, pdf_path):
    from weasyprint import HTML, CSS

    html = HTML(filename=html_path)  # 或 HTML(string=html_string, base_url='.')
    css = CSS(string='''
    @page {
    size: A4;
    margin: 2cm;
    }
    @page :first {
    margin-top: 4cm;
    }
    ''')

    # 把 CSS 传给 write_pdf，输出到文件
    html.write_pdf(pdf_path, stylesheets=[css])

def convert_md_to_pdf(review_type, md_path, pdf_path):
    iit_gotenberg_url = "https://test.noahai.co/iit-gotenberg/forms/chromium/convert/markdown"
    html_template = ""
    if review_type == "formal":
        html_template = formal_html_template
    elif review_type == "scientific":
        html_template = scientific_html_template
    try:
        with open(md_path, "r", encoding="utf-8") as f:
            markdown_content = f.read()
    except FileNotFoundError:
        print(f"❌ 找不到文件：{md_path}，请检查路径是否正确！")
        raise

    files = [
        ('files', ('index.html', html_template.encode('utf-8'), 'text/html')),
        ('files', ('document.md', markdown_content.encode('utf-8'), 'text/markdown'))
    ]

    form_data = {
        'paperWidth': 8.27,
        'paperHeight': 11.69,
        'marginTop': 1.0,
        'marginBottom': 0.8,
        'waitDelay': '1s'
    }

    print(f"正在向 {iit_gotenberg_url} 发送转换请求，请稍候...")

    try:
        response = requests.post(iit_gotenberg_url, files=files, data=form_data)

        if response.status_code == 200:
            print(f"响应内容类型 (Content-Type): {response.headers.get('Content-Type')}")
            with open(pdf_path, "wb") as f:
                f.write(response.content)
            print(f"✅ 转换成功！PDF 已保存到: {pdf_path}")
        else:
            print(f"❌ 转换失败！HTTP 状态码: {response.status_code}")
            print(f"服务器返回信息: {response.text}")

    except requests.exceptions.RequestException as e:
        print(f"❌ 网络请求异常: {e}")
        
def add_header_and_footer(input_pdf: str,
                                output_pdf: str,
                                img_path: str,
                                top_margin: float = 10.0) -> None:
    """
    修改说明：
    1. header_x: 增大右边距，实现 Logo 左移。
    2. header_y: 额外减去偏移量，实现 Logo 下移（靠近正文）。
    3. footer_y: 增大底边距，实现页脚上移（靠近正文）。
    """
    reader = PdfReader(input_pdf)
    writer = PdfWriter()

    # 注册中文字体 (如果系统支持)
    try:
        pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
        zh_font_name = 'STSong-Light'
    except Exception:
        zh_font_name = 'Helvetica'

    # --- 1. 确定页脚文字逻辑 ---
    footer_text = "NOAH AI-AI Agent Specialized in Life Science"
    normalized_img_path = img_path.replace("\\", "/")
    if 'static/roche-logo.png' in normalized_img_path:
        footer_text = "AI 智慧联  轻松做科研"

    # --- 2. 确定图片尺寸逻辑 ---
    # 保持 Word 逻辑：固定宽度 0.96 英寸
    target_img_width = 0.96 * 72 
    
    from PIL import Image as PILImage
    with PILImage.open(img_path) as im:
        orig_w, orig_h = im.size
        target_img_height = target_img_width * (orig_h / orig_w)

    for i, page in enumerate(reader.pages):
        media_box = page.mediabox
        page_width = float(media_box.width)
        page_height = float(media_box.height)

        packet = io.BytesIO()
        c = canvas.Canvas(packet, pagesize=(page_width, page_height))

        # --- 3. 绘制页眉 (Header) ---
        # 【调整1：Logo 左移】
        # 之前是减去 36 (0.5英寸)，现在减去 54 (0.75英寸)，让图片离右边缘更远一点
        right_margin_padding = 54 
        header_x = page_width - target_img_width - right_margin_padding
        
        # 【调整2：Logo 下移 / 靠近正文】
        # top_margin 是函数参数，额外增加 header_push_down 让图片更靠下
        header_push_down = 24 
        header_y = page_height - target_img_height - top_margin - header_push_down
        
        c.drawImage(img_path, header_x, header_y, width=target_img_width, height=target_img_height, mask='auto')

        # --- 4. 绘制页脚 (Footer) ---
        # 【调整3：页脚上移 / 靠近正文】
        # 之前是 20，现在改为 45，让文字离底边更高一点
        footer_y = 45 
        
        c.setFont("Helvetica", 9)
        if "智慧联" in footer_text:
             c.setFont(zh_font_name, 9)

        c.drawCentredString(page_width / 2, footer_y, footer_text)

        c.save()

        # --- 5. 合并 ---
        packet.seek(0)
        overlay_reader = PdfReader(packet)
        overlay_page = overlay_reader.pages[0]
        
        page.merge_page(overlay_page)
        writer.add_page(page)

    with open(output_pdf, "wb") as fout:
        writer.write(fout)

def convert_html_to_pdf_iit(html_path, pdf_path, logo_path):
    convert_html_to_pdf(html_path, pdf_path)
    add_header_and_footer(
        input_pdf=pdf_path,
        output_pdf=pdf_path,
        img_path=logo_path,
        top_margin=8.0,
    )

def convert_md_to_pdf_iit(review_type, md_path, pdf_path, logo_path):
    convert_md_to_pdf(review_type, md_path, pdf_path)
    add_header_and_footer(
        input_pdf=pdf_path,
        output_pdf=pdf_path,
        img_path=logo_path,
        top_margin=8.0,
    )

def test_html2pdf():
    html_path = "/Users/ivylyx/Code/NoahAgent/formal.html"
    pdf_path = "/Users/ivylyx/Code/NoahAgent/formal.pdf"
    convert_html_to_pdf(html_path, pdf_path)
    img_path="static/roche-logo.png"
    add_header_and_footer(
        input_pdf=pdf_path,
        output_pdf=pdf_path,
        img_path=img_path,
        top_margin=8.0,
    )

if __name__ == "__main__":
    test_html2pdf()