from pathlib import Path
from typing import Any
import joblib

BASE_DIR = Path(__file__).resolve().parents[2]
MODELS_DIR = BASE_DIR / "trained_models" / "companies"
MODEL_FILENAME = "customer_repurchase.joblib"


def _safe_company_id(company_id: str) -> str:
    value = str(company_id or "").strip()
    if not value or not value.replace("-", "").isalnum():
        raise ValueError("company_id inválido.")
    return value


def get_company_model_path(company_id: str) -> Path:
    return MODELS_DIR / _safe_company_id(company_id) / MODEL_FILENAME


def model_exists(company_id: str) -> bool:
    return get_company_model_path(company_id).exists()


def save_model(company_id: str, package: dict[str, Any]) -> Path:
    path = get_company_model_path(company_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(package, path)
    return path


def load_model(company_id: str) -> dict[str, Any]:
    path = get_company_model_path(company_id)
    if not path.exists():
        raise FileNotFoundError("La empresa todavía no tiene un modelo entrenado.")
    package = joblib.load(path)
    if not isinstance(package, dict) or "model" not in package:
        raise ValueError("El archivo del modelo no tiene un formato válido.")
    return package
