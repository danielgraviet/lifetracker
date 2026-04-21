from fastapi import FastAPI

app = FastAPI(title="LifeTracker API", version="0.1.0")


@app.get("/health")
async def health():
    return {"status": "ok"}


# Routes will be added in Phase 3
# from api.routes import entries, tags, analytics, weekly_summary
# app.include_router(entries.router)
# app.include_router(tags.router)
# app.include_router(analytics.router)
# app.include_router(weekly_summary.router)
