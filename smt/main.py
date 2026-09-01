from contextlib import asynccontextmanager

import uvicorn
from fastapi import APIRouter, FastAPI
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.staticfiles import StaticFiles

from smt.api.v1.routes import (
    action_log_router,
    frontend_router,
    inventory_router,
    pool_router,
    positions_router,
    price_history_router,
    settings_router,
    statistics_router,
    steam_router,
)
from smt.api.v1.routes.frontend_pages import STATIC_DIR
from smt.core.config import get_settings
from smt.logger import setup_all_loggers
from smt.worker.arq import get_arq_service


settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_all_loggers()
    arq_service = get_arq_service()
    await arq_service.get_pool()

    yield

    await arq_service.close()


app = FastAPI(title=settings.PROJECT_NAME, debug=settings.DEBUG, lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=settings.SESSION_SECRET_KEY)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

api_router = APIRouter(prefix=f"/api/{settings.API_VERSION}")
api_router.include_router(action_log_router)
api_router.include_router(inventory_router)
api_router.include_router(pool_router)
api_router.include_router(positions_router)
api_router.include_router(price_history_router)
api_router.include_router(settings_router)
api_router.include_router(statistics_router)
api_router.include_router(steam_router)

app.include_router(api_router)
app.include_router(frontend_router)


if __name__ == "__main__":
    uvicorn.run("smt.main:app", host="0.0.0.0", port=settings.PORT, reload=settings.DEBUG)
