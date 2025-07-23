import os
import sys
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
import markdown2

from src.logger import log

# Add project root to the Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

router = APIRouter(
    prefix="/documentation",
    include_in_schema=False
)

@router.get("", response_class=HTMLResponse, summary="Get Documentation Index")
async def get_documentation_index():
    """
    Serves the main documentation index page.
    """
    index_path = os.path.join(project_root, 'docs', 'index.html')
    if not os.path.exists(index_path):
        raise HTTPException(status_code=404, detail="Documentation index not found.")
    
    try:
        with open(index_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return HTMLResponse(content=content)
    except Exception as e:
        log.error(f"Failed to read documentation index: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to process documentation index.")

@router.get("/{filename}", response_class=HTMLResponse, summary="Get Specific Documentation File")
async def get_documentation_file(filename: str):
    """
    Retrieves and renders a specific documentation file from the 'docs' directory.
    """
    # Security: Prevent directory traversal attacks
    if ".." in filename or "/" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename.")

    doc_path = os.path.join(project_root, 'docs', f"{filename}.md")

    if not os.path.exists(doc_path):
        raise HTTPException(status_code=404, detail=f"Documentation file '{filename}.md' not found.")

    try:
        with open(doc_path, 'r', encoding='utf-8') as f:
            md_content = f.read()
        
        # Convert markdown to HTML
        html_content = markdown2.markdown(md_content, extras=["fenced-code-blocks", "tables", "header-ids"])
        
        # Basic styling for better readability
        styled_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>{filename}</title>
            <style>
                body {{ font-family: sans-serif; line-height: 1.6; padding: 20px; max-width: 800px; margin: auto; }}
                h1, h2, h3 {{ color: #333; }}
                code {{ background-color: #f4f4f4; padding: 2px 4px; border-radius: 4px; }}
                pre {{ background-color: #f4f4f4; padding: 10px; border-radius: 4px; overflow-x: auto; }}
                table {{ border-collapse: collapse; width: 100%; }}
                th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
                th {{ background-color: #f2f2f2; }}
            </style>
        </head>
        <body>
            {html_content}
        </body>
        </html>
        """
        return HTMLResponse(content=styled_html)
    except Exception as e:
        log.error(f"Failed to read or render documentation file '{filename}.md': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to process documentation file.")
