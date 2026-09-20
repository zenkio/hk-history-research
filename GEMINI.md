# Hong Kong History Research Project - Instructions

## Model Strategy
To optimize for performance and quota:
1. **Development/Coding Agent:** Use Pro-class models (e.g., `gemini-pro`) for complex reasoning, refactoring, and debugging.
2. **Research Pipeline (Cron):** Use Flash-class models (e.g., `gemini-3.5-flash`) for high-throughput automated tasks like summarization and categorization.

## Automation & Pipeline Configuration
- **Frequency:** The pipeline runs every 3 hours via `cron` to stay within the free-tier API quota (20 requests/day).
- **Batch Size:** The pipeline processes exactly 1 file per execution to ensure reliability and minimize rate-limit failures.
- **Error Handling:** The pipeline implements exponential backoff and structured JSON outputs for reliable data ingestion.
- **Git Strategy:** Automated commits and pushes to `origin/main` happen locally and are pushed automatically.
