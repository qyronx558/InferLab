"""Export schema-only OpenAPI and validate synthetic fixtures without starting services."""

import argparse
import json
from pathlib import Path

from inferlab_api.contracts import ContractCatalog, validate_submission

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "contracts/openapi.json"
FIXTURE = ROOT / "contracts/fixtures/demo.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    schema = ContractCatalog.model_json_schema(ref_template="#/components/schemas/{model}")
    definitions = schema.pop("$defs")
    definitions["ContractCatalog"] = schema
    document = {
        "openapi": "3.1.0",
        "info": {
            "title": "InferLab wire contracts",
            "version": "1.0.0",
            "description": "Schema-only contract catalog; paths are intentionally empty. "
            "This does not expose or implement an API.",
        },
        "paths": {},
        "components": {"schemas": definitions},
    }
    content = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != content:
            raise SystemExit("OpenAPI drift: run npm run contracts:generate")
    else:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(content, encoding="utf-8", newline="\n")
    fixture = ContractCatalog.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    if fixture.registry.state != "complete":
        raise SystemExit("Demo fixture must include its registry")
    validate_submission(fixture.submit_request, fixture.registry.data)
    print("Pydantic contracts and synthetic wire fixtures validated.")


if __name__ == "__main__":
    main()
