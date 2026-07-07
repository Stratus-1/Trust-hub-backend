import subprocess
import os

def convert_docx_to_pdf_libreoffice(docx_path: str, output_dir: str) -> str:
    try:
        subprocess.run([
            "soffice",
            "--headless",
            "--convert-to", "pdf",
            "--outdir", output_dir,
            docx_path
        ], check=True)

        pdf_path = os.path.join(
            output_dir,
            os.path.splitext(os.path.basename(docx_path))[0] + ".pdf"
        )

        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF not found at {pdf_path}")

        return pdf_path

    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"❌ LibreOffice failed to convert DOCX: {str(e)}")
    except Exception as e:
        raise RuntimeError(f"❌ Conversion error: {str(e)}")
