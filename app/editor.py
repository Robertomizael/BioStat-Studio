from __future__ import annotations

import math
import uuid
from typing import Any

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.main import DATASETS, clean, schema

router = APIRouter(prefix="/api/editor", tags=["editor"])
VARIABLE_META: dict[str, list[dict[str, Any]]] = {}


class NewDatasetRequest(BaseModel):
    name: str = "Datos sin título"
    rows: int = Field(default=30, ge=1, le=10000)
    columns: int = Field(default=5, ge=1, le=500)


class SaveDatasetRequest(BaseModel):
    dataset_id: str
    name: str = "Datos sin título"
    variables: list[dict[str, Any]]
    data: list[dict[str, Any]]


def default_meta(columns: list[str]) -> list[dict[str, Any]]:
    return [{
        "name": c,
        "label": c,
        "type": "Numérica",
        "width": 8,
        "decimals": 2,
        "values": "",
        "missing_values": "",
        "level": "Escala",
        "role": "Entrada",
    } for c in columns]


def normalized_name(value: Any, index: int, used: set[str]) -> str:
    raw = str(value or f"VAR{index + 1:03d}").strip().replace(" ", "_")
    raw = "".join(ch for ch in raw if ch.isalnum() or ch == "_") or f"VAR{index + 1:03d}"
    if raw[0].isdigit():
        raw = f"V_{raw}"
    candidate, suffix = raw, 2
    while candidate in used:
        candidate = f"{raw}_{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def build_dataframe(variables: list[dict[str, Any]], records: list[dict[str, Any]]) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    used: set[str] = set()
    metas: list[dict[str, Any]] = []
    original_names: list[str] = []
    for i, item in enumerate(variables):
        original = str(item.get("name") or f"VAR{i + 1:03d}")
        name = normalized_name(original, i, used)
        original_names.append(original)
        typ = str(item.get("type", "Numérica"))
        metas.append({
            "name": name,
            "label": str(item.get("label") or name),
            "type": typ,
            "width": int(item.get("width") or 8),
            "decimals": int(item.get("decimals") or 0),
            "values": str(item.get("values") or ""),
            "missing_values": str(item.get("missing_values") or ""),
            "level": str(item.get("level") or ("Escala" if typ == "Numérica" else "Nominal")),
            "role": str(item.get("role") or "Entrada"),
        })
    rows: list[dict[str, Any]] = []
    for record in records:
        row: dict[str, Any] = {}
        for old, meta in zip(original_names, metas):
            value = record.get(old, record.get(meta["name"], None))
            if value == "":
                value = None
            row[meta["name"]] = value
        rows.append(row)
    df = pd.DataFrame(rows, columns=[m["name"] for m in metas])
    for meta in metas:
        c = meta["name"]
        if meta["type"] == "Numérica":
            df[c] = pd.to_numeric(df[c], errors="coerce")
        elif meta["type"] == "Fecha":
            df[c] = pd.to_datetime(df[c], errors="coerce")
        else:
            df[c] = df[c].where(df[c].notna(), None)
    return df, metas


@router.post("/new")
def new_dataset(req: NewDatasetRequest) -> dict[str, Any]:
    columns = [f"VAR{i + 1:03d}" for i in range(req.columns)]
    df = pd.DataFrame([{c: None for c in columns} for _ in range(req.rows)])
    dataset_id = str(uuid.uuid4())
    DATASETS[dataset_id] = df
    metas = default_meta(columns)
    VARIABLE_META[dataset_id] = metas
    return clean({
        "dataset_id": dataset_id,
        "name": req.name,
        "rows": len(df),
        "columns": len(df.columns),
        "variables": metas,
        "preview": df.to_dict(orient="records"),
    })


@router.post("/save")
def save_dataset(req: SaveDatasetRequest) -> dict[str, Any]:
    if not req.variables:
        raise HTTPException(400, "Defina al menos una variable.")
    df, metas = build_dataframe(req.variables, req.data)
    DATASETS[req.dataset_id] = df
    VARIABLE_META[req.dataset_id] = metas
    return clean({
        "dataset_id": req.dataset_id,
        "name": req.name,
        "rows": len(df),
        "columns": len(df.columns),
        "variables": metas,
        "preview": df.head(1000).to_dict(orient="records"),
        "message": "Cambios guardados correctamente.",
    })


@router.get("/{dataset_id}")
def get_editor_dataset(dataset_id: str) -> dict[str, Any]:
    if dataset_id not in DATASETS:
        raise HTTPException(404, "Base no encontrada.")
    df = DATASETS[dataset_id]
    metas = VARIABLE_META.get(dataset_id)
    if metas is None:
        metas = []
        for item in schema(df):
            metas.append({
                "name": item["name"], "label": item.get("label", item["name"]),
                "type": item.get("type", "Numérica"), "width": 8,
                "decimals": item.get("decimals", 2), "values": "",
                "missing_values": "", "level": item.get("level", "Escala"),
                "role": item.get("role", "Entrada")
            })
        VARIABLE_META[dataset_id] = metas
    return clean({
        "dataset_id": dataset_id,
        "rows": len(df),
        "columns": len(df.columns),
        "variables": metas,
        "preview": df.head(1000).to_dict(orient="records"),
    })
