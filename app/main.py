from __future__ import annotations

import io
import math
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from scipy import stats

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DATASETS: dict[str, pd.DataFrame] = {}

app = FastAPI(title="BioStat Studio", version="0.3.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clean(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not math.isfinite(float(value)) else float(value)
    if value is None or pd.isna(value):
        return None
    return value


def read_upload(filename: str, content: bytes) -> pd.DataFrame:
    suffix = Path(filename).suffix.lower()
    try:
        if suffix == ".csv":
            try:
                df = pd.read_csv(io.BytesIO(content))
            except UnicodeDecodeError:
                df = pd.read_csv(io.BytesIO(content), encoding="latin-1")
        elif suffix in {".xlsx", ".xls"}:
            df = pd.read_excel(io.BytesIO(content))
        elif suffix in {".sav", ".zsav", ".por"}:
            import pyreadstat
            if suffix == ".por":
                df, _ = pyreadstat.read_por(io.BytesIO(content))
            else:
                df, _ = pyreadstat.read_sav(io.BytesIO(content), apply_value_formats=False)
        elif suffix == ".dta":
            df = pd.read_stata(io.BytesIO(content), convert_categoricals=False)
        elif suffix == ".sas7bdat":
            df = pd.read_sas(io.BytesIO(content), format="sas7bdat")
        else:
            raise HTTPException(415, "Formato no compatible. Use CSV, Excel, SPSS, Stata o SAS.")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, f"No fue posible abrir el archivo: {exc}") from exc
    if df.empty:
        raise HTTPException(400, "El archivo no contiene registros.")
    df.columns = [str(c).strip() or f"variable_{i+1}" for i, c in enumerate(df.columns)]
    return df


def get_df(dataset_id: str) -> pd.DataFrame:
    if dataset_id not in DATASETS:
        raise HTTPException(404, "La base ya no está disponible. Vuelva a importarla.")
    return DATASETS[dataset_id]


def schema(df: pd.DataFrame) -> list[dict[str, Any]]:
    output = []
    for col in df.columns:
        s = df[col]
        numeric = pd.api.types.is_numeric_dtype(s)
        output.append({
            "name": col,
            "type": "Numérica" if numeric else "Texto",
            "level": "Escala" if numeric and s.nunique(dropna=True) > 10 else "Nominal/ordinal",
            "missing": int(s.isna().sum()),
            "unique": int(s.nunique(dropna=True)),
        })
    return output


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.3.0"}


@app.post("/api/import")
async def import_data(file: UploadFile = File(...)) -> dict[str, Any]:
    df = read_upload(file.filename or "datos.csv", await file.read())
    dataset_id = str(uuid.uuid4())
    DATASETS[dataset_id] = df
    return clean({
        "dataset_id": dataset_id,
        "name": file.filename,
        "rows": len(df),
        "columns": len(df.columns),
        "variables": schema(df),
        "preview": df.head(100).replace({np.nan: None}).to_dict(orient="records"),
    })


class ColumnsRequest(BaseModel):
    dataset_id: str
    columns: list[str]


class FrequencyRequest(BaseModel):
    dataset_id: str
    column: str


class CorrelationRequest(BaseModel):
    dataset_id: str
    columns: list[str]
    method: str = "pearson"


class TTestRequest(BaseModel):
    dataset_id: str
    outcome: str
    group: str


@app.post("/api/descriptives")
def descriptives(req: ColumnsRequest) -> dict[str, Any]:
    df = get_df(req.dataset_id)
    rows = []
    for col in req.columns:
        if col not in df.columns:
            continue
        s = pd.to_numeric(df[col], errors="coerce").dropna()
        if s.empty:
            continue
        rows.append({
            "Variable": col,
            "n": len(s),
            "Media": s.mean(),
            "DE": s.std(ddof=1),
            "Mediana": s.median(),
            "Mínimo": s.min(),
            "Máximo": s.max(),
            "Asimetría": stats.skew(s, bias=False) if len(s) > 2 else np.nan,
        })
    return clean({"analysis": "Estadística descriptiva", "rows": rows})


@app.post("/api/frequencies")
def frequencies(req: FrequencyRequest) -> dict[str, Any]:
    df = get_df(req.dataset_id)
    if req.column not in df.columns:
        raise HTTPException(400, "Variable no encontrada.")
    s = df[req.column].fillna("(Perdido)").astype(str)
    counts = s.value_counts(dropna=False)
    rows = [{"Categoría": k, "Frecuencia": int(v), "Porcentaje": v / len(s) * 100} for k, v in counts.items()]
    return clean({"analysis": f"Frecuencias: {req.column}", "rows": rows})


@app.post("/api/correlation")
def correlation(req: CorrelationRequest) -> dict[str, Any]:
    df = get_df(req.dataset_id)
    cols = [c for c in req.columns if c in df.columns]
    if len(cols) < 2:
        raise HTTPException(400, "Seleccione al menos dos variables numéricas.")
    numeric = df[cols].apply(pd.to_numeric, errors="coerce")
    method = req.method if req.method in {"pearson", "spearman", "kendall"} else "pearson"
    matrix = numeric.corr(method=method)
    return clean({"analysis": f"Correlación {method.title()}", "columns": cols, "matrix": matrix.values.tolist()})


@app.post("/api/ttest")
def ttest(req: TTestRequest) -> dict[str, Any]:
    df = get_df(req.dataset_id)
    if req.outcome not in df.columns or req.group not in df.columns:
        raise HTTPException(400, "Variable no encontrada.")
    groups = df[req.group].dropna().unique().tolist()
    if len(groups) != 2:
        raise HTTPException(400, "La variable de grupo debe tener exactamente dos categorías.")
    a = pd.to_numeric(df.loc[df[req.group] == groups[0], req.outcome], errors="coerce").dropna()
    b = pd.to_numeric(df.loc[df[req.group] == groups[1], req.outcome], errors="coerce").dropna()
    if len(a) < 2 or len(b) < 2:
        raise HTTPException(400, "Cada grupo debe tener al menos dos datos válidos.")
    lev_stat, lev_p = stats.levene(a, b, center="median")
    equal_var = bool(lev_p >= 0.05)
    t_stat, p_value = stats.ttest_ind(a, b, equal_var=equal_var)
    pooled = np.sqrt(((len(a)-1)*a.var(ddof=1)+(len(b)-1)*b.var(ddof=1))/(len(a)+len(b)-2))
    d = (a.mean()-b.mean())/pooled if pooled else np.nan
    return clean({
        "analysis": "Prueba t para muestras independientes",
        "rows": [{
            "Grupo 1": str(groups[0]), "n1": len(a), "Media 1": a.mean(),
            "Grupo 2": str(groups[1]), "n2": len(b), "Media 2": b.mean(),
            "t": t_stat, "p": p_value, "Levene p": lev_p, "d de Cohen": d,
        }],
    })


@app.get("/api/export/{dataset_id}.csv")
def export_csv(dataset_id: str) -> StreamingResponse:
    df = get_df(dataset_id)
    data = df.to_csv(index=False).encode("utf-8-sig")
    return StreamingResponse(io.BytesIO(data), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=BioStat_datos.csv"})
