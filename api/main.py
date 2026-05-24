from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from datetime import datetime
import os
import sys

# Añadir el directorio parent al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.models.database import create_tables, get_db
from config.config import PANEL_NAME, PANEL_VERSION

# Importar rutas (las crearemos después)
# from api.routes import users, domains, php, ssl, ipv6

# Crear app FastAPI
app = FastAPI(
    title=PANEL_NAME,
    description="Panel de control para servidores web",
    version=PANEL_VERSION,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost", "http://localhost:3000", "127.0.0.1"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Crear tablas al iniciar
@app.on_event("startup")
async def startup():
    create_tables()
    print(f"✓ {PANEL_NAME} v{PANEL_VERSION} iniciado")
    print(f"✓ Base de datos sincronizada")

# Health check
@app.get("/", tags=["Health"])
async def root():
    return {
        "status": "ok",
        "panel": PANEL_NAME,
        "version": PANEL_VERSION,
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/api/health", tags=["Health"])
async def health_check(db: Session = Depends(get_db)):
    """Health check con verificación de BD"""
    try:
        # Verificar conexión a BD
        db.execute("SELECT 1")
        return {
            "status": "ok",
            "database": "connected",
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "error", "message": str(e)}
        )

# Incluir rutas (cuando las creemos)
# app.include_router(users.router, prefix="/api/users", tags=["Users"])
# app.include_router(domains.router, prefix="/api/domains", tags=["Domains"])
# app.include_router(php.router, prefix="/api/php", tags=["PHP"])
# app.include_router(ssl.router, prefix="/api/ssl", tags=["SSL"])
# app.include_router(ipv6.router, prefix="/api/ipv6", tags=["IPv6"])

# Manejo de errores global
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "status": "error",
            "message": "Error interno del servidor",
            "detail": str(exc) if os.getenv("DEBUG") else None
        }
    )

if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("PANEL_PORT", 8001))
    host = os.getenv("PANEL_HOST", "127.0.0.1")
    
    print(f"\n{'='*50}")
    print(f"  {PANEL_NAME} v{PANEL_VERSION}")
    print(f"{'='*50}")
    print(f"  URL: http://{host}:{port}")
    print(f"  Docs: http://{host}:{port}/docs")
    print(f"{'='*50}\n")
    
    uvicorn.run(
        "api.main:app",
        host=host,
        port=port,
        reload=True,
        log_level="info"
    )
