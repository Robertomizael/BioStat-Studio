import json
import sys
from pathlib import Path

import pandas as pd
import pyreadstat


def clean_value(value):
    if pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return value


def read_dataset(filename):
    ext = Path(filename).suffix.lower()
    if ext in {".sav", ".zsav"}:
        frame, meta = pyreadstat.read_sav(filename, apply_value_formats=False, formats_as_category=False)
    elif ext == ".por":
        frame, meta = pyreadstat.read_por(filename, apply_value_formats=False, formats_as_category=False)
    elif ext == ".dta":
        frame, meta = pyreadstat.read_dta(filename, apply_value_formats=False, formats_as_category=False)
    elif ext == ".sas7bdat":
        frame, meta = pyreadstat.read_sas7bdat(filename, apply_value_formats=False, formats_as_category=False)
    elif ext == ".xpt":
        frame, meta = pyreadstat.read_xport(filename, apply_value_formats=False, formats_as_category=False)
    else:
        raise ValueError(f"Formato no compatible: {ext}")

    frame.columns = [str(c).strip() for c in frame.columns]
    records = [{str(k): clean_value(v) for k, v in row.items()} for row in frame.to_dict(orient="records")]
    labels = getattr(meta, "column_names_to_labels", {}) or {}
    value_labels = getattr(meta, "variable_value_labels", {}) or {}
    measure_levels = getattr(meta, "variable_measure", {}) or {}
    variables = []
    for name in frame.columns:
        series = frame[name]
        numeric = pd.api.types.is_numeric_dtype(series)
        variables.append({
            "name": name,
            "type": "numeric" if numeric else "string",
            "decimals": 2 if numeric else 0,
            "label": labels.get(name) or "",
            "missing": "Ninguno",
            "level": {"scale": "Escala", "ordinal": "Ordinal", "nominal": "Nominal"}.get(str(measure_levels.get(name, "")).lower()) or ("Escala" if numeric else "Nominal"),
            "role": "Entrada",
            "unique": int(series.nunique(dropna=True)),
            "values": {str(k): str(v) for k, v in (value_labels.get(name) or {}).items()},
        })
    return {"name": Path(filename).stem, "rows": records, "variables": variables}


if __name__ == "__main__":
    try:
        if len(sys.argv) != 3 or sys.argv[1] != "import":
            raise ValueError("Uso: biostat-importer import <archivo>")
        print(json.dumps(read_dataset(sys.argv[2]), ensure_ascii=False, separators=(",", ":")))
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
