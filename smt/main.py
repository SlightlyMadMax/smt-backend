from contextlib import asynccontextmanager

import uvicorn
from fastapi import APIRouter, FastAPI
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.staticfiles import StaticFiles

from smt.api.v1.routes import frontend_router, inventory_router, pool_router, price_history_router, settings_router
from smt.core.config import get_settings
from smt.worker.arq import get_arq_service


settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    arq_service = get_arq_service()
    # set up connection
    _ = await arq_service.get_pool()

    yield

    arq_service = get_arq_service()
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

app.mount("/static", StaticFiles(directory="/code/smt/static"), name="static")

api_router = APIRouter(prefix=f"/api/{settings.API_VERSION}")
api_router.include_router(inventory_router)
api_router.include_router(pool_router)
api_router.include_router(price_history_router)
api_router.include_router(settings_router)

app.include_router(api_router)
app.include_router(frontend_router)


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", reload=True)
