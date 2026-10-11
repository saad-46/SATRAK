# application/jobs

Framework-independent background processing for the EO pipeline: `JobRunner` (chaining +
retries + failure handling), `JobTracker` (progress/status reporting), and the default
handlers adapting each pipeline service to a job. All execution flows through the shared
`TaskQueue` port — **no Celery here**; the Celery adapter lives in `infrastructure/jobs`
(ADR-0008) and only calls `JobRunner.execute`.
