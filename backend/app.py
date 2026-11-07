# Load only the explicitly approved private local connection before route policy.
from backend.services.oomp_local import load_local_connection
load_local_connection()

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from backend.routes.chat import router as chat_router
from backend.routes.auth import router as auth_router
from backend.database.database import connect_db
from backend.routes.feedback import router as feedback_router
from backend.routes.sessions import router as sessions_router
from backend.routes.analytics import router as analytics_router


app = FastAPI(title="TRACE AI Chatbot")


# ----------------------------
# 1. CORS SETUP
# ----------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----------------------------
# 2. DATABASE CONNECTION
# ----------------------------
connect_db()


# ----------------------------
# 3. API ROUTES
# ----------------------------
from backend.services.oomp_security import MemoryOwnerMiddleware, require_memory_owner

app.add_middleware(MemoryOwnerMiddleware)
app.include_router(chat_router, dependencies=[Depends(require_memory_owner)])
app.include_router(auth_router)
app.include_router(feedback_router, dependencies=[Depends(require_memory_owner)])
app.include_router(sessions_router, dependencies=[Depends(require_memory_owner)])
app.include_router(analytics_router, dependencies=[Depends(require_memory_owner)])


# ----------------------------
# 4. DEFAULT ROUTE
# ----------------------------
@app.get("/")
def home():
    return RedirectResponse(
        url="/login.html"
    )


# ----------------------------
# 5. HEALTH CHECK
# ----------------------------
@app.get("/health")
def health():
    return {"status": "ok"}


# ----------------------------
# 6. FRONTEND MOUNT
# IMPORTANT: KEEP THIS LAST
# ----------------------------
app.mount(
    "/",
    StaticFiles(
        directory="frontend",
        html=True
    ),
    name="frontend"
)
