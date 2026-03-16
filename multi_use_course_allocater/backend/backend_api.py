import io
import json
from typing import Any

import pandas as pd
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field

from allocate import _preference_order, run_allocation


class AllocationConfig(BaseModel):
    xWeight: float = Field(ge=0, le=1)
    sectionSkillLimit: int = Field(ge=1)
    sectionSlot: dict[str, str]
    skillCapacity: dict[str, int] | None = None
    defaultSkillCapacity: int | None = Field(default=None, ge=1)


class InspectResponse(BaseModel):
    skills: list[str]
    sections: list[str]
    preferenceColumns: list[str]


class ExportPayload(BaseModel):
    rows: list[dict[str, Any]]
    filename: str = "export.xlsx"


app = FastAPI(title="Life Skill Allocation API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _detect_from_dataframe(df: pd.DataFrame) -> InspectResponse:
    meta_keys = {"student", "name", "reg", "registration", "cgpa", "section", "attendance"}
    pref_keywords = ("row", "pref", "preference", "choice", "option", "skill")

    pref_cols = sorted(
        [c for c in df.columns if any(k in str(c).lower() for k in pref_keywords)],
        key=_preference_order,
    )

    if not pref_cols:
        for col in df.columns:
            cl = str(col).lower()
            if any(k in cl for k in meta_keys):
                continue
            if df[col].dtype == object:
                pref_cols.append(col)
        pref_cols = sorted(pref_cols, key=_preference_order)

    if not pref_cols:
        raise ValueError("No preference columns found in Excel upload.")

    skills: set[str] = set()
    for col in pref_cols:
        series = df[col].dropna().astype(str).str.strip()
        for val in series:
            if not val or val.lower() in {"nan", "none", "na", "n/a", "-"}:
                continue
            skills.add(val)

    section_col = next((c for c in df.columns if "section" in str(c).lower()), None)
    sections: list[str] = []
    if section_col is not None:
        series = pd.to_numeric(df[section_col], errors="coerce").dropna()
        if len(series):
            sections = sorted(series.astype(int).astype(str).unique().tolist())
        else:
            raw = df[section_col].dropna().astype(str).str.strip()
            if len(raw):
                sections = sorted(raw.unique().tolist())

    return InspectResponse(
        skills=sorted(skills),
        sections=sections,
        preferenceColumns=[str(c) for c in pref_cols],
    )


@app.post("/export")
async def export_excel(payload: ExportPayload) -> Response:
    try:
        df = pd.DataFrame(payload.rows)
        buf = io.BytesIO()
        df.to_excel(buf, index=False, engine="openpyxl")
        buf.seek(0)
        safe_name = payload.filename.replace('"', "")
        return Response(
            content=buf.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Export failed: {exc}") from exc


@app.post("/inspect-excel", response_model=InspectResponse)
async def inspect_excel(file: UploadFile = File(...)) -> InspectResponse:
    try:
        file_bytes = await file.read()
        dataframe = pd.read_excel(io.BytesIO(file_bytes))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid Excel upload: {exc}") from exc

    try:
        return _detect_from_dataframe(dataframe)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/run-allocation")
async def run_allocation_endpoint(
    file: UploadFile = File(...),
    config: str = Form(...),
) -> dict[str, Any]:
    try:
        try:
            parsed_config = AllocationConfig.model_validate_json(config)
        except AttributeError:
            parsed_config = AllocationConfig.parse_raw(config)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid config payload: {exc}") from exc

    try:
        file_bytes = await file.read()
        dataframe = pd.read_excel(io.BytesIO(file_bytes))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid Excel upload: {exc}") from exc

    try:
        config_payload = (
            parsed_config.model_dump()
            if hasattr(parsed_config, "model_dump")
            else parsed_config.dict()
        )
        return run_allocation(dataframe, config_payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Allocation failed: {exc}") from exc


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend_api:app", host="0.0.0.0", port=8000, reload=True)
