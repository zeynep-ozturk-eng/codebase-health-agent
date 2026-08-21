from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from app.parser import parse_source, FileFacts
from app.scanner import scan_directory, ProjectSummary

app = FastAPI(
    title="Codebase Health Agent API",
    description="Kod tabanlarını analiz eden AI servisi",
    version="0.1.0"
)

# İstek Modelleri
class CodeAnalyzeRequest(BaseModel):
    code: str
    language: str = "python"
    file_path: str = "main.py"

class ScanDirectoryRequest(BaseModel):
    directory_path: str = "."  # 4 boşluk içeride olmalı


# Endpoint'ler
@app.get("/")
def health_check():
    return {"status": "healthy", "service": "Codebase Health Agent"}

@app.post("/analyze", response_model=FileFacts)
def analyze_code(payload: CodeAnalyzeRequest):
    try:
        facts = parse_source(
            source=payload.code,
            language=payload.language,
            path=payload.file_path
        )
        return facts
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ayrıştırma hatası: {str(e)}")

@app.post("/scan", response_model=ProjectSummary)
def scan_project(payload: ScanDirectoryRequest):
    """
    Verilen klasör yolundaki tüm projeyi turlar ve 
    toplu sağlık raporu döndürür.
    """
    try:
        summary = scan_directory(payload.directory_path)
        return summary
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))