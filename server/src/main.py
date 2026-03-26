from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import sys
import os

# Add the src directory to Python path for absolute imports
sys.path.insert(0, os.path.dirname(__file__))

from api.xbrl_route import router as xbrl_router
from api.xml_route import router as xml_router
from api.html_route import router as html_router
from api.xbrl_finder import router as inter_router
from api.analysis_route import router as analysis_router
from api.batch_xbrl_finder import router as batch_inter_router
from api.xbrl_ws_route import router as xbrl_ws_router
from api.xbrl_ws_hist import router as xbrl_ws_hist_router
from api.Xbrl_annual_extractor import router as xbrl_annual_router
from api.llm_route import router as llm_router
from api.companies_route import router as companies_router
from api.company_route import router as company_router


load_dotenv()

app = FastAPI(title="Financial Data Extractor API")

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(xbrl_router, prefix="/api", tags=["xbrl"])
app.include_router(xml_router, prefix="/api", tags=["xml"])
app.include_router(html_router, prefix="/api", tags=["html"])
app.include_router(inter_router, prefix="/api", tags=["inter"])
app.include_router(batch_inter_router, prefix="/api", tags=["batch_inter"])
app.include_router(analysis_router, prefix="/api", tags=["analysis"])
app.include_router(xbrl_ws_router, prefix="/api", tags=["xbrl_ws"])
app.include_router(xbrl_ws_hist_router, prefix="/api", tags=["xbrl_ws_hist"])
app.include_router(xbrl_annual_router, prefix="/api", tags=["xbrl_annual"])
app.include_router(llm_router, prefix="/api", tags=["llm"])
app.include_router(companies_router, prefix="/api", tags=["companies"])
app.include_router(company_router, prefix="/api", tags=["company"])

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host='0.0.0.0',#nosec B104
        port=8001,
        reload=False,
    )