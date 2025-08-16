from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, ValidationError
import google.generativeai as genai
import os
import json
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware
import PyPDF2

load_dotenv()

app = FastAPI(title="AI Resume Scorer API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-1.5-flash")

# --- Models ---
class ResumeRequest(BaseModel):
    resume_text: str

class ResumeScoreResponse(BaseModel):
    summary: str
    skills_score: float
    experience_score: float
    overall_score: float
    feedback: str
    missing_aspects: list[str] 

# --- Utils ---
def call_gemini(prompt: str) -> str:
    response = model.generate_content(prompt)
    return response.text.strip()

def clean_json(raw_text: str) -> str:
    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`")
        raw_text = raw_text.replace("json", "").strip()
    return raw_text

def validate_and_parse_json(raw_text: str) -> dict:
    try:
        data = json.loads(raw_text)
        ResumeScoreResponse(**data)
        return data
    except (json.JSONDecodeError, ValidationError):
        return None

def extract_text_from_pdf(file: UploadFile) -> str:
    try:
        reader = PyPDF2.PdfReader(file.file)
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""
        return text.strip()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error reading PDF: {e}")

# --- API ---


@app.post("/score", response_model=ResumeScoreResponse)
def score_resume(request: ResumeRequest):
    return process_resume(request.resume_text)

@app.post("/upload", response_model=ResumeScoreResponse)
async def upload_resume(file: UploadFile = File(...)):
    if file.content_type == "application/pdf":
        resume_text = extract_text_from_pdf(file)
    elif file.content_type == "application/json":
        try:
            data = json.load(file.file)
            resume_text = data.get("resume_text") or json.dumps(data)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON file")
    else:
        raise HTTPException(status_code=400, detail="Only PDF or JSON files are supported")

    return process_resume(resume_text)

# --- Shared Processing ---
def process_resume(resume_text: str) -> ResumeScoreResponse:
    prompt = f"""
    You are an expert HR and career coach.
    Analyze the following resume and:
    1. Summarize it in 1-2 sentences under the key "summary".
    2. Give a score from 1-10 for Skills.
    3. Give a score from 1-10 for Experience.
    4. Give an overall score from 1-10.
    5. Provide constructive feedback in 2-3 sentences.
    6. List 2-4 key aspects missing from the resume in "missing_aspects".

    Resume:
    {resume_text}

    Return ONLY valid JSON in this format:
    {{
      "summary": "string",
      "skills_score": number,
      "experience_score": number,
      "overall_score": number,
      "feedback": "string",
      "missing_aspects": ["string", "string", "string"]
    }}
    No markdown. No code blocks. No extra text.
    """

    for attempt in range(3):
        raw_text = clean_json(call_gemini(prompt))
        parsed = validate_and_parse_json(raw_text)
        if parsed:
            return ResumeScoreResponse(**parsed)

    raise HTTPException(status_code=500, detail="Model failed to return valid JSON after 3 attempts")
