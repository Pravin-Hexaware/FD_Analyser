from fastapi import FastAPI
from api.xbrl_route import router as xbrl_router
from api.xml_route import router as xml_router
from api.html_route import router as html_router
from api.xbrl_finder import router as inter_router

app = FastAPI(title="Financial Data Extractor API")

# Include routers
app.include_router(xbrl_router, prefix="/api", tags=["xbrl"])
app.include_router(xml_router, prefix="/api", tags=["xml"])
app.include_router(html_router, prefix="/api", tags=["html"])
app.include_router(inter_router, prefix="/api", tags=["inter"])

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host='0.0.0.0',#nosec B104
        port=8001,
        reload=False,
    )