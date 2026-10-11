# domain

Pure domain layer: aggregates, value objects, ports, and events. **Imports only `app.shared` and stdlib** — no FastAPI, SQLAlchemy, GDAL, or provider SDKs (enforced by import-linter). Fully unit-testable without infrastructure.
