from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from config import settings
from database import init_db
from routes import auth, download, upload, payment, user, admin
import uvicorn, logging

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="MediaFlow Pro API",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url=None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.FRONTEND_URL,
        "http://localhost",
        "http://127.0.0.1",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router,     prefix="/api/auth",     tags=["Auth"])
app.include_router(user.router,     prefix="/api/user",     tags=["User"])
app.include_router(download.router, prefix="/api/download", tags=["Download"])
app.include_router(upload.router,   prefix="/api/upload",   tags=["Upload"])
app.include_router(payment.router,  prefix="/api/payment",  tags=["Payment"])
app.include_router(admin.router,    prefix="/api/admin",    tags=["Admin"])


@app.get("/api/health")
async def health():
    return {"status": "ok"}

@app.exception_handler(404)
async def not_found(r: Request, e): return JSONResponse({"success":False,"message":"Not found."}, 404)
@app.exception_handler(500)
async def server_err(r: Request, e): return JSONResponse({"success":False,"message":"Server error."}, 500)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
