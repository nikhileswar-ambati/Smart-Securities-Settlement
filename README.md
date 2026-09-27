# Finance Helper

Finance Helper is a local, finance-only requirements workspace. It captures stakeholder context, indexes finance project sources, retrieves passages for evidence-grounded requirement drafts, runs quality checks, and suggests a delivery approach for human review.

## Start

Use the project's virtual environment in PowerShell:

    .\.venv\Scripts\Activate.ps1
    uvicorn app.main:app --reload

The workspace is at http://127.0.0.1:8000. Python package installation can use requirements.txt. Optional model and embedding provider settings are documented in .env.example.

## Workflow

1. Describe a financial-services workflow, objective, and user roles. Unrelated project scopes are declined by both the intake form and API.
2. Answer at most five follow-up questions.
3. Upload your own finance source documents (TXT, Markdown, CSV, PDF, or DOCX). Uploaded contents are size-limited and common sensitive identifiers are masked before indexing.
4. Review retrieved source passages and create requirement drafts.
5. Refine requirement wording and acceptance criteria, record review status, run quality checks, and review the delivery approach.
6. Download project JSON or a Markdown requirements pack.

The local mode uses ChromaDB with project-scoped collections and deterministic local hashed embeddings. LLM generation is optional; without a configured provider, the app uses evidence-only drafts. Outputs need human review. This prototype has no authentication, role enforcement, or multi-user isolation. Scanned PDFs require OCR. Legal determinations remain outside the application scope.

## Project layout

- app/main.py: FastAPI routes and project intake
- app/services/: document handling, retrieval, generation, quality, delivery scoring, and storage
- app/templates/ and app/static/: Finance Helper interface
- tests/: automated test suite

Runtime finance project records and vector indexes are stored under data/. The bundled demo portfolio and example source content have been cleared.
