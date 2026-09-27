from __future__ import annotations

import re

from app.schemas import Category, Evidence, Requirement


KEYWORDS: list[tuple[Category, tuple[str, ...]]] = [
    (Category.BUSINESS, ("business objective", "business goal", "value", "revenue", "cost")),
    (Category.STAKEHOLDER, ("customer", "stakeholder", "user", "operator", "analyst")),
    (Category.FUNCTIONAL, ("shall", "must", "should", "will", "allow", "support", "process")),
    (Category.SECURITY, ("authentication", "authorisation", "authorization", "encrypt", "security", "access", "mfa")),
    (Category.PRIVACY, ("personal data", "privacy", "consent", "retention", "mask")),
    (Category.REGULATORY, ("regulation", "compliance", "policy", "legal", "kyc")),
    (Category.PERFORMANCE, ("response", "performance", "latency", "throughput", "seconds")),
    (Category.AVAILABILITY, ("availability", "recovery", "uptime", "reliable")),
    (Category.INTEGRATION, ("api", "integration", "legacy", "interface")),
    (Category.AUDIT, ("audit", "report", "logging", "trace")),
    (Category.DATA, ("data", "database", "record", "document")),
    (Category.OPERATIONAL, ("monitor", "maintenance", "deployment", "operation")),
    (Category.USABILITY, ("accessible", "usability", "user-friendly", "interface", "ease of use")),
]


def classify(text: str) -> list[Category]:
    found = [category for category, terms in KEYWORDS if any(term in text.lower() for term in terms)]
    return found or [Category.FUNCTIONAL]


def _candidate_sentences(chunks: list[dict]) -> list[tuple[dict, str]]:
    candidates = []
    for chunk in chunks:
        for sentence in re.split(r"(?<=[.!?])\s+", chunk["text"]):
            if len(sentence) >= 35 and re.search(r"\b(shall|must|should|will|require|ensure|support|allow)\b", sentence, re.I):
                candidates.append((chunk, sentence.strip()))
    return candidates


def generate_evidence_drafts(functionality: str, chunks: list[dict]) -> list[Requirement]:
    requirements: list[Requirement] = []
    for index, (chunk, sentence) in enumerate(_candidate_sentences(chunks)[:10], start=1):
        evidence = Evidence(
            document_id=chunk["document_id"], document_name=chunk["document_name"],
            chunk_id=chunk["id"], excerpt=sentence, relevance=chunk["relevance"]
        )
        requirements.append(Requirement(
            id=f"REQ-{index:03d}", statement=sentence, categories=classify(sentence), evidence=[evidence],
            source_stakeholder=chunk.get("source_stakeholder", chunk.get("document_name")),
            business_justification=f"Supports the documented {functionality} need.", priority="Should",
            acceptance_criteria=["A reviewer must confirm measurable acceptance criteria before baseline approval."],
            confidence=min(0.9, max(0.45, chunk["relevance"])),
            reasoning="Evidence-only draft derived verbatim from the cited source; human refinement is required.",
            approval_status="Needs review"
        ))
    if not requirements and chunks:
        chunk = chunks[0]
        requirements.append(Requirement(
            id="REQ-001", statement=f"The system shall support the documented {functionality} workflow.",
            categories=[Category.FUNCTIONAL], evidence=[Evidence(document_id=chunk["document_id"], document_name=chunk["document_name"], chunk_id=chunk["id"], excerpt=chunk["text"][:400], relevance=chunk["relevance"])],
            business_justification="A draft was requested for the selected functionality.", priority="Should",
            assumptions=["The source excerpt describes the intended workflow."],
            acceptance_criteria=["Human reviewer defines measurable outcomes."], confidence=0.35,
            reasoning="Conservative placeholder based on the highest-ranked source. It must be rewritten and approved by a human.", approval_status="Needs review"
        ))
    return requirements
