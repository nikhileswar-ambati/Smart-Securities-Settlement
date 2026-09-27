let projectId = null;
let currentProjectRequirements = [];
let questionIndex = 0;
let questionQueue = [];
let askedQuestionKeys = new Set();
const interviewAnswers = {};
const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>\'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[char]));
const INTERVIEW_QUESTION_LIMIT = 5;
const coverageQuestions = [
  { key: "business rules", topic: "Decision rules", prompt: "Which rules, limits, approvals, or eligibility conditions decide whether the workflow can continue?" },
  { key: "exceptions", topic: "Exceptions", prompt: "What should happen for failures, missing information, rejected decisions, or manual overrides? Who owns the resolution?" },
  { key: "data and integrations", topic: "Data and integrations", prompt: "Which data is collected or exchanged, which systems or third parties are involved, and what happens if an integration is unavailable?" },
  { key: "security and compliance", topic: "Security and compliance", prompt: "Which access controls, audit records, privacy obligations, fraud checks, or compliance requirements must be met?" },
  { key: "service levels and scale", topic: "Operational scale", prompt: "What volumes, peak periods, response times, availability targets, or recovery expectations should the solution support?" },
  { key: "delivery constraints", topic: "Delivery context", prompt: "What deadlines, budget or team constraints, stakeholder availability, technical dependencies, and change expectations should shape delivery?" },
  { key: "validation and rollout", topic: "Validation and rollout", prompt: "How should this be tested, approved, piloted, released, monitored, and improved after launch?" },
];
const domainOpeners = [
  { terms: ["onboard", "kyc", "identity", "account opening"], topic: "Onboarding", prompt: "For the onboarding journey, what starts identity verification, what evidence is checked, and what outcome should the customer receive?" },
  { terms: ["payment", "transfer", "transaction", "card"], topic: "Payments", prompt: "For the payment journey, what starts a transaction, which decisions or checks occur, and what confirmation should each party receive?" },
  { terms: ["loan", "credit", "lending"], topic: "Loan processing", prompt: "For the lending journey, what starts an application, which decisions occur, and what result should the applicant receive?" },
  { terms: ["fraud", "suspicious", "risk detection"], topic: "Fraud detection", prompt: "Which events start a fraud investigation, how are cases assessed, and what outcome should the case owner receive?" },
  { terms: ["insurance", "claim", "policyholder"], topic: "Insurance", prompt: "For the claim journey, what starts assessment, which decisions occur, and what outcome should the policyholder receive?" },
  { terms: ["report", "regulatory", "compliance"], topic: "Reporting", prompt: "For the reporting journey, what starts a report, which validation and approval decisions occur, and what submission outcome is required?" },
];

function answerExcerpt(answer) {
  const compact = answer.replace(/\s+/g, " ").trim();
  return compact.length > 150 ? `${compact.slice(0, 147)}...` : compact;
}
function selectOpeningQuestion(context) {
  const opener = domainOpeners.find((rule) => rule.terms.some((term) => context.includes(term)));
  return { key: "workflow and outcomes", ...(opener || { topic: "Workflow", prompt: "Walk through the normal journey. What starts the process, what decisions happen, and what outcome should the user receive?" }) };
}
function selectNextQuestion(previousAnswer) {
  const remaining = coverageQuestions.filter((question) => !askedQuestionKeys.has(question.key));
  if (!remaining.length) return null;
  const answer = previousAnswer.toLowerCase();
  const followUpOrder = [
    { key: "exceptions", terms: ["fail", "error", "reject", "declin", "exception", "manual", "override"] },
    { key: "data and integrations", terms: ["api", "system", "integrat", "third party", "vendor", "data", "document"] },
    { key: "security and compliance", terms: ["risk", "fraud", "security", "audit", "privacy", "compliance", "access"] },
    { key: "business rules", terms: ["rule", "limit", "approv", "eligib", "decision", "threshold"] },
    { key: "service levels and scale", terms: ["volume", "peak", "time", "urgent", "daily", "availability", "customer"] },
  ];
  const followUp = followUpOrder.find((rule) => rule.terms.some((term) => answer.includes(term)));
  const selected = remaining.find((question) => question.key === followUp?.key) || remaining[0];
  const context = previousAnswer ? `You mentioned “${answerExcerpt(previousAnswer)}”. ` : "To complete the project picture, ";
  return { ...selected, prompt: `${context}${selected.prompt}` };
}

