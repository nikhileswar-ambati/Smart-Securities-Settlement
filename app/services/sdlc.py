from __future__ import annotations

from app.schemas import Category, Requirement, SdlcFactor, SdlcOption, SdlcRecommendation, WorkflowPhase


def _requirement_ids(requirements: list[Requirement], categories: set[Category]) -> list[str]:
    return [requirement.id for requirement in requirements if categories & set(requirement.categories)]


def _factor(name: str, score: int, value: str, rationale: str, requirement_ids: list[str] | None = None) -> SdlcFactor:
    return SdlcFactor(name=name, score=score, value=value, rationale=rationale, requirement_ids=requirement_ids or [])


def _score(base: int, adjustments: list[tuple[bool, int]]) -> int:
    return max(0, min(100, base + sum(amount for applies, amount in adjustments if applies)))


def recommend(requirements: list[Requirement]) -> SdlcRecommendation:
    """Rank requested SDLC models from requirement signals without inventing project facts."""
    categories = {category for requirement in requirements for category in requirement.categories}
    needs_review = sum(requirement.approval_status != "Approved" for requirement in requirements)
    measurable = sum(bool(requirement.acceptance_criteria) and not any("reviewer" in item.lower() for item in requirement.acceptance_criteria) for requirement in requirements)
    high_risk = sum(requirement.risk_level == "High" for requirement in requirements)
    security_or_compliance = {Category.SECURITY, Category.PRIVACY, Category.REGULATORY, Category.AUDIT}
    risk_ids = _requirement_ids(requirements, security_or_compliance)
    integration_ids = _requirement_ids(requirements, {Category.INTEGRATION, Category.DATA})
    stakeholder_ids = _requirement_ids(requirements, {Category.STAKEHOLDER, Category.USABILITY, Category.BUSINESS})

    stability_score = 2 if needs_review else 4
    clarity_score = 4 if measurable == len(requirements) else 2 if measurable == 0 else 3
    risk_score = 5 if high_risk or risk_ids else 3
    complexity_score = 4 if integration_ids else 2
    early_prototype_score = 4 if clarity_score <= 2 or complexity_score >= 4 else 3
    time_score = 3
    involvement_score = 4 if stakeholder_ids else 3
    change_score = 3
    iterative_score = 4 if clarity_score <= 2 or needs_review else 3
    risk_analysis_score = 5 if risk_score >= 5 or complexity_score >= 4 else 3

    factors = [
        _factor("Requirement stability", stability_score, "Needs validation" if needs_review else "Baseline approved", "Draft or unapproved requirements indicate that stability has not yet been demonstrated." if needs_review else "All requirements have an explicit approval status.", [requirement.id for requirement in requirements if requirement.approval_status != "Approved"]),
        _factor("Requirement clarity", clarity_score, "Low" if clarity_score <= 2 else "Moderate" if clarity_score == 3 else "High", "Measured from the presence of concrete, non-placeholder acceptance criteria.", [requirement.id for requirement in requirements if not requirement.acceptance_criteria or any("reviewer" in item.lower() for item in requirement.acceptance_criteria)]),
        _factor("Risk", risk_score, "High" if risk_score >= 5 else "Medium", "Derived from stated high risk and security, privacy, regulatory, or audit classifications.", risk_ids),
        _factor("Complexity", complexity_score, "High" if complexity_score >= 4 else "Low", "Integration and data-management requirements increase coordination and technical complexity.", integration_ids),
        _factor("Need for early prototype", early_prototype_score, "Likely" if early_prototype_score >= 4 else "Confirm with stakeholders", "Unclear requirements or integration complexity make early learning and validation valuable."),
        _factor("Time constraints", time_score, "Not evidenced", "No schedule or deadline evidence is available in the generated requirements; confirm this with the project sponsor."),
        _factor("Customer involvement", involvement_score, "Evidenced" if stakeholder_ids else "Not evidenced", "Derived only from business, stakeholder, or usability requirements; otherwise this must be confirmed.", stakeholder_ids),
        _factor("Frequency of changes", change_score, "Not evidenced", "Requirement documents do not establish the expected change rate; confirm with product and business stakeholders."),
        _factor("Need for iterative development", iterative_score, "Likely" if iterative_score >= 4 else "Confirm with stakeholders", "Unapproved or unclear requirements benefit from repeated review and validation cycles."),
        _factor("Need for risk analysis", risk_analysis_score, "High" if risk_analysis_score >= 5 else "Medium", "Security/compliance concerns or complex integration warrant explicit risk analysis.", sorted(set(risk_ids + integration_ids))),
    ]

    stable = stability_score >= 4
    clear = clarity_score >= 4
    unclear = clarity_score <= 2
    high_risk_or_analysis = risk_score >= 5 or risk_analysis_score >= 5
    complex_project = complexity_score >= 4
    prototype_helpful = early_prototype_score >= 4
    iterative = iterative_score >= 4
    customer_available = bool(stakeholder_ids)
    time_pressure = time_score >= 4

    options = [
        SdlcOption(name="Waterfall", score=_score(42, [(stable, 25), (clear, 20), (not iterative, 8), (high_risk_or_analysis, 5), (unclear, -20)]), suitability="Best when requirements are stable, fully specified, and changes are controlled."),
        SdlcOption(name="V-Model", score=_score(44, [(stable, 20), (clear, 18), (high_risk_or_analysis, 18), (unclear, -18)]), suitability="Best when each specification stage needs a linked verification and validation activity."),
        SdlcOption(name="Prototyping", score=_score(45, [(prototype_helpful, 26), (unclear, 18), (customer_available, 10), (complex_project, 8)]), suitability="Best for validating uncertain user needs, workflows, and interfaces before committing to a full build."),
        SdlcOption(name="RAD", score=_score(40, [(time_pressure, 25), (customer_available, 20), (iterative, 15), (high_risk_or_analysis, -10), (complex_project, -8)]), suitability="Best for time-boxed delivery with available users and modular, lower-risk scope."),
        SdlcOption(name="Spiral", score=_score(43, [(high_risk_or_analysis, 27), (complex_project, 18), (prototype_helpful, 12), (iterative, 8)]), suitability="Best when risk analysis, prototypes, and repeated risk-reduction cycles are central."),
        SdlcOption(name="Incremental", score=_score(46, [(iterative, 18), (complex_project, 12), (prototype_helpful, 10), (customer_available, 8), (time_pressure, 8)]), suitability="Best when value can be divided into validated, independently testable increments."),
        SdlcOption(name="Agile", score=_score(45, [(iterative, 22), (customer_available, 18), (prototype_helpful, 12), (unclear, 10), (high_risk_or_analysis, 3)]), suitability="Best for frequent feedback and evolving requirements, with planned governance for high-risk work."),
        SdlcOption(name="DevSecOps", score=_score(40, [(high_risk_or_analysis, 20), (iterative, 12), (bool(security_or_compliance & categories), 18), (complex_project, 8)]), suitability="Best when security controls, continuous integration, automated testing, and operational feedback must be built into delivery."),
        SdlcOption(name="Hybrid", score=_score(46, [(high_risk_or_analysis, 18), (iterative, 15), (stable, 8), (unclear, 8), (complex_project, 8)]), suitability="Best when iterative discovery and delivery need formal verification, compliance, or release gates."),
    ]
    options.sort(key=lambda option: option.score, reverse=True)
    choice = options[0].name
    factor_summary = ", ".join(f"{factor.name.lower()} is {factor.value.lower()}" for factor in factors[:5])
    return SdlcRecommendation(
        recommended_sdlc=choice,
        factors=factors,
        options=options,
        justification=f"{choice} has the highest transparent score because {factor_summary}. Factors marked 'Not evidenced' are deliberately neutral and require stakeholder confirmation before the SDLC is approved.",
        workflow=[
            WorkflowPhase(phase="Validate requirements", activities=["Resolve quality issues", "Confirm stability, time constraints, and expected changes", "Prioritise requirement baseline"], roles=["Business analyst", "Customer representative"], deliverables=["Validated requirements", "SDLC factor assessment"], gate="Stakeholder confirms project assumptions"),
            WorkflowPhase(phase="Plan the model", activities=["Review ranked SDLC options", "Plan risk analysis", "Define iteration or stage gates"], roles=["Project manager", "Architect", "Risk owner"], deliverables=["Approved SDLC decision", "Delivery review plan"], gate="Engineering and business approval"),
            WorkflowPhase(phase="Develop and validate", activities=["Build planned scope", "Run acceptance, security, and integration tests", "Review feedback and risks"], roles=["Developers", "QA", "Security", "Customer representative"], deliverables=["Working increment or verified stage", "Test evidence", "Security findings"], gate="Quality, security, and stakeholder acceptance"),
            WorkflowPhase(phase="Release and learn", activities=["Complete compliance and operational readiness review", "Release approved scope", "Monitor outcomes and reassess risks"], roles=["Operations", "Product owner", "Project manager", "Compliance reviewer"], deliverables=["Release record", "Compliance sign-off", "Updated SDLC assessment"], gate="Human release and change-control approval"),
        ],
    )
