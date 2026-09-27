from app.schemas import Category
from app.services.documents import chunk_text, mask_sensitive, retrieve
from app.services.generator import generate_evidence_drafts
from app.services.quality import analyse
from io import BytesIO
from urllib.error import HTTPError

from app.services import rag
from app.services.rag import RagConfigurationError, VectorStore, _api_key, _embed, provider_configured
from app.services.sdlc import recommend


def test_pipeline_creates_grounded_requirements_and_recommendation():
    text = "The system shall encrypt personal data. The system must record audit events for every decision."
    chunks = [chunk.__dict__ for chunk in chunk_text(mask_sensitive(text))]
    documents = [{"id": "DOC-001", "name": "policy.txt", "chunks": chunks}]
    evidence = retrieve("personal data and audit", documents)

    requirements = generate_evidence_drafts("customer onboarding", evidence)

    assert requirements
    assert all(requirement.evidence for requirement in requirements)
    assert Category.SECURITY in requirements[0].categories or Category.PRIVACY in requirements[0].categories
    assert isinstance(analyse(requirements), list)
    recommendation = recommend(requirements)
    assert recommendation.options[0].score >= recommendation.options[-1].score
    assert {option.name for option in recommendation.options} >= {"Waterfall", "V-Model", "Prototyping", "RAD", "Spiral", "Incremental", "Agile", "DevSecOps", "Hybrid"}
    assert {factor.name for factor in recommendation.factors} == {"Requirement stability", "Requirement clarity", "Risk", "Complexity", "Need for early prototype", "Time constraints", "Customer involvement", "Frequency of changes", "Need for iterative development", "Need for risk analysis"}


def test_masking_replaces_account_like_values():
    assert "1234567890123456" not in mask_sensitive("Account 1234567890123456 must be protected.")


