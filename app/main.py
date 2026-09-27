from __future__ import annotations

import json
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app.schemas import Project, RequirementUpdate
from app.services.documents import chunk_text, extract_text, mask_sensitive
from app.services.generator import generate_evidence_drafts
from app.services.llm import enabled as llm_enabled, generate_requirements as generate_llm_requirements
from app.services.quality import analyse
from app.services.rag import RagConfigurationError, VectorStore, provider_configured
from app.services.sdlc import recommend
from app.services.storage import ProjectStore

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT.parent / ".env")
store = ProjectStore()
vector_store = VectorStore()
FINANCE_SCOPE = re.compile(r"\b(finance|financial|fintech|bank(?:ing)?|credit|debit|loan|lending|mortgage|payment|payroll|insurance|investment|investing|wealth|brokerage|trading|securities|portfolio|accounting|ledger|treasury|remittance|money transfer|fund transfer|wallet|merchant|invoice|billing|reconciliation|underwriting|kyc|aml|deposit|withdrawal|interest rate|forex|currency exchange|tax reporting|financial crime|fraud detection|capital market|financial statement)\b", re.I)
def is_finance_project(text: str) -> bool:
    return bool(FINANCE_SCOPE.search(text))



@asynccontextmanager
async def lifespan(_: FastAPI):
    print("\n" + "=" * 56)
    print("  Finance Helper is running")
    print("  App:      http://127.0.0.1:8000")
    print("  API docs: http://127.0.0.1:8000/docs")
    print("  RAG:      ChromaDB + OpenAI-compatible embeddings")
    print("  Storage:  local JSON project data and ChromaDB vectors")
    print("  Stop:     press Ctrl+C")
    print("=" * 56 + "\n")
    yield
    print("Finance Helper stopped.")


