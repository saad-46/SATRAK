# apps/ai (placeholder)

**AI/ML workspace** — model code, training pipelines, evaluation harnesses, and
served inference for the detection pipeline (TDD §5; Blueprint §4).

Separated from `services/` because model artifacts, training data, and
notebook-driven work have a fundamentally different lifecycle from API services
(versioned in a model registry, released independently of API deploys, owned by
the ML team).

**Planned structure**

```
apps/ai/
├── models/          # building-detection, change-detection, road-detection, risk-scoring, llm-assistant
├── training/        # training scripts, experiment configs (Hydra)
├── evaluation/      # region-stratified benchmark runners (release gate)
└── serving/         # KServe/Ray Serve wrappers behind ai-orchestration-service
```

**Planned stack:** Python 3.12 · PyTorch · torchgeo · MMSegmentation · XGBoost/LightGBM · ONNX · KServe.

No implementation yet — reserved boundary. The `ai-orchestration-service` (the thin
API/queue consumer that calls these models) will live under `services/` when built.
Domain work begins in the AI Detection Pipeline epic.