def test_rag_requires_explicit_provider_key(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    try:
        _api_key()
    except RagConfigurationError:
        return
    raise AssertionError("RAG must not run without an embedding-provider key")


def test_rag_configuration_never_exposes_api_key(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "not-for-the-client")
    monkeypatch.setenv("LLM_MODEL", "test-model")

    configuration = VectorStore.configuration()

    assert configuration["vector_database"] == "ChromaDB"
    assert configuration["llm_model"] == "test-model"
    assert "not-for-the-client" not in str(configuration)


def test_rag_uses_local_embeddings_without_provider_key(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    vectors = _embed(["identity verification requires an audit record"])

    assert len(vectors) == 1
    assert len(vectors[0]) == 384
    assert any(vectors[0])


def test_rag_falls_back_to_local_embeddings_when_provider_rejects_request(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")

    def rejected_request(*_args, **_kwargs):
        raise HTTPError("https://example.invalid/v1/embeddings", 404, "Not Found", {}, BytesIO())

    monkeypatch.setattr(rag, "urlopen", rejected_request)

    vectors = rag._embed(["Identity verification requires an audit record."])

    assert len(vectors) == 1
    assert len(vectors[0]) == 384
    assert any(vectors[0])


def test_openai_api_key_environment_variable_is_supported(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    assert provider_configured()
    assert _api_key() == "test-key"


def test_project_creation_works_without_provider_key(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from app.services.storage import ProjectStore

    monkeypatch.setenv("VECTOR_DB_PATH", str(tmp_path / "chroma"))
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "projects"))
    from app import main

    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(main, "vector_store", VectorStore())
    monkeypatch.setattr(main, "store", ProjectStore())
    client = TestClient(main.app)
    response = client.post(
        "/api/projects",
        data={"functionality": "Digital customer onboarding", "stakeholder_input": '{"identity": "Verify identity and record each decision."}'},
    )

    assert response.status_code == 200
    assert response.json()["rag"]["vector_database"] == "ChromaDB"


def test_chunking_respects_size_and_keeps_overlap():
    from app.services.documents import chunk_text

    text = " ".join(f"transaction-control-{index}" for index in range(120))
    chunks = chunk_text(text, size=180, overlap=30)

    assert len(chunks) > 1
    assert all(len(chunk.text) <= 180 for chunk in chunks)
    assert set(chunks[0].text.split()) & set(chunks[1].text.split())


def test_chroma_index_retrieves_source_with_citation_metadata(monkeypatch, tmp_path):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("VECTOR_DB_PATH", str(tmp_path / "vectors"))
    store = VectorStore()
    docs = [{
        "id": "DOC-001", "name": "onboarding-policy.txt", "document_type": "TXT",
        "jurisdiction": "IN", "version": "2.1", "chunks": [
            {"id": "chunk-001", "text": "The onboarding system shall verify identity documents and preserve an audit record."},
            {"id": "chunk-002", "text": "The office kitchen stocks tea and coffee each morning."},
        ],
    }]

    assert store.index("testproject01", docs) == 2
    matches = store.retrieve("testproject01", "onboarding verify identity audit")

    assert matches[0]["document_name"] == "onboarding-policy.txt"
    assert matches[0]["id"] == "chunk-001"
    assert matches[0]["jurisdiction"] == "IN"
    assert matches[0]["version"] == "2.1"


def test_health_requirement_edit_and_delivery_artifact(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from app.services.storage import ProjectStore
    from app import main

    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("VECTOR_DB_PATH", str(tmp_path / "vectors"))
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "projects"))
    monkeypatch.setattr(main, "vector_store", VectorStore())
    monkeypatch.setattr(main, "store", ProjectStore())
    client = TestClient(main.app)

    assert client.get("/api/health").json()["status"] == "ok"
    created = client.post("/api/projects", data={
        "functionality": "Bank customer onboarding identity verification",
        "stakeholder_input": '{"business objective":"The onboarding system shall verify identity documents using authentication and preserve an audit record for each decision."}',
        "jurisdiction": "IN", "version": "2.1", "uploaded_by": "Compliance team",
    }, files={"files": ("identity-policy.txt", b"The onboarding system shall verify identity documents using authentication and preserve an audit record for each decision. Reviewers must retain exception evidence.", "text/plain")})
    assert created.status_code == 200
    assert created.json()["documents"][0]["jurisdiction"] == "IN"
    assert created.json()["documents"][1]["version"] == "2.1"
    project_id = created.json()["project_id"]
    generated = client.post(f"/api/projects/{project_id}/requirements")
    assert generated.status_code == 200
    requirement = generated.json()["requirements"][0]
    edited = client.patch(f"/api/projects/{project_id}/requirements/{requirement['id']}", json={
        "statement": "The onboarding system shall verify identity documents before account approval.",
        "acceptance_criteria": ["A valid document produces a recorded verification decision."],
    })
    assert edited.status_code == 200
    assert client.post(f"/api/projects/{project_id}/sdlc").status_code == 200
    sdlc_approval = client.post(f"/api/projects/{project_id}/sdlc/approval", data={"status": "Approved"})
    assert sdlc_approval.status_code == 200
    assert sdlc_approval.json()["approval_status"] == "Approved"
    artifact = client.get(f"/api/projects/{project_id}/artifacts")
    assert artifact.status_code == 200
    assert "Software Requirements Specification" in artifact.text
    assert "chunk-001" in artifact.text
    clarification = client.post(f"/api/projects/{project_id}/requirements/{requirement['id']}/clarification")
    assert clarification.status_code == 200
    assert {entry["action"] for entry in audit} >= {"requirement_modified", "clarification_requested"}


def test_retrieval_rebuilds_missing_project_index(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from app import main
    from app.schemas import Project
    from app.services.storage import ProjectStore
    from datetime import datetime, timezone

    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("VECTOR_DB_PATH", str(tmp_path / "vectors"))
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "projects"))
    project_store = ProjectStore()
    project = Project(
        id="abcd1234abcd", functionality="identity verification",
        created_at=datetime.now(timezone.utc),
        documents=[{"id": "DOC-001", "name": "policy.txt", "chunks": [{"id": "chunk-001", "text": "Identity verification must preserve an audit record."}]}],
    )
    project_store.save(project)
    monkeypatch.setattr(main, "store", project_store)
    monkeypatch.setattr(main, "vector_store", VectorStore())

    response = TestClient(main.app).get(f"/api/projects/{project.id}/retrieval?query=identity verification")

    assert response.status_code == 200
    assert response.json()["matches"][0]["document_name"] == "policy.txt"
