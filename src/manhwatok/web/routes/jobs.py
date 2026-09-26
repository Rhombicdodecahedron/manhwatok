"""A job's own page (its live log, and the phone it drives), and the questions jobs ask —
shown in a dialog on whatever page is open, answered once."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, Response

from manhwatok.domain.errors import ManhwatokError
from manhwatok.web.routes.common import done, page

router = APIRouter()


def _job(request: Request, job_id: str):
    try:
        return request.app.state.jobs.get(job_id)
    except ManhwatokError:
        return None


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_page(request: Request, job_id: str) -> HTMLResponse:
    return page(request, "job.html", page="posts", job=_job(request, job_id), job_id=job_id)


@router.get("/jobs/{job_id}/log", response_class=HTMLResponse)
def job_log(request: Request, job_id: str) -> HTMLResponse:
    return page(request, "_job_log.html", job=_job(request, job_id))


@router.get("/questions", response_class=HTMLResponse)
def question(request: Request) -> HTMLResponse:
    pending = request.app.state.jobs.pending()
    return page(request, "_question.html", q=pending[0] if pending else None)


@router.post("/questions/{question_id}")
def answer(request: Request, question_id: str, value: str = Form("")) -> Response:
    if request.app.state.jobs.answer(question_id, value):
        return done(request, "answered")
    return done(request, "that question was already answered", "warning")
