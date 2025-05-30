import uvicorn
from api.v1.routes.auth import auth
from api.v1.routes.frontend import home
from fastapi import APIRouter, FastAPI
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.staticfiles import StaticFiles

from smt.core.config import settings


app = FastAPI(title=settings.PROJECT_NAME, debug=settings.DEBUG)
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

api_router.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(api_router)
app.include_router(home.router)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", reload=True)
