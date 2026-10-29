"""HTTP API for VibePrompt / Invisible Grill."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_engine, get_repository, require_api_secret
from app.compilation.readiness import assess_readiness
from app.compilation.spec import compile_specification
from app.config import Settings, get_settings
from app.grill.lifecycle import update_finding_status
from app.orchestration.engine import GrillEngine
from app.persistence.repository import ProjectRepository
from app.projects.models import (
    ChatRequest,
    ChatResponse,
    Finding,
    FindingUpdateRequest,
    ProjectCreate,
    ProjectState,
    ProjectSummary,
    ReadinessResult,
    SpecificationResult,
)

router = APIRouter(dependencies=[Depends(require_api_secret)])


@router.get("/health")
def health(settings: Settings = Depends(get_settings)) -> dict:
    return {
        "status": "ok",
        "product": "VibePrompt Invisible Grill",
        "providers": settings.provider_status(),
    }


@router.get("/projects", response_model=list[ProjectSummary])
def list_projects(repo: ProjectRepository = Depends(get_repository)) -> list[ProjectSummary]:
    return repo.list_summaries()


@router.post("/projects", response_model=ProjectState)
async def create_project(
    body: ProjectCreate,
    repo: ProjectRepository = Depends(get_repository),
    engine: GrillEngine = Depends(get_engine),
) -> ProjectState:
    project = ProjectState(
        name=body.name.strip(),
        objective=(body.objective or "").strip(),
    )
    project = repo.create(project)
    if body.initial_message and body.initial_message.strip():
        await engine.handle_message(project.id, body.initial_message.strip())
        refreshed = repo.get(project.id)
        if refreshed:
            return refreshed
    return project


@router.get("/projects/{project_id}", response_model=ProjectState)
def get_project(
    project_id: str,
    repo: ProjectRepository = Depends(get_repository),
) -> ProjectState:
    project = repo.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.delete("/projects/{project_id}")
def delete_project(
    project_id: str,
    repo: ProjectRepository = Depends(get_repository),
) -> dict:
    if not repo.delete(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    return {"deleted": True}


@router.post("/projects/{project_id}/messages", response_model=ChatResponse)
async def send_message(
    project_id: str,
    body: ChatRequest,
    engine: GrillEngine = Depends(get_engine),
) -> ChatResponse:
    try:
        return await engine.handle_message(project_id, body.content)
    except KeyError:
        raise HTTPException(status_code=404, detail="Project not found") from None


@router.get("/projects/{project_id}/findings", response_model=list[Finding])
def list_findings(
    project_id: str,
    repo: ProjectRepository = Depends(get_repository),
) -> list[Finding]:
    project = repo.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project.findings


@router.patch("/projects/{project_id}/findings/{finding_id}", response_model=Finding)
def update_finding(
    project_id: str,
    finding_id: str,
    body: FindingUpdateRequest,
    repo: ProjectRepository = Depends(get_repository),
) -> Finding:
    project = repo.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    finding = next((f for f in project.findings if f.id == finding_id), None)
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")
    update_finding_status(finding, body.status, body.note)
    repo.save(project)
    return finding


@router.get("/projects/{project_id}/readiness", response_model=ReadinessResult)
def get_readiness(
    project_id: str,
    repo: ProjectRepository = Depends(get_repository),
) -> ReadinessResult:
    project = repo.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return assess_readiness(project)


@router.post("/projects/{project_id}/specification", response_model=SpecificationResult)
def generate_specification(
    project_id: str,
    repo: ProjectRepository = Depends(get_repository),
) -> SpecificationResult:
    project = repo.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return compile_specification(project)