app = FastAPI(title="Finance Helper", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


def retrieve_project_evidence(project: Project, query: str) -> list[dict]:
    try:
        return vector_store.retrieve(project.id, query)
    except RagConfigurationError as exc:
        if "vector collection is unavailable" not in str(exc):
            raise
        indexed = vector_store.index(project.id, project.documents)
        store.save(project)
        return vector_store.retrieve(project.id, query)


@app.get("/")
def home() -> FileResponse:
    return FileResponse(ROOT / "templates" / "index.html")


@app.get("/api/rag/status")
def rag_status() -> JSONResponse:
    return JSONResponse({
        **vector_store.configuration(),
        "embedding_provider_configured": provider_configured(),
        "generation_mode": "LLM generation with citation validation" if llm_enabled() else "Evidence-only drafts until LLM_API_KEY is configured",
        "evidence_policy": "Retrieved content is untrusted evidence; regulatory conclusions require human review.",
    })


@app.get("/api/health")
def health() -> JSONResponse:
    return JSONResponse({"status": "ok", "service": "Finance Helper", "version": app.version})


@app.get("/api/projects")
def list_projects() -> JSONResponse:
    projects = store.list()
    return JSONResponse([{
        "id": project.id, "functionality": project.functionality, "created_at": project.created_at.isoformat(),
        "documents": len(project.documents), "requirements": len(project.requirements),
        "pending_approvals": sum(item.approval_status == "Needs review" for item in project.requirements),
    } for project in projects])


@app.post("/api/projects")
async def create_project(
    functionality: str = Form(...),
    stakeholder_input: str = Form("{}"),
    jurisdiction: str | None = Form(default=None),
    effective_date: str | None = Form(default=None),
    version: str | None = Form(default=None),
    document_type: str | None = Form(default=None),
    applicability: str | None = Form(default=None),
    uploaded_by: str | None = Form(default=None),
    files: list[UploadFile] = File(default=[]),
) -> JSONResponse:
    functionality = functionality.strip()
    if len(functionality) < 3:
        raise HTTPException(422, "Enter a financial functionality of at least three characters.")
    try:
        answers = json.loads(stakeholder_input)
    except json.JSONDecodeError as exc:
        raise HTTPException(422, "Stakeholder answers could not be processed.") from exc
    if not isinstance(answers, dict):
        raise HTTPException(422, "Stakeholder answers must be a structured set of responses.")
    answers = {str(question): str(answer).strip() for question, answer in answers.items() if str(answer).strip()}
    if sum(q.lower() not in {"business objective", "users and roles"} for q in answers) > 5:
        raise HTTPException(422, "Finance Helper allows up to five follow-up answers per project.")
    source_metadata = {
        "jurisdiction": jurisdiction.strip() if jurisdiction else None,
        "effective_date": effective_date.strip() if effective_date else None,
        "version": version.strip() if version else None,
        "applicability": applicability.strip() if applicability else functionality,
        "uploaded_by": uploaded_by.strip() if uploaded_by else None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    uploads = [upload for upload in files if upload.filename]
    if not uploads and not is_finance_project(" ".join([functionality, *answers.keys(), *answers.values()])):
        raise HTTPException(422, "Not suitable: Finance Helper only accepts projects related to finance or financial services.")
    if not answers and not uploads:
        raise HTTPException(422, "Answer at least one stakeholder question or upload a supporting document.")
    documents = []
    created_at = source_metadata["created_at"]
    if answers:
        interview_text = "\n".join(f"{question}: {answer}" for question, answer in answers.items())
        masked_text = mask_sensitive(interview_text)
        documents.append({"id": "DOC-001", "name": "Stakeholder interview", "source": "Stakeholder interview", **source_metadata, "document_type": "Interview transcript", "chunks": [chunk.__dict__ for chunk in chunk_text(masked_text)]})
    for upload in uploads:
        content = await upload.read(5_000_001)
        if len(content) > 5_000_000:
            raise HTTPException(413, f"{upload.filename} exceeds the 5 MB prototype limit.")
        try:
            text = mask_sensitive(extract_text(upload.filename, content))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(422, f"{upload.filename} could not be parsed as a valid document.") from exc
        if not text.strip():
            raise HTTPException(422, f"{upload.filename} contains no extractable text.")
        doc_id = f"DOC-{len(documents)+1:03d}"
        documents.append({"id": doc_id, "name": upload.filename, "source": upload.filename, **source_metadata, "document_type": document_type.strip() if document_type else upload.filename.rsplit(".", 1)[-1].upper(), "chunks": [chunk.__dict__ for chunk in chunk_text(text)]})
    financial_context = " ".join([functionality, *answers.keys(), *answers.values()] + [chunk.get("text", "") for doc in documents for chunk in doc.get("chunks", [])])
    if not is_finance_project(financial_context):
        raise HTTPException(422, "Not suitable: Finance Helper only accepts projects related to finance or financial services.")
    project = Project(
        id=uuid4().hex[:12], functionality=functionality,
        business_objective=answers.get("business objective", ""),
        users_and_roles=answers.get("users and roles", ""),
        created_at=datetime.now(timezone.utc), documents=documents,
    )
    try:
        indexed_chunks = vector_store.index(project.id, documents)
    except RagConfigurationError as exc:
        raise HTTPException(503, str(exc)) from exc
    store.save(project)
    return JSONResponse({
        "project_id": project.id,
        "documents": [{**{key: doc.get(key) for key in ("id", "name", "source", "jurisdiction", "effective_date", "version", "document_type", "applicability", "uploaded_by", "created_at")}, "chunks": len(doc["chunks"])} for doc in documents],
        "rag": {**vector_store.configuration(), "indexed_chunks": indexed_chunks},
    })


@app.get("/api/projects/{project_id}/retrieval")
def retrieve_evidence(project_id: str, query: str | None = None) -> JSONResponse:
    try:
        project = store.get(project_id)
    except KeyError as exc:
        raise HTTPException(404, "Project not found.") from exc
    search_query = (query or project.functionality).strip()
    if len(search_query) < 3:
        raise HTTPException(422, "Enter a retrieval query of at least three characters.")
    try:
        evidence = retrieve_project_evidence(project, search_query)
    except RagConfigurationError as exc:
        raise HTTPException(503, str(exc)) from exc
    strongest = max((item["relevance"] for item in evidence), default=0)
    return JSONResponse({"query": search_query, "matches": evidence, "count": len(evidence), "confidence": strongest, "evidence_sufficient": strongest >= 0.12})


@app.post("/api/projects/{project_id}/requirements")
def generate_requirements(project_id: str) -> JSONResponse:
    try:
        project = store.get(project_id)
    except KeyError as exc:
        raise HTTPException(404, "Project not found.") from exc
    try:
        evidence = retrieve_project_evidence(project, project.functionality)
    except RagConfigurationError as exc:
        raise HTTPException(503, str(exc)) from exc
    if not evidence:
        raise HTTPException(422, "No retrievable evidence was found in the uploaded documents.")
    if max((item["relevance"] for item in evidence), default=0) < 0.12:
        raise HTTPException(422, "The retrieved sources do not provide sufficient evidence. Add or select a more relevant source before generating requirements.")
    generation_mode = "evidence-only"
    if llm_enabled():
        try:
            project.requirements = generate_llm_requirements(project.functionality, evidence)
            generation_mode = "LLM-assisted"
        except (RuntimeError, ValueError) as exc:
            project.requirements = generate_evidence_drafts(project.functionality, evidence)
    else:
        project.requirements = generate_evidence_drafts(project.functionality, evidence)
    project.quality_issues = analyse(project.requirements)
    store.save(project)
    return JSONResponse(project.model_dump(mode="json"))


@app.post("/api/projects/{project_id}/requirements/{requirement_id}/approval")
def update_approval(project_id: str, requirement_id: str, status: str = Form(...)) -> JSONResponse:
    if status not in {"Approved", "Rejected", "Needs review", "Draft"}:
        raise HTTPException(422, "Invalid approval status.")
    try:
        project = store.get(project_id)
    except KeyError as exc:
        raise HTTPException(404, "Project not found.") from exc
    requirement = next((item for item in project.requirements if item.id == requirement_id), None)
    if not requirement:
        raise HTTPException(404, "Requirement not found.")
    previous = requirement.approval_status
    requirement.approval_status = status
    store.save(project)
    return JSONResponse(requirement.model_dump(mode="json"))


@app.post("/api/projects/{project_id}/sdlc")
def sdlc_analysis(project_id: str) -> JSONResponse:
    try:
        project = store.get(project_id)
    except KeyError as exc:
        raise HTTPException(404, "Project not found.") from exc
    if not project.requirements:
        raise HTTPException(422, "Generate requirements before SDLC analysis.")
    project.sdlc = recommend(project.requirements)
    store.save(project)
    return JSONResponse(project.sdlc.model_dump(mode="json"))


@app.post("/api/projects/{project_id}/sdlc/approval")
def update_sdlc_approval(project_id: str, status: str = Form(...)) -> JSONResponse:
    if status not in {"Approved", "Rejected", "Needs review"}:
        raise HTTPException(422, "Invalid SDLC approval status.")
    try:
        project = store.get(project_id)
    except KeyError as exc:
        raise HTTPException(404, "Project not found.") from exc
    if not project.sdlc:
        raise HTTPException(422, "Run the SDLC analysis before recording an approval decision.")
    previous = project.sdlc.approval_status
    project.sdlc.approval_status = status
    store.save(project)
    return JSONResponse(project.sdlc.model_dump(mode="json"))


@app.get("/api/projects/{project_id}")
def get_project(project_id: str) -> JSONResponse:
    try:
        return JSONResponse(store.get(project_id).model_dump(mode="json"))
    except KeyError as exc:
        raise HTTPException(404, "Project not found.") from exc


@app.patch("/api/projects/{project_id}/requirements/{requirement_id}")
def edit_requirement(project_id: str, requirement_id: str, changes: RequirementUpdate) -> JSONResponse:
    try:
        project = store.get(project_id)
    except KeyError as exc:
        raise HTTPException(404, "Project not found.") from exc
    requirement = next((item for item in project.requirements if item.id == requirement_id), None)
    if not requirement:
        raise HTTPException(404, "Requirement not found.")
    updates = changes.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(422, "Provide at least one requirement field to update.")
    before = {key: getattr(requirement, key) for key in updates}
    for key, value in updates.items():
        if isinstance(value, str):
            value = value.strip()
        setattr(requirement, key, value)
    if requirement.approval_status == "Approved":
        requirement.approval_status = "Needs review"
    project.quality_issues = analyse(project.requirements)
    store.save(project)
    return JSONResponse(requirement.model_dump(mode="json"))


@app.post("/api/projects/{project_id}/requirements/{requirement_id}/clarification")
def request_clarification(project_id: str, requirement_id: str) -> JSONResponse:
    try:
        project = store.get(project_id)
    except KeyError as exc:
        raise HTTPException(404, "Project not found.") from exc
    requirement = next((item for item in project.requirements if item.id == requirement_id), None)
    if not requirement:
        raise HTTPException(404, "Requirement not found.")
    previous = requirement.approval_status
    requirement.approval_status = "Needs review"
    store.save(project)
    return JSONResponse({"requirement_id": requirement_id, "status": requirement.approval_status})


@app.get("/api/projects/{project_id}/export")
def export_project(project_id: str) -> JSONResponse:
    try:
        payload = store.export(store.get(project_id))
        return JSONResponse(payload, headers={"Content-Disposition": f'attachment; filename="finance-helper-{project_id}.json"'})
    except KeyError as exc:
        raise HTTPException(404, "Project not found.") from exc


@app.get("/api/projects/{project_id}/artifacts")
def export_artifacts(project_id: str) -> PlainTextResponse:
    try:
        project = store.get(project_id)
    except KeyError as exc:
        raise HTTPException(404, "Project not found.") from exc
    if not project.requirements:
        raise HTTPException(422, "Generate requirements before exporting the SRS pack.")
    lines = [
        f"# Software Requirements Specification — {project.functionality}",
        "", "> Advisory draft. Regulatory applicability and all high-impact requirements require authorised human review.",
        "", "## 1. Purpose and scope", "",
        project.business_objective or f"Requirements for {project.functionality}.",
        "", "## 2. Stakeholders and sources", "",
        f"Users and roles: {project.users_and_roles or 'Not recorded; clarify with the project sponsor.'}", "",
    ]
    source_names = sorted({doc.get("name", "Unknown source") for doc in project.documents})
    lines.extend(f"- {name}" for name in source_names)
    lines.extend(["", "## 3. Requirements", ""])
    for requirement in project.requirements:
        citations = ", ".join(f"{item.document_name} ({item.document_id}:{item.chunk_id})" for item in requirement.evidence) or "No evidence linked"
        lines.extend([
            f"### {requirement.id} — {requirement.statement}", "",
            f"- Categories: {', '.join(category.value for category in requirement.categories)}",
            f"- Source stakeholder/document: {requirement.source_stakeholder or 'Not recorded'}",
            f"- Priority: {requirement.priority}; confidence: {requirement.confidence:.0%}",
            f"- Approval: {requirement.approval_status}",
            f"- Business justification: {requirement.business_justification}",
            f"- Applicable policy (unverified): {requirement.applicable_policy or 'Not specified'}",
            f"- Evidence: {citations}", "- Acceptance criteria:",
        ])
        lines.extend(f"  - {item}" for item in requirement.acceptance_criteria or ["Needs definition by the project team."])
        if requirement.assumptions:
            lines.append("- Assumptions: " + "; ".join(requirement.assumptions))
        if requirement.dependencies:
            lines.append("- Dependencies: " + "; ".join(requirement.dependencies))
        lines.append("")
    lines.extend(["## 4. User stories", ""])
    for requirement in project.requirements:
        source = project.users_and_roles or "project user"
        citations = ", ".join(f"{e.document_id}:{e.chunk_id}" for e in requirement.evidence) or "no citation"
        lines.extend([f"- **{requirement.id}:** As a {source}, I need {requirement.statement.rstrip('.')} so that {requirement.business_justification} _(Source: {citations})_", ""])
    lines.extend(["## 5. Use cases", ""])
    for index, requirement in enumerate(project.requirements, start=1):
        citations = ", ".join(f"{e.document_id}:{e.chunk_id}" for e in requirement.evidence) or "no citation"
        lines.extend([
            f"### UC-{index:03d} — {requirement.id}", "",
            f"- Primary actor: {project.users_and_roles or 'To be confirmed'}",
            f"- Goal: {requirement.statement}",
            "- Preconditions: To be confirmed during stakeholder review.",
            "- Main flow: Perform the requirement and validate its acceptance criteria.",
            "- Alternative/error flows: Clarify with stakeholders; no unsupported flow is assumed.",
            f"- Evidence: {citations}", "",
        ])
    lines.extend(["", "## 6. Open issues and assumptions", ""])
    lines.extend(f"- **{issue.severity} — {issue.check} ({issue.requirement_id or 'Project'}):** {issue.message} Suggested action: {issue.recommendation}" for issue in project.quality_issues)
    if not project.quality_issues:
        lines.append("- Run the quality review and confirm unresolved assumptions before baselining.")
    lines.extend(["", "## 7. Delivery approach", ""])
    if project.sdlc:
        lines.append(f"**{project.sdlc.recommended_sdlc} — {project.sdlc.approval_status}.** {project.sdlc.justification}")
        lines.extend(["", "### Project-specific workflow", ""])
        for phase in project.sdlc.workflow:
            lines.append(f"- **{phase.phase}:** {', '.join(phase.activities)} Roles: {', '.join(phase.roles)}. Deliverables: {', '.join(phase.deliverables)}. Gate: {phase.gate}.")
    else:
        lines.append("No SDLC recommendation has been run.")
    return PlainTextResponse("\n".join(lines), media_type="text/markdown", headers={"Content-Disposition": f'attachment; filename="finance-helper-srs-{project.id}.md"'})
