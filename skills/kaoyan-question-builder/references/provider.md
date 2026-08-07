# Vision Provider Configuration

The provider adapter targets OpenAI-compatible /chat/completions APIs. The local server captures all provider settings from environment variables when it starts; browser requests cannot override the base URL, model, or key variable name.

| Setting | Environment variable | Default |
| --- | --- | --- |
| Base URL | KAOYAN_VISION_BASE_URL | https://api.openai.com/v1 |
| Model | KAOYAN_VISION_MODEL | gpt-4.1-mini |
| Key variable name | KAOYAN_VISION_API_KEY_ENV | OPENAI_API_KEY |
| Timeout seconds | KAOYAN_VISION_TIMEOUT | 90 |
| Retry count | KAOYAN_VISION_RETRIES | 2 |
| Images per request | KAOYAN_VISION_BATCH_LIMIT | 4 |
| High-resolution images | KAOYAN_VISION_HIGH_RES | true |

Set the API key itself in the named environment variable. Never write it to .env, JSON, source code, examples, frontend storage, project files, or logs. The UI may display only whether the named variable is available.
Restart the local server after changing any provider setting. This binds the selected key variable to the configured endpoint for that server process and prevents a browser request from redirecting an environment secret.


If the provider rejects JSON mode, is unavailable, or returns invalid JSON, keep the candidate unchanged and use the manual review form. Do not downgrade silently to guessed text.