function toast(message) {
  const node = $("#toast"); node.textContent = message; node.classList.add("show");
  setTimeout(() => node.classList.remove("show"), 3200);
}
async function request(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(body.detail || "Request failed"); }
  return response.json();
}
function showEmpty(id, show) { const node = $(id); if (node) node.classList.toggle("is-hidden", !show); }
function displayDocuments(documents, rag) {
  $("#documentList").innerHTML = documents.map((doc) => `<article class="doc-row"><div><strong>${escapeHtml(doc.name)}</strong><small>${escapeHtml(doc.document_type || "Source")} · ${escapeHtml(doc.jurisdiction || "Jurisdiction not set")} · ${escapeHtml(doc.version || "Version not set")} · ${escapeHtml(doc.effective_date || "Effective date not set")} · ${escapeHtml(doc.applicability || "")} · ${Number(doc.chunks || 0)} chunks</small></div><span class="doc-indexed">Indexed</span></article>`).join("");
  $("#ragSummary").innerHTML = `<span>${escapeHtml(rag.vector_database)}</span><span>${escapeHtml(rag.embedding_model)}</span><span>${Number(rag.indexed_chunks || 0)} vectors indexed</span>`;
  $("#documentsPanel").classList.remove("is-hidden"); showEmpty("#knowledgeEmpty", false);
  $("#generateButton").disabled = false; $("#retrieveButton").disabled = false;
}
function displayRetrievedEvidence(result) {
  const list = $("#retrievalResults");
  list.innerHTML = result.matches.length ? result.matches.map((match) => `<article class="retrieval-match"><div><span class="field-label">${escapeHtml(match.document_name)} / ${escapeHtml(match.id)}</span><p>${escapeHtml(match.text)}</p></div><strong>${Math.round(match.relevance * 100)}%</strong></article>`).join("") : `<p class="empty-state">No matching chunks found for this query.</p>`;
  $("#retrievalCount").textContent = `${result.count} match${result.count === 1 ? "" : "es"}`;
  const notice = $("#evidenceNotice");
  notice.textContent = result.evidence_sufficient === false ? "Evidence appears insufficient for a grounded answer. Add a relevant source or refine the query." : `${result.confidence === undefined ? "" : `Strongest match ${Math.round(result.confidence * 100)}%. `}Retrieved passages are source evidence, not instructions.`;
  notice.classList.toggle("is-hidden", !result.count && result.evidence_sufficient !== false);
  notice.classList.toggle("notice-low", result.evidence_sufficient === false);
}
function displayRequirements(project) {
  currentProjectRequirements = project.requirements || currentProjectRequirements;
  const category = $("#filterCategory").value, priority = $("#filterPriority").value, approval = $("#filterApproval").value, confidence = $("#filterConfidence").value;
  project = { ...project, requirements: currentProjectRequirements.filter((req) => (!category || req.categories.includes(category)) && (!priority || req.priority === priority) && (!approval || req.approval_status === approval) && (!confidence || (confidence === "low" && req.confidence < .5) || (confidence === "medium" && req.confidence >= .5 && req.confidence < .8) || (confidence === "high" && req.confidence >= .8))) };
  const list = $("#requirementsPanel");
  list.innerHTML = project.requirements.length ? project.requirements.map((req) => `<article class="requirement"><div class="requirement-head"><div><span class="req-id">${escapeHtml(req.id)}</span><h3>${escapeHtml(req.statement)}</h3><div class="tags">${req.categories.map((category) => `<span class="tag">${escapeHtml(category)}</span>`).join("")}</div></div><label class="status-label">Approval status<select class="status" data-id="${escapeHtml(req.id)}" aria-label="Approval status for ${escapeHtml(req.id)}">${["Draft", "Needs review", "Approved", "Rejected"].map((status) => `<option ${req.approval_status === status ? "selected" : ""}>${status}</option>`).join("")}</select></label></div><div class="requirement-grid"><div><span class="field-label">Business justification</span><p>${escapeHtml(req.business_justification)}</p></div><div><span class="field-label">Confidence / risk</span><p>${Math.round(req.confidence * 100)}% confidence · ${escapeHtml(req.risk_level)} risk · ${escapeHtml(req.priority)}</p></div><div><span class="field-label">Acceptance criteria</span><p>${req.acceptance_criteria.length ? req.acceptance_criteria.map(escapeHtml).join("<br>") : "Needs definition"}</p></div><div><span class="field-label">Assumptions / dependencies</span><p>${[...req.assumptions, ...req.dependencies].length ? [...req.assumptions, ...req.dependencies].map(escapeHtml).join("<br>") : "None recorded"}</p></div></div>${req.evidence.map((evidence) => `<div class="evidence"><span class="field-label">Source citation · ${escapeHtml(evidence.document_name)} / ${escapeHtml(evidence.chunk_id)} · ${Math.round(evidence.relevance * 100)}% relevance</span><p>${escapeHtml(evidence.excerpt)}</p></div>`).join("")}<details class="edit-panel"><summary>Edit draft fields</summary><form class="edit-form" data-id="${escapeHtml(req.id)}"><label>Requirement statement<textarea name="statement" minlength="10" required>${escapeHtml(req.statement)}</textarea></label><label>Business justification<textarea name="business_justification">${escapeHtml(req.business_justification)}</textarea></label><label>Priority<select name="priority">${["Must", "Should", "Could"].map((value) => `<option ${req.priority === value ? "selected" : ""}>${value}</option>`).join("")}</select></label><label>Acceptance criteria <small>One criterion per line</small><textarea name="acceptance_criteria">${escapeHtml(req.acceptance_criteria.join("\n"))}</textarea></label><div class="interview-actions"><button type="submit">Save changes</button><button class="request-clarification button-outline" type="button" data-id="${escapeHtml(req.id)}">Request clarification</button></div></form></details></article>`).join("") : `<div class="surface-card empty-state">No requirements match these filters.</div>`;
  $("#requirementCount").textContent = `${project.requirements.length} of ${currentProjectRequirements.length} draft${currentProjectRequirements.length === 1 ? "" : "s"}`;
  $("#generateButton").textContent = currentProjectRequirements.length ? "Regenerate requirements" : "Generate requirements";
  list.classList.remove("is-hidden"); showEmpty("#requirementsEmpty", !currentProjectRequirements.length); showEmpty("#requirementFilters", currentProjectRequirements.length > 0);
  list.querySelectorAll("select").forEach((select) => select.addEventListener("change", async () => {
    const data = new FormData(); data.append("status", select.value);
    try { await request(`/api/projects/${projectId}/requirements/${encodeURIComponent(select.dataset.id)}/approval`, { method: "POST", body: data }); await refreshAnalysis(); await refreshDashboard(); toast("Review status updated."); }
    catch (error) { toast(error.message); }
  }));
  list.querySelectorAll(".edit-form").forEach((form) => form.addEventListener("submit", async (event) => {
    event.preventDefault(); const data = new FormData(form);
    const payload = { statement: data.get("statement"), business_justification: data.get("business_justification"), priority: data.get("priority"), acceptance_criteria: String(data.get("acceptance_criteria") || "").split("\n").map((line) => line.trim()).filter(Boolean) };
    try { await request(`/api/projects/${projectId}/requirements/${encodeURIComponent(form.dataset.id)}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }); await refreshAnalysis(); toast("Draft updated; approved baseline returned to review where needed."); }
    catch (error) { toast(error.message); }
  }));
  list.querySelectorAll(".request-clarification").forEach((button) => button.addEventListener("click", async () => {
    try { await request(`/api/projects/${projectId}/requirements/${encodeURIComponent(button.dataset.id)}/clarification`, { method: "POST" }); await refreshAnalysis(); toast("Clarification requested."); }
    catch (error) { toast(error.message); }
  }));
}
function displayIssues(issues) {
  const list = $("#qualityPanel");
  list.innerHTML = issues.length ? issues.map((issue) => `<article class="issue"><div><span class="severity severity-${escapeHtml(issue.severity.toLowerCase())}">${escapeHtml(issue.severity)}</span><p class="muted">${escapeHtml(issue.check)}</p></div><div><strong>${escapeHtml(issue.requirement_id || "Project")}</strong><p>${escapeHtml(issue.message)}</p><p class="recommendation">${escapeHtml(issue.recommendation)}</p></div></article>`).join("") : `<div class="surface-card empty-state">No rule-based issues found. Human review is still required.</div>`;
  $("#issueCount").textContent = `${issues.length} finding${issues.length === 1 ? "" : "s"}`; list.classList.remove("is-hidden"); showEmpty("#qualityEmpty", false);
}
function displaySdlc(sdlc) {
  $("#sdlcResult").innerHTML = `<div class="sdlc-overview"><div><p class="eyebrow">Recommended model · ${escapeHtml(sdlc.approval_status || "Needs review")}</p><h3>${escapeHtml(sdlc.recommended_sdlc)}</h3><p>${escapeHtml(sdlc.justification)}</p><div class="sdlc-actions"><span class="review-pill">Human decision required</span><button type="button" data-sdlc-status="Approved">Approve</button><button class="button-outline" type="button" data-sdlc-status="Rejected">Reject</button></div></div><div class="rankings">${sdlc.options.map((option) => `<div class="ranking"><span>${escapeHtml(option.name)}</span><div class="bar"><span style="width:${option.score}%"></span></div><strong>${option.score}%</strong></div>`).join("")}</div></div><div class="workflow"><p class="eyebrow">Decision factors</p><div class="factor-grid">${sdlc.factors.map((factor) => `<div class="factor"><h4>${escapeHtml(factor.name)}</h4><strong>${escapeHtml(factor.value)}</strong><p>${escapeHtml(factor.rationale)}</p>${factor.requirement_ids.length ? `<small>Linked: ${escapeHtml(factor.requirement_ids.join(", "))}</small>` : ""}</div>`).join("")}</div></div><div class="workflow"><p class="eyebrow">Project-specific workflow</p><div class="workflow-grid">${sdlc.workflow.map((phase) => `<div class="phase"><h4>${escapeHtml(phase.phase)}</h4><p>${escapeHtml(phase.activities.join(" · "))}</p><p><strong>Gate:</strong> ${escapeHtml(phase.gate)}</p><small>${escapeHtml(phase.roles.join(", "))}</small></div>`).join("")}</div></div>`;
  $("#sdlcPanel").classList.remove("is-hidden"); showEmpty("#sdlcEmpty", false);
  document.querySelectorAll("[data-sdlc-status]").forEach((button) => button.addEventListener("click", async () => {
    const data = new FormData(); data.append("status", button.dataset.sdlcStatus);
    try { displaySdlc(await request(`/api/projects/${projectId}/sdlc/approval`, { method: "POST", body: data })); const project = await request(`/api/projects/${projectId}`);  toast(`SDLC recommendation ${button.dataset.sdlcStatus.toLowerCase()}.`); }
    catch (error) { toast(error.message); }
  }));
}
async function refreshAnalysis() {
  if (!projectId) return;
  const project = await request("/api/projects/" + projectId);
  if (project.requirements.length) { displayRequirements(project); displayIssues(project.quality_issues || []); }
  if (project.sdlc) displaySdlc(project.sdlc);
  $("#sdlcButton").disabled = !project.requirements.length;
  return project;
}
async function loadProject(id) {
  projectId = id;
  ["#filterCategory", "#filterPriority", "#filterApproval", "#filterConfidence"].forEach((selector) => { $(selector).value = ""; });
  const project = await request(`/api/projects/${projectId}`);
  currentProjectRequirements = project.requirements || [];
  showEmpty("#requirementFilters", currentProjectRequirements.length === 0);
  $("#functionality").value = project.functionality;
  $("#businessObjective").value = project.business_objective || "";
  $("#usersRoles").value = project.users_and_roles || "";
  $("#projectState").innerHTML = `<span class="status-dot"></span> ${escapeHtml(project.functionality)}`;
  $("#workspace-title").textContent = "Review the loaded project";
  $("#workspaceDescription").textContent = "This saved project is open below. Use New project from the portfolio to start another intake.";
  $("#interviewStartForm").classList.add("is-hidden"); $("#interviewSession").classList.add("is-hidden"); $("#interviewComplete").classList.add("is-hidden");
  $("#exportLink").href = `/api/projects/${projectId}/export`; $("#exportLink").classList.remove("is-hidden");
  $("#artifactLink").href = `/api/projects/${projectId}/artifacts`; $("#artifactLink").classList.remove("is-hidden");
  const chunks = project.documents.reduce((sum, doc) => sum + (doc.chunks || []).length, 0);
  displayDocuments(project.documents.map((doc) => ({ ...doc, chunks: (doc.chunks || []).length })), { vector_database: "ChromaDB", embedding_model: "Project index", indexed_chunks: chunks });
  try { displayRetrievedEvidence(await request(`/api/projects/${projectId}/retrieval`)); } catch (error) { toast(error.message); }
  if (project.requirements.length) await refreshAnalysis();
  showEmpty("#requirementsEmpty", !project.requirements.length);
  $("#generateButton").disabled = false;
  $("#sdlcButton").disabled = !project.requirements.length;
  location.hash = "workspace";
}
function startNewProject() {
  projectId = null;
  currentProjectRequirements = [];
  ["#filterCategory", "#filterPriority", "#filterApproval", "#filterConfidence"].forEach((selector) => { $(selector).value = ""; });
  $("#functionality").value = ""; $("#businessObjective").value = ""; $("#usersRoles").value = ""; $("#files").value = "";
  ["#jurisdiction", "#effectiveDate", "#documentVersion", "#applicability", "#uploadedBy"].forEach((selector) => { $(selector).value = ""; });
  $("#workspace-title").textContent = "Start with the people and workflow";
  $("#workspaceDescription").textContent = "An adaptive interview creates an auditable project record and prepares source material for retrieval.";
  $("#projectState").innerHTML = `<span class="status-dot"></span> No project loaded`;
  $("#interviewStartForm").classList.remove("is-hidden"); $("#interviewSession").classList.add("is-hidden"); $("#interviewComplete").classList.add("is-hidden");
  $("#documentsPanel").classList.add("is-hidden"); showEmpty("#knowledgeEmpty", true);
  $("#requirementsPanel").classList.add("is-hidden"); showEmpty("#requirementsEmpty", true);
  showEmpty("#requirementFilters", false);
  $("#qualityPanel").classList.add("is-hidden"); showEmpty("#qualityEmpty", true);
  $("#sdlcPanel").classList.add("is-hidden"); showEmpty("#sdlcEmpty", true);
  $("#generateButton").disabled = true; $("#sdlcButton").disabled = true;
  $("#artifactLink").classList.add("is-hidden"); $("#exportLink").classList.add("is-hidden");
  $("#requirementCount").textContent = "No requirements"; $("#issueCount").textContent = "No checks run";
}
async function refreshDashboard() {
  const projects = await request("/api/projects");
  $("#projectMetric").textContent = projects.length;
  $("#requirementMetric").textContent = projects.reduce((sum, item) => sum + item.requirements, 0);
  $("#approvalMetric").textContent = projects.reduce((sum, item) => sum + item.pending_approvals, 0);
  $("#portfolioCount").textContent = `${projects.length} project${projects.length === 1 ? "" : "s"}`;
  $("#projectList").innerHTML = projects.length ? projects.map((item) => `<button class="project-row" data-project="${escapeHtml(item.id)}"><span class="project-avatar">${escapeHtml(item.functionality.slice(0, 1).toUpperCase())}</span><span class="project-info"><strong>${escapeHtml(item.functionality)}</strong><small>${item.documents} source(s) · ${item.requirements} requirement(s) · ${escapeHtml(new Date(item.created_at).toLocaleDateString())}</small></span><span class="project-arrow">→</span></button>`).join("") : `<p class="empty-state">No projects yet. Start a new project intake to build your first evidence library.</p>`;
  $("#projectList").querySelectorAll("[data-project]").forEach((button) => button.addEventListener("click", () => loadProject(button.dataset.project).catch((error) => toast(error.message))));
  const rag = await request("/api/rag/status");
  $("#knowledgeHealth").innerHTML = `<span class="health-indicator"></span><span>${escapeHtml(rag.vector_database)} ready · ${escapeHtml(rag.embedding_model)}</span>`;
}
function renderQuestion() {
  const question = questionQueue[questionIndex];
  if (!question) { $("#interviewSession").classList.add("is-hidden"); $("#interviewComplete").classList.remove("is-hidden"); $("#interviewSummary").textContent = `Interview prompts complete. ${Object.keys(interviewAnswers).length} responses are ready for project indexing.`; return; }
  $("#questionProgress").textContent = `Question ${questionIndex + 1} of ${INTERVIEW_QUESTION_LIMIT}`;
  $("#answerCount").textContent = `${Object.keys(interviewAnswers).length} answers saved`;
  $("#questionTopic").textContent = question.topic; $("#interviewQuestion").textContent = question.prompt;
  $("#interviewAnswer").value = interviewAnswers[question.key] || ""; $("#interviewAnswer").focus();
}
function advanceInterview(saveAnswer) {
  const question = questionQueue[questionIndex]; const answer = $("#interviewAnswer").value.trim();
  if (saveAnswer && !answer) { toast("Add an answer or choose Skip for now."); return; }
  if (answer) interviewAnswers[question.key] = answer;
  if (questionQueue.length < INTERVIEW_QUESTION_LIMIT) { const nextQuestion = selectNextQuestion(answer); if (nextQuestion) { askedQuestionKeys.add(nextQuestion.key); questionQueue.push(nextQuestion); } }
  questionIndex += 1; renderQuestion();
}

$("#interviewStartForm").addEventListener("submit", (event) => {
  event.preventDefault(); const functionality = $("#functionality").value.trim(); const objective = $("#businessObjective").value.trim(); const users = $("#usersRoles").value.trim();
  if (functionality.length < 3 || !objective || !users) { toast("Complete the functionality, business objective, and users/roles to begin."); return; }
  Object.keys(interviewAnswers).forEach((key) => delete interviewAnswers[key]);
  interviewAnswers["business objective"] = objective; interviewAnswers["users and roles"] = users;
  const openingQuestion = selectOpeningQuestion(`${functionality} ${objective} ${users}`.toLowerCase());
  questionQueue = [openingQuestion]; askedQuestionKeys = new Set([openingQuestion.key]); questionIndex = 0;
  $("#interviewStartForm").classList.add("is-hidden"); $("#interviewSession").classList.remove("is-hidden"); renderQuestion();
});
$("#continueInterview").addEventListener("click", () => advanceInterview(true));
$("#skipInterviewQuestion").addEventListener("click", () => advanceInterview(false));
$("#createProject").addEventListener("click", async () => {
  const button = $("#createProject"); button.disabled = true;
  try {
    const data = new FormData(); data.append("functionality", $("#functionality").value.trim()); data.append("stakeholder_input", JSON.stringify(interviewAnswers));
    data.append("jurisdiction", $("#jurisdiction").value.trim()); data.append("effective_date", $("#effectiveDate").value); data.append("version", $("#documentVersion").value.trim()); data.append("applicability", $("#applicability").value.trim()); data.append("uploaded_by", $("#uploadedBy").value.trim());
    [...$("#files").files].forEach((file) => data.append("files", file));
    const result = await request("/api/projects", { method: "POST", body: data });
    projectId = result.project_id; $("#projectState").innerHTML = `<span class="status-dot"></span> Project ready`;
    $("#exportLink").href = `/api/projects/${projectId}/export`; $("#exportLink").classList.remove("is-hidden");
    $("#artifactLink").href = `/api/projects/${projectId}/artifacts`; $("#artifactLink").classList.remove("is-hidden");
    displayDocuments(result.documents, result.rag); displayRetrievedEvidence(await request(`/api/projects/${projectId}/retrieval`));
    $("#interviewComplete").classList.add("is-hidden"); $("#interviewStartForm").classList.remove("is-hidden");
    await refreshDashboard(); await refreshAnalysis(); toast("Sources indexed. Review retrieval evidence before generating drafts.");
  } catch (error) { toast(error.message); } finally { button.disabled = false; }
});
$("#retrieveButton").addEventListener("click", async () => {
  if (!projectId) return; const button = $("#retrieveButton"); button.disabled = true;
  try { const query = $("#retrievalQuery").value.trim() || $("#functionality").value.trim(); displayRetrievedEvidence(await request(`/api/projects/${projectId}/retrieval?query=${encodeURIComponent(query)}`)); }
  catch (error) { toast(error.message); } finally { button.disabled = false; }
});
$("#generateButton").addEventListener("click", async () => {
  if (!projectId) return; const button = $("#generateButton"); button.disabled = true;
  try { const project = await request(`/api/projects/${projectId}/requirements`, { method: "POST" }); displayRequirements(project); displayIssues(project.quality_issues); await refreshAnalysis(); await refreshDashboard(); toast("Finance requirement drafts are ready for review."); }
  catch (error) { toast(error.message); } finally { button.disabled = false; }
});
$("#sdlcButton").addEventListener("click", async () => {
  if (!projectId) return; const button = $("#sdlcButton"); button.disabled = true;
  try { displaySdlc(await request(`/api/projects/${projectId}/sdlc`, { method: "POST" })); const project = await request(`/api/projects/${projectId}`);  toast("SDLC recommendation generated. Human approval remains required."); }
  catch (error) { toast(error.message); } finally { button.disabled = false; }
});
document.querySelectorAll(".nav-link").forEach((link) => link.addEventListener("click", () => {
  document.querySelectorAll(".nav-link").forEach((item) => item.classList.remove("active")); link.classList.add("active");
}));
$("#requirementFilters").querySelectorAll("select").forEach((select) => select.addEventListener("change", () => displayRequirements({ requirements: currentProjectRequirements })));
$("#newProject").addEventListener("click", startNewProject);
$("#heroNew").addEventListener("click", startNewProject);
refreshDashboard().catch((error) => { $("#projectList").innerHTML = `<p class="empty-state">Unable to load portfolio: ${escapeHtml(error.message)}</p>`; toast(error.message); });

// Reject non-financial project requests before the intake flow starts.
document.querySelector("#interviewStartForm").addEventListener("submit", function(event) {
  const financeTerms = /\b(finance|financial|fintech|bank(?:ing)?|credit|debit|loan|lending|mortgage|payment|payroll|insurance|investment|investing|wealth|brokerage|trading|securities|portfolio|accounting|ledger|treasury|remittance|money transfer|wallet|merchant|invoice|billing|reconciliation|underwriting|kyc|aml|deposit|withdrawal|forex|currency exchange|tax reporting|financial crime|fraud detection|capital market|financial statement)\b/i;
  const context = ["#functionality", "#businessObjective", "#usersRoles"].map(function(s) { return document.querySelector(s).value; }).join(" ");
  if (!financeTerms.test(context)) {
    event.preventDefault(); event.stopImmediatePropagation();
    const notice = document.querySelector("#financeGate");
    notice.textContent = "Not suitable: Finance Helper only accepts projects related to finance or financial services.";
    notice.classList.remove("is-hidden");
  }
}, true);
