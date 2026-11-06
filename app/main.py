"""FastAPI application factory."""
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from . import api, config, ui
from .services.core import AppError


def wants_html(request: Request) -> bool:
    return request.method == "GET" and "text/html" in request.headers.get("accept", "")


def create_app() -> FastAPI:
    app = FastAPI(title="Fieldwise", version="0.1.0", docs_url="/api/docs", redoc_url=None)
    app.add_middleware(SessionMiddleware, secret_key=config.SECRET_KEY, same_site="lax", https_only=False,
                       session_cookie="fieldwise_session")
    app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
    app.include_router(api.router)
    app.include_router(ui.router)

    @app.exception_handler(AppError)
    async def app_error(request: Request, exc: AppError):
        if wants_html(request):
            if exc.status == 401:
                return RedirectResponse(f"/login?next={request.url.path}", status_code=303)
            return ui.templates.TemplateResponse(request, "error.html", {"actor": None, "flash": None, "persona": ui.PERSONA,
                                                                          "status": exc.status, "message": exc.message},
                                                 status_code=exc.status)
        return JSONResponse(exc.body(), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def bad_input(request: Request, exc: RequestValidationError):
        return JSONResponse({"error": "invalid_request", "message": "Some fields are missing or malformed.",
                             "details": [{"field": ".".join(str(p) for p in e["loc"][1:]), "problem": e["msg"]} for e in exc.errors()]},
                            status_code=422)

    @app.exception_handler(404)
    async def missing(request: Request, exc):
        if wants_html(request):
            return HTMLResponse("<h1>Not found</h1><p><a href='/'>Back to Fieldwise</a></p>", status_code=404)
        return JSONResponse({"error": "not_found", "message": "Not found"}, status_code=404)

    return app


app = create_app()
