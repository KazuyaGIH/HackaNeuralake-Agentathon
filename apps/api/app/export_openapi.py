"""Exporta o schema OpenAPI (mesma fonte dos contratos Pydantic) para gerar tipos do frontend.

Uso: python -m app.export_openapi [caminho]  (default: apps/api/openapi.json)
"""

import json
import sys
from pathlib import Path

from app.config import API_DIR, Settings
from app.main import create_app


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else API_DIR / "openapi.json"
    app = create_app(Settings(_env_file=None))
    out.write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OpenAPI exportado para {out}")


if __name__ == "__main__":
    main()
