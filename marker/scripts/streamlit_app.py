import os

from marker.settings import settings

os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
os.environ["IN_STREAMLIT"] = "true"

import base64
import io
import re
import tempfile
from typing import Any, Dict

import pypdfium2
import streamlit as st
from PIL import Image

from marker.converters.pdf import PdfConverter
from marker.models import create_model_dict
from marker.config.parser import ConfigParser
from marker.output import text_from_rendered

@st.cache_resource()
def load_models():
    return create_model_dict()


def convert_pdf(fname: str, config_parser: ConfigParser) -> (str, Dict[str, Any], dict):
    config_dict = config_parser.generate_config_dict()
    config_dict["pdftext_workers"] = 1
    converter = PdfConverter(
        config=config_dict,
        artifact_dict=model_dict,
        processor_list=config_parser.get_processors(),
        renderer=config_parser.get_renderer()
    )
    return converter(fname)


def open_pdf(pdf_file):
    stream = io.BytesIO(pdf_file.getvalue())
    return pypdfium2.PdfDocument(stream)


def img_to_html(img, img_alt):
    img_bytes = io.BytesIO()
    img.save(img_bytes, format=settings.OUTPUT_IMAGE_FORMAT)
    img_bytes = img_bytes.getvalue()
    encoded = base64.b64encode(img_bytes).decode()
    img_html = f'<img src="data:image/{settings.OUTPUT_IMAGE_FORMAT.lower()};base64,{encoded}" alt="{img_alt}" style="max-width: 100%;">'
    return img_html


def markdown_insert_images(markdown, images):
    image_tags = re.findall(r'(!\[(?P<image_title>[^\]]*)\]\((?P<image_path>[^\)"\s]+)\s*([^\)]*)\))', markdown)

    for image in image_tags:
        image_markdown = image[0]
        image_alt = image[1]
        image_path = image[2]
        if image_path in images:
            markdown = markdown.replace(image_markdown, img_to_html(images[image_path], image_alt))
    return markdown


@st.cache_data()
def get_page_image(pdf_file, page_num, dpi=96):
    doc = open_pdf(pdf_file)
    renderer = doc.render(
        pypdfium2.PdfBitmap.to_pil,
        page_indices=[page_num],
        scale=dpi / 72,
    )
    png = list(renderer)[0]
    png_image = png.convert("RGB")
    return png_image


@st.cache_data()
def page_count(pdf_file):
    doc = open_pdf(pdf_file)
    return len(doc) - 1


st.set_page_config(layout="wide")
col1, col2 = st.columns([.5, .5])

model_dict = load_models()


st.markdown("""
# Marker Demo

This app will let you try marker, a PDF -> Markdown converter. It works with any languages, and extracts images, tables, equations, etc.

Find the project [here](https://github.com/VikParuchuri/marker).
""")

in_file = st.sidebar.file_uploader("PDF file:", type=["pdf"])

if in_file is None:
    st.stop()

filetype = in_file.type

with col1:
    page_count = page_count(in_file)
    page_number = st.number_input(f"Page number out of {page_count}:", min_value=0, value=0, max_value=page_count)
    pil_image = get_page_image(in_file, page_number)

    st.image(pil_image, caption="PDF file (preview)", use_container_width=True)

page_range = st.sidebar.text_input("Page range to parse, comma separated like 0,5-10,20", value=f"{page_number}-{page_number}")
output_format = st.sidebar.selectbox("Output format", ["markdown", "json", "html"], index=0)
run_marker = st.sidebar.button("Run Marker")

use_llm = st.sidebar.checkbox("Use LLM", help="Use LLM for higher quality processing", value=False)
force_ocr = st.sidebar.checkbox("Force OCR", help="Force OCR on all pages", value=False)
strip_existing_ocr = st.sidebar.checkbox("Strip existing OCR", help="Strip existing OCR text from the PDF and re-OCR.", value=False)
debug = st.sidebar.checkbox("Debug", help="Show debug information", value=False)

if not run_marker:
    st.stop()

# Run Marker
with tempfile.NamedTemporaryFile(suffix=".pdf", mode="wb+") as temp_pdf:
    temp_pdf.write(in_file.getvalue())
    temp_pdf.seek(0)
    filename = temp_pdf.name
    cli_options = {
        "output_format": output_format,
        "page_range": page_range,
        "force_ocr": force_ocr,
        "debug": debug,
        "output_dir": settings.DEBUG_DATA_FOLDER if debug else None,
        "use_llm": use_llm,
        "strip_existing_ocr": strip_existing_ocr
    }
    config_parser = ConfigParser(cli_options)
    rendered = convert_pdf(
        filename,
        config_parser
    )
    page_range = config_parser.generate_config_dict()["page_range"]
    first_page = page_range[0] if page_range else 0

text, ext, images = text_from_rendered(rendered)
with col2:
    if output_format == "markdown":
        text = markdown_insert_images(text, images)
        st.markdown(text, unsafe_allow_html=True)
    elif output_format == "json":
        st.json(text)
    elif output_format == "html":
        st.html(text)

if debug:
    with col1:
        debug_data_path = rendered.metadata.get("debug_data_path")
        if debug_data_path:
            pdf_image_path = os.path.join(debug_data_path, f"pdf_page_{first_page}.png")
            img = Image.open(pdf_image_path)
            st.image(img, caption="PDF debug image", use_container_width=True)
            layout_image_path = os.path.join(debug_data_path, f"layout_page_{first_page}.png")
            img = Image.open(layout_image_path)
            st.image(img, caption="Layout debug image", use_container_width=True)
