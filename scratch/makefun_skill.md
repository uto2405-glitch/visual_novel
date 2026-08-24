# MakeFun AI Public API Reference

Provides guidance on MakeFun AI's public REST APIs for third-party developers and AI agents.

## Authentication
Use `Authorization: Bearer <API_TOKEN>` for all requests.
- Base URL: https://video.a2e.ai
- OpenAPI JSON: https://video.a2e.ai/dev/openapi-spec
- Full Documentation: https://video.a2e.ai/dev

## AI Quickstart
1. Before asking the user to create an API token, first read `${XDG_CONFIG_HOME:-$HOME/.config}/media-generation/credentials.json` on Unix or `%APPDATA%\media-generation\credentials.json` on Windows. Reuse `access_token` only when the file's `base_url` exactly matches `https://video.a2e.ai`. If no matching saved token exists, ask the user to create one in `Account > API Token`; after they provide it, keep it secret and save `{"base_url":"https://video.a2e.ai","access_token":"<API_TOKEN>","token_type":"Bearer"}` to that same file for future requests.
2. Load the machine-readable OpenAPI spec from `https://video.a2e.ai/dev/openapi-spec`.
3. Use the endpoint catalog below to choose the correct media workflow.

## API Catalog

### Image & Video Generation
#### Image to Video

##### POST /api/v1/userImage2Video/start — Start image to video conversion
Convert an image to video using AI generation with custom prompts. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `image_url`. - API-token callers may include `webhook_url` and `webhook_token` for best-effort terminal-state notifications; ordinary JWT/cookie calls ignore these fields. ### Behavior - This is an asynchronous operation: a successful submission creates a task and returns before processing finishes. - Persist the returned task identifier and use the corresponding detail or list operation to observe progress. - Treat the detail endpoint as the source of truth even when webhook delivery is enabled. ### Response - A `200` response confirms task acceptance; it does not by itself mean media generation has completed. - Retain the returned identifier and wait for a documented terminal status before using output URLs. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid parameters. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userImage2Video/allRecords` — List image to video tasks. - `POST /api/v1/userImage2Video/{_id}/markShared` — markShared. - `POST /api/v1/userImage2Video/{_id}/markDownloaded` — markDownloaded. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1UserImage2VideoStart`
- JSON body fields:
  - `name` (body, optional; string; example: `My Image Animation`) — Name of the image to video task
  - `image_url` (body, required; string; example: `https://example.com/image.jpg`) — URL of the source image
  - `prompt` (body, optional; string; example: `Make the person in the image wave their hand`) — Generation prompt
  - `negative_prompt` (body, optional; string; example: `blurry, distorted, static`) — Negative prompt to avoid unwanted features
  - `lora` (body, optional; string) — Lora ID. If provided, prompt/negative_prompt can be omitted (prompt will be overwritten by lora preset on backend).
  - `model_type` (body, optional; string; allowed: `GENERAL`, `FLF2V`; default: `GENERAL`) — Model type for generation
  - `model_version` (body, optional; string; allowed: `a2e`, `a2e-v2`, `a2e-v2-flash`) — Algorithm model version. When omitted, Ultra users default to a2e-v2 and other roles default to a2e. a2e-v2 costs more per second; a2e-v2-flash uses a2e pricing. V2 models are not covered by plan waivers and ignore auto_add_audio because they generate audio by themselves.
  - `end_image_url` (body, optional; string; example: `https://example.com/end_image.jpg`) — End image URL (required for FLF2V model)
  - `extend_prompt` (body, optional; boolean; default: `true`) — Whether to extend the prompt automatically
  - `number_of_images` (body, optional; integer; default: `1`; min: 1; max: 8; example: `1`) — Number of videos to generate at once
  - `video_time` (body, optional; integer; default: `5`; min: 5; max: 20; example: `5`) — Video time in seconds (5, 10, 15, or 20 seconds)
  - `video_length` (body, optional; integer; min: 1; max: 1000; example: `81`) — (Deprecated) Video length in frames. Prefer video_time. Backend converts frames to seconds internally.
  - `skip_face_enhance` (body, optional; boolean; default: `false`) — Whether to skip face similarity enhancement. Defaults to false (enhancing face similarity).
  - `mask_face` (body, optional; boolean) — Web NSFW preflight result. Set true only after the user confirms masking a detected human face.
  - `minor_suspected_skip` (body, optional; boolean; default: `false`) — If suspected minor is detected (10 <= age < 15), set to true to acknowledge and proceed
  - `webhook_url` (body, optional; string; max length: 2048; example: `https://your-server.example.com/a2e/webhook`) — HTTPS URL to receive task.completed / task.failed notifications. Best-effort delivery, single attempt, no retries; clients should treat the detail API as the source of truth.
  - `webhook_token` (body, optional; string; max length: 256; example: `a-shared-secret`) — Optional plaintext token returned in the X-A2e-Webhook-Token header so receivers can verify the request originated from a2e.
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/userImage2Video/start" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "name": "My Image Animation",
  "image_url": "https://example.com/image.jpg",
  "prompt": "Make the person in the image wave their hand",
  "negative_prompt": "blurry, distorted, static",
  "model_type": "GENERAL",
  "end_image_url": "https://example.com/end_image.jpg",
  "extend_prompt": true,
  "number_of_images": 1,
  "video_time": 5,
  "video_length": 81,
  "skip_face_enhance": false,
  "minor_suspected_skip": false,
  "webhook_url": "https://your-server.example.com/a2e/webhook",
  "webhook_token": "a-shared-secret"
}
JSON
```
- Responses:
  - `200` — Image to video task started successfully
  - `400` — Bad Request - Invalid parameters
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/userImage2Video/allRecords — List image to video tasks
List current user's image to video tasks (only non-expired records will be returned). ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supported query parameters: `pageNum`, `pageSize`. Omitted values use the defaults shown in the parameter schema. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid parameters. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `POST /api/v1/userImage2Video/{_id}/markShared` — markShared. - `POST /api/v1/userImage2Video/{_id}/markDownloaded` — markDownloaded. - `POST /api/v1/userImage2Video/{_id}/markCopied` — markCopied. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1UserImage2VideoAllRecords`
- Request parameters:
  - `pageNum` (query, optional; integer; default: `1`; min: 1; example: `1`) — pageNum parameter
  - `pageSize` (query, optional; integer; default: `10`; min: 1; max: 100; example: `10`) — pageSize parameter
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/userImage2Video/allRecords?pageNum=1&pageSize=10" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task list fetched successfully
  - `400` — Bad Request - Invalid parameters
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/userImage2Video/batchDetail — Batch query task details
Query details for multiple tasks at once by providing an array of task IDs. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `ids`. ### Behavior - Fetches several task records in one request, reducing the number of individual detail calls. - Results remain subject to the same authentication and ownership checks as single-record lookups. - Match returned records by their identifiers instead of relying on response ordering. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userImage2Video/allRecords` — List image to video tasks. - `POST /api/v1/userImage2Video/{_id}/markShared` — markShared. - `POST /api/v1/userImage2Video/{_id}/markDownloaded` — markDownloaded. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1UserImage2VideoBatchDetail`
- JSON body fields:
  - `ids` (body, required; string[]; example: `["example"]`) — Array of task IDs to query
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/userImage2Video/batchDetail" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "ids": [
    "example"
  ]
}
JSON
```
- Responses:
  - `200` — Batch details retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/userImage2Video/avgProcessingTime — Get average processing time
avgProcessingTime. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - No request body or operation-specific parameters are required. ### Behavior - Retrieves the current server-side representation of the requested resource or task. - For asynchronous tasks, inspect the documented status and result fields before consuming generated media. - Repeat the request only as needed for polling and stop after the task reaches a terminal state. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userImage2Video/allRecords` — List image to video tasks. - `POST /api/v1/userImage2Video/{_id}/markShared` — markShared. - `POST /api/v1/userImage2Video/{_id}/markDownloaded` — markDownloaded. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1UserImage2VideoAvgProcessingTime`
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/userImage2Video/avgProcessingTime" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Successful response
  - `400` — Bad Request
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/userImage2Video/unlimitedQueueLevel — UnlimitedQueueLevel
unlimitedQueueLevel. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - No request body or operation-specific parameters are required. ### Behavior - Retrieves the current server-side representation of the requested resource or task. - For asynchronous tasks, inspect the documented status and result fields before consuming generated media. - Repeat the request only as needed for polling and stop after the task reaches a terminal state. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userImage2Video/allRecords` — List image to video tasks. - `POST /api/v1/userImage2Video/{_id}/markShared` — markShared. - `POST /api/v1/userImage2Video/{_id}/markDownloaded` — markDownloaded. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1UserImage2VideoUnlimitedQueueLevel`
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/userImage2Video/unlimitedQueueLevel" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Successful response
  - `400` — Bad Request
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/userImage2Video/{_id}/markShared — Mark record as shared
markShared. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Records the named client interaction for the identified task. - The operation does not regenerate or otherwise modify the task's media output. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userImage2Video/allRecords` — List image to video tasks. - `POST /api/v1/userImage2Video/{_id}/markDownloaded` — markDownloaded. - `POST /api/v1/userImage2Video/{_id}/markCopied` — markCopied. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1UserImage2VideoIdMarkShared`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — _id parameter
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/userImage2Video/507f1f77bcf86cd799439011/markShared" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Successful response
  - `400` — Bad Request
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/userImage2Video/{_id}/markDownloaded — Mark record as downloaded
markDownloaded. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Records the named client interaction for the identified task. - The operation does not regenerate or otherwise modify the task's media output. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userImage2Video/allRecords` — List image to video tasks. - `POST /api/v1/userImage2Video/{_id}/markShared` — markShared. - `POST /api/v1/userImage2Video/{_id}/markCopied` — markCopied. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1UserImage2VideoIdMarkDownloaded`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — _id parameter
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/userImage2Video/507f1f77bcf86cd799439011/markDownloaded" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Successful response
  - `400` — Bad Request
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/userImage2Video/{_id}/markCopied — Mark record as copied
markCopied. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Records the named client interaction for the identified task. - The operation does not regenerate or otherwise modify the task's media output. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userImage2Video/allRecords` — List image to video tasks. - `POST /api/v1/userImage2Video/{_id}/markShared` — markShared. - `POST /api/v1/userImage2Video/{_id}/markDownloaded` — markDownloaded. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1UserImage2VideoIdMarkCopied`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — _id parameter
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/userImage2Video/507f1f77bcf86cd799439011/markCopied" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Successful response
  - `400` — Bad Request
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/userImage2Video/{_id} — Get image to video task detail
Get one image to video task detail by id. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Retrieves the current server-side representation of the requested resource or task. - For asynchronous tasks, inspect the documented status and result fields before consuming generated media. - Repeat the request only as needed for polling and stop after the task reaches a terminal state. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid parameters. - `401` — Unauthorized - Invalid or missing JWT token. - `404` — Not Found - Task not found. ### Related Operations - `GET /api/v1/userImage2Video/allRecords` — List image to video tasks. - `POST /api/v1/userImage2Video/{_id}/markShared` — markShared. - `POST /api/v1/userImage2Video/{_id}/markDownloaded` — markDownloaded. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1UserImage2VideoId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — Task ID
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/userImage2Video/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task detail fetched successfully
  - `400` — Bad Request - Invalid parameters
  - `401` — Unauthorized - Invalid or missing JWT token
  - `404` — Not Found - Task not found

##### DELETE /api/v1/userImage2Video/{_id} — Delete an image to video task
Delete a user's image to video task. Only final status tasks can be deleted (initialized/completed/failed). initialized tasks will be refunded. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Deletes or marks the selected resource as deleted according to the endpoint's documented lifecycle rules. - Use the resource identifier from a list, creation, or detail response; deleting one resource does not affect unrelated records. - Do not assume an in-progress task can be cancelled unless the endpoint explicitly documents that behavior. ### Response - A `200` response confirms that the deletion request was applied to the selected record. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Task in processing or invalid parameters. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userImage2Video/allRecords` — List image to video tasks. - `POST /api/v1/userImage2Video/{_id}/markShared` — markShared. - `POST /api/v1/userImage2Video/{_id}/markDownloaded` — markDownloaded. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `deleteApiV1UserImage2VideoId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — Task ID
- Example request:
```bash
curl -X DELETE "https://video.a2e.ai/api/v1/userImage2Video/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task deleted successfully
  - `400` — Bad Request - Task in processing or invalid parameters
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/userImage2Video/prompt_extension — Extend prompt for image to video
Extend prompt and negative prompt with LLM for general image2video. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `reference_id`, `image_url`, `prompt`, `negative_prompt`. ### Behavior - Validates the submitted payload and performs the operation described by the request schema. - Conditional fields, mutually exclusive inputs, limits, and defaults are enforced as documented by their schemas. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid parameters. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userImage2Video/allRecords` — List image to video tasks. - `POST /api/v1/userImage2Video/{_id}/markShared` — markShared. - `POST /api/v1/userImage2Video/{_id}/markDownloaded` — markDownloaded. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1UserImage2VideoPromptExtension`
- JSON body fields:
  - `reference_id` (body, required; string; example: `507f1f77bcf86cd799439011`)
  - `image_url` (body, required; string; example: `https://example.com/image.jpg`)
  - `prompt` (body, required; string; example: `high quality, clear, cinematic`)
  - `negative_prompt` (body, required; string; example: `blurry, low quality, watermark, distorted`)
  - `lang` (body, optional; string; default: `en`; example: `en`)
  - `max_length` (body, optional; integer; example: `1`) — Optional hard character limit for generated prompts. This is not a target length.
  - `stream` (body, optional; boolean; example: `false`) — Set to true to return Server-Sent Events. Events include delta, result, done, and error.
  - `template` (body, optional; string; allowed: `default`, `cinematic`; default: `default`; example: `default`) — Prompt style. "default" keeps the original single-shot rewrite. "cinematic" returns a multi-shot film structure (scene bible, SHOT 1..N, Audio), intended for models that support cuts and audio.
  - `shot_count` (body, optional; integer; default: `2`; example: `2`) — Number of shots for the cinematic template. Any integer is accepted; the server clamps out-of-range values to 1-4. Ignored by the default template.
  - `with_audio` (body, optional; boolean; default: `true`; example: `true`) — Whether the cinematic template appends an Audio section. Ignored by the default template.
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/userImage2Video/prompt_extension" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "reference_id": "507f1f77bcf86cd799439011",
  "image_url": "https://example.com/image.jpg",
  "prompt": "high quality, clear, cinematic",
  "negative_prompt": "blurry, low quality, watermark, distorted",
  "lang": "en",
  "max_length": 1,
  "stream": false,
  "template": "default",
  "shot_count": 2,
  "with_audio": true
}
JSON
```
- Responses:
  - `200` — Prompt extended successfully
  - `400` — Bad Request - Invalid parameters
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/userImage2Video/flf2v_prompt_extension — Extend prompt for FLF2V image to video
Extend prompt and negative prompt with LLM for FLF2V (requires end_image_url). ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `reference_id`, `image_url`, `end_image_url`, `prompt`, `negative_prompt`. ### Behavior - Validates the submitted payload and performs the operation described by the request schema. - Conditional fields, mutually exclusive inputs, limits, and defaults are enforced as documented by their schemas. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid parameters. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userImage2Video/allRecords` — List image to video tasks. - `POST /api/v1/userImage2Video/{_id}/markShared` — markShared. - `POST /api/v1/userImage2Video/{_id}/markDownloaded` — markDownloaded. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1UserImage2VideoFlf2vPromptExtension`
- JSON body fields:
  - `reference_id` (body, required; string; example: `507f1f77bcf86cd799439011`)
  - `image_url` (body, required; string; example: `https://example.com/image.jpg`)
  - `end_image_url` (body, required; string; example: `https://example.com/image.jpg`)
  - `prompt` (body, required; string; example: `high quality, clear, cinematic`)
  - `negative_prompt` (body, required; string; example: `blurry, low quality, watermark, distorted`)
  - `lang` (body, optional; string; default: `en`; example: `en`)
  - `max_length` (body, optional; integer; example: `1`) — Optional hard character limit for generated prompts. This is not a target length.
  - `stream` (body, optional; boolean; example: `false`) — Set to true to return Server-Sent Events. Events include delta, result, done, and error.
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/userImage2Video/flf2v_prompt_extension" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "reference_id": "507f1f77bcf86cd799439011",
  "image_url": "https://example.com/image.jpg",
  "end_image_url": "https://example.com/image.jpg",
  "prompt": "high quality, clear, cinematic",
  "negative_prompt": "blurry, low quality, watermark, distorted",
  "lang": "en",
  "max_length": 1,
  "stream": false
}
JSON
```
- Responses:
  - `200` — Prompt extended successfully
  - `400` — Bad Request - Invalid parameters
  - `401` — Unauthorized - Invalid or missing JWT token
#### Text to Image

##### POST /api/v1/userText2Image/start — Start text to image generation
Create one or more asynchronous text-to-image tasks from the prompt and selected model settings, then return the records used to monitor generated images. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `prompt`. - API-token callers may include `webhook_url` and `webhook_token` for best-effort terminal-state notifications; ordinary JWT/cookie calls ignore these fields. ### Behavior - This is an asynchronous operation: a successful submission creates a task and returns before processing finishes. - Persist the returned task identifier and use the corresponding detail or list operation to observe progress. - Treat the detail endpoint as the source of truth even when webhook delivery is enabled. ### Response - A `200` response confirms task acceptance; it does not by itself mean media generation has completed. - Retain the returned identifier and wait for a documented terminal status before using output URLs. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid parameters. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userText2Image/allRecords` — Get all text to image records. - `GET /api/v1/userText2Image/{_id}` — Get text to image record detail. - `DELETE /api/v1/userText2Image/{_id}` — Delete task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1UserText2ImageStart`
- JSON body fields:
  - `name` (body, optional; string; example: `My Generated Image`) — Name of the text to image task (optional, auto-generated if not provided)
  - `prompt` (body, required; string; example: `A beautiful sunset over mountains`) — Text prompt for image generation
  - `width` (body, optional; number; default: `1024`; example: `1024`) — Image width
  - `height` (body, optional; number; default: `1024`; example: `1024`) — Image height
  - `model_type` (body, optional; string; allowed: `a2e`, `seedream`; default: `a2e`; example: `a2e`) — Model type to use for generation
  - `input_images` (body, optional; string[]; max items: 10; example: `["https://example.com/image1.jpg","https://example.com/image2.jpg"]`) — Reference images for A2E/Seedream model. A2E max 2 images; Seedream 5.0 Pro max 10 images.
  - `skip_face_enhance` (body, optional; boolean; default: `false`; example: `false`) — Whether to disable face similarity enhancement for A2E image edit. Defaults to false.
  - `aspect_ratio` (body, optional; string; allowed: `1:1`, `4:3`, `3:4`, `16:9`, `9:16`, `2:3`, `3:2`, `21:9`; example: `1:1`) — Aspect ratio for Seedream model
  - `max_images` (body, optional; integer; min: 1; max: 8; example: `1`) — Maximum number of images to generate (creates multiple tasks internally)
  - `webhook_url` (body, optional; string; max length: 2048; example: `https://your-server.example.com/a2e/webhook`) — HTTPS URL to receive task.completed / task.failed notifications. Best-effort delivery, single attempt, no retries; clients should treat the detail API as the source of truth.
  - `webhook_token` (body, optional; string; max length: 256; example: `a-shared-secret`) — Optional plaintext token returned in the X-A2e-Webhook-Token header so receivers can verify the request originated from a2e.
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/userText2Image/start" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "name": "My Generated Image",
  "prompt": "A beautiful sunset over mountains",
  "width": 1024,
  "height": 1024,
  "model_type": "a2e",
  "input_images": [
    "https://example.com/image1.jpg",
    "https://example.com/image2.jpg"
  ],
  "skip_face_enhance": false,
  "aspect_ratio": "1:1",
  "max_images": 1,
  "webhook_url": "https://your-server.example.com/a2e/webhook",
  "webhook_token": "a-shared-secret"
}
JSON
```
- Responses:
  - `200` — Text to image task started successfully
  - `400` — Bad Request - Invalid parameters
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/userText2Image/allRecords — Get all text to image records
Retrieve paginated list of all text to image generation records for the authenticated user. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supported query parameters: `pageNum`, `pageSize`. Omitted values use the defaults shown in the parameter schema. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized. ### Related Operations - `GET /api/v1/userText2Image/{_id}` — Get text to image record detail. - `DELETE /api/v1/userText2Image/{_id}` — Delete task. - `POST /api/v1/userText2Image/start` — Start text to image generation. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1UserText2ImageAllRecords`
- Request parameters:
  - `pageNum` (query, optional; integer; default: `1`; example: `1`) — Page number
  - `pageSize` (query, optional; integer; default: `10`; example: `10`) — Number of records per page
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/userText2Image/allRecords?pageNum=1&pageSize=10" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Records retrieved successfully
  - `401` — Unauthorized

##### POST /api/v1/userText2Image/batchDetail — Batch query task details
Query details for multiple tasks at once by providing an array of task IDs. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `ids`. ### Behavior - Fetches several task records in one request, reducing the number of individual detail calls. - Results remain subject to the same authentication and ownership checks as single-record lookups. - Match returned records by their identifiers instead of relying on response ordering. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userText2Image/allRecords` — Get all text to image records. - `GET /api/v1/userText2Image/{_id}` — Get text to image record detail. - `DELETE /api/v1/userText2Image/{_id}` — Delete task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1UserText2ImageBatchDetail`
- JSON body fields:
  - `ids` (body, required; string[]; example: `["example"]`) — Array of task IDs to query
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/userText2Image/batchDetail" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "ids": [
    "example"
  ]
}
JSON
```
- Responses:
  - `200` — Batch details retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/userText2Image/{_id} — Get text to image record detail
Retrieve detailed information of a specific text to image generation record. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Retrieves the current server-side representation of the requested resource or task. - For asynchronous tasks, inspect the documented status and result fields before consuming generated media. - Repeat the request only as needed for polling and stop after the task reaches a terminal state. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized. - `404` — Record not found. ### Related Operations - `GET /api/v1/userText2Image/allRecords` — Get all text to image records. - `DELETE /api/v1/userText2Image/{_id}` — Delete task. - `POST /api/v1/userText2Image/start` — Start text to image generation. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1UserText2ImageId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — Record ID
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/userText2Image/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Record detail retrieved successfully
  - `401` — Unauthorized
  - `404` — Record not found

##### DELETE /api/v1/userText2Image/{_id} — Delete task
Remove the authenticated user's text-to-image task identified by `_id` from the task history without affecting other generated-image records. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Deletes or marks the selected resource as deleted according to the endpoint's documented lifecycle rules. - Use the resource identifier from a list, creation, or detail response; deleting one resource does not affect unrelated records. - Do not assume an in-progress task can be cancelled unless the endpoint explicitly documents that behavior. ### Response - A `200` response confirms that the deletion request was applied to the selected record. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userText2Image/allRecords` — Get all text to image records. - `GET /api/v1/userText2Image/{_id}` — Get text to image record detail. - `POST /api/v1/userText2Image/start` — Start text to image generation. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `deleteApiV1UserText2ImageId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — Task ID to delete
- Example request:
```bash
curl -X DELETE "https://video.a2e.ai/api/v1/userText2Image/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task deleted successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/userText2Image/quickAddAvatar — Quick add avatar from generated image
Create a custom avatar directly from a text to image generation result. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `_id`. ### Behavior - Validates the submitted payload and performs the operation described by the request schema. - Conditional fields, mutually exclusive inputs, limits, and defaults are enforced as documented by their schemas. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad request. - `401` — Unauthorized. ### Related Operations - `GET /api/v1/userText2Image/allRecords` — Get all text to image records. - `GET /api/v1/userText2Image/{_id}` — Get text to image record detail. - `DELETE /api/v1/userText2Image/{_id}` — Delete task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1UserText2ImageQuickAddAvatar`
- JSON body fields:
  - `_id` (body, required; string; example: `507f1f77bcf86cd799439011`) — Text to image record ID
  - `gender` (body, optional; string; allowed: `female`, `male`; example: `female`) — Avatar gender
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/userText2Image/quickAddAvatar" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "_id": "507f1f77bcf86cd799439011",
  "gender": "female"
}
JSON
```
- Responses:
  - `200` — Avatar created successfully
  - `400` — Bad request
  - `401` — Unauthorized
#### Nano Banana

##### POST /api/v1/userNanoBanana/start — Start Nano Banana image generation
Generate images using Nano Banana models with advanced conversational capabilities and NSFW content pre-filtering. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `name`, `prompt`. - API-token callers may include `webhook_url` and `webhook_token` for best-effort terminal-state notifications; ordinary JWT/cookie calls ignore these fields. ### Behavior - This is an asynchronous operation: a successful submission creates a task and returns before processing finishes. - Persist the returned task identifier and use the corresponding detail or list operation to observe progress. - Treat the detail endpoint as the source of truth even when webhook delivery is enabled. ### Response - A `200` response confirms task acceptance; it does not by itself mean media generation has completed. - Retain the returned identifier and wait for a documented terminal status before using output URLs. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid parameters. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userNanoBanana/allRecords` — Get Nano Banana task list. - `GET /api/v1/userNanoBanana/detail/{id}` — Get task details. - `DELETE /api/v1/userNanoBanana/delete/{id}` — Delete task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1UserNanoBananaStart`
- JSON body fields:
  - `name` (body, required; string; example: `Beautiful Landscape`) — Name of the image generation task
  - `prompt` (body, required; string; example: `A serene mountain landscape at sunset with a crystal clear lake`) — Text prompt for image generation
  - `model` (body, optional; string; allowed: `nano-banana`, `nano-banana-pro`, `nano-banana-2`, `nano-banana-2-lite`; default: `nano-banana-pro`; example: `nano-banana-pro`) — Model to use for generation. Options: nano-banana (no resolution control, auto edit mode with images), nano-banana-pro (with resolution control), nano-banana-2 (with resolution control), nano-banana-2-lite (1K only)
  - `input_images` (body, optional; string[]; example: `["https://example.com/image1.jpg"]`) — Array of input image URLs (for editing and composition modes)
  - `aspect_ratio` (body, optional; string; allowed: `auto`, `16:9`, `1:1`, `9:16`, `4:3`, `3:4`, `2:3`, `3:2`, `4:5`, `5:4`, `21:9`; default: `auto`; example: `auto`) — Aspect ratio of the generated image. Options: auto, 16:9, 1:1, 9:16, 4:3, 3:4, 2:3, 3:2, 4:5, 5:4, 21:9
  - `image_size` (body, optional; string; allowed: `1K`, `2K`, `4K`; default: `1K`; example: `1K`) — Size of the generated image. Options: 1K, 2K, 4K. Note: supported by nano-banana-pro and nano-banana-2 models; nano-banana-2-lite is always forced to 1K.
  - `google_search` (body, optional; boolean; default: `false`) — Use Google Web Search grounding to generate images based on real-time information. Only supported by nano-banana-2 model.
  - `force_generate` (body, optional; boolean; default: `true`) — Force generation even if NSFW content is detected. Defaults to true for API users, false for web users
  - `webhook_url` (body, optional; string; max length: 2048; example: `https://your-server.example.com/a2e/webhook`) — HTTPS URL to receive task.completed / task.failed notifications. Best-effort delivery, single attempt, no retries; clients should treat the detail API as the source of truth.
  - `webhook_token` (body, optional; string; max length: 256; example: `a-shared-secret`) — Optional plaintext token returned in the X-A2e-Webhook-Token header so receivers can verify the request originated from a2e.
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/userNanoBanana/start" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "name": "Beautiful Landscape",
  "prompt": "A serene mountain landscape at sunset with a crystal clear lake",
  "model": "nano-banana-pro",
  "input_images": [
    "https://example.com/image1.jpg"
  ],
  "aspect_ratio": "auto",
  "image_size": "1K",
  "google_search": false,
  "force_generate": true,
  "webhook_url": "https://your-server.example.com/a2e/webhook",
  "webhook_token": "a-shared-secret"
}
JSON
```
- Responses:
  - `200` — Nano Banana task started successfully or NSFW content detected
  - `400` — Bad Request - Invalid parameters
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/userNanoBanana/allRecords — Get Nano Banana task list
Retrieve paginated list of user's Nano Banana image generation tasks. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supported query parameters: `pageNum`, `pageSize`, `status`. Omitted values use the defaults shown in the parameter schema. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userNanoBanana/detail/{id}` — Get task details. - `DELETE /api/v1/userNanoBanana/delete/{id}` — Delete task. - `POST /api/v1/userNanoBanana/start` — Start Nano Banana image generation. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1UserNanoBananaAllRecords`
- Request parameters:
  - `pageNum` (query, required; integer; min: 1; example: `1`) — Page number
  - `pageSize` (query, required; integer; min: 1; max: 100; example: `1`) — Number of items per page
  - `status` (query, optional; string; allowed: `initialized`, `processing`, `completed`, `failed`; example: `initialized`) — Filter by task status
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/userNanoBanana/allRecords?pageNum=1&pageSize=1&status=initialized" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task list retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/userNanoBanana/batchDetail — Batch query task details
Query details for multiple tasks at once by providing an array of task IDs. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `ids`. ### Behavior - Fetches several task records in one request, reducing the number of individual detail calls. - Results remain subject to the same authentication and ownership checks as single-record lookups. - Match returned records by their identifiers instead of relying on response ordering. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userNanoBanana/allRecords` — Get Nano Banana task list. - `GET /api/v1/userNanoBanana/detail/{id}` — Get task details. - `DELETE /api/v1/userNanoBanana/delete/{id}` — Delete task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1UserNanoBananaBatchDetail`
- JSON body fields:
  - `ids` (body, required; string[]; example: `["example"]`) — Array of task IDs to query
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/userNanoBanana/batchDetail" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "ids": [
    "example"
  ]
}
JSON
```
- Responses:
  - `200` — Batch details retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/userNanoBanana/detail/{id} — Get task details
Retrieve detailed information about a specific Nano Banana task. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `id` in the URL path. ### Behavior - Retrieves the current server-side representation of the requested resource or task. - For asynchronous tasks, inspect the documented status and result fields before consuming generated media. - Repeat the request only as needed for polling and stop after the task reaches a terminal state. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. - `404` — Task not found. ### Related Operations - `GET /api/v1/userNanoBanana/allRecords` — Get Nano Banana task list. - `DELETE /api/v1/userNanoBanana/delete/{id}` — Delete task. - `POST /api/v1/userNanoBanana/start` — Start Nano Banana image generation. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1UserNanoBananaDetailId`
- Request parameters:
  - `id` (path, required; string; example: `507f1f77bcf86cd799439011`) — Task ID
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/userNanoBanana/detail/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task details retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token
  - `404` — Task not found

##### DELETE /api/v1/userNanoBanana/delete/{id} — Delete task
Soft-delete the authenticated user's Nano Banana image task identified by `id`, preserving the stored record while excluding it from normal task lists. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `id` in the URL path. ### Behavior - Deletes or marks the selected resource as deleted according to the endpoint's documented lifecycle rules. - Use the resource identifier from a list, creation, or detail response; deleting one resource does not affect unrelated records. - Do not assume an in-progress task can be cancelled unless the endpoint explicitly documents that behavior. ### Response - A `200` response confirms that the deletion request was applied to the selected record. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. - `404` — Task not found. ### Related Operations - `GET /api/v1/userNanoBanana/allRecords` — Get Nano Banana task list. - `GET /api/v1/userNanoBanana/detail/{id}` — Get task details. - `POST /api/v1/userNanoBanana/start` — Start Nano Banana image generation. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `deleteApiV1UserNanoBananaDeleteId`
- Request parameters:
  - `id` (path, required; string; example: `507f1f77bcf86cd799439011`) — Task ID to delete
- Example request:
```bash
curl -X DELETE "https://video.a2e.ai/api/v1/userNanoBanana/delete/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task deleted successfully
  - `401` — Unauthorized - Invalid or missing JWT token
  - `404` — Task not found
#### GPT Image

##### POST /api/v1/userGptImage/start — Start GPT Image generation or editing
Generate images from text or edit existing images using GPT Image (4o Image) model. **Features:** - Text-to-Image generation - Image-to-Image editing (supports up to 16 reference images) - High-fidelity visuals with accurate text rendering **Output:** - Images are stored in R2 storage and expire after 3 days. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `name`, `prompt`. - API-token callers may include `webhook_url` and `webhook_token` for best-effort terminal-state notifications; ordinary JWT/cookie calls ignore these fields. ### Behavior - This is an asynchronous operation: a successful submission creates a task and returns before processing finishes. - Persist the returned task identifier and use the corresponding detail or list operation to observe progress. - Treat the detail endpoint as the source of truth even when webhook delivery is enabled. ### Response - A `200` response confirms task acceptance; it does not by itself mean media generation has completed. - Retain the returned identifier and wait for a documented terminal status before using output URLs. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userGptImage/list` — Get GPT Image task list. - `GET /api/v1/userGptImage/detail/{id}` — Get task details. - `DELETE /api/v1/userGptImage/{id}` — Delete GPT Image task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1UserGptImageStart`
- JSON body fields:
  - `name` (body, required; string) — Name of the image generation task
  - `prompt` (body, required; string) — Text prompt for image generation (max 3000 chars)
  - `input_images` (body, optional; string[]) — Array of input image URLs for image-to-image editing (up to 16 images for GPT Image 1.5)
  - `model` (body, optional; string; allowed: `gpt-image-1.5`, `gpt-image-2`; default: `gpt-image-1.5`) — Model variant. gpt-image-1.5 (20/35 coins) supports both aspect_ratio and quality. gpt-image-2 (25/35/45 coins per image based on resolution: 1K=25, 2K=35, 4K=45; aspect_ratio=auto is billed as 1K, aspect_ratio=1:1 + 4K is downgraded to 2K) follows the current model spec: quality is fixed to medium; aspect_ratio exposes 9 ratios (auto/1:1/9:16/21:9/16:9/4:3/3:2/3:4/2:3); resolution supports 1K/2K/4K.
  - `aspect_ratio` (body, optional; string; allowed: `auto`, `1:1`, `9:16`, `21:9`, `16:9`, `4:3`, `3:2`, `3:4`, `2:3`; default: `1:1`) — gpt-image-1.5 only supports 1:1/3:2/2:3 (other values are normalized to 1:1). gpt-image-2 supports 9 ratios. Note: 5:4/4:5 are not exposed because fallback generation would lose the aspect ratio.
  - `quality` (body, optional; string; allowed: `medium`, `high`; default: `medium`) — Image quality level. Only used by gpt-image-1.5
  - `resolution` (body, optional; string; allowed: `1K`, `2K`, `4K`; default: `1K`) — Image resolution. Only used by gpt-image-2. Constraints: aspect_ratio=1:1 cannot use 4K; aspect_ratio=auto (or omitted) only supports 1K, otherwise upstream will reject the task.
  - `force_generate` (body, optional; boolean) — Force generation even if NSFW content is detected
  - `webhook_url` (body, optional; string; max length: 2048; example: `https://your-server.example.com/a2e/webhook`) — HTTPS URL to receive task.completed / task.failed notifications. Best-effort delivery, single attempt, no retries; clients should treat the detail API as the source of truth.
  - `webhook_token` (body, optional; string; max length: 256; example: `a-shared-secret`) — Optional plaintext token returned in the X-A2e-Webhook-Token header so receivers can verify the request originated from a2e.
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/userGptImage/start" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "name": "<name>",
  "prompt": "<prompt>",
  "model": "gpt-image-1.5",
  "aspect_ratio": "1:1",
  "quality": "medium",
  "resolution": "1K",
  "webhook_url": "https://your-server.example.com/a2e/webhook",
  "webhook_token": "a-shared-secret"
}
JSON
```
- Responses:
  - `200` — Task started successfully or NSFW content detected
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/userGptImage/list — Get GPT Image task list
Return the authenticated user's GPT Image generation and editing tasks using the requested pagination controls. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supported query parameters: `page`, `page_size`. Omitted values use the defaults shown in the parameter schema. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userGptImage/detail/{id}` — Get task details. - `DELETE /api/v1/userGptImage/{id}` — Delete GPT Image task. - `POST /api/v1/userGptImage/start` — Start GPT Image generation or editing. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1UserGptImageList`
- Request parameters:
  - `page` (query, optional; integer; default: `1`; example: `1`) — page parameter
  - `page_size` (query, optional; integer; default: `20`; example: `20`) — page_size parameter
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/userGptImage/list?page=1&page_size=20" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task list retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/userGptImage/batchDetail — Batch query task details
Query details for multiple tasks at once by providing an array of task IDs. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `ids`. ### Behavior - Fetches several task records in one request, reducing the number of individual detail calls. - Results remain subject to the same authentication and ownership checks as single-record lookups. - Match returned records by their identifiers instead of relying on response ordering. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userGptImage/list` — Get GPT Image task list. - `GET /api/v1/userGptImage/detail/{id}` — Get task details. - `DELETE /api/v1/userGptImage/{id}` — Delete GPT Image task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1UserGptImageBatchDetail`
- JSON body fields:
  - `ids` (body, required; string[]; example: `["example"]`) — Array of task IDs to query
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/userGptImage/batchDetail" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "ids": [
    "example"
  ]
}
JSON
```
- Responses:
  - `200` — Batch details retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/userGptImage/detail/{id} — Get task details
Return the authenticated user's GPT Image generation or editing task identified by `id`, including its current status and generated image fields. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `id` in the URL path. ### Behavior - Retrieves the current server-side representation of the requested resource or task. - For asynchronous tasks, inspect the documented status and result fields before consuming generated media. - Repeat the request only as needed for polling and stop after the task reaches a terminal state. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userGptImage/list` — Get GPT Image task list. - `DELETE /api/v1/userGptImage/{id}` — Delete GPT Image task. - `POST /api/v1/userGptImage/start` — Start GPT Image generation or editing. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1UserGptImageDetailId`
- Request parameters:
  - `id` (path, required; string; example: `507f1f77bcf86cd799439011`) — id parameter
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/userGptImage/detail/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task detail retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### DELETE /api/v1/userGptImage/{id} — Delete GPT Image task
Soft-delete the authenticated user's GPT Image task identified by `id`; the task is excluded from subsequent list results. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `id` in the URL path. ### Behavior - Deletes or marks the selected resource as deleted according to the endpoint's documented lifecycle rules. - Use the resource identifier from a list, creation, or detail response; deleting one resource does not affect unrelated records. - Do not assume an in-progress task can be cancelled unless the endpoint explicitly documents that behavior. ### Response - A `200` response confirms that the deletion request was applied to the selected record. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userGptImage/list` — Get GPT Image task list. - `GET /api/v1/userGptImage/detail/{id}` — Get task details. - `POST /api/v1/userGptImage/start` — Start GPT Image generation or editing. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `deleteApiV1UserGptImageId`
- Request parameters:
  - `id` (path, required; string; example: `507f1f77bcf86cd799439011`) — id parameter
- Example request:
```bash
curl -X DELETE "https://video.a2e.ai/api/v1/userGptImage/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task deleted successfully
  - `401` — Unauthorized - Invalid or missing JWT token
#### Flux 2

##### POST /api/v1/userFlux2/start — Start Flux 2 Pro image generation or editing
Generate high-quality images from text or edit existing images using Flux 2 Pro model. **Features:** - Text-to-Image generation with advanced prompt understanding - Image-to-Image editing (supports up to 8 reference images) - Character consistency across multiple images - Text rendering within images - High-quality output with professional-grade results **Processing Time:** - Usually 20-60 seconds **Output:** - Images are stored in R2 storage (7days-apac bucket) and expire after 7 days. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `name`, `prompt`. - API-token callers may include `webhook_url` and `webhook_token` for best-effort terminal-state notifications; ordinary JWT/cookie calls ignore these fields. ### Behavior - This is an asynchronous operation: a successful submission creates a task and returns before processing finishes. - Persist the returned task identifier and use the corresponding detail or list operation to observe progress. - Treat the detail endpoint as the source of truth even when webhook delivery is enabled. ### Response - A `200` response confirms task acceptance; it does not by itself mean media generation has completed. - Retain the returned identifier and wait for a documented terminal status before using output URLs. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Invalid request parameters. - `401` — Unauthorized - Invalid or missing token. - `402` — Insufficient credits. - `500` — Internal server error. ### Related Operations - `GET /api/v1/userFlux2/list` — Get Flux 2 Pro task list. - `GET /api/v1/userFlux2/detail/{id}` — Get task details. - `DELETE /api/v1/userFlux2/{id}` — Delete Flux 2 Pro task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1UserFlux2Start`
- JSON body fields:
  - `name` (body, required; string; example: `Elon Musk and Mark Zuckerberg boxing`) — Name of the image generation task
  - `prompt` (body, required; string; example: `Elon Musk and Mark Zuckerberg boxing in a professional ring`) — Text prompt for image generation or editing instruction.
  - `input_images` (body, optional; string[]; example: `["https://example.com/reference1.jpg","https://example.com/reference2.jpg"]`) — Array of input image URLs for image-to-image editing or multi-image composition (up to 8 images). When provided, automatically switches to image-to-image mode for character consistency.
  - `aspect_ratio` (body, optional; string; allowed: `1:1`, `16:9`, `9:16`, `4:3`, `3:4`, `2:3`, `3:2`, `custom`, `match_input_image`; default: `9:16`; example: `9:16`) — Aspect ratio of the generated image. Options: 1:1, 16:9, 9:16, 4:3, 3:4, 2:3, 3:2, custom, match_input_image
  - `resolution` (body, optional; string; allowed: `1K`, `2K`; default: `1K`; example: `1K`) — Resolution of the generated image. - 1K: ~1 megapixel - 2K: ~2 megapixels
  - `force_generate` (body, optional; boolean; default: `true`) — Force generation even if NSFW content is detected. Defaults to true for API users, false for web users
  - `webhook_url` (body, optional; string; max length: 2048; example: `https://your-server.example.com/a2e/webhook`) — HTTPS URL to receive task.completed / task.failed notifications. Best-effort delivery, single attempt, no retries; clients should treat the detail API as the source of truth.
  - `webhook_token` (body, optional; string; max length: 256; example: `a-shared-secret`) — Optional plaintext token returned in the X-A2e-Webhook-Token header so receivers can verify the request originated from a2e.
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/userFlux2/start" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "name": "Elon Musk and Mark Zuckerberg boxing",
  "prompt": "Elon Musk and Mark Zuckerberg boxing in a professional ring",
  "input_images": [
    "https://example.com/reference1.jpg",
    "https://example.com/reference2.jpg"
  ],
  "aspect_ratio": "9:16",
  "resolution": "1K",
  "force_generate": true,
  "webhook_url": "https://your-server.example.com/a2e/webhook",
  "webhook_token": "a-shared-secret"
}
JSON
```
- Responses:
  - `200` — Flux 2 Pro task started successfully or NSFW content detected
  - `400` — Invalid request parameters
  - `401` — Unauthorized - Invalid or missing token
  - `402` — Insufficient credits
  - `500` — Internal server error

##### GET /api/v1/userFlux2/list — Get Flux 2 Pro task list
Retrieve paginated list of user's Flux 2 Pro image generation tasks. Tasks are sorted by creation date (newest first). Only returns tasks that haven't expired (7 days retention). ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supported query parameters: `page`, `page_size`, `status`. Omitted values use the defaults shown in the parameter schema. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userFlux2/detail/{id}` — Get task details. - `DELETE /api/v1/userFlux2/{id}` — Delete Flux 2 Pro task. - `POST /api/v1/userFlux2/start` — Start Flux 2 Pro image generation or editing. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1UserFlux2List`
- Request parameters:
  - `page` (query, optional; integer; default: `1`; min: 1; example: `1`) — Page number (starting from 1)
  - `page_size` (query, optional; integer; default: `20`; min: 1; max: 100; example: `20`) — Number of items per page (max 100)
  - `status` (query, optional; string; allowed: `initialized`, `processing`, `completed`, `failed`; example: `initialized`) — Filter by task status
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/userFlux2/list?page=1&page_size=20&status=initialized" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task list retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/userFlux2/batchDetail — Batch query task details
Query details for multiple tasks at once by providing an array of task IDs. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `ids`. ### Behavior - Fetches several task records in one request, reducing the number of individual detail calls. - Results remain subject to the same authentication and ownership checks as single-record lookups. - Match returned records by their identifiers instead of relying on response ordering. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userFlux2/list` — Get Flux 2 Pro task list. - `GET /api/v1/userFlux2/detail/{id}` — Get task details. - `DELETE /api/v1/userFlux2/{id}` — Delete Flux 2 Pro task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1UserFlux2BatchDetail`
- JSON body fields:
  - `ids` (body, required; string[]; example: `["example"]`) — Array of task IDs to query
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/userFlux2/batchDetail" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "ids": [
    "example"
  ]
}
JSON
```
- Responses:
  - `200` — Batch details retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/userFlux2/detail/{id} — Get task details
Retrieve detailed information about a specific Flux 2 Pro task, including generation status, image URL, and processing time. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `id` in the URL path. ### Behavior - Retrieves the current server-side representation of the requested resource or task. - For asynchronous tasks, inspect the documented status and result fields before consuming generated media. - Repeat the request only as needed for polling and stop after the task reaches a terminal state. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. - `404` — Task not found. ### Related Operations - `GET /api/v1/userFlux2/list` — Get Flux 2 Pro task list. - `DELETE /api/v1/userFlux2/{id}` — Delete Flux 2 Pro task. - `POST /api/v1/userFlux2/start` — Start Flux 2 Pro image generation or editing. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1UserFlux2DetailId`
- Request parameters:
  - `id` (path, required; string; example: `507f1f77bcf86cd799439011`) — Task ID
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/userFlux2/detail/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task detail retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token
  - `404` — Task not found

##### DELETE /api/v1/userFlux2/{id} — Delete Flux 2 Pro task
Soft-delete the authenticated user's Flux 2 Pro image task identified by `id`, preserving the stored record while excluding it from normal task lists. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `id` in the URL path. ### Behavior - Deletes or marks the selected resource as deleted according to the endpoint's documented lifecycle rules. - Use the resource identifier from a list, creation, or detail response; deleting one resource does not affect unrelated records. - Do not assume an in-progress task can be cancelled unless the endpoint explicitly documents that behavior. ### Response - A `200` response confirms that the deletion request was applied to the selected record. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userFlux2/list` — Get Flux 2 Pro task list. - `GET /api/v1/userFlux2/detail/{id}` — Get task details. - `POST /api/v1/userFlux2/start` — Start Flux 2 Pro image generation or editing. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `deleteApiV1UserFlux2Id`
- Request parameters:
  - `id` (path, required; string; example: `507f1f77bcf86cd799439011`) — id parameter
- Example request:
```bash
curl -X DELETE "https://video.a2e.ai/api/v1/userFlux2/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task deleted successfully
  - `401` — Unauthorized - Invalid or missing JWT token
#### Qwen Image

##### POST /api/v1/userQwen2Image/start — Start a new Qwen2 image generation/edit task
Create an asynchronous Qwen2 task for text-to-image generation or image editing, according to `creation_mode` and the supplied input images. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `name`, `prompt`. - API-token callers may include `webhook_url` and `webhook_token` for best-effort terminal-state notifications; ordinary JWT/cookie calls ignore these fields. ### Behavior - This is an asynchronous operation: a successful submission creates a task and returns before processing finishes. - Persist the returned task identifier and use the corresponding detail or list operation to observe progress. - Treat the detail endpoint as the source of truth even when webhook delivery is enabled. ### Response - A `200` response confirms task acceptance; it does not by itself mean media generation has completed. - Retain the returned identifier and wait for a documented terminal status before using output URLs. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userQwen2Image/list` — List Qwen2 image tasks. - `GET /api/v1/userQwen2Image/detail/{id}` — Get Qwen2 image task details. - `DELETE /api/v1/userQwen2Image/{id}` — Delete a Qwen2 image task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1UserQwen2ImageStart`
- JSON body fields:
  - `name` (body, required; string) — Task name
  - `prompt` (body, required; string) — Image generation or editing prompt
  - `model` (body, optional; string; allowed: `qwen-image-2.0`, `qwen-image-2.0-pro`, `qwen-image-3.0`, `qwen-image-3.0-pro`; default: `qwen-image-2.0`)
  - `input_images` (body, optional; string[]) — Optional public reference image URLs
  - `size` (body, optional; string; allowed: `1024*1024`, `1328*880`, `880*1328`, `1152*864`, `864*1152`, `1280*720`, `720*1280`, `1512*648`, `2048*2048`, `2048*1365`, `1365*2048`, `2048*1536`, `1536*2048`, `2048*1152`, `1152*2048`; default: `1024*1024`) — 1K sizes are supported by all Qwen Image models. 2K sizes (2048*) are supported only by qwen-image-3.0-pro.
  - `webhook_url` (body, optional; string; max length: 2048; example: `https://your-server.example.com/a2e/webhook`) — HTTPS URL to receive task.completed / task.failed notifications. Best-effort delivery, single attempt, no retries; clients should treat the detail API as the source of truth.
  - `webhook_token` (body, optional; string; max length: 256; example: `a-shared-secret`) — Optional plaintext token returned in the X-A2e-Webhook-Token header so receivers can verify the request originated from a2e.
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/userQwen2Image/start" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "name": "<name>",
  "prompt": "<prompt>",
  "model": "qwen-image-2.0",
  "size": "1024*1024",
  "webhook_url": "https://your-server.example.com/a2e/webhook",
  "webhook_token": "a-shared-secret"
}
JSON
```
- Responses:
  - `200` — Task created successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/userQwen2Image/list — List Qwen2 image tasks
Return the authenticated user's Qwen2 image generation and editing tasks using the requested pagination controls. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - No request body or operation-specific parameters are required. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userQwen2Image/detail/{id}` — Get Qwen2 image task details. - `DELETE /api/v1/userQwen2Image/{id}` — Delete a Qwen2 image task. - `POST /api/v1/userQwen2Image/start` — Start a new Qwen2 image generation/edit task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1UserQwen2ImageList`
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/userQwen2Image/list" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task list
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/userQwen2Image/detail/{id} — Get Qwen2 image task details
Return the authenticated user's Qwen2 image task identified by `id`, including its current status and generated image fields. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `id` in the URL path. ### Behavior - Retrieves the current server-side representation of the requested resource or task. - For asynchronous tasks, inspect the documented status and result fields before consuming generated media. - Repeat the request only as needed for polling and stop after the task reaches a terminal state. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userQwen2Image/list` — List Qwen2 image tasks. - `DELETE /api/v1/userQwen2Image/{id}` — Delete a Qwen2 image task. - `POST /api/v1/userQwen2Image/start` — Start a new Qwen2 image generation/edit task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1UserQwen2ImageDetailId`
- Request parameters:
  - `id` (path, required; string; example: `507f1f77bcf86cd799439011`) — id parameter
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/userQwen2Image/detail/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task details
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/userQwen2Image/batchDetail — Batch get Qwen2 image task details
Return up to 200 authenticated-user Qwen2 image tasks matching the submitted `ids`; callers should match records by identifier. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `ids`. ### Behavior - Fetches several task records in one request, reducing the number of individual detail calls. - Results remain subject to the same authentication and ownership checks as single-record lookups. - Match returned records by their identifiers instead of relying on response ordering. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userQwen2Image/list` — List Qwen2 image tasks. - `GET /api/v1/userQwen2Image/detail/{id}` — Get Qwen2 image task details. - `DELETE /api/v1/userQwen2Image/{id}` — Delete a Qwen2 image task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1UserQwen2ImageBatchDetail`
- JSON body fields:
  - `ids` (body, required; string[]; example: `["example"]`) — Array of task IDs to query
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/userQwen2Image/batchDetail" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "ids": [
    "example"
  ]
}
JSON
```
- Responses:
  - `200` — Task details
  - `401` — Unauthorized - Invalid or missing JWT token

##### DELETE /api/v1/userQwen2Image/{id} — Delete a Qwen2 image task
Soft-delete the authenticated user's Qwen2 image task identified by `id`; the task is excluded from subsequent list results. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `id` in the URL path. ### Behavior - Deletes or marks the selected resource as deleted according to the endpoint's documented lifecycle rules. - Use the resource identifier from a list, creation, or detail response; deleting one resource does not affect unrelated records. - Do not assume an in-progress task can be cancelled unless the endpoint explicitly documents that behavior. ### Response - A `200` response confirms that the deletion request was applied to the selected record. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userQwen2Image/list` — List Qwen2 image tasks. - `GET /api/v1/userQwen2Image/detail/{id}` — Get Qwen2 image task details. - `POST /api/v1/userQwen2Image/start` — Start a new Qwen2 image generation/edit task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `deleteApiV1UserQwen2ImageId`
- Request parameters:
  - `id` (path, required; string; example: `507f1f77bcf86cd799439011`) — id parameter
- Example request:
```bash
curl -X DELETE "https://video.a2e.ai/api/v1/userQwen2Image/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task deleted
  - `401` — Unauthorized - Invalid or missing JWT token
#### Kling Image

##### POST /api/v1/userKlingImage/start — Start Kling 3.0 image generation
Create one or more asynchronous Kling 3.0 image tasks from the prompt and optional reference images, subject to the request's `n` limit. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `name`, `prompt`. - API-token callers may include `webhook_url` and `webhook_token` for best-effort terminal-state notifications; ordinary JWT/cookie calls ignore these fields. ### Behavior - This is an asynchronous operation: a successful submission creates a task and returns before processing finishes. - Persist the returned task identifier and use the corresponding detail or list operation to observe progress. - Treat the detail endpoint as the source of truth even when webhook delivery is enabled. ### Response - A `200` response confirms task acceptance; it does not by itself mean media generation has completed. - Retain the returned identifier and wait for a documented terminal status before using output URLs. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userKlingImage/list` — List Kling image tasks. - `GET /api/v1/userKlingImage/detail/{id}` — Get Kling image task details. - `DELETE /api/v1/userKlingImage/{id}` — Delete a Kling image task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1UserKlingImageStart`
- JSON body fields:
  - `name` (body, required; string) — Task name
  - `prompt` (body, required; string) — Image generation prompt
  - `input_images` (body, optional; string[]) — Optional public reference image URLs
  - `aspect_ratio` (body, optional; string; allowed: `1:1`, `16:9`, `9:16`, `4:3`, `3:4`, `2:3`, `3:2`, `21:9`; default: `9:16`)
  - `resolution` (body, optional; string; allowed: `1k`, `2k`; default: `1k`)
  - `n` (body, optional; integer; min: 1; max: 9)
  - `webhook_url` (body, optional; string; max length: 2048; example: `https://your-server.example.com/a2e/webhook`) — HTTPS URL to receive task.completed / task.failed notifications. Best-effort delivery, single attempt, no retries; clients should treat the detail API as the source of truth.
  - `webhook_token` (body, optional; string; max length: 256; example: `a-shared-secret`) — Optional plaintext token returned in the X-A2e-Webhook-Token header so receivers can verify the request originated from a2e.
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/userKlingImage/start" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "name": "<name>",
  "prompt": "<prompt>",
  "aspect_ratio": "9:16",
  "resolution": "1k",
  "webhook_url": "https://your-server.example.com/a2e/webhook",
  "webhook_token": "a-shared-secret"
}
JSON
```
- Responses:
  - `200` — Task created successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/userKlingImage/list — List Kling image tasks
Return the authenticated user's Kling image tasks using the requested pagination controls. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - No request body or operation-specific parameters are required. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userKlingImage/detail/{id}` — Get Kling image task details. - `DELETE /api/v1/userKlingImage/{id}` — Delete a Kling image task. - `POST /api/v1/userKlingImage/start` — Start Kling 3.0 image generation. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1UserKlingImageList`
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/userKlingImage/list" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task list
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/userKlingImage/batchDetail — Batch get Kling image task details
Return up to 200 authenticated-user Kling image tasks matching the submitted `ids`; callers should match records by identifier. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `ids`. ### Behavior - Fetches several task records in one request, reducing the number of individual detail calls. - Results remain subject to the same authentication and ownership checks as single-record lookups. - Match returned records by their identifiers instead of relying on response ordering. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userKlingImage/list` — List Kling image tasks. - `GET /api/v1/userKlingImage/detail/{id}` — Get Kling image task details. - `DELETE /api/v1/userKlingImage/{id}` — Delete a Kling image task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1UserKlingImageBatchDetail`
- JSON body fields:
  - `ids` (body, required; string[]; example: `["example"]`) — Array of task IDs to query
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/userKlingImage/batchDetail" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "ids": [
    "example"
  ]
}
JSON
```
- Responses:
  - `200` — Task details
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/userKlingImage/detail/{id} — Get Kling image task details
Return the authenticated user's Kling image task identified by `id`, including its current status and generated image fields. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `id` in the URL path. ### Behavior - Retrieves the current server-side representation of the requested resource or task. - For asynchronous tasks, inspect the documented status and result fields before consuming generated media. - Repeat the request only as needed for polling and stop after the task reaches a terminal state. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userKlingImage/list` — List Kling image tasks. - `DELETE /api/v1/userKlingImage/{id}` — Delete a Kling image task. - `POST /api/v1/userKlingImage/start` — Start Kling 3.0 image generation. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1UserKlingImageDetailId`
- Request parameters:
  - `id` (path, required; string; example: `507f1f77bcf86cd799439011`) — id parameter
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/userKlingImage/detail/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task details
  - `401` — Unauthorized - Invalid or missing JWT token

##### DELETE /api/v1/userKlingImage/{id} — Delete a Kling image task
Soft-delete the authenticated user's Kling image task identified by `id`; the task is excluded from subsequent list results. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `id` in the URL path. ### Behavior - Deletes or marks the selected resource as deleted according to the endpoint's documented lifecycle rules. - Use the resource identifier from a list, creation, or detail response; deleting one resource does not affect unrelated records. - Do not assume an in-progress task can be cancelled unless the endpoint explicitly documents that behavior. ### Response - A `200` response confirms that the deletion request was applied to the selected record. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userKlingImage/list` — List Kling image tasks. - `GET /api/v1/userKlingImage/detail/{id}` — Get Kling image task details. - `POST /api/v1/userKlingImage/start` — Start Kling 3.0 image generation. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `deleteApiV1UserKlingImageId`
- Request parameters:
  - `id` (path, required; string; example: `507f1f77bcf86cd799439011`) — id parameter
- Example request:
```bash
curl -X DELETE "https://video.a2e.ai/api/v1/userKlingImage/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task deleted
  - `401` — Unauthorized - Invalid or missing JWT token
#### Wan Image to Video

##### POST /api/v1/userWan25/start — Start Wan video generation
Start a Wan video generation task. This endpoint supports Wan 2.5 image-to-video, Wan 2.6 image-to-video and Wan 2.7 multi-mode video generation. For Wan 2.7, set `model` to `wan2.7-i2v` and select the generation mode with `task_type`: - `text_to_video`: text prompt only. Do not provide image/video material. - `first_frame`: image-to-video from one first-frame image. Requires `image_url`. - `first_last_frame`: image-to-video with first and last frame control. Requires `image_url` and `last_frame_url`. - `reference_image`: reference-to-video. Requires 1 to 5 ordered image/video entries in `reference_media`; legacy pure-image clients may continue using `reference_image_urls`. - `video_extend`: extend an existing video clip. Requires `first_clip_url`; optional `last_frame_url`. - `video_edit`: edit an existing video. Requires `edit_video_url`; optional `reference_image_urls` with up to 3 image URLs. `text_to_video`, `first_last_frame`, `reference_image`, `video_extend` and `video_edit` are only available when `model=wan2.7-i2v`. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `prompt`. - API-token callers may include `webhook_url` and `webhook_token` for best-effort terminal-state notifications; ordinary JWT/cookie calls ignore these fields. ### Behavior - This is an asynchronous operation: a successful submission creates a task and returns before processing finishes. - Persist the returned task identifier and use the corresponding detail or list operation to observe progress. - Treat the detail endpoint as the source of truth even when webhook delivery is enabled. ### Response - A `200` response confirms task acceptance; it does not by itself mean media generation has completed. - Retain the returned identifier and wait for a documented terminal status before using output URLs. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid parameters. - `401` — Unauthorized - Invalid or missing JWT token. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1UserWan25Start`
- JSON body fields:
  - `name` (body, optional; string; example: `My Wan Video`) — Optional display name for the task
  - `image_url` (body, optional; string; example: `https://example.com/image.jpg`) — Source image URL. Required for `first_frame` and `first_last_frame`.
  - `prompt` (body, required; string; example: `Make the person in the image wave their hand`) — Generation prompt
  - `negative_prompt` (body, optional; string; example: `blurry, distorted`) — Negative prompt to avoid unwanted features
  - `duration` (body, optional; string; allowed: `2`, `3`, `4`, `5`, `6`, `7`, `8`, `9`, `10`, `11`, `12`, `13`, `14`, `15`; default: `5`) — Video duration in seconds. Wan2.7 reference_image supports 2-15 with images only or 2-10 when a reference video is present; text_to_video/first_frame/first_last_frame/video_extend use 5/10/15; video_edit uses 5-10. Wan 2.5 only supports 5/10.
  - `resolution` (body, optional; string; allowed: `480p`, `720p`, `1080p`; default: `720p`) — Video resolution
  - `ratio` (body, optional; string; allowed: `16:9`, `9:16`, `1:1`, `4:3`, `3:4`; default: `16:9`) — Video aspect ratio. Only used by Wan 2.7 `text_to_video` and `reference_image`.
  - `enable_prompt_expansion` (body, optional; boolean; default: `false`) — Whether to enable prompt rewriting using LLM
  - `multi_shots` (body, optional; boolean; default: `false`) — Enable intelligent multi-shot segmentation (only active when enable_prompt_expansion is true)
  - `model` (body, optional; string; allowed: `wan2.5-i2v-preview`, `wan2.6-i2v`, `wan2.6-i2v-flash`, `wan2.7-i2v`; default: `wan2.5-i2v-preview`) — AI model version (wan2.6-i2v and wan2.7-i2v require VIP/Max user, wan2.6-i2v-flash is available to all users)
  - `task_type` (body, optional; string; allowed: `text_to_video`, `first_frame`, `first_last_frame`, `reference_image`, `video_extend`, `video_edit`; default: `first_frame`) — Wan 2.7 generation mode. Only used when `model=wan2.7-i2v`.
  - `last_frame_url` (body, optional; string; example: `https://example.com/last-frame.jpg`) — Last-frame image URL. Required for `first_last_frame`; optional for `video_extend`.
  - `first_clip_url` (body, optional; string; example: `https://example.com/clip.mp4`) — Existing video clip URL. Required for Wan 2.7 `video_extend`.
  - `edit_video_url` (body, optional; string; example: `https://example.com/input-video.mp4`) — Input video URL. Required for Wan 2.7 `video_edit`.
  - `reference_image_urls` (body, optional; string[]; example: `["https://example.com/reference-1.jpg","https://example.com/reference-2.jpg"]`) — Legacy pure-image reference URLs for Wan 2.7 `reference_image`; optional for `video_edit` (up to 3 images).
  - `reference_media` (body, optional; object[]; min items: 1; max items: 5) — Ordered Wan2.7 reference-to-video media. Input videos are billed together with output duration according to the official 5-second input cap.
  - `seed` (body, optional; number; min: 0; max: 2147483647) — Random seed for reproducibility. Value must be in the range [0, 2147483647]. If not specified, system generates a random seed.
  - `audio` (body, optional; boolean; default: `true`) — Whether to generate audio for the video
  - `audio_url` (body, optional; string; example: `https://example.com/audio.mp3`) — URL of audio file to use for first-frame/first-last-frame video generation. Supports WAV/MP3, 3-30s duration, max 15MB. If longer than video duration, audio will be truncated.
  - `webhook_url` (body, optional; string; max length: 2048; example: `https://your-server.example.com/a2e/webhook`) — HTTPS URL to receive task.completed / task.failed notifications. Best-effort delivery, single attempt, no retries; clients should treat the detail API as the source of truth.
  - `webhook_token` (body, optional; string; max length: 256; example: `a-shared-secret`) — Optional plaintext token returned in the X-A2e-Webhook-Token header so receivers can verify the request originated from a2e.
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/userWan25/start" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "name": "My Wan Video",
  "image_url": "https://example.com/image.jpg",
  "prompt": "Make the person in the image wave their hand",
  "negative_prompt": "blurry, distorted",
  "duration": "5",
  "resolution": "720p",
  "ratio": "16:9",
  "enable_prompt_expansion": false,
  "multi_shots": false,
  "model": "wan2.5-i2v-preview",
  "task_type": "first_frame",
  "last_frame_url": "https://example.com/last-frame.jpg",
  "first_clip_url": "https://example.com/clip.mp4",
  "edit_video_url": "https://example.com/input-video.mp4",
  "reference_image_urls": [
    "https://example.com/reference-1.jpg",
    "https://example.com/reference-2.jpg"
  ],
  "audio": true,
  "audio_url": "https://example.com/audio.mp3",
  "webhook_url": "https://your-server.example.com/a2e/webhook",
  "webhook_token": "a-shared-secret"
}
JSON
```
- Responses:
  - `200` — Wan video task started successfully
  - `400` — Bad Request - Invalid parameters
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/userWan25/allRecords — Get all Wan 2.5 tasks
Return the authenticated user's Wan 2.5 image-to-video tasks using the requested pagination controls, including current status and available output metadata. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supported query parameters: `pageNum`, `pageSize`. Omitted values use the defaults shown in the parameter schema. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userWan25/{_id}` — Get Wan 2.5 task details. - `DELETE /api/v1/userWan25/{_id}` — Delete a Wan 2.5 task. - `POST /api/v1/userWan25/batchDetail` — Batch query task details. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1UserWan25AllRecords`
- Request parameters:
  - `pageNum` (query, optional; integer; default: `1`; example: `1`) — Page number
  - `pageSize` (query, optional; integer; default: `10`; example: `10`) — Number of items per page
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/userWan25/allRecords?pageNum=1&pageSize=10" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task list retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/userWan25/batchDetail — Batch query task details
Query details for multiple tasks at once by providing an array of task IDs. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `ids`. ### Behavior - Fetches several task records in one request, reducing the number of individual detail calls. - Results remain subject to the same authentication and ownership checks as single-record lookups. - Match returned records by their identifiers instead of relying on response ordering. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userWan25/allRecords` — Get all Wan 2.5 tasks. - `GET /api/v1/userWan25/{_id}` — Get Wan 2.5 task details. - `DELETE /api/v1/userWan25/{_id}` — Delete a Wan 2.5 task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1UserWan25BatchDetail`
- JSON body fields:
  - `ids` (body, required; string[]; example: `["example"]`) — Array of task IDs to query
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/userWan25/batchDetail" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "ids": [
    "example"
  ]
}
JSON
```
- Responses:
  - `200` — Batch details retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/userWan25/{_id} — Get Wan 2.5 task details
Return the authenticated user's Wan 2.5 image-to-video task identified by `_id`, including its generation settings, current status, and available video output. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Retrieves the current server-side representation of the requested resource or task. - For asynchronous tasks, inspect the documented status and result fields before consuming generated media. - Repeat the request only as needed for polling and stop after the task reaches a terminal state. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userWan25/allRecords` — Get all Wan 2.5 tasks. - `DELETE /api/v1/userWan25/{_id}` — Delete a Wan 2.5 task. - `POST /api/v1/userWan25/batchDetail` — Batch query task details. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1UserWan25Id`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — Task ID
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/userWan25/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task details retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### DELETE /api/v1/userWan25/{_id} — Delete a Wan 2.5 task
Remove the authenticated user's Wan 2.5 image-to-video task identified by `_id` from normal task history without affecting unrelated tasks. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Deletes or marks the selected resource as deleted according to the endpoint's documented lifecycle rules. - Use the resource identifier from a list, creation, or detail response; deleting one resource does not affect unrelated records. - Do not assume an in-progress task can be cancelled unless the endpoint explicitly documents that behavior. ### Response - A `200` response confirms that the deletion request was applied to the selected record. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userWan25/allRecords` — Get all Wan 2.5 tasks. - `GET /api/v1/userWan25/{_id}` — Get Wan 2.5 task details. - `POST /api/v1/userWan25/batchDetail` — Batch query task details. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `deleteApiV1UserWan25Id`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — Task ID
- Example request:
```bash
curl -X DELETE "https://video.a2e.ai/api/v1/userWan25/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task deleted successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/userWanSpicy/start — Start Wan Spicy image-to-video generation
Start a Wan Spicy image-to-video task via mulerouter.ai/carrothub. - wan2.7-i2v-spicy: with audio support, resolution 720p/1080p, duration 2-15 seconds. - wan2.2-i2v-spicy: no audio, resolution 480p/720p, duration 5 or 8 seconds. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `prompt`, `image_url`, `resolution`, `duration`. - API-token callers may include `webhook_url` and `webhook_token` for best-effort terminal-state notifications; ordinary JWT/cookie calls ignore these fields. ### Behavior - This is an asynchronous operation: a successful submission creates a task and returns before processing finishes. - Persist the returned task identifier and use the corresponding detail or list operation to observe progress. - Treat the detail endpoint as the source of truth even when webhook delivery is enabled. ### Response - A `200` response confirms task acceptance; it does not by itself mean media generation has completed. - Retain the returned identifier and wait for a documented terminal status before using output URLs. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userWanSpicy/allRecords` — Get all Wan Spicy tasks. - `GET /api/v1/userWanSpicy/{_id}` — Get Wan Spicy task details. - `DELETE /api/v1/userWanSpicy/{_id}` — Delete a Wan Spicy task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1UserWanSpicyStart`
- JSON body fields:
  - `model` (body, optional; string; allowed: `wan2.7-i2v-spicy`, `wan2.2-i2v-spicy`; default: `wan2.7-i2v-spicy`) — Model variant (2.7 supports audio, 2.2 no audio)
  - `name` (body, optional; string) — Optional display name for the task
  - `prompt` (body, required; string) — Generation prompt
  - `negative_prompt` (body, optional; string) — Negative prompt (only valid when model = wan2.7-i2v-spicy)
  - `image_url` (body, required; string) — Reference image URL (https only)
  - `audio_url` (body, optional; string) — Audio URL (https, .wav/.mp3, only valid when model = wan2.7-i2v-spicy)
  - `resolution` (body, required; string; allowed: `480p`, `720p`, `1080p`) — Resolution tier (wan2.7 720p/1080p, wan2.2 480p/720p)
  - `duration` (body, required; number) — Output duration in seconds (wan2.7 2-15, wan2.2 5 or 8)
  - `prompt_extend` (body, optional; boolean; default: `true`)
  - `seed` (body, optional; integer) — Random seed
  - `minor_suspected_skip` (body, optional; boolean; default: `false`) — Skip pre-charge minor-suspect prompt for the input image
  - `webhook_url` (body, optional; string; max length: 2048; example: `https://your-server.example.com/a2e/webhook`) — HTTPS URL to receive task.completed / task.failed notifications. Best-effort delivery, single attempt, no retries; clients should treat the detail API as the source of truth.
  - `webhook_token` (body, optional; string; max length: 256; example: `a-shared-secret`) — Optional plaintext token returned in the X-A2e-Webhook-Token header so receivers can verify the request originated from a2e.
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/userWanSpicy/start" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "model": "wan2.7-i2v-spicy",
  "prompt": "Animate the subject with smooth, cinematic motion.",
  "image_url": "https://example.com/input.jpg",
  "resolution": "720p",
  "duration": 5
}
JSON
```
- Responses:
  - `200` — Task started successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/userWanSpicy/allRecords — Get all Wan Spicy tasks
Return the authenticated user's Wan Spicy image-to-video tasks using the requested pagination controls. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supported query parameters: `pageNum`, `pageSize`. Omitted values use the defaults shown in the parameter schema. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userWanSpicy/{_id}` — Get Wan Spicy task details. - `DELETE /api/v1/userWanSpicy/{_id}` — Delete a Wan Spicy task. - `POST /api/v1/userWanSpicy/start` — Start Wan Spicy image-to-video generation. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1UserWanSpicyAllRecords`
- Request parameters:
  - `pageNum` (query, optional; integer; default: `1`; example: `1`) — pageNum parameter
  - `pageSize` (query, optional; integer; default: `10`; example: `10`) — pageSize parameter
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/userWanSpicy/allRecords?pageNum=1&pageSize=10" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task list retrieved
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/userWanSpicy/batchDetail — Batch query task details
Query details for multiple tasks at once by providing an array of task IDs. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `ids`. ### Behavior - Fetches several task records in one request, reducing the number of individual detail calls. - Results remain subject to the same authentication and ownership checks as single-record lookups. - Match returned records by their identifiers instead of relying on response ordering. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userWanSpicy/allRecords` — Get all Wan Spicy tasks. - `GET /api/v1/userWanSpicy/{_id}` — Get Wan Spicy task details. - `DELETE /api/v1/userWanSpicy/{_id}` — Delete a Wan Spicy task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1UserWanSpicyBatchDetail`
- JSON body fields:
  - `ids` (body, required; string[]; example: `["example"]`) — Array of task IDs to query
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/userWanSpicy/batchDetail" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "ids": [
    "example"
  ]
}
JSON
```
- Responses:
  - `200` — Batch details retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/userWanSpicy/{_id} — Get Wan Spicy task details
Return the authenticated user's Wan Spicy image-to-video task identified by `_id`, including its current status and video output fields. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Retrieves the current server-side representation of the requested resource or task. - For asynchronous tasks, inspect the documented status and result fields before consuming generated media. - Repeat the request only as needed for polling and stop after the task reaches a terminal state. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userWanSpicy/allRecords` — Get all Wan Spicy tasks. - `DELETE /api/v1/userWanSpicy/{_id}` — Delete a Wan Spicy task. - `POST /api/v1/userWanSpicy/start` — Start Wan Spicy image-to-video generation. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1UserWanSpicyId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — _id parameter
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/userWanSpicy/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task details retrieved
  - `401` — Unauthorized - Invalid or missing JWT token

##### DELETE /api/v1/userWanSpicy/{_id} — Delete a Wan Spicy task
Soft-delete the authenticated user's Wan Spicy image-to-video task identified by `_id`. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Deletes or marks the selected resource as deleted according to the endpoint's documented lifecycle rules. - Use the resource identifier from a list, creation, or detail response; deleting one resource does not affect unrelated records. - Do not assume an in-progress task can be cancelled unless the endpoint explicitly documents that behavior. ### Response - A `200` response confirms that the deletion request was applied to the selected record. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userWanSpicy/allRecords` — Get all Wan Spicy tasks. - `GET /api/v1/userWanSpicy/{_id}` — Get Wan Spicy task details. - `POST /api/v1/userWanSpicy/start` — Start Wan Spicy image-to-video generation. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `deleteApiV1UserWanSpicyId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — _id parameter
- Example request:
```bash
curl -X DELETE "https://video.a2e.ai/api/v1/userWanSpicy/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task deleted successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/userWan30/start — Start Wan3.0 all-in-one video generation
Generate a video with `wan3.0-video` or `wan3.0-video-prime`. Both models produce identical quality; `wan3.0-video-prime` only trades a higher per-second price for much faster inference (about 2 minutes instead of about 14 minutes for a 720P 15-second clip). The request/response contract is identical — switch by replacing the model name. Reference mode accepts image, video, audio, file, and public web-page media. Each reference video must be 3–15 seconds; all reference videos together must not exceed 15 seconds, and reference-video plus output duration must not exceed 30 seconds. Strict first-frame/first-last-frame media cannot be mixed with reference media. File and link inputs are mutually exclusive. `prompt_extend` controls upstream prompt rewriting and defaults to false; when it stays off, write prompts following the Wan3.0 creator handbook prompt guide. `negative_prompt` is not supported. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `model`, `input`, `parameters`. - API-token callers may include `webhook_url` and `webhook_token` for best-effort terminal-state notifications; ordinary JWT/cookie calls ignore these fields. ### Behavior - This is an asynchronous operation: a successful submission creates a task and returns before processing finishes. - Persist the returned task identifier and use the corresponding detail or list operation to observe progress. - Treat the detail endpoint as the source of truth even when webhook delivery is enabled. ### Response - A `200` response confirms task acceptance; it does not by itself mean media generation has completed. - Retain the returned identifier and wait for a documented terminal status before using output URLs. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Invalid mode, media combination, or generation parameter. - `401` — Unauthorized - Invalid or missing JWT token. - `503` — Provider or Wan3.0 pricing is not configured. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1UserWan30Start`
- JSON body fields:
  - `name` (body, optional; string)
  - `model` (body, required; string; allowed: `wan3.0-video`, `wan3.0-video-prime`; default: `wan3.0-video`)
  - `mode` (body, optional; string; allowed: `text-to-video`, `first-frame`, `first-last-frames`, `reference`; default: `text-to-video`)
  - `input` (body, required; object)
  - `parameters` (body, required; object)
  - `webhook_url` (body, optional; string; max length: 2048; example: `https://your-server.example.com/a2e/webhook`) — HTTPS URL to receive task.completed / task.failed notifications. Best-effort delivery, single attempt, no retries; clients should treat the detail API as the source of truth.
  - `webhook_token` (body, optional; string; max length: 256; example: `a-shared-secret`) — Optional plaintext token returned in the X-A2e-Webhook-Token header so receivers can verify the request originated from a2e.
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/userWan30/start" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "model": "wan3.0-video",
  "mode": "text-to-video",
  "input": {
    "prompt": "<prompt>",
    "media": [
      {
        "type": "reference_image",
        "url": "<url>",
        "duration": 0
      }
    ]
  },
  "parameters": {
    "resolution": "1080P",
    "ratio": "adaptive",
    "duration": 5,
    "audio": true,
    "prompt_extend": false,
    "seed": 0,
    "watermark": false
  },
  "webhook_url": "https://your-server.example.com/a2e/webhook",
  "webhook_token": "a-shared-secret"
}
JSON
```
- Responses:
  - `200` — Task created
  - `400` — Invalid mode, media combination, or generation parameter
  - `401` — Unauthorized - Invalid or missing JWT token
  - `503` — Provider or Wan3.0 pricing is not configured
#### HappyHorse Video

##### POST /api/v1/userHappyhorseVideo/start — Start HappyHorse video generation task (T2V / I2V / R2V / Video-Edit)
Generate a video using HappyHorse models on Alibaba DashScope. If model_version is omitted, new tasks keep the legacy 1.0 behavior. Supported modes: - t2v: text → video (happyhorse-1.0-t2v / happyhorse-1.1-t2v) - i2v: image first_frame → video (happyhorse-1.0-i2v / happyhorse-1.1-i2v) - r2v: reference images → video (happyhorse-1.0-r2v / happyhorse-1.1-r2v) - video-edit: video + reference images → edited video (happyhorse-1.0-video-edit) ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `mode`. - API-token callers may include `webhook_url` and `webhook_token` for best-effort terminal-state notifications; ordinary JWT/cookie calls ignore these fields. ### Behavior - This is an asynchronous operation: a successful submission creates a task and returns before processing finishes. - Persist the returned task identifier and use the corresponding detail or list operation to observe progress. - Treat the detail endpoint as the source of truth even when webhook delivery is enabled. ### Response - A `200` response confirms task acceptance; it does not by itself mean media generation has completed. - Retain the returned identifier and wait for a documented terminal status before using output URLs. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userHappyhorseVideo/allRecords` — List HappyHorse tasks. - `GET /api/v1/userHappyhorseVideo/{_id}` — Get HappyHorse task details. - `DELETE /api/v1/userHappyhorseVideo/{_id}` — Delete a HappyHorse task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1UserHappyhorseVideoStart`
- JSON body fields:
  - `mode` (body, required; string; allowed: `t2v`, `i2v`, `r2v`, `video-edit`) — Generation mode
  - `name` (body, optional; string) — Task name
  - `model_version` (body, optional; string; allowed: `1.0`, `1.1`; default: `1.0`) — Model version for t2v / i2v / r2v. video-edit always uses 1.0. HappyHorse 1.0 keeps the legacy duration/ratio options; 1.1 supports 3-15s, additional aspect ratios, and 480P/720P/1080P.
  - `prompt` (body, optional; string) — Required for t2v / r2v / video-edit; optional for i2v
  - `image_url` (body, optional; string) — First frame image URL (i2v only)
  - `reference_image_urls` (body, optional; string[]) — Reference images (r2v requires 1-9; video-edit allows 0-5)
  - `edit_video_url` (body, optional; string) — Input video URL (video-edit only)
  - `input_video_seconds` (body, optional; number) — Frontend-detected input video duration in seconds (used to estimate coins for video-edit)
  - `duration` (body, optional; string; allowed: `3`, `4`, `5`, `6`, `7`, `8`, `9`, `10`, `11`, `12`, `13`, `14`, `15`; default: `5`) — Output duration (seconds). model_version=1.0 supports 5/10/15; model_version=1.1 supports 3-15. Ignored for video-edit (decided by input video).
  - `resolution` (body, optional; string; allowed: `480P`, `720P`, `1080P`; default: `720P`) — Output resolution. 480P is only supported by HappyHorse 1.1 t2v / i2v / r2v; 1.0 and video-edit support 720P / 1080P.
  - `ratio` (body, optional; string; allowed: `16:9`, `9:16`, `1:1`, `4:3`, `3:4`, `4:5`, `5:4`, `9:21`, `21:9`; default: `16:9`) — Aspect ratio (t2v / r2v only). model_version=1.0 supports 16:9, 9:16, 1:1, 4:3, 3:4; model_version=1.1 also supports 4:5, 5:4, 9:21, 21:9.
  - `audio_setting` (body, optional; string; allowed: `auto`, `origin`; default: `auto`) — Audio control (video-edit only). auto = model decides; origin = keep input video audio.
  - `seed` (body, optional; integer) — Random seed [0, 2147483647]
  - `watermark` (body, optional; boolean; default: `true`) — DashScope watermark switch
  - `minor_suspected_skip` (body, optional; boolean; default: `false`)
  - `webhook_url` (body, optional; string; max length: 2048; example: `https://your-server.example.com/a2e/webhook`) — HTTPS URL to receive task.completed / task.failed notifications. Best-effort delivery, single attempt, no retries; clients should treat the detail API as the source of truth.
  - `webhook_token` (body, optional; string; max length: 256; example: `a-shared-secret`) — Optional plaintext token returned in the X-A2e-Webhook-Token header so receivers can verify the request originated from a2e.
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/userHappyhorseVideo/start" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "mode": "t2v",
  "model_version": "1.0",
  "duration": "5",
  "resolution": "720P",
  "ratio": "16:9",
  "audio_setting": "auto",
  "watermark": true,
  "minor_suspected_skip": false,
  "webhook_url": "https://your-server.example.com/a2e/webhook",
  "webhook_token": "a-shared-secret"
}
JSON
```
- Responses:
  - `200` — Task created successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/userHappyhorseVideo/allRecords — List HappyHorse tasks
Return the authenticated user's HappyHorse text-to-video, image-to-video, reference-to-video, and video-edit tasks using pagination. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supported query parameters: `pageNum`, `pageSize`. Omitted values use the defaults shown in the parameter schema. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userHappyhorseVideo/{_id}` — Get HappyHorse task details. - `DELETE /api/v1/userHappyhorseVideo/{_id}` — Delete a HappyHorse task. - `POST /api/v1/userHappyhorseVideo/start` — Start HappyHorse video generation task (T2V / I2V / R2V / Video-Edit) Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1UserHappyhorseVideoAllRecords`
- Request parameters:
  - `pageNum` (query, optional; integer; default: `1`; example: `1`) — pageNum parameter
  - `pageSize` (query, optional; integer; default: `10`; example: `10`) — pageSize parameter
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/userHappyhorseVideo/allRecords?pageNum=1&pageSize=10" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task list
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/userHappyhorseVideo/batchDetail — Batch query task details
Return up to 200 authenticated-user HappyHorse video tasks matching the submitted `ids`; callers should match records by identifier. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `ids`. ### Behavior - Fetches several task records in one request, reducing the number of individual detail calls. - Results remain subject to the same authentication and ownership checks as single-record lookups. - Match returned records by their identifiers instead of relying on response ordering. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userHappyhorseVideo/allRecords` — List HappyHorse tasks. - `GET /api/v1/userHappyhorseVideo/{_id}` — Get HappyHorse task details. - `DELETE /api/v1/userHappyhorseVideo/{_id}` — Delete a HappyHorse task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1UserHappyhorseVideoBatchDetail`
- JSON body fields:
  - `ids` (body, required; string[]; example: `["example"]`)
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/userHappyhorseVideo/batchDetail" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "ids": [
    "example"
  ]
}
JSON
```
- Responses:
  - `200` — Batch details
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/userHappyhorseVideo/{_id} — Get HappyHorse task details
Return the authenticated user's HappyHorse video task identified by `_id`, including its mode, current status, and video output fields. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Retrieves the current server-side representation of the requested resource or task. - For asynchronous tasks, inspect the documented status and result fields before consuming generated media. - Repeat the request only as needed for polling and stop after the task reaches a terminal state. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userHappyhorseVideo/allRecords` — List HappyHorse tasks. - `DELETE /api/v1/userHappyhorseVideo/{_id}` — Delete a HappyHorse task. - `POST /api/v1/userHappyhorseVideo/start` — Start HappyHorse video generation task (T2V / I2V / R2V / Video-Edit) Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1UserHappyhorseVideoId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — _id parameter
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/userHappyhorseVideo/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task detail
  - `401` — Unauthorized - Invalid or missing JWT token

##### DELETE /api/v1/userHappyhorseVideo/{_id} — Delete a HappyHorse task
Soft-delete the authenticated user's HappyHorse video task identified by `_id`. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Deletes or marks the selected resource as deleted according to the endpoint's documented lifecycle rules. - Use the resource identifier from a list, creation, or detail response; deleting one resource does not affect unrelated records. - Do not assume an in-progress task can be cancelled unless the endpoint explicitly documents that behavior. ### Response - A `200` response confirms that the deletion request was applied to the selected record. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userHappyhorseVideo/allRecords` — List HappyHorse tasks. - `GET /api/v1/userHappyhorseVideo/{_id}` — Get HappyHorse task details. - `POST /api/v1/userHappyhorseVideo/start` — Start HappyHorse video generation task (T2V / I2V / R2V / Video-Edit) Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `deleteApiV1UserHappyhorseVideoId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — _id parameter
- Example request:
```bash
curl -X DELETE "https://video.a2e.ai/api/v1/userHappyhorseVideo/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task deleted
  - `401` — Unauthorized - Invalid or missing JWT token
#### Seedance 1.5 Pro

##### POST /api/v1/seedanceVideo/start — Start Seedance 1.5 Pro video generation
Generate videos using BytePlus ModelArk Seedance 1.5 Pro. Supports 3 modes - text-to-video, image-to-video, first-last-frames. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `prompt`. - API-token callers may include `webhook_url` and `webhook_token` for best-effort terminal-state notifications; ordinary JWT/cookie calls ignore these fields. ### Behavior - This is an asynchronous operation: a successful submission creates a task and returns before processing finishes. - Persist the returned task identifier and use the corresponding detail or list operation to observe progress. - Treat the detail endpoint as the source of truth even when webhook delivery is enabled. ### Response - A `200` response confirms task acceptance; it does not by itself mean media generation has completed. - Retain the returned identifier and wait for a documented terminal status before using output URLs. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid parameters. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/seedanceVideo/allRecords` — Get all Seedance video records. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1SeedanceVideoStart`
- JSON body fields:
  - `name` (body, optional; string; example: `My Seedance Video`) — Name of the video generation task
  - `mode` (body, optional; string; allowed: `text-to-video`, `image-to-video`; default: `text-to-video`; example: `image-to-video`) — Generation mode. For first-last-frames usage, send mode=image-to-video together with image_url + end_image_url; the backend will normalize it.
  - `prompt` (body, required; string; example: `A girl holding a fox, the girl opens her eyes...`) — Text prompt describing the desired video
  - `image_url` (body, optional; string; example: `https://example.com/input.jpg`) — Input image URL (required for image-to-video mode; also used as the first frame in first-last-frames usage)
  - `end_image_url` (body, optional; string; example: `https://example.com/last.jpg`) — Last frame image URL. When provided together with image_url, mode is automatically treated as first-last-frames.
  - `duration` (body, optional; string; allowed: `5`, `10`; default: `5`) — Video duration in seconds
  - `aspect_ratio` (body, optional; string; allowed: `16:9`, `9:16`, `1:1`; default: `16:9`) — Video aspect ratio
  - `resolution` (body, optional; string; allowed: `480p`, `720p`; default: `720p`) — Video resolution
  - `camera_fixed` (body, optional; boolean; default: `false`) — Whether the camera is fixed
  - `generate_audio` (body, optional; boolean; default: `false`) — Whether to generate audio
  - `webhook_url` (body, optional; string; max length: 2048; example: `https://your-server.example.com/a2e/webhook`) — HTTPS URL to receive task.completed / task.failed notifications. Best-effort delivery, single attempt, no retries; clients should treat the detail API as the source of truth.
  - `webhook_token` (body, optional; string; max length: 256; example: `a-shared-secret`) — Optional plaintext token returned in the X-A2e-Webhook-Token header so receivers can verify the request originated from a2e.
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/seedanceVideo/start" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "name": "My Seedance Video",
  "mode": "image-to-video",
  "prompt": "A girl holding a fox, the girl opens her eyes...",
  "image_url": "https://example.com/input.jpg",
  "end_image_url": "https://example.com/last.jpg",
  "duration": "5",
  "aspect_ratio": "16:9",
  "resolution": "720p",
  "camera_fixed": false,
  "generate_audio": false,
  "webhook_url": "https://your-server.example.com/a2e/webhook",
  "webhook_token": "a-shared-secret"
}
JSON
```
- Responses:
  - `200` — Video generation task started successfully
  - `400` — Bad Request - Invalid parameters
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/seedanceVideo/allRecords — Get all Seedance video records
Retrieve all Seedance video generation records for the authenticated user. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supported query parameters: `pageNum`, `pageSize`. Omitted values use the defaults shown in the parameter schema. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `POST /api/v1/seedanceVideo/start` — Start Seedance 1.5 Pro video generation. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1SeedanceVideoAllRecords`
- Request parameters:
  - `pageNum` (query, optional; integer; default: `1`; example: `1`) — Page number
  - `pageSize` (query, optional; integer; default: `20`; example: `20`) — Items per page
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/seedanceVideo/allRecords?pageNum=1&pageSize=20" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Successfully retrieved records
  - `401` — Unauthorized - Invalid or missing JWT token
#### Seedance 2.x

##### POST /api/v1/seedance2Video/start — Start Seedance 2.x video generation
Generate videos with Seedance 2.0 (standard/mini/fast) or Seedance 2.5 (model_version=2.5). Supports text-to-video, image-to-video, first-last-frames, and reference modes. Image / video / audio inputs must be public URLs (asset:// URIs are not accepted from clients). Seedance 2.5 raises the limits: single-shot output up to 30s (2.0: 15s), up to 30 reference images / 10 reference videos / 10 reference audios (2.0: 9 / 3 / 3), reference video total duration up to 30s, resolution up to 1080p, and audio-only references are allowed (2.0 requires at least one image or video). ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `prompt`. - API-token callers may include `webhook_url` and `webhook_token` for best-effort terminal-state notifications; ordinary JWT/cookie calls ignore these fields. ### Behavior - This is an asynchronous operation: a successful submission creates a task and returns before processing finishes. - Persist the returned task identifier and use the corresponding detail or list operation to observe progress. - Treat the detail endpoint as the source of truth even when webhook delivery is enabled. ### Response - A `200` response confirms task acceptance; it does not by itself mean media generation has completed. - Retain the returned identifier and wait for a documented terminal status before using output URLs. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/seedance2Video/allRecords` — Get all records. - `GET /api/v1/seedance2Video/{_id}` — Get task detail. - `PUT /api/v1/seedance2Video/{_id}` — Rename task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1Seedance2VideoStart`
- JSON body fields:
  - `name` (body, optional; string)
  - `mode` (body, optional; string; allowed: `text-to-video`, `image-to-video`, `first-last-frames`, `reference`; default: `text-to-video`) — image-to-video uses image_url (+ optional last_frame_url); first-last-frames uses first_frame_url + last_frame_url; reference accepts any combination of reference_urls (image) / video_urls / audio_urls. On Seedance 2.0 audio cannot be used alone and must accompany at least one image or video reference; on Seedance 2.5 audio-only references are supported.
  - `model_version` (body, optional; string; allowed: `standard`, `mini`, `fast`, `2.5`; default: `standard`) — standard / mini / fast select a Seedance 2.0 tier. "2.5" selects Seedance 2.5, which currently has a single tier and higher input limits (see duration / reference_urls / video_urls / audio_urls).
  - `omni_reference_task_type` (body, optional; string; allowed: `reference`, `edit`, `extend`) — Seedance 2.5 reference-mode task hint. edit uses ratio=adaptive and duration=-1; extend uses ratio=adaptive; reference keeps the requested ratio and duration. edit currently accepts exactly one video_url. auto is intentionally not exposed because its output duration is unknown before billing.
  - `prompt` (body, required; string)
  - `image_url` (body, optional; string) — First frame for image-to-video mode.
  - `first_frame_url` (body, optional; string) — Required for first-last-frames mode.
  - `last_frame_url` (body, optional; string) — Optional last frame for image-to-video; required for first-last-frames.
  - `reference_urls` (body, optional; string[]; max items: 30) — Reference images for reference mode. Max 9 on Seedance 2.0, max 30 on Seedance 2.5.
  - `video_urls` (body, optional; string[]; max items: 10) — Reference videos (mp4/mov). Seedance 2.0: max 3 clips, each 2-15s, total <= 15 × number_of_videos seconds. Seedance 2.5: max 10 clips with a combined cap of 30s; omni_reference_task_type=edit currently requires exactly one clip. The server always probes video_urls (public hosts only, with separate connection/download/parse limits) as the authoritative duration for billing.
  - `audio_urls` (body, optional; string[]; max items: 10) — Reference audios (mp3/wav). Seedance 2.0: max 3 clips, each 2-15s, total <=15s, and audio cannot be used standalone (at least one image or video reference is required). Seedance 2.5: max 10 clips and audio-only references are allowed.
  - `input_video_duration` (body, optional; number; min: 2; max: 45.5) — Optional client estimate of the total reference-video duration in seconds. This value is never trusted for final billing: the server always probes video_urls and bills on max(measured, this value), so passing a smaller number does not lower the price. Must be within [2, 15 × number_of_videos] on Seedance 2.0 and within [2, 30] on Seedance 2.5.
  - `duration` (body, optional; integer; default: `5`) — Output length in seconds. Max 15 on Seedance 2.0; max 30 on Seedance 2.5. Seedance 2.5 edit tasks require -1.
  - `aspect_ratio` (body, optional; string; allowed: `adaptive`, `21:9`, `16:9`, `4:3`, `1:1`, `3:4`, `9:16`; default: `16:9`)
  - `resolution` (body, optional; string; allowed: `480p`, `720p`, `1080p`, `4k`; default: `720p`) — Only the standard tier of Seedance 2.0 supports 4k. Seedance 2.5 supports 480p / 720p / 1080p. The fast / mini tiers of Seedance 2.0 are limited to 480p / 720p.
  - `generate_audio` (body, optional; boolean; default: `true`) — Defaults to true to match billing (audio is included); pass false explicitly to disable.
  - `minor_suspected_skip` (body, optional; boolean; default: `false`) — Skip soft minor-suspect block (code 1004); hard CSAM block (code 1003) is always enforced.
  - `webhook_url` (body, optional; string; max length: 2048; example: `https://your-server.example.com/a2e/webhook`) — HTTPS URL to receive task.completed / task.failed notifications. Best-effort delivery, single attempt, no retries; clients should treat the detail API as the source of truth.
  - `webhook_token` (body, optional; string; max length: 256; example: `a-shared-secret`) — Optional plaintext token returned in the X-A2e-Webhook-Token header so receivers can verify the request originated from a2e.
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/seedance2Video/start" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "mode": "text-to-video",
  "model_version": "standard",
  "prompt": "<prompt>",
  "duration": 5,
  "aspect_ratio": "16:9",
  "resolution": "720p",
  "generate_audio": true,
  "minor_suspected_skip": false,
  "webhook_url": "https://your-server.example.com/a2e/webhook",
  "webhook_token": "a-shared-secret"
}
JSON
```
- Responses:
  - `200` — Task started successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/seedance2Video/allRecords — Get all records
List the current user's Seedance 2.0 video tasks with pagination. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supported query parameters: `pageNum`, `pageSize`. Omitted values use the defaults shown in the parameter schema. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/seedance2Video/{_id}` — Get task detail. - `PUT /api/v1/seedance2Video/{_id}` — Rename task. - `DELETE /api/v1/seedance2Video/{_id}` — Delete task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1Seedance2VideoAllRecords`
- Request parameters:
  - `pageNum` (query, optional; integer; default: `1`; example: `1`) — Page number (1-based)
  - `pageSize` (query, optional; integer; default: `20`; example: `20`) — Page size
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/seedance2Video/allRecords?pageNum=1&pageSize=20" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Success
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/seedance2Video/batchDetail — Batch get task details
Fetch multiple Seedance 2.0 video task records in a single request (up to 200 ids). ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `ids`. ### Behavior - Fetches several task records in one request, reducing the number of individual detail calls. - Results remain subject to the same authentication and ownership checks as single-record lookups. - Match returned records by their identifiers instead of relying on response ordering. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/seedance2Video/allRecords` — Get all records. - `GET /api/v1/seedance2Video/{_id}` — Get task detail. - `PUT /api/v1/seedance2Video/{_id}` — Rename task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1Seedance2VideoBatchDetail`
- JSON body fields:
  - `ids` (body, required; string[]; example: `["example"]`) — Task record ids (max 200)
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/seedance2Video/batchDetail" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "ids": [
    "example"
  ]
}
JSON
```
- Responses:
  - `200` — Success
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/seedance2Video/{_id} — Get task detail
Return the authenticated user's Seedance 2.0 video task identified by `_id`, including its generation settings, current status, and available video output. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Retrieves the current server-side representation of the requested resource or task. - For asynchronous tasks, inspect the documented status and result fields before consuming generated media. - Repeat the request only as needed for polling and stop after the task reaches a terminal state. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/seedance2Video/allRecords` — Get all records. - `PUT /api/v1/seedance2Video/{_id}` — Rename task. - `DELETE /api/v1/seedance2Video/{_id}` — Delete task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1Seedance2VideoId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — Task record id
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/seedance2Video/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Success
  - `401` — Unauthorized - Invalid or missing JWT token

##### PUT /api/v1/seedance2Video/{_id} — Rename task
Rename the authenticated user's Seedance 2.0 video task identified by `_id`; generation settings, processing status, and output media are unchanged. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. - Send an `application/json` body. Required fields: `name`. ### Behavior - Updates the identified resource using the fields accepted by the request schema and the operation's access controls. - Fields omitted from the request retain their existing values unless the schema states otherwise. - Read the returned record or call the detail operation to confirm the persisted state. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/seedance2Video/allRecords` — Get all records. - `GET /api/v1/seedance2Video/{_id}` — Get task detail. - `DELETE /api/v1/seedance2Video/{_id}` — Delete task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `putApiV1Seedance2VideoId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — Task record id
- JSON body fields:
  - `name` (body, required; string; example: `My Task`) — New task name
- Example request:
```bash
curl -X PUT "https://video.a2e.ai/api/v1/seedance2Video/507f1f77bcf86cd799439011" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "name": "My Task"
}
JSON
```
- Responses:
  - `200` — Updated
  - `401` — Unauthorized - Invalid or missing JWT token

##### DELETE /api/v1/seedance2Video/{_id} — Delete task
Remove the authenticated user's Seedance 2.0 video task identified by `_id` from normal task history without affecting unrelated tasks. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Deletes or marks the selected resource as deleted according to the endpoint's documented lifecycle rules. - Use the resource identifier from a list, creation, or detail response; deleting one resource does not affect unrelated records. - Do not assume an in-progress task can be cancelled unless the endpoint explicitly documents that behavior. ### Response - A `200` response confirms that the deletion request was applied to the selected record. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/seedance2Video/allRecords` — Get all records. - `GET /api/v1/seedance2Video/{_id}` — Get task detail. - `PUT /api/v1/seedance2Video/{_id}` — Rename task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `deleteApiV1Seedance2VideoId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — Task record id
- Example request:
```bash
curl -X DELETE "https://video.a2e.ai/api/v1/seedance2Video/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Deleted
  - `401` — Unauthorized - Invalid or missing JWT token
#### Veo Video

##### POST /api/v1/veoVideo/start — Start Veo 3.1 video generation
Generate videos using Google DeepMind's Veo 3.1 AI model. Supports text-to-video, image-to-video, and reference-based generation. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `prompt`. - API-token callers may include `webhook_url` and `webhook_token` for best-effort terminal-state notifications; ordinary JWT/cookie calls ignore these fields. ### Behavior - This is an asynchronous operation: a successful submission creates a task and returns before processing finishes. - Persist the returned task identifier and use the corresponding detail or list operation to observe progress. - Treat the detail endpoint as the source of truth even when webhook delivery is enabled. ### Response - A `200` response confirms task acceptance; it does not by itself mean media generation has completed. - Retain the returned identifier and wait for a documented terminal status before using output URLs. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid parameters. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `POST /api/v1/veoVideo/batchDetail` — Batch query task details. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1VeoVideoStart`
- JSON body fields:
  - `name` (body, optional; string; example: `My Veo Video`) — Name of the video generation task (optional, auto-generated if not provided)
  - `prompt` (body, required; string; example: `Two person street interview in New York City. Sample Dialogue: Host: "Did you hear the news?" Person: "Yes! Veo 3.1 is now available on A2E. If you want to see it, go check their website."`) — Text prompt describing the video content. Can be empty to use default placeholder text.
  - `generationType` (body, optional; string; allowed: `TEXT_2_VIDEO`, `FIRST_AND_LAST_FRAMES_2_VIDEO`, `REFERENCE_2_VIDEO`; default: `TEXT_2_VIDEO`; example: `TEXT_2_VIDEO`) — Type of generation (TEXT_2_VIDEO for text-only, FIRST_AND_LAST_FRAMES_2_VIDEO for image frames, REFERENCE_2_VIDEO for reference images)
  - `imageUrls` (body, optional; string[]; example: `["https://example.com/start_frame.jpg","https://example.com/end_frame.jpg"]`) — Image URLs for image-to-video generation. For FIRST_AND_LAST_FRAMES_2_VIDEO mode, 1-2 images (start/end frames). For REFERENCE_2_VIDEO mode, 1-3 reference images.
  - `model` (body, optional; string; allowed: `veo3`, `veo3_fast`; default: `veo3_fast`; example: `veo3_fast`) — Generation model (veo3 for quality, veo3_fast for speed)
  - `aspectRatio` (body, optional; string; allowed: `16:9`, `9:16`, `Auto`; default: `Auto`; example: `16:9`) — Video aspect ratio (Auto will determine automatically)
  - `watermark` (body, optional; string; example: `MyBrand`) — Custom watermark text (optional)
  - `seeds` (body, optional; number; example: `12345`) — Random seed for reproducible generation (10000-99999, optional)
  - `webhook_url` (body, optional; string; max length: 2048; example: `https://your-server.example.com/a2e/webhook`) — HTTPS URL to receive task.completed / task.failed notifications. Best-effort delivery, single attempt, no retries; clients should treat the detail API as the source of truth.
  - `webhook_token` (body, optional; string; max length: 256; example: `a-shared-secret`) — Optional plaintext token returned in the X-A2e-Webhook-Token header so receivers can verify the request originated from a2e.
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/veoVideo/start" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "name": "My Veo Video",
  "prompt": "Two person street interview in New York City. Sample Dialogue: Host: \"Did you hear the news?\" Person: \"Yes! Veo 3.1 is now available on A2E. If you want to see it, go check their website.\"",
  "generationType": "TEXT_2_VIDEO",
  "imageUrls": [
    "https://example.com/start_frame.jpg",
    "https://example.com/end_frame.jpg"
  ],
  "model": "veo3_fast",
  "aspectRatio": "16:9",
  "watermark": "MyBrand",
  "seeds": 12345,
  "webhook_url": "https://your-server.example.com/a2e/webhook",
  "webhook_token": "a-shared-secret"
}
JSON
```
- Responses:
  - `200` — Video generation task started successfully
  - `400` — Bad Request - Invalid parameters
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/veoVideo/allRecords — Get all Veo video records
Retrieve paginated list of user's Veo video generation records. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supported query parameters: `pageNum`, `pageSize`. Omitted values use the defaults shown in the parameter schema. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/veoVideo/{_id}` — Get Veo video detail. - `DELETE /api/v1/veoVideo/{_id}` — Delete Veo video record. - `GET /api/v1/veoVideo/{_id}/1080p` — Get 1080P HD video. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1VeoVideoAllRecords`
- Request parameters:
  - `pageNum` (query, optional; integer; default: `1`; example: `1`) — Page number
  - `pageSize` (query, optional; integer; default: `10`; example: `10`) — Number of records per page
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/veoVideo/allRecords?pageNum=1&pageSize=10" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Records retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/veoVideo/batchDetail — Batch query task details
Query details for multiple tasks at once by providing an array of task IDs. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `ids`. ### Behavior - Fetches several task records in one request, reducing the number of individual detail calls. - Results remain subject to the same authentication and ownership checks as single-record lookups. - Match returned records by their identifiers instead of relying on response ordering. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `POST /api/v1/veoVideo/start` — Start Veo 3.1 video generation. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1VeoVideoBatchDetail`
- JSON body fields:
  - `ids` (body, required; string[]; example: `["example"]`) — Array of task IDs to query
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/veoVideo/batchDetail" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "ids": [
    "example"
  ]
}
JSON
```
- Responses:
  - `200` — Batch details retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/veoVideo/{_id} — Get Veo video detail
Retrieve detailed information of a specific Veo video generation record. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Retrieves the current server-side representation of the requested resource or task. - For asynchronous tasks, inspect the documented status and result fields before consuming generated media. - Repeat the request only as needed for polling and stop after the task reaches a terminal state. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/veoVideo/allRecords` — Get all Veo video records. - `DELETE /api/v1/veoVideo/{_id}` — Delete Veo video record. - `GET /api/v1/veoVideo/{_id}/1080p` — Get 1080P HD video. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1VeoVideoId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — Video record ID
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/veoVideo/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Video detail retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### DELETE /api/v1/veoVideo/{_id} — Delete Veo video record
Soft-delete the authenticated user's Veo video task identified by `_id`, preserving the stored record while excluding it from normal task lists. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Deletes or marks the selected resource as deleted according to the endpoint's documented lifecycle rules. - Use the resource identifier from a list, creation, or detail response; deleting one resource does not affect unrelated records. - Do not assume an in-progress task can be cancelled unless the endpoint explicitly documents that behavior. ### Response - A `200` response confirms that the deletion request was applied to the selected record. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/veoVideo/allRecords` — Get all Veo video records. - `GET /api/v1/veoVideo/{_id}` — Get Veo video detail. - `GET /api/v1/veoVideo/{_id}/1080p` — Get 1080P HD video. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `deleteApiV1VeoVideoId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — Video record ID
- Example request:
```bash
curl -X DELETE "https://video.a2e.ai/api/v1/veoVideo/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Video record deleted successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/veoVideo/{_id}/1080p — Get 1080P HD video
Retrieve 1080P high-definition version of the video (only available for 16:9 aspect ratio) ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Reads the requested information without creating a generation task. - Use the returned fields as documented; availability may depend on the caller and current resource state. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Invalid aspect ratio or missing task ID. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/veoVideo/allRecords` — Get all Veo video records. - `GET /api/v1/veoVideo/{_id}` — Get Veo video detail. - `DELETE /api/v1/veoVideo/{_id}` — Delete Veo video record. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1VeoVideoId1080p`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — Video record ID
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/veoVideo/507f1f77bcf86cd799439011/1080p" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — 1080P video retrieved successfully
  - `202` — 1080P video is being processed, please try again later
  - `400` — Invalid aspect ratio or missing task ID
  - `401` — Unauthorized - Invalid or missing JWT token
#### Grok Video

##### POST /api/v1/grokVideo/start — Start Grok Imagine video generation
Generate videos using Grok Imagine. Supports both text-to-video and image-to-video modes. **Modes:** - `text-to-video`: Generate video from a text prompt. Requires `prompt`. - `image-to-video`: Generate video from a reference image. Requires at least one image in `image_urls` (or `image_url`). **Duration:** `6`, `10`, or `15` seconds. **Model version:** `legacy` (default) uses the existing Grok Imagine path. `1.5` uses Grok Imagine Video 1.5 and only supports `image-to-video`. **Mode:** `fun`, `normal` (default), or `spicy`. This is an asynchronous API. After calling this endpoint, poll `/api/v1/grokVideo/{_id}` to check task status until `current_status` becomes `completed` or `failed`. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body when using the optional controls documented in the request schema. - API-token callers may include `webhook_url` and `webhook_token` for best-effort terminal-state notifications; ordinary JWT/cookie calls ignore these fields. ### Behavior - This is an asynchronous operation: a successful submission creates a task and returns before processing finishes. - Persist the returned task identifier and use the corresponding detail or list operation to observe progress. - Treat the detail endpoint as the source of truth even when webhook delivery is enabled. ### Response - A `200` response confirms task acceptance; it does not by itself mean media generation has completed. - Retain the returned identifier and wait for a documented terminal status before using output URLs. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid parameters. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/grokVideo/allRecords` — Get Grok Video task list. - `GET /api/v1/grokVideo/{_id}` — Get Grok Video task detail. - `DELETE /api/v1/grokVideo/{_id}` — Delete Grok Video task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1GrokVideoStart`
- JSON body fields:
  - `name` (body, optional; string; example: `My Grok Video`) — Name of the video generation task (optional, for identifying the task)
  - `model_type` (body, optional; string; allowed: `text-to-video`, `image-to-video`; default: `text-to-video`; example: `text-to-video`) — Generation mode. `text-to-video` generates video from text prompt, `image-to-video` generates video from a reference image.
  - `model_version` (body, optional; string; allowed: `legacy`, `1.5`; default: `legacy`; example: `1.5`) — Model version. `1.5` uses Grok Imagine Video 1.5 and only supports image-to-video.
  - `prompt` (body, optional; string; example: `A cat playing with a ball of yarn in a cozy living room, warm lighting, cinematic style`) — Text prompt describing the video content. Required for text-to-video mode, optional for image-to-video mode.
  - `mode` (body, optional; string; allowed: `fun`, `normal`, `spicy`; default: `normal`; example: `normal`) — Generation style mode. For image-to-video, upstream may fallback spicy to normal.
  - `image_urls` (body, optional; string[]; example: `["https://example.com/reference.jpg"]`) — Array of reference image URLs for image-to-video mode. At least one image is required when `model_type` is `image-to-video`.
  - `image_url` (body, optional; string; example: `https://example.com/image.jpg`) — Single reference image URL (alternative to `image_urls`). Will be prepended to `image_urls` array.
  - `aspect_ratio` (body, optional; string; allowed: `auto`, `1:1`, `16:9`, `9:16`, `4:3`, `3:4`, `3:2`, `2:3`; default: `16:9`; example: `16:9`) — Video aspect ratio. Legacy text-to-video supports 1:1/16:9/9:16; legacy image-to-video can additionally accept 4:3/3:4/3:2/2:3 depending on the selected generation path. Grok 1.5 accepts the full list including auto.
  - `duration` (body, optional; string; allowed: `6`, `10`, `15`; default: `6`; example: `6`) — Video duration in seconds.
  - `nsfw_checker` (body, optional; boolean; default: `false`) — Whether to enable additional NSFW checking for Grok 1.5.
  - `webhook_url` (body, optional; string; max length: 2048; example: `https://your-server.example.com/a2e/webhook`) — HTTPS URL to receive task.completed / task.failed notifications. Best-effort delivery, single attempt, no retries; clients should treat the detail API as the source of truth.
  - `webhook_token` (body, optional; string; max length: 256; example: `a-shared-secret`) — Optional plaintext token returned in the X-A2e-Webhook-Token header so receivers can verify the request originated from a2e.
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/grokVideo/start" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "name": "My Grok Video",
  "model_type": "image-to-video",
  "model_version": "1.5",
  "prompt": "Bring the reference image to life with subtle, natural motion.",
  "image_url": "https://example.com/reference.jpg",
  "aspect_ratio": "16:9",
  "duration": "6"
}
JSON
```
- Responses:
  - `200` — Video generation task started successfully
  - `400` — Bad Request - Invalid parameters
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/grokVideo/allRecords — Get Grok Video task list
Retrieve paginated list of user's Grok Imagine video generation tasks, ordered by creation time (newest first). ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supported query parameters: `pageNum`, `pageSize`. Omitted values use the defaults shown in the parameter schema. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized. ### Related Operations - `GET /api/v1/grokVideo/{_id}` — Get Grok Video task detail. - `DELETE /api/v1/grokVideo/{_id}` — Delete Grok Video task. - `POST /api/v1/grokVideo/start` — Start Grok Imagine video generation. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1GrokVideoAllRecords`
- Request parameters:
  - `pageNum` (query, optional; integer; default: `1`; example: `1`) — Page number (starts from 1)
  - `pageSize` (query, optional; integer; default: `10`; example: `10`) — Number of items per page
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/grokVideo/allRecords?pageNum=1&pageSize=10" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task list retrieved successfully
  - `401` — Unauthorized

##### POST /api/v1/grokVideo/batchDetail — Batch query task details
Query details for multiple tasks at once by providing an array of task IDs. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `ids`. ### Behavior - Fetches several task records in one request, reducing the number of individual detail calls. - Results remain subject to the same authentication and ownership checks as single-record lookups. - Match returned records by their identifiers instead of relying on response ordering. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/grokVideo/allRecords` — Get Grok Video task list. - `GET /api/v1/grokVideo/{_id}` — Get Grok Video task detail. - `DELETE /api/v1/grokVideo/{_id}` — Delete Grok Video task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1GrokVideoBatchDetail`
- JSON body fields:
  - `ids` (body, required; string[]; example: `["example"]`) — Array of task IDs to query
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/grokVideo/batchDetail" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "ids": [
    "example"
  ]
}
JSON
```
- Responses:
  - `200` — Batch details retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/grokVideo/{_id} — Get Grok Video task detail
Retrieve detailed information of a specific Grok Imagine video generation task by ID. Use this endpoint to poll task status after creation. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Retrieves the current server-side representation of the requested resource or task. - For asynchronous tasks, inspect the documented status and result fields before consuming generated media. - Repeat the request only as needed for polling and stop after the task reaches a terminal state. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized. ### Related Operations - `GET /api/v1/grokVideo/allRecords` — Get Grok Video task list. - `DELETE /api/v1/grokVideo/{_id}` — Delete Grok Video task. - `POST /api/v1/grokVideo/start` — Start Grok Imagine video generation. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1GrokVideoId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — Task ID (MongoDB ObjectId)
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/grokVideo/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task detail retrieved successfully
  - `401` — Unauthorized

##### DELETE /api/v1/grokVideo/{_id} — Delete Grok Video task
Remove the authenticated user's Grok Imagine video task identified by `_id` from normal task history without affecting unrelated tasks. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Deletes or marks the selected resource as deleted according to the endpoint's documented lifecycle rules. - Use the resource identifier from a list, creation, or detail response; deleting one resource does not affect unrelated records. - Do not assume an in-progress task can be cancelled unless the endpoint explicitly documents that behavior. ### Response - A `200` response confirms that the deletion request was applied to the selected record. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized. ### Related Operations - `GET /api/v1/grokVideo/allRecords` — Get Grok Video task list. - `GET /api/v1/grokVideo/{_id}` — Get Grok Video task detail. - `POST /api/v1/grokVideo/start` — Start Grok Imagine video generation. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `deleteApiV1GrokVideoId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — Task ID (MongoDB ObjectId)
- Example request:
```bash
curl -X DELETE "https://video.a2e.ai/api/v1/grokVideo/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task deleted successfully
  - `401` — Unauthorized
#### Kling Video

##### POST /api/v1/klingVideo/start — Start Kling video generation
Generate videos using Kling Official API. **Modes:** - `text-to-video` – generate video from text prompt - `image-to-video` – generate video from an image (+ optional end frame in PRO) - `motion-control` – transfer motion from a video onto an image **Versions:** `2.6` (5s/10s) and `3.0` (standard/fast: 3s–15s) **Quality:** `std` (Standard), `pro` (Professional), or `4k` (Kling 3.0 Native 4K for text/image video). ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `mode`, `prompt`. - API-token callers may include `webhook_url` and `webhook_token` for best-effort terminal-state notifications; ordinary JWT/cookie calls ignore these fields. ### Behavior - This is an asynchronous operation: a successful submission creates a task and returns before processing finishes. - Persist the returned task identifier and use the corresponding detail or list operation to observe progress. - Treat the detail endpoint as the source of truth even when webhook delivery is enabled. ### Response - A `200` response confirms task acceptance; it does not by itself mean media generation has completed. - Retain the returned identifier and wait for a documented terminal status before using output URLs. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid parameters. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/klingVideo/allRecords` — Get all Kling video records. - `GET /api/v1/klingVideo/{_id}` — Get Kling video detail. - `PUT /api/v1/klingVideo/{_id}` — Update Kling video name. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1KlingVideoStart`
- JSON body fields:
  - `name` (body, optional; string; example: `My Kling Video`) — Name of the video generation task
  - `mode` (body, required; string; allowed: `text-to-video`, `image-to-video`, `motion-control`; example: `image-to-video`) — Generation mode: text-to-video, image-to-video, or motion-control
  - `prompt` (body, required; string; example: `A beautiful sunset over the ocean`) — Text prompt describing the desired video
  - `version` (body, optional; string; allowed: `2.6`, `3.0`; default: `2.6`; example: `3.0`) — Kling model version. 2.6 supports 5s/10s, 3.0 supports 5s/10s/15s
  - `model_version` (body, optional; string; allowed: `standard`, `fast`; default: `standard`; example: `fast`) — Kling 3.0 model variant. fast requires version=3.0, supports text-to-video/image-to-video, supports 3–15s, and uses resolution instead of quality_mode=4k.
  - `resolution` (body, optional; string; allowed: `720p`, `1080p`; default: `720p`; example: `720p`) — Output resolution for model_version=fast
  - `quality_mode` (body, optional; string; allowed: `std`, `pro`, `4k`; default: `std`; example: `std`) — Quality mode. 4K is only available for Kling 3.0 text-to-video and image-to-video
  - `duration` (body, optional; string; allowed: `3`, `4`, `5`, `6`, `7`, `8`, `9`, `10`, `11`, `12`, `13`, `14`, `15`; default: `5`; example: `5`) — Video duration in seconds. Kling 2.6 supports 5s/10s; Kling 3.0 supports 3–15s.
  - `image_url` (body, optional; string; example: `https://example.com/input.jpg`) — Input image URL (required for image-to-video and motion-control modes)
  - `video_url` (body, optional; string; example: `https://example.com/input.mp4`) — Input video URL (required for motion-control mode)
  - `aspect_ratio` (body, optional; string; allowed: `16:9`, `9:16`, `1:1`; default: `16:9`; example: `16:9`) — Video aspect ratio (text-to-video mode only)
  - `sound` (body, optional; boolean; default: `false`; example: `false`) — Enable audio generation. For v2.6 only available in PRO mode (STD does not support sound). v3.0 supports sound in STD/PRO. 4K is billed as a separate quality tier.
  - `end_image_url` (body, optional; string; example: `https://example.com/end_frame.jpg`) — End frame image URL (image-to-video + PRO mode only). Cannot be used with sound in v2.6
  - `character_orientation` (body, optional; string; allowed: `video`, `image`; default: `video`; example: `video`) — Character orientation for motion-control mode. 'image' limits duration to 3-10s, 'video' allows 3-30s
  - `negative_prompt` (body, optional; string; example: `blurry, low quality`) — Negative prompt to avoid certain elements
  - `seed` (body, optional; number; example: `12345`) — Random seed for reproducibility
  - `webhook_url` (body, optional; string; max length: 2048; example: `https://your-server.example.com/a2e/webhook`) — HTTPS URL to receive task.completed / task.failed notifications. Best-effort delivery, single attempt, no retries; clients should treat the detail API as the source of truth.
  - `webhook_token` (body, optional; string; max length: 256; example: `a-shared-secret`) — Optional plaintext token returned in the X-A2e-Webhook-Token header so receivers can verify the request originated from a2e.
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/klingVideo/start" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "name": "My Kling Video",
  "mode": "image-to-video",
  "prompt": "A beautiful sunset over the ocean",
  "version": "3.0",
  "model_version": "fast",
  "resolution": "720p",
  "quality_mode": "std",
  "duration": "5",
  "image_url": "https://example.com/input.jpg",
  "video_url": "https://example.com/input.mp4",
  "aspect_ratio": "16:9",
  "sound": false,
  "end_image_url": "https://example.com/end_frame.jpg",
  "character_orientation": "video",
  "negative_prompt": "blurry, low quality",
  "seed": 12345,
  "webhook_url": "https://your-server.example.com/a2e/webhook",
  "webhook_token": "a-shared-secret"
}
JSON
```
- Responses:
  - `200` — Video generation task started successfully
  - `400` — Bad Request - Invalid parameters
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/klingVideo/allRecords — Get all Kling video records
Retrieve all Kling video generation records for the authenticated user. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supported query parameters: `pageNum`, `pageSize`. Omitted values use the defaults shown in the parameter schema. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/klingVideo/{_id}` — Get Kling video detail. - `PUT /api/v1/klingVideo/{_id}` — Update Kling video name. - `DELETE /api/v1/klingVideo/{_id}` — Delete Kling video. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1KlingVideoAllRecords`
- Request parameters:
  - `pageNum` (query, optional; integer; default: `1`; example: `1`) — Page number
  - `pageSize` (query, optional; integer; default: `20`; example: `20`) — Items per page
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/klingVideo/allRecords?pageNum=1&pageSize=20" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Successfully retrieved records
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/klingVideo/batchDetail — Batch query task details
Query details for multiple tasks at once by providing an array of task IDs. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `ids`. ### Behavior - Fetches several task records in one request, reducing the number of individual detail calls. - Results remain subject to the same authentication and ownership checks as single-record lookups. - Match returned records by their identifiers instead of relying on response ordering. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/klingVideo/allRecords` — Get all Kling video records. - `GET /api/v1/klingVideo/{_id}` — Get Kling video detail. - `PUT /api/v1/klingVideo/{_id}` — Update Kling video name. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1KlingVideoBatchDetail`
- JSON body fields:
  - `ids` (body, required; string[]; example: `["example"]`) — Array of task IDs to query
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/klingVideo/batchDetail" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "ids": [
    "example"
  ]
}
JSON
```
- Responses:
  - `200` — Batch details retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/klingVideo/{_id} — Get Kling video detail
Get detailed information about a specific Kling video generation task. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Retrieves the current server-side representation of the requested resource or task. - For asynchronous tasks, inspect the documented status and result fields before consuming generated media. - Repeat the request only as needed for polling and stop after the task reaches a terminal state. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. - `404` — Task not found. ### Related Operations - `GET /api/v1/klingVideo/allRecords` — Get all Kling video records. - `PUT /api/v1/klingVideo/{_id}` — Update Kling video name. - `DELETE /api/v1/klingVideo/{_id}` — Delete Kling video. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1KlingVideoId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — Task ID
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/klingVideo/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Successfully retrieved task details
  - `401` — Unauthorized - Invalid or missing JWT token
  - `404` — Task not found

##### PUT /api/v1/klingVideo/{_id} — Update Kling video name
Rename the authenticated user's Kling video task identified by `_id`; generation settings, processing status, and output media are unchanged. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. - Send an `application/json` body. Required fields: `name`. ### Behavior - Updates the identified resource using the fields accepted by the request schema and the operation's access controls. - Fields omitted from the request retain their existing values unless the schema states otherwise. - Read the returned record or call the detail operation to confirm the persisted state. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. - `404` — Task not found. ### Related Operations - `GET /api/v1/klingVideo/allRecords` — Get all Kling video records. - `GET /api/v1/klingVideo/{_id}` — Get Kling video detail. - `DELETE /api/v1/klingVideo/{_id}` — Delete Kling video. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `putApiV1KlingVideoId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — Task ID
- JSON body fields:
  - `name` (body, required; string; example: `My Task`) — New name for the task
- Example request:
```bash
curl -X PUT "https://video.a2e.ai/api/v1/klingVideo/507f1f77bcf86cd799439011" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "name": "My Task"
}
JSON
```
- Responses:
  - `200` — Name updated successfully
  - `401` — Unauthorized - Invalid or missing JWT token
  - `404` — Task not found

##### DELETE /api/v1/klingVideo/{_id} — Delete Kling video
Remove the authenticated user's Kling video task identified by `_id` from normal task history without affecting unrelated tasks. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Deletes or marks the selected resource as deleted according to the endpoint's documented lifecycle rules. - Use the resource identifier from a list, creation, or detail response; deleting one resource does not affect unrelated records. - Do not assume an in-progress task can be cancelled unless the endpoint explicitly documents that behavior. ### Response - A `200` response confirms that the deletion request was applied to the selected record. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. - `404` — Task not found. ### Related Operations - `GET /api/v1/klingVideo/allRecords` — Get all Kling video records. - `GET /api/v1/klingVideo/{_id}` — Get Kling video detail. - `PUT /api/v1/klingVideo/{_id}` — Update Kling video name. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `deleteApiV1KlingVideoId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — Task ID
- Example request:
```bash
curl -X DELETE "https://video.a2e.ai/api/v1/klingVideo/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task deleted successfully
  - `401` — Unauthorized - Invalid or missing JWT token
  - `404` — Task not found
#### Kling Omni

##### POST /api/v1/klingOmni/start — Start Kling Omni video generation
Generate videos using Kling Omni API (model: kling-v3-omni). This is a simplified wrapper around the official Kling API. **Key Features:** - Multi-reference images: up to 7 images, use `<<<image_N>>>` tags in prompt - Multi-shot editing: AI Director (intelligence) or manual (customize) storyboard - Native sound generation via `sound` parameter - Flexible duration: 3–15 seconds **Simplified vs Official API:** - `image_list`: accepts `string[]` (image URLs); official uses `[{image_url, type?}]`, auto-converted on server - `sound`: accepts `boolean`; official uses `"on"/"off"`, auto-converted on server - `multi_prompt`: items need `prompt` + `duration`; server auto-adds `index` field for official API - `prompt` is required when `multi_shot=false` or `shot_type=intelligence` - `multi_prompt` total duration must equal `duration` when `shot_type=customize`. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body when using the optional controls documented in the request schema. - API-token callers may include `webhook_url` and `webhook_token` for best-effort terminal-state notifications; ordinary JWT/cookie calls ignore these fields. ### Behavior - This is an asynchronous operation: a successful submission creates a task and returns before processing finishes. - Persist the returned task identifier and use the corresponding detail or list operation to observe progress. - Treat the detail endpoint as the source of truth even when webhook delivery is enabled. ### Response - A `200` response confirms task acceptance; it does not by itself mean media generation has completed. - Retain the returned identifier and wait for a documented terminal status before using output URLs. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid parameters. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/klingOmni/allRecords` — Get all Kling Omni video records. - `GET /api/v1/klingOmni/{_id}` — Get Kling Omni video detail. - `PUT /api/v1/klingOmni/{_id}` — Update Kling Omni video name. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1KlingOmniStart`
- JSON body fields:
  - `name` (body, optional; string; example: `My Kling Omni Video`) — Task name (internal use)
  - `prompt` (body, optional; string; example: `<<<image_1>>> walks towards <<<image_2>>> in a sunny park`) — Text prompt. Use <<<image_N>>> to reference images. Required when multi_shot=false or shot_type=intelligence.
  - `image_list` (body, optional; string[]; example: `["https://example.com/ref1.jpg"]`) — Reference image URLs (up to 7, jpg/jpeg/png, max 10MB). Simplified: pass URLs directly; server converts to official [{image_url}] format.
  - `mode` (body, optional; string; allowed: `std`, `pro`; default: `std`) — Video generation mode. std=standard (720p), pro=professional (1080p)
  - `duration` (body, optional; string; default: `5`) — Video duration in seconds (3–15)
  - `aspect_ratio` (body, optional; string; allowed: `16:9`, `9:16`, `1:1`; default: `16:9`)
  - `sound` (body, optional; boolean; default: `false`) — Enable native sound generation. Simplified: pass boolean; server converts to official 'on'/'off'.
  - `multi_shot` (body, optional; boolean; default: `false`) — Enable multi-shot mode
  - `shot_type` (body, optional; string; allowed: `intelligence`, `customize`) — Shot type. Required when multi_shot=true.
  - `multi_prompt` (body, optional; object[]) — Manual storyboard (required when shot_type=customize, 1–6 items, total duration must equal duration). Server auto-adds index field for official API.
  - `webhook_url` (body, optional; string; max length: 2048; example: `https://your-server.example.com/a2e/webhook`) — HTTPS URL to receive task.completed / task.failed notifications. Best-effort delivery, single attempt, no retries; clients should treat the detail API as the source of truth.
  - `webhook_token` (body, optional; string; max length: 256; example: `a-shared-secret`) — Optional plaintext token returned in the X-A2e-Webhook-Token header so receivers can verify the request originated from a2e.
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/klingOmni/start" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "name": "My Kling Omni Video",
  "prompt": "<<<image_1>>> walks towards <<<image_2>>> in a sunny park",
  "image_list": [
    "https://example.com/ref1.jpg"
  ],
  "mode": "std",
  "duration": "5",
  "aspect_ratio": "16:9",
  "sound": false,
  "multi_shot": false,
  "webhook_url": "https://your-server.example.com/a2e/webhook",
  "webhook_token": "a-shared-secret"
}
JSON
```
- Responses:
  - `200` — Video generation task started successfully
  - `400` — Bad Request - Invalid parameters
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/klingOmni/allRecords — Get all Kling Omni video records
Retrieve paginated list of Kling Omni video generation tasks for the authenticated user. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supported query parameters: `pageNum`, `pageSize`. Omitted values use the defaults shown in the parameter schema. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized. ### Related Operations - `GET /api/v1/klingOmni/{_id}` — Get Kling Omni video detail. - `PUT /api/v1/klingOmni/{_id}` — Update Kling Omni video name. - `DELETE /api/v1/klingOmni/{_id}` — Delete Kling Omni video. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1KlingOmniAllRecords`
- Request parameters:
  - `pageNum` (query, optional; integer; default: `1`; example: `1`) — Page number
  - `pageSize` (query, optional; integer; default: `20`; example: `20`) — Number of records per page
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/klingOmni/allRecords?pageNum=1&pageSize=20" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Records retrieved successfully
  - `401` — Unauthorized

##### POST /api/v1/klingOmni/batchDetail — Batch get Kling Omni video details
Get details of multiple Kling Omni tasks by their IDs (max 200). ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `ids`. ### Behavior - Fetches several task records in one request, reducing the number of individual detail calls. - Results remain subject to the same authentication and ownership checks as single-record lookups. - Match returned records by their identifiers instead of relying on response ordering. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized. ### Related Operations - `GET /api/v1/klingOmni/allRecords` — Get all Kling Omni video records. - `GET /api/v1/klingOmni/{_id}` — Get Kling Omni video detail. - `PUT /api/v1/klingOmni/{_id}` — Update Kling Omni video name. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1KlingOmniBatchDetail`
- JSON body fields:
  - `ids` (body, required; string[]; example: `["example"]`) — Array of task IDs
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/klingOmni/batchDetail" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "ids": [
    "example"
  ]
}
JSON
```
- Responses:
  - `200` — Batch details retrieved successfully
  - `401` — Unauthorized

##### GET /api/v1/klingOmni/{_id} — Get Kling Omni video detail
Get detailed information about a specific Kling Omni video generation task. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Retrieves the current server-side representation of the requested resource or task. - For asynchronous tasks, inspect the documented status and result fields before consuming generated media. - Repeat the request only as needed for polling and stop after the task reaches a terminal state. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized. - `404` — Task not found. ### Related Operations - `GET /api/v1/klingOmni/allRecords` — Get all Kling Omni video records. - `PUT /api/v1/klingOmni/{_id}` — Update Kling Omni video name. - `DELETE /api/v1/klingOmni/{_id}` — Delete Kling Omni video. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1KlingOmniId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — Task ID
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/klingOmni/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task detail retrieved successfully
  - `401` — Unauthorized
  - `404` — Task not found

##### PUT /api/v1/klingOmni/{_id} — Update Kling Omni video name
Rename the authenticated user's Kling Omni video task identified by `_id`; generation settings, processing status, and output media are unchanged. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. - Send an `application/json` body. Required fields: `name`. ### Behavior - Updates the identified resource using the fields accepted by the request schema and the operation's access controls. - Fields omitted from the request retain their existing values unless the schema states otherwise. - Read the returned record or call the detail operation to confirm the persisted state. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized. - `404` — Task not found. ### Related Operations - `GET /api/v1/klingOmni/allRecords` — Get all Kling Omni video records. - `GET /api/v1/klingOmni/{_id}` — Get Kling Omni video detail. - `DELETE /api/v1/klingOmni/{_id}` — Delete Kling Omni video. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `putApiV1KlingOmniId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — Task ID
- JSON body fields:
  - `name` (body, required; string; example: `My Task`) — New name for the task
- Example request:
```bash
curl -X PUT "https://video.a2e.ai/api/v1/klingOmni/507f1f77bcf86cd799439011" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "name": "My Task"
}
JSON
```
- Responses:
  - `200` — Updated successfully
  - `401` — Unauthorized
  - `404` — Task not found

##### DELETE /api/v1/klingOmni/{_id} — Delete Kling Omni video
Soft-delete the authenticated user's Kling Omni video task identified by `_id`, preserving the stored record while excluding it from normal task lists. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Deletes or marks the selected resource as deleted according to the endpoint's documented lifecycle rules. - Use the resource identifier from a list, creation, or detail response; deleting one resource does not affect unrelated records. - Do not assume an in-progress task can be cancelled unless the endpoint explicitly documents that behavior. ### Response - A `200` response confirms that the deletion request was applied to the selected record. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized. - `404` — Task not found. ### Related Operations - `GET /api/v1/klingOmni/allRecords` — Get all Kling Omni video records. - `GET /api/v1/klingOmni/{_id}` — Get Kling Omni video detail. - `PUT /api/v1/klingOmni/{_id}` — Update Kling Omni video name. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `deleteApiV1KlingOmniId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — Task ID
- Example request:
```bash
curl -X DELETE "https://video.a2e.ai/api/v1/klingOmni/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Deleted successfully
  - `401` — Unauthorized
  - `404` — Task not found
#### Sora 2 Pro Video

##### POST /api/v1/soraVideo/start — Start Sora 2 Pro video generation (powered by Kling 3.0)
Generate videos using Kling 3.0 official API. Supports text-to-video and image-to-video. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `prompt`. - API-token callers may include `webhook_url` and `webhook_token` for best-effort terminal-state notifications; ordinary JWT/cookie calls ignore these fields. ### Behavior - This is an asynchronous operation: a successful submission creates a task and returns before processing finishes. - Persist the returned task identifier and use the corresponding detail or list operation to observe progress. - Treat the detail endpoint as the source of truth even when webhook delivery is enabled. ### Response - A `200` response confirms task acceptance; it does not by itself mean media generation has completed. - Retain the returned identifier and wait for a documented terminal status before using output URLs. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/soraVideo/allRecords` — List Sora 2 Pro records. - `GET /api/v1/soraVideo/{_id}` — Get Sora 2 Pro record detail. - `DELETE /api/v1/soraVideo/{_id}` — Delete Sora 2 Pro record. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1SoraVideoStart`
- JSON body fields:
  - `name` (body, optional; string) — Task name (optional)
  - `model_type` (body, optional; string; allowed: `text-to-video`, `image-to-video`; default: `image-to-video`) — Generation mode
  - `prompt` (body, required; string) — Text prompt for video generation
  - `image_urls` (body, optional; string[]) — Required when model_type=image-to-video
  - `aspect_ratio` (body, optional; string; allowed: `portrait`, `landscape`; default: `landscape`)
  - `duration_seconds` (body, optional; string; allowed: `5`, `10`, `15`; default: `5`)
  - `quality` (body, optional; string; allowed: `standard`, `high`; default: `standard`)
  - `webhook_url` (body, optional; string; max length: 2048; example: `https://your-server.example.com/a2e/webhook`) — HTTPS URL to receive task.completed / task.failed notifications. Best-effort delivery, single attempt, no retries; clients should treat the detail API as the source of truth.
  - `webhook_token` (body, optional; string; max length: 256; example: `a-shared-secret`) — Optional plaintext token returned in the X-A2e-Webhook-Token header so receivers can verify the request originated from a2e.
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/soraVideo/start" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "model_type": "image-to-video",
  "prompt": "<prompt>",
  "aspect_ratio": "landscape",
  "duration_seconds": "5",
  "quality": "standard",
  "webhook_url": "https://your-server.example.com/a2e/webhook",
  "webhook_token": "a-shared-secret"
}
JSON
```
- Responses:
  - `200` — Task created successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/soraVideo/allRecords — List Sora 2 Pro records
Return the authenticated user's Sora 2 Pro video tasks using the requested pagination controls. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supported query parameters: `pageNum`, `pageSize`. Omitted values use the defaults shown in the parameter schema. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/soraVideo/{_id}` — Get Sora 2 Pro record detail. - `DELETE /api/v1/soraVideo/{_id}` — Delete Sora 2 Pro record. - `POST /api/v1/soraVideo/start` — Start Sora 2 Pro video generation (powered by Kling 3.0) Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1SoraVideoAllRecords`
- Request parameters:
  - `pageNum` (query, optional; integer; default: `1`; example: `1`) — pageNum parameter
  - `pageSize` (query, optional; integer; default: `10`; example: `10`) — pageSize parameter
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/soraVideo/allRecords?pageNum=1&pageSize=10" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — OK
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/soraVideo/batchDetail — Batch get Sora 2 Pro video task details
Query details for multiple Sora 2 Pro video tasks at once by providing an array of task IDs. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `ids`. ### Behavior - Fetches several task records in one request, reducing the number of individual detail calls. - Results remain subject to the same authentication and ownership checks as single-record lookups. - Match returned records by their identifiers instead of relying on response ordering. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/soraVideo/allRecords` — List Sora 2 Pro records. - `GET /api/v1/soraVideo/{_id}` — Get Sora 2 Pro record detail. - `DELETE /api/v1/soraVideo/{_id}` — Delete Sora 2 Pro record. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1SoraVideoBatchDetail`
- JSON body fields:
  - `ids` (body, required; string[]; example: `["example"]`) — Array of task IDs to query
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/soraVideo/batchDetail" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "ids": [
    "example"
  ]
}
JSON
```
- Responses:
  - `200` — Task details
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/soraVideo/{_id} — Get Sora 2 Pro record detail
Return the authenticated user's Sora 2 Pro video task identified by `_id`, including its current status and video output fields. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Retrieves the current server-side representation of the requested resource or task. - For asynchronous tasks, inspect the documented status and result fields before consuming generated media. - Repeat the request only as needed for polling and stop after the task reaches a terminal state. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/soraVideo/allRecords` — List Sora 2 Pro records. - `DELETE /api/v1/soraVideo/{_id}` — Delete Sora 2 Pro record. - `POST /api/v1/soraVideo/start` — Start Sora 2 Pro video generation (powered by Kling 3.0) Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1SoraVideoId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — _id parameter
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/soraVideo/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — OK
  - `401` — Unauthorized - Invalid or missing JWT token

##### DELETE /api/v1/soraVideo/{_id} — Delete Sora 2 Pro record
Soft-delete the authenticated user's Sora 2 Pro video task identified by `_id`. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Deletes or marks the selected resource as deleted according to the endpoint's documented lifecycle rules. - Use the resource identifier from a list, creation, or detail response; deleting one resource does not affect unrelated records. - Do not assume an in-progress task can be cancelled unless the endpoint explicitly documents that behavior. ### Response - A `200` response confirms that the deletion request was applied to the selected record. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/soraVideo/allRecords` — List Sora 2 Pro records. - `GET /api/v1/soraVideo/{_id}` — Get Sora 2 Pro record detail. - `POST /api/v1/soraVideo/start` — Start Sora 2 Pro video generation (powered by Kling 3.0) Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `deleteApiV1SoraVideoId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — _id parameter
- Example request:
```bash
curl -X DELETE "https://video.a2e.ai/api/v1/soraVideo/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — OK
  - `401` — Unauthorized - Invalid or missing JWT token
#### Image Edit

##### POST /api/v1/userImageEdit/start — Start image editing task
Edit images using AI with different edit types like clothing or product editing. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `edit_type`, `image_urls`. - API-token callers may include `webhook_url` and `webhook_token` for best-effort terminal-state notifications; ordinary JWT/cookie calls ignore these fields. ### Behavior - This is an asynchronous operation: a successful submission creates a task and returns before processing finishes. - Persist the returned task identifier and use the corresponding detail or list operation to observe progress. - Treat the detail endpoint as the source of truth even when webhook delivery is enabled. ### Response - A `200` response confirms task acceptance; it does not by itself mean media generation has completed. - Retain the returned identifier and wait for a documented terminal status before using output URLs. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid parameters. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userImageEdit/allRecords` — Get all task records. - `GET /api/v1/userImageEdit/{_id}` — Get task details. - `DELETE /api/v1/userImageEdit/{_id}` — Delete task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1UserImageEditStart`
- JSON body fields:
  - `name` (body, optional; string; default: ``; example: `Clothing Edit`) — Name of the image edit task
  - `edit_type` (body, required; string; allowed: `clothing`, `product`; example: `clothing`) — Type of edit to perform
  - `image_urls` (body, required; string[]; min items: 2; example: `["https://example.com/image1.jpg","https://example.com/image2.jpg"]`) — Array of image URLs to edit (minimum 2)
  - `timeout` (body, optional; number; default: `120`; example: `120`) — Processing timeout in seconds
  - `webhook_url` (body, optional; string; max length: 2048; example: `https://your-server.example.com/a2e/webhook`) — HTTPS URL to receive task.completed / task.failed notifications. Best-effort delivery, single attempt, no retries; clients should treat the detail API as the source of truth.
  - `webhook_token` (body, optional; string; max length: 256; example: `a-shared-secret`) — Optional plaintext token returned in the X-A2e-Webhook-Token header so receivers can verify the request originated from a2e.
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/userImageEdit/start" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "name": "Clothing Edit",
  "edit_type": "clothing",
  "image_urls": [
    "https://example.com/image1.jpg",
    "https://example.com/image2.jpg"
  ],
  "timeout": 120,
  "webhook_url": "https://your-server.example.com/a2e/webhook",
  "webhook_token": "a-shared-secret"
}
JSON
```
- Responses:
  - `200` — Image edit task started successfully
  - `400` — Bad Request - Invalid parameters
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/userImageEdit/allRecords — Get all task records
Return the authenticated user's image-editing tasks, newest first, using the requested page number and page size. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supported query parameters: `pageNum`, `pageSize`. Omitted values use the defaults shown in the parameter schema. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userImageEdit/{_id}` — Get task details. - `DELETE /api/v1/userImageEdit/{_id}` — Delete task. - `POST /api/v1/userImageEdit/start` — Start image editing task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1UserImageEditAllRecords`
- Request parameters:
  - `pageNum` (query, optional; integer; min: 1; example: `1`) — Page number
  - `pageSize` (query, optional; integer; example: `10`) — Page size
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/userImageEdit/allRecords?pageNum=1&pageSize=10" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task list retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/userImageEdit/batchDetail — Batch query task details
Query details for multiple tasks at once by providing an array of task IDs. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `ids`. ### Behavior - Fetches several task records in one request, reducing the number of individual detail calls. - Results remain subject to the same authentication and ownership checks as single-record lookups. - Match returned records by their identifiers instead of relying on response ordering. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userImageEdit/allRecords` — Get all task records. - `GET /api/v1/userImageEdit/{_id}` — Get task details. - `DELETE /api/v1/userImageEdit/{_id}` — Delete task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1UserImageEditBatchDetail`
- JSON body fields:
  - `ids` (body, required; string[]; example: `["example"]`) — Array of task IDs to query
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/userImageEdit/batchDetail" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "ids": [
    "example"
  ]
}
JSON
```
- Responses:
  - `200` — Batch details retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/userImageEdit/{_id} — Get task details
Return the authenticated user's image-editing task identified by `_id`, including its current processing status and generated image fields. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Retrieves the current server-side representation of the requested resource or task. - For asynchronous tasks, inspect the documented status and result fields before consuming generated media. - Repeat the request only as needed for polling and stop after the task reaches a terminal state. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userImageEdit/allRecords` — Get all task records. - `DELETE /api/v1/userImageEdit/{_id}` — Delete task. - `POST /api/v1/userImageEdit/start` — Start image editing task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1UserImageEditId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — Task ID
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/userImageEdit/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task details retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### DELETE /api/v1/userImageEdit/{_id} — Delete task
Remove the authenticated user's image-editing task identified by `_id` from the task history without affecting other generated-image records. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Deletes or marks the selected resource as deleted according to the endpoint's documented lifecycle rules. - Use the resource identifier from a list, creation, or detail response; deleting one resource does not affect unrelated records. - Do not assume an in-progress task can be cancelled unless the endpoint explicitly documents that behavior. ### Response - A `200` response confirms that the deletion request was applied to the selected record. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userImageEdit/allRecords` — Get all task records. - `GET /api/v1/userImageEdit/{_id}` — Get task details. - `POST /api/v1/userImageEdit/start` — Start image editing task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `deleteApiV1UserImageEditId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — Task ID to delete
- Example request:
```bash
curl -X DELETE "https://video.a2e.ai/api/v1/userImageEdit/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task deleted successfully
  - `401` — Unauthorized - Invalid or missing JWT token

### Face & Body
#### Face Swap

##### POST /api/v1/userFaceSwapImage/add — Add a new face image for face swapping
Add a new face image to the user's face swap image collection. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `face_url`. ### Behavior - Validates the submitted payload and performs the operation described by the request schema. - Conditional fields, mutually exclusive inputs, limits, and defaults are enforced as documented by their schemas. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid parameters. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userFaceSwapImage/records` — Get user's face swap image records. - `DELETE /api/v1/userFaceSwapImage/{_id}` — Remove a face swap image. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1UserFaceSwapImageAdd`
- JSON body fields:
  - `face_url` (body, required; string; example: `https://example.com/face-image.jpg`) — URL of the face image to be used for face swapping
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/userFaceSwapImage/add" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "face_url": "https://example.com/face-image.jpg"
}
JSON
```
- Responses:
  - `200` — Face image added successfully
  - `400` — Bad Request - Invalid parameters
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/userFaceSwapImage/records — Get user's face swap image records
Return the authenticated user's saved face-swap source images and their reusable record identifiers. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - No request body or operation-specific parameters are required. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `DELETE /api/v1/userFaceSwapImage/{_id}` — Remove a face swap image. - `POST /api/v1/userFaceSwapImage/add` — Add a new face image for face swapping. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1UserFaceSwapImageRecords`
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/userFaceSwapImage/records" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Face swap image records retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### DELETE /api/v1/userFaceSwapImage/{_id} — Remove a face swap image
Delete a specific face swap image from the user's collection. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Deletes or marks the selected resource as deleted according to the endpoint's documented lifecycle rules. - Use the resource identifier from a list, creation, or detail response; deleting one resource does not affect unrelated records. - Do not assume an in-progress task can be cancelled unless the endpoint explicitly documents that behavior. ### Response - A `200` response confirms that the deletion request was applied to the selected record. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid ID format. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userFaceSwapImage/records` — Get user's face swap image records. - `POST /api/v1/userFaceSwapImage/add` — Add a new face image for face swapping. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `deleteApiV1UserFaceSwapImageId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — ID of the face swap image to delete
- Example request:
```bash
curl -X DELETE "https://video.a2e.ai/api/v1/userFaceSwapImage/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Face swap image deleted successfully
  - `400` — Bad Request - Invalid ID format
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/userFaceSwapPreview/add — Create a new face swap preview task
Create a face swap preview task using video and face image URLs. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `video_url`, `face_url`. ### Behavior - Validates the submitted payload and performs the operation described by the request schema. - Conditional fields, mutually exclusive inputs, limits, and defaults are enforced as documented by their schemas. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid parameters. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userFaceSwapPreview/status` — Get face swap preview status. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1UserFaceSwapPreviewAdd`
- JSON body fields:
  - `video_url` (body, required; string; example: `https://example.com/video.mp4`) — URL of the video to swap face in
  - `face_url` (body, required; string; example: `https://example.com/face.jpg`) — URL of the face image to swap with
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/userFaceSwapPreview/add" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "video_url": "https://example.com/video.mp4",
  "face_url": "https://example.com/face.jpg"
}
JSON
```
- Responses:
  - `200` — Face swap preview task created successfully
  - `400` — Bad Request - Invalid parameters
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/userFaceSwapPreview/status — Get face swap preview status
Check the processing status of a specific face swap preview task. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supported query parameters: `_id`. Omitted values use the defaults shown in the parameter schema. ### Behavior - Retrieves the current server-side representation of the requested resource or task. - For asynchronous tasks, inspect the documented status and result fields before consuming generated media. - Repeat the request only as needed for polling and stop after the task reaches a terminal state. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid task ID format. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `POST /api/v1/userFaceSwapPreview/add` — Create a new face swap preview task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1UserFaceSwapPreviewStatus`
- Request parameters:
  - `_id` (query, required; string; example: `507f1f77bcf86cd799439011`) — ID of the face swap preview task
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/userFaceSwapPreview/status?_id=507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Preview status retrieved successfully
  - `400` — Bad Request - Invalid task ID format
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/userFaceSwapTask/add — Create a new face swap task
Create a face swap task with video, face image, and optional cover image. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `name`, `video_url`, `face_url`. - API-token callers may include `webhook_url` and `webhook_token` for best-effort terminal-state notifications; ordinary JWT/cookie calls ignore these fields. ### Behavior - This is an asynchronous operation: a successful submission creates a task and returns before processing finishes. - Persist the returned task identifier and use the corresponding detail or list operation to observe progress. - Treat the detail endpoint as the source of truth even when webhook delivery is enabled. ### Response - A `200` response confirms task acceptance; it does not by itself mean media generation has completed. - Retain the returned identifier and wait for a documented terminal status before using output URLs. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid parameters. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userFaceSwapTask/records` — Get user's face swap task records. - `GET /api/v1/userFaceSwapTask/{_id}` — Get face swap task details. - `DELETE /api/v1/userFaceSwapTask/{_id}` — Delete face swap task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1UserFaceSwapTaskAdd`
- JSON body fields:
  - `name` (body, required; string; example: `My Face Swap Video`) — Name of the face swap task
  - `video_url` (body, required; string; example: `https://example.com/video.mp4`) — URL of the video to swap face in
  - `face_url` (body, required; string; example: `https://example.com/face.jpg`) — URL of the face image to swap with
  - `cover_url` (body, optional; string; example: `https://example.com/cover.jpg`) — Optional cover image URL
  - `model_version` (body, optional; string; allowed: `v1`, `v2`; example: `v1`) — Face swap model version: v1 (JAH pipeline, default), v2 (ComfyUI, image only)
  - `webhook_url` (body, optional; string; max length: 2048; example: `https://your-server.example.com/a2e/webhook`) — HTTPS URL to receive task.completed / task.failed notifications. Best-effort delivery, single attempt, no retries; clients should treat the detail API as the source of truth.
  - `webhook_token` (body, optional; string; max length: 256; example: `a-shared-secret`) — Optional plaintext token returned in the X-A2e-Webhook-Token header so receivers can verify the request originated from a2e.
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/userFaceSwapTask/add" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "name": "My Face Swap Video",
  "video_url": "https://example.com/video.mp4",
  "face_url": "https://example.com/face.jpg",
  "cover_url": "https://example.com/cover.jpg",
  "model_version": "v1",
  "webhook_url": "https://your-server.example.com/a2e/webhook",
  "webhook_token": "a-shared-secret"
}
JSON
```
- Responses:
  - `200` — Face swap task created successfully
  - `400` — Bad Request - Invalid parameters
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/userFaceSwapTask/records — Get user's face swap task records
Retrieve paginated list of face swap tasks for the authenticated user. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supported query parameters: `pageNum`, `pageSize`. Omitted values use the defaults shown in the parameter schema. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid pagination parameters. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userFaceSwapTask/{_id}` — Get face swap task details. - `DELETE /api/v1/userFaceSwapTask/{_id}` — Delete face swap task. - `POST /api/v1/userFaceSwapTask/add` — Create a new face swap task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1UserFaceSwapTaskRecords`
- Request parameters:
  - `pageNum` (query, required; integer; default: `1`; min: 1; example: `1`) — Page number (starts from 1)
  - `pageSize` (query, required; integer; default: `10`; min: 1; max: 100; example: `10`) — Number of records per page
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/userFaceSwapTask/records?pageNum=1&pageSize=10" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task records retrieved successfully
  - `400` — Bad Request - Invalid pagination parameters
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/userFaceSwapTask/status — Get user's face swap task status
Get overall face swap task status information for the authenticated user. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - No request body or operation-specific parameters are required. ### Behavior - Retrieves the current server-side representation of the requested resource or task. - For asynchronous tasks, inspect the documented status and result fields before consuming generated media. - Repeat the request only as needed for polling and stop after the task reaches a terminal state. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userFaceSwapTask/records` — Get user's face swap task records. - `GET /api/v1/userFaceSwapTask/{_id}` — Get face swap task details. - `DELETE /api/v1/userFaceSwapTask/{_id}` — Delete face swap task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1UserFaceSwapTaskStatus`
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/userFaceSwapTask/status" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task status retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/userFaceSwapTask/batchDetail — Batch query task details
Query details for multiple tasks at once by providing an array of task IDs. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `ids`. ### Behavior - Fetches several task records in one request, reducing the number of individual detail calls. - Results remain subject to the same authentication and ownership checks as single-record lookups. - Match returned records by their identifiers instead of relying on response ordering. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userFaceSwapTask/records` — Get user's face swap task records. - `GET /api/v1/userFaceSwapTask/{_id}` — Get face swap task details. - `DELETE /api/v1/userFaceSwapTask/{_id}` — Delete face swap task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1UserFaceSwapTaskBatchDetail`
- JSON body fields:
  - `ids` (body, required; string[]; example: `["example"]`) — Array of task IDs to query
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/userFaceSwapTask/batchDetail" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "ids": [
    "example"
  ]
}
JSON
```
- Responses:
  - `200` — Batch details retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/userFaceSwapTask/{_id} — Get face swap task details
Retrieve detailed information about a specific face swap task. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Retrieves the current server-side representation of the requested resource or task. - For asynchronous tasks, inspect the documented status and result fields before consuming generated media. - Repeat the request only as needed for polling and stop after the task reaches a terminal state. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid task ID format. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userFaceSwapTask/records` — Get user's face swap task records. - `DELETE /api/v1/userFaceSwapTask/{_id}` — Delete face swap task. - `POST /api/v1/userFaceSwapTask/add` — Create a new face swap task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1UserFaceSwapTaskId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — ID of the face swap task
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/userFaceSwapTask/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task details retrieved successfully
  - `400` — Bad Request - Invalid task ID format
  - `401` — Unauthorized - Invalid or missing JWT token

##### DELETE /api/v1/userFaceSwapTask/{_id} — Delete face swap task
Delete a face swap task from the user's collection (DELETE method) ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Deletes or marks the selected resource as deleted according to the endpoint's documented lifecycle rules. - Use the resource identifier from a list, creation, or detail response; deleting one resource does not affect unrelated records. - Do not assume an in-progress task can be cancelled unless the endpoint explicitly documents that behavior. ### Response - A `200` response confirms that the deletion request was applied to the selected record. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid task ID format. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userFaceSwapTask/records` — Get user's face swap task records. - `GET /api/v1/userFaceSwapTask/{_id}` — Get face swap task details. - `POST /api/v1/userFaceSwapTask/add` — Create a new face swap task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `deleteApiV1UserFaceSwapTaskId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — ID of the face swap task to delete
- Example request:
```bash
curl -X DELETE "https://video.a2e.ai/api/v1/userFaceSwapTask/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task deleted successfully
  - `400` — Bad Request - Invalid task ID format
  - `401` — Unauthorized - Invalid or missing JWT token
#### Head Swap

##### POST /api/v1/headSwap/start — Start head swap generation
Generate a head swap result by replacing the head in a target image/video with a source head. **Supported modes:** - **Image to Image**: Provide an image as `target_image_url` to get a head-swapped image - **Image to Video**: Provide a video as `target_image_url` to get a head-swapped video (max 15 seconds) **Content moderation:** - Minor detection is performed on input images - If a minor is detected (age < 10), the request will be rejected with code 1003 - If a suspected minor is detected (10 <= age < 15), set `minor_suspected_skip: true` to proceed **Async workflow:** 1. Task is created with status `initialized` 2. Task is queued and sent to algorithm service (status: `sent`) 3. Algorithm processes the task (status: `processing`) 4. Result is ready (status: `completed`) or failed (status: `failed`) 5. Use `/api/v1/headSwap/{_id}` to poll for status updates. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `image_url`, `target_image_url`. - API-token callers may include `webhook_url` and `webhook_token` for best-effort terminal-state notifications; ordinary JWT/cookie calls ignore these fields. ### Behavior - This is an asynchronous operation: a successful submission creates a task and returns before processing finishes. - Persist the returned task identifier and use the corresponding detail or list operation to observe progress. - Treat the detail endpoint as the source of truth even when webhook delivery is enabled. ### Response - A `200` response confirms task acceptance; it does not by itself mean media generation has completed. - Retain the returned identifier and wait for a documented terminal status before using output URLs. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Invalid request parameters or insufficient coins. - `401` — Unauthorized - Invalid or missing JWT token. - `403` — Content moderation failed (code 1003 = minor detected, code 1004 = suspected minor) ### Related Operations - `GET /api/v1/headSwap/allRecords` — Get all head swap records. - `GET /api/v1/headSwap/{_id}` — Get head swap task detail. - `DELETE /api/v1/headSwap/{_id}` — Delete head swap task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1HeadSwapStart`
- JSON body fields:
  - `image_url` (body, required; string; format: uri; example: `https://example.com/head.jpg`) — URL of the source head image (the head to be transplanted)
  - `target_image_url` (body, required; string; format: uri; example: `https://example.com/body.jpg`) — URL of the target body image or video (where the head will be placed)
  - `minor_suspected_skip` (body, optional; boolean; default: `false`; example: `false`) — Skip suspected minor warning (for ages 10-14). Use with caution.
  - `webhook_url` (body, optional; string; max length: 2048; example: `https://your-server.example.com/a2e/webhook`) — HTTPS URL to receive task.completed / task.failed notifications. Best-effort delivery, single attempt, no retries; clients should treat the detail API as the source of truth.
  - `webhook_token` (body, optional; string; max length: 256; example: `a-shared-secret`) — Optional plaintext token returned in the X-A2e-Webhook-Token header so receivers can verify the request originated from a2e.
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/headSwap/start" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "image_url": "https://example.com/head.jpg",
  "target_image_url": "https://example.com/body.jpg",
  "minor_suspected_skip": false,
  "webhook_url": "https://your-server.example.com/a2e/webhook",
  "webhook_token": "a-shared-secret"
}
JSON
```
- Responses:
  - `200` — Head swap task started successfully
  - `400` — Invalid request parameters or insufficient coins
  - `401` — Unauthorized - Invalid or missing JWT token
  - `403` — Content moderation failed (code 1003 = minor detected, code 1004 = suspected minor)

##### GET /api/v1/headSwap/allRecords — Get all head swap records
Get a paginated list of the current user's head swap tasks. Results are sorted by creation time (newest first) and filtered by expiration. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supported query parameters: `pageNum`, `pageSize`. Omitted values use the defaults shown in the parameter schema. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/headSwap/{_id}` — Get head swap task detail. - `DELETE /api/v1/headSwap/{_id}` — Delete head swap task. - `POST /api/v1/headSwap/start` — Start head swap generation. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1HeadSwapAllRecords`
- Request parameters:
  - `pageNum` (query, optional; integer; default: `1`; min: 1; example: `1`) — Page number (starts from 1)
  - `pageSize` (query, optional; integer; default: `10`; min: 1; max: 100; example: `10`) — Number of items per page
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/headSwap/allRecords?pageNum=1&pageSize=10" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Head swap records retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/headSwap/batchDetail — Batch query task details
Query details for multiple tasks at once by providing an array of task IDs. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `ids`. ### Behavior - Fetches several task records in one request, reducing the number of individual detail calls. - Results remain subject to the same authentication and ownership checks as single-record lookups. - Match returned records by their identifiers instead of relying on response ordering. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/headSwap/allRecords` — Get all head swap records. - `GET /api/v1/headSwap/{_id}` — Get head swap task detail. - `DELETE /api/v1/headSwap/{_id}` — Delete head swap task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1HeadSwapBatchDetail`
- JSON body fields:
  - `ids` (body, required; string[]; example: `["example"]`) — Array of task IDs to query
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/headSwap/batchDetail" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "ids": [
    "example"
  ]
}
JSON
```
- Responses:
  - `200` — Batch details retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/headSwap/{_id} — Get head swap task detail
Get detailed information of a specific head swap task by ID. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Retrieves the current server-side representation of the requested resource or task. - For asynchronous tasks, inspect the documented status and result fields before consuming generated media. - Repeat the request only as needed for polling and stop after the task reaches a terminal state. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Invalid task ID format. - `401` — Unauthorized - Invalid or missing JWT token. - `404` — Task not found. ### Related Operations - `GET /api/v1/headSwap/allRecords` — Get all head swap records. - `DELETE /api/v1/headSwap/{_id}` — Delete head swap task. - `POST /api/v1/headSwap/start` — Start head swap generation. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1HeadSwapId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — Head swap task ID (MongoDB ObjectId)
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/headSwap/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task detail retrieved successfully
  - `400` — Invalid task ID format
  - `401` — Unauthorized - Invalid or missing JWT token
  - `404` — Task not found

##### DELETE /api/v1/headSwap/{_id} — Delete head swap task
Delete a head swap task by ID. **Status behavior:** - `initialized`: Can be deleted with coin refund (task not yet sent to algorithm service) - `sent/pending/processing`: Cannot be deleted, returns 400 error (task is processing) - `completed/failed`: Can be deleted without refund (task already completed or failed) ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Deletes or marks the selected resource as deleted according to the endpoint's documented lifecycle rules. - Use the resource identifier from a list, creation, or detail response; deleting one resource does not affect unrelated records. - Do not assume an in-progress task can be cancelled unless the endpoint explicitly documents that behavior. ### Response - A `200` response confirms that the deletion request was applied to the selected record. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Cannot delete task in processing state. - `401` — Unauthorized - Invalid or missing JWT token. - `404` — Task not found. ### Related Operations - `GET /api/v1/headSwap/allRecords` — Get all head swap records. - `GET /api/v1/headSwap/{_id}` — Get head swap task detail. - `POST /api/v1/headSwap/start` — Start head swap generation. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `deleteApiV1HeadSwapId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — Head swap task ID (MongoDB ObjectId)
- Example request:
```bash
curl -X DELETE "https://video.a2e.ai/api/v1/headSwap/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task deleted successfully
  - `400` — Cannot delete task in processing state
  - `401` — Unauthorized - Invalid or missing JWT token
  - `404` — Task not found
#### Actor Swap

##### POST /api/v1/actorSwap/start — Start actor swap task
Generate actor swap video by swapping actor from image to video. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `image_url`, `video_url`. - API-token callers may include `webhook_url` and `webhook_token` for best-effort terminal-state notifications; ordinary JWT/cookie calls ignore these fields. ### Behavior - This is an asynchronous operation: a successful submission creates a task and returns before processing finishes. - Persist the returned task identifier and use the corresponding detail or list operation to observe progress. - Treat the detail endpoint as the source of truth even when webhook delivery is enabled. ### Response - A `200` response confirms task acceptance; it does not by itself mean media generation has completed. - Retain the returned identifier and wait for a documented terminal status before using output URLs. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/actorSwap/allRecords` — Get all task records. - `GET /api/v1/actorSwap/{_id}` — Get task details. - `DELETE /api/v1/actorSwap/{_id}` — Delete task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1ActorSwapStart`
- JSON body fields:
  - `name` (body, optional; string; example: `My Actor Swap`) — Name of the actor swap task
  - `image_url` (body, required; string; format: uri; example: `https://example.com/actor.jpg`) — URL of the reference actor image
  - `video_url` (body, required; string; format: uri; example: `https://example.com/video.mp4`) — URL of the control video
  - `prompt` (body, optional; string; example: `high quality, realistic`) — Positive prompt for generation
  - `negative_prompt` (body, optional; string; example: `blurry, distorted`) — Negative prompt to avoid unwanted features
  - `timeout` (body, optional; integer; default: `300`; example: `300`) — Timeout in seconds
  - `webhook_url` (body, optional; string; max length: 2048; example: `https://your-server.example.com/a2e/webhook`) — HTTPS URL to receive task.completed / task.failed notifications. Best-effort delivery, single attempt, no retries; clients should treat the detail API as the source of truth.
  - `webhook_token` (body, optional; string; max length: 256; example: `a-shared-secret`) — Optional plaintext token returned in the X-A2e-Webhook-Token header so receivers can verify the request originated from a2e.
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/actorSwap/start" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "name": "My Actor Swap",
  "image_url": "https://example.com/actor.jpg",
  "video_url": "https://example.com/video.mp4",
  "prompt": "high quality, realistic",
  "negative_prompt": "blurry, distorted",
  "timeout": 300,
  "webhook_url": "https://your-server.example.com/a2e/webhook",
  "webhook_token": "a-shared-secret"
}
JSON
```
- Responses:
  - `200` — Actor swap task started successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/actorSwap/allRecords — Get all task records
Return the authenticated user's actor-swap tasks, newest first, using the requested page number and page size. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supported query parameters: `pageNum`, `pageSize`. Omitted values use the defaults shown in the parameter schema. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/actorSwap/{_id}` — Get task details. - `DELETE /api/v1/actorSwap/{_id}` — Delete task. - `POST /api/v1/actorSwap/start` — Start actor swap task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1ActorSwapAllRecords`
- Request parameters:
  - `pageNum` (query, optional; integer; min: 1; example: `1`) — Page number
  - `pageSize` (query, optional; integer; example: `10`) — Page size
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/actorSwap/allRecords?pageNum=1&pageSize=10" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task list retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/actorSwap/batchDetail — Batch query task details
Query details for multiple tasks at once by providing an array of task IDs. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `ids`. ### Behavior - Fetches several task records in one request, reducing the number of individual detail calls. - Results remain subject to the same authentication and ownership checks as single-record lookups. - Match returned records by their identifiers instead of relying on response ordering. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/actorSwap/allRecords` — Get all task records. - `GET /api/v1/actorSwap/{_id}` — Get task details. - `DELETE /api/v1/actorSwap/{_id}` — Delete task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1ActorSwapBatchDetail`
- JSON body fields:
  - `ids` (body, required; string[]; example: `["example"]`) — Array of task IDs to query
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/actorSwap/batchDetail" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "ids": [
    "example"
  ]
}
JSON
```
- Responses:
  - `200` — Batch details retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/actorSwap/{_id} — Get task details
Return the authenticated user's actor-swap task identified by `_id`, including its current processing status and available video output. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Retrieves the current server-side representation of the requested resource or task. - For asynchronous tasks, inspect the documented status and result fields before consuming generated media. - Repeat the request only as needed for polling and stop after the task reaches a terminal state. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/actorSwap/allRecords` — Get all task records. - `DELETE /api/v1/actorSwap/{_id}` — Delete task. - `POST /api/v1/actorSwap/start` — Start actor swap task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1ActorSwapId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — Task ID
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/actorSwap/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task details retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### DELETE /api/v1/actorSwap/{_id} — Delete task
Remove the authenticated user's actor-swap task identified by `_id` from the task history without affecting other generated videos. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Deletes or marks the selected resource as deleted according to the endpoint's documented lifecycle rules. - Use the resource identifier from a list, creation, or detail response; deleting one resource does not affect unrelated records. - Do not assume an in-progress task can be cancelled unless the endpoint explicitly documents that behavior. ### Response - A `200` response confirms that the deletion request was applied to the selected record. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/actorSwap/allRecords` — Get all task records. - `GET /api/v1/actorSwap/{_id}` — Get task details. - `POST /api/v1/actorSwap/start` — Start actor swap task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `deleteApiV1ActorSwapId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — Task ID to delete
- Example request:
```bash
curl -X DELETE "https://video.a2e.ai/api/v1/actorSwap/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task deleted successfully
  - `401` — Unauthorized - Invalid or missing JWT token
#### Talking Photo

##### POST /api/v1/talkingPhoto/start — Start talking photo generation
Create an asynchronous talking-photo task from the submitted portrait image and audio or text input, then return the task record used to monitor video generation. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `name`, `image_url`, `prompt`, `negative_prompt`. - API-token callers may include `webhook_url` and `webhook_token` for best-effort terminal-state notifications; ordinary JWT/cookie calls ignore these fields. ### Behavior - This is an asynchronous operation: a successful submission creates a task and returns before processing finishes. - Persist the returned task identifier and use the corresponding detail or list operation to observe progress. - Treat the detail endpoint as the source of truth even when webhook delivery is enabled. ### Response - A `200` response confirms task acceptance; it does not by itself mean media generation has completed. - Retain the returned identifier and wait for a documented terminal status before using output URLs. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid parameters. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/talkingPhoto/allRecords` — Get all task records. - `GET /api/v1/talkingPhoto/{_id}` — Get task details. - `DELETE /api/v1/talkingPhoto/{_id}` — Delete task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1TalkingPhotoStart`
- JSON body fields:
  - `name` (body, required; string; example: `My Talking Photo`) — Name of the talking photo task
  - `image_url` (body, required; string; example: `https://example.com/photo.jpg`) — URL of the source image
  - `audio_url` (body, optional; string; example: `https://example.com/audio.mp3`) — Optional audio URL
  - `duration` (body, optional; integer; default: `3`; min: 1; max: 20; example: `5`) — Duration in seconds
  - `prompt` (body, required; string; example: `Make this person smile and speak`) — Generation prompt
  - `negative_prompt` (body, required; string; example: `blurry, distorted`) — Negative prompt to avoid unwanted features
  - `webhook_url` (body, optional; string; max length: 2048; example: `https://your-server.example.com/a2e/webhook`) — HTTPS URL to receive task.completed / task.failed notifications. Best-effort delivery, single attempt, no retries; clients should treat the detail API as the source of truth.
  - `webhook_token` (body, optional; string; max length: 256; example: `a-shared-secret`) — Optional plaintext token returned in the X-A2e-Webhook-Token header so receivers can verify the request originated from a2e.
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/talkingPhoto/start" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "name": "My Talking Photo",
  "image_url": "https://example.com/photo.jpg",
  "audio_url": "https://example.com/audio.mp3",
  "duration": 5,
  "prompt": "Make this person smile and speak",
  "negative_prompt": "blurry, distorted",
  "webhook_url": "https://your-server.example.com/a2e/webhook",
  "webhook_token": "a-shared-secret"
}
JSON
```
- Responses:
  - `200` — Talking photo task started successfully
  - `400` — Bad Request - Invalid parameters
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/talkingPhoto/allRecords — Get all task records
Return the authenticated user's talking-photo tasks, newest first, using the requested page number and page size. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supported query parameters: `pageNum`, `pageSize`. Omitted values use the defaults shown in the parameter schema. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/talkingPhoto/{_id}` — Get task details. - `DELETE /api/v1/talkingPhoto/{_id}` — Delete task. - `POST /api/v1/talkingPhoto/start` — Start talking photo generation. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1TalkingPhotoAllRecords`
- Request parameters:
  - `pageNum` (query, optional; integer; min: 1; example: `1`) — Page number
  - `pageSize` (query, optional; integer; example: `10`) — Page size
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/talkingPhoto/allRecords?pageNum=1&pageSize=10" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task list retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/talkingPhoto/batchDetail — Batch query task details
Query details for multiple tasks at once by providing an array of task IDs. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `ids`. ### Behavior - Fetches several task records in one request, reducing the number of individual detail calls. - Results remain subject to the same authentication and ownership checks as single-record lookups. - Match returned records by their identifiers instead of relying on response ordering. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/talkingPhoto/allRecords` — Get all task records. - `GET /api/v1/talkingPhoto/{_id}` — Get task details. - `DELETE /api/v1/talkingPhoto/{_id}` — Delete task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1TalkingPhotoBatchDetail`
- JSON body fields:
  - `ids` (body, required; string[]; example: `["example"]`) — Array of task IDs to query
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/talkingPhoto/batchDetail" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "ids": [
    "example"
  ]
}
JSON
```
- Responses:
  - `200` — Batch details retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/talkingPhoto/{_id} — Get task details
Return the authenticated user's talking-photo task identified by `_id`, including its current processing status and available video output. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Retrieves the current server-side representation of the requested resource or task. - For asynchronous tasks, inspect the documented status and result fields before consuming generated media. - Repeat the request only as needed for polling and stop after the task reaches a terminal state. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/talkingPhoto/allRecords` — Get all task records. - `DELETE /api/v1/talkingPhoto/{_id}` — Delete task. - `POST /api/v1/talkingPhoto/start` — Start talking photo generation. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1TalkingPhotoId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — Task ID
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/talkingPhoto/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task details retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### DELETE /api/v1/talkingPhoto/{_id} — Delete task
Remove the authenticated user's talking-photo task identified by `_id` from the task history without affecting other generated videos. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Deletes or marks the selected resource as deleted according to the endpoint's documented lifecycle rules. - Use the resource identifier from a list, creation, or detail response; deleting one resource does not affect unrelated records. - Do not assume an in-progress task can be cancelled unless the endpoint explicitly documents that behavior. ### Response - A `200` response confirms that the deletion request was applied to the selected record. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/talkingPhoto/allRecords` — Get all task records. - `GET /api/v1/talkingPhoto/{_id}` — Get task details. - `POST /api/v1/talkingPhoto/start` — Start talking photo generation. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `deleteApiV1TalkingPhotoId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — Task ID to delete
- Example request:
```bash
curl -X DELETE "https://video.a2e.ai/api/v1/talkingPhoto/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task deleted successfully
  - `401` — Unauthorized - Invalid or missing JWT token
#### Talking Video

##### POST /api/v1/talkingVideo/start — Start talking video generation
Create an asynchronous talking-video task from the submitted source video and audio or text input, then return the record used to monitor generation. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `name`, `video_url`, `prompt`, `negative_prompt`. - API-token callers may include `webhook_url` and `webhook_token` for best-effort terminal-state notifications; ordinary JWT/cookie calls ignore these fields. ### Behavior - This is an asynchronous operation: a successful submission creates a task and returns before processing finishes. - Persist the returned task identifier and use the corresponding detail or list operation to observe progress. - Treat the detail endpoint as the source of truth even when webhook delivery is enabled. ### Response - A `200` response confirms task acceptance; it does not by itself mean media generation has completed. - Retain the returned identifier and wait for a documented terminal status before using output URLs. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid parameters. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/talkingVideo/allRecords` — Get all task records. - `GET /api/v1/talkingVideo/{_id}` — Get task details. - `DELETE /api/v1/talkingVideo/{_id}` — Delete task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1TalkingVideoStart`
- JSON body fields:
  - `name` (body, required; string; example: `My Talking Video`) — Name of the talking video task
  - `video_url` (body, required; string; example: `https://example.com/video.mp4`) — URL of the source video
  - `audio_url` (body, optional; string; example: `https://example.com/audio.mp3`) — Optional audio URL
  - `duration` (body, optional; integer; default: `3`; min: 1; max: 20; example: `5`) — Duration in seconds
  - `prompt` (body, required; string; example: `Make this person smile and speak`) — Generation prompt
  - `negative_prompt` (body, required; string; example: `blurry, distorted`) — Negative prompt to avoid unwanted features
  - `webhook_url` (body, optional; string; max length: 2048; example: `https://your-server.example.com/a2e/webhook`) — HTTPS URL to receive task.completed / task.failed notifications. Best-effort delivery, single attempt, no retries; clients should treat the detail API as the source of truth.
  - `webhook_token` (body, optional; string; max length: 256; example: `a-shared-secret`) — Optional plaintext token returned in the X-A2e-Webhook-Token header so receivers can verify the request originated from a2e.
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/talkingVideo/start" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "name": "My Talking Video",
  "video_url": "https://example.com/video.mp4",
  "audio_url": "https://example.com/audio.mp3",
  "duration": 5,
  "prompt": "Make this person smile and speak",
  "negative_prompt": "blurry, distorted",
  "webhook_url": "https://your-server.example.com/a2e/webhook",
  "webhook_token": "a-shared-secret"
}
JSON
```
- Responses:
  - `200` — Talking video task started successfully
  - `400` — Bad Request - Invalid parameters
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/talkingVideo/allRecords — Get all task records
Return the authenticated user's talking-video tasks, newest first, using the requested page number and page size. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supported query parameters: `pageNum`, `pageSize`. Omitted values use the defaults shown in the parameter schema. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/talkingVideo/{_id}` — Get task details. - `DELETE /api/v1/talkingVideo/{_id}` — Delete task. - `POST /api/v1/talkingVideo/start` — Start talking video generation. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1TalkingVideoAllRecords`
- Request parameters:
  - `pageNum` (query, optional; integer; min: 1; example: `1`) — Page number
  - `pageSize` (query, optional; integer; example: `10`) — Page size
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/talkingVideo/allRecords?pageNum=1&pageSize=10" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task list retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/talkingVideo/batchDetail — Batch query task details
Query details for multiple tasks at once by providing an array of task IDs. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `ids`. ### Behavior - Fetches several task records in one request, reducing the number of individual detail calls. - Results remain subject to the same authentication and ownership checks as single-record lookups. - Match returned records by their identifiers instead of relying on response ordering. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/talkingVideo/allRecords` — Get all task records. - `GET /api/v1/talkingVideo/{_id}` — Get task details. - `DELETE /api/v1/talkingVideo/{_id}` — Delete task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1TalkingVideoBatchDetail`
- JSON body fields:
  - `ids` (body, required; string[]; example: `["example"]`) — Array of task IDs to query
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/talkingVideo/batchDetail" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "ids": [
    "example"
  ]
}
JSON
```
- Responses:
  - `200` — Batch details retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/talkingVideo/{_id} — Get task details
Return the authenticated user's talking-video task identified by `_id`, including its current processing status and available video output. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Retrieves the current server-side representation of the requested resource or task. - For asynchronous tasks, inspect the documented status and result fields before consuming generated media. - Repeat the request only as needed for polling and stop after the task reaches a terminal state. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/talkingVideo/allRecords` — Get all task records. - `DELETE /api/v1/talkingVideo/{_id}` — Delete task. - `POST /api/v1/talkingVideo/start` — Start talking video generation. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1TalkingVideoId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — Task ID
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/talkingVideo/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task details retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### DELETE /api/v1/talkingVideo/{_id} — Delete task
Remove the authenticated user's talking-video task identified by `_id` from the task history without affecting other generated videos. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Deletes or marks the selected resource as deleted according to the endpoint's documented lifecycle rules. - Use the resource identifier from a list, creation, or detail response; deleting one resource does not affect unrelated records. - Do not assume an in-progress task can be cancelled unless the endpoint explicitly documents that behavior. ### Response - A `200` response confirms that the deletion request was applied to the selected record. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/talkingVideo/allRecords` — Get all task records. - `GET /api/v1/talkingVideo/{_id}` — Get task details. - `POST /api/v1/talkingVideo/start` — Start talking video generation. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `deleteApiV1TalkingVideoId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — Task ID to delete
- Example request:
```bash
curl -X DELETE "https://video.a2e.ai/api/v1/talkingVideo/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task deleted successfully
  - `401` — Unauthorized - Invalid or missing JWT token
#### Virtual Try-On

##### POST /api/v1/virtualTryOn/start — Start virtual try-on task
Start a virtual try-on task with clothing images on person photos. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `image_urls`. - API-token callers may include `webhook_url` and `webhook_token` for best-effort terminal-state notifications; ordinary JWT/cookie calls ignore these fields. ### Behavior - This is an asynchronous operation: a successful submission creates a task and returns before processing finishes. - Persist the returned task identifier and use the corresponding detail or list operation to observe progress. - Treat the detail endpoint as the source of truth even when webhook delivery is enabled. ### Response - A `200` response confirms task acceptance; it does not by itself mean media generation has completed. - Retain the returned identifier and wait for a documented terminal status before using output URLs. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid parameters. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/virtualTryOn/allRecords` — Get all virtual try-on records. - `GET /api/v1/virtualTryOn/{_id}` — Get virtual try-on task detail. - `DELETE /api/v1/virtualTryOn/{_id}` — Delete virtual try-on task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1VirtualTryOnStart`
- JSON body fields:
  - `name` (body, optional; string; default: ``; example: `Summer Dress Try-On`) — Name of the virtual try-on task
  - `image_urls` (body, required; string[]; min items: 2; max items: 4; example: `["https://example.com/person.jpg","https://example.com/dress.jpg"]`) — Array of 2 image URLs - [0] person image, [1] clothing image
  - `timeout` (body, optional; number; default: `120`; example: `120`) — Processing timeout in seconds
  - `webhook_url` (body, optional; string; max length: 2048; example: `https://your-server.example.com/a2e/webhook`) — HTTPS URL to receive task.completed / task.failed notifications. Best-effort delivery, single attempt, no retries; clients should treat the detail API as the source of truth.
  - `webhook_token` (body, optional; string; max length: 256; example: `a-shared-secret`) — Optional plaintext token returned in the X-A2e-Webhook-Token header so receivers can verify the request originated from a2e.
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/virtualTryOn/start" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "name": "Summer Dress Try-On",
  "image_urls": [
    "https://example.com/person.jpg",
    "https://example.com/dress.jpg"
  ],
  "timeout": 120,
  "webhook_url": "https://your-server.example.com/a2e/webhook",
  "webhook_token": "a-shared-secret"
}
JSON
```
- Responses:
  - `200` — Virtual try-on task started successfully
  - `400` — Bad Request - Invalid parameters
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/virtualTryOn/allRecords — Get all virtual try-on records
Retrieve paginated list of virtual try-on tasks for the current user. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supported query parameters: `pageNum`, `pageSize`. Omitted values use the defaults shown in the parameter schema. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid parameters. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/virtualTryOn/{_id}` — Get virtual try-on task detail. - `DELETE /api/v1/virtualTryOn/{_id}` — Delete virtual try-on task. - `POST /api/v1/virtualTryOn/start` — Start virtual try-on task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1VirtualTryOnAllRecords`
- Request parameters:
  - `pageNum` (query, optional; integer; default: `1`; min: 1; example: `1`) — Page number for pagination
  - `pageSize` (query, optional; integer; default: `10`; min: 1; max: 100; example: `10`) — Number of items per page
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/virtualTryOn/allRecords?pageNum=1&pageSize=10" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Virtual try-on records retrieved successfully
  - `400` — Bad Request - Invalid parameters
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/virtualTryOn/batchDetail — Batch query task details
Query details for multiple tasks at once by providing an array of task IDs. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `ids`. ### Behavior - Fetches several task records in one request, reducing the number of individual detail calls. - Results remain subject to the same authentication and ownership checks as single-record lookups. - Match returned records by their identifiers instead of relying on response ordering. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/virtualTryOn/allRecords` — Get all virtual try-on records. - `GET /api/v1/virtualTryOn/{_id}` — Get virtual try-on task detail. - `DELETE /api/v1/virtualTryOn/{_id}` — Delete virtual try-on task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1VirtualTryOnBatchDetail`
- JSON body fields:
  - `ids` (body, required; string[]; example: `["example"]`) — Array of task IDs to query
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/virtualTryOn/batchDetail" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "ids": [
    "example"
  ]
}
JSON
```
- Responses:
  - `200` — Batch details retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/virtualTryOn/{_id} — Get virtual try-on task detail
Retrieve detailed information of a virtual try-on task by its ID. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Retrieves the current server-side representation of the requested resource or task. - For asynchronous tasks, inspect the documented status and result fields before consuming generated media. - Repeat the request only as needed for polling and stop after the task reaches a terminal state. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid parameters. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/virtualTryOn/allRecords` — Get all virtual try-on records. - `DELETE /api/v1/virtualTryOn/{_id}` — Delete virtual try-on task. - `POST /api/v1/virtualTryOn/start` — Start virtual try-on task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1VirtualTryOnId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — Virtual try-on task ID
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/virtualTryOn/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Virtual try-on task detail retrieved successfully
  - `400` — Bad Request - Invalid parameters
  - `401` — Unauthorized - Invalid or missing JWT token

##### DELETE /api/v1/virtualTryOn/{_id} — Delete virtual try-on task
Remove the authenticated user's virtual try-on task identified by `_id` from the task history without affecting other generated try-on results. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Deletes or marks the selected resource as deleted according to the endpoint's documented lifecycle rules. - Use the resource identifier from a list, creation, or detail response; deleting one resource does not affect unrelated records. - Do not assume an in-progress task can be cancelled unless the endpoint explicitly documents that behavior. ### Response - A `200` response confirms that the deletion request was applied to the selected record. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid parameters. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/virtualTryOn/allRecords` — Get all virtual try-on records. - `GET /api/v1/virtualTryOn/{_id}` — Get virtual try-on task detail. - `POST /api/v1/virtualTryOn/start` — Start virtual try-on task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `deleteApiV1VirtualTryOnId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — Virtual try-on task ID
- Example request:
```bash
curl -X DELETE "https://video.a2e.ai/api/v1/virtualTryOn/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Virtual try-on task deleted successfully
  - `400` — Bad Request - Invalid parameters
  - `401` — Unauthorized - Invalid or missing JWT token
#### Motion Transfer

##### POST /api/v1/motionTransfer/start — Start motion transfer task
Start a motion transfer task to transfer motion from video to image. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `image_url`, `video_url`. - API-token callers may include `webhook_url` and `webhook_token` for best-effort terminal-state notifications; ordinary JWT/cookie calls ignore these fields. ### Behavior - This is an asynchronous operation: a successful submission creates a task and returns before processing finishes. - Persist the returned task identifier and use the corresponding detail or list operation to observe progress. - Treat the detail endpoint as the source of truth even when webhook delivery is enabled. ### Response - A `200` response confirms task acceptance; it does not by itself mean media generation has completed. - Retain the returned identifier and wait for a documented terminal status before using output URLs. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid parameters. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/motionTransfer/allRecords` — Get all motion transfer records. - `GET /api/v1/motionTransfer/{_id}` — Get motion transfer task detail. - `DELETE /api/v1/motionTransfer/{_id}` — Delete motion transfer task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1MotionTransferStart`
- JSON body fields:
  - `name` (body, optional; string; default: ``; example: `Dance Motion Transfer`) — Name of the motion transfer task
  - `image_url` (body, required; string; format: uri; example: `https://example.com/person.jpg`) — Reference image URL for motion transfer
  - `video_url` (body, required; string; format: uri; example: `https://example.com/dance.mp4`) — Control video URL for motion source
  - `positive_prompt` (body, optional; string; example: `high quality motion transfer, natural pose transition, smooth movement`) — Positive prompt for motion transfer
  - `negative_prompt` (body, optional; string; example: `blurry, distorted limbs, unnatural poses, deformation`) — Negative prompt for motion transfer
  - `timeout` (body, optional; number; default: `300`; example: `300`) — Processing timeout in seconds
  - `webhook_url` (body, optional; string; max length: 2048; example: `https://your-server.example.com/a2e/webhook`) — HTTPS URL to receive task.completed / task.failed notifications. Best-effort delivery, single attempt, no retries; clients should treat the detail API as the source of truth.
  - `webhook_token` (body, optional; string; max length: 256; example: `a-shared-secret`) — Optional plaintext token returned in the X-A2e-Webhook-Token header so receivers can verify the request originated from a2e.
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/motionTransfer/start" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "name": "Dance Motion Transfer",
  "image_url": "https://example.com/person.jpg",
  "video_url": "https://example.com/dance.mp4",
  "positive_prompt": "high quality motion transfer, natural pose transition, smooth movement",
  "negative_prompt": "blurry, distorted limbs, unnatural poses, deformation",
  "timeout": 300,
  "webhook_url": "https://your-server.example.com/a2e/webhook",
  "webhook_token": "a-shared-secret"
}
JSON
```
- Responses:
  - `200` — Motion transfer task started successfully
  - `400` — Bad Request - Invalid parameters
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/motionTransfer/allRecords — Get all motion transfer records
Retrieve paginated list of motion transfer tasks for the current user. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supported query parameters: `pageNum`, `pageSize`. Omitted values use the defaults shown in the parameter schema. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid parameters. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/motionTransfer/{_id}` — Get motion transfer task detail. - `DELETE /api/v1/motionTransfer/{_id}` — Delete motion transfer task. - `POST /api/v1/motionTransfer/start` — Start motion transfer task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1MotionTransferAllRecords`
- Request parameters:
  - `pageNum` (query, optional; integer; default: `1`; min: 1; example: `1`) — Page number for pagination
  - `pageSize` (query, optional; integer; default: `10`; min: 1; max: 100; example: `10`) — Number of items per page
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/motionTransfer/allRecords?pageNum=1&pageSize=10" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Motion transfer records retrieved successfully
  - `400` — Bad Request - Invalid parameters
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/motionTransfer/batchDetail — Batch query task details
Query details for multiple tasks at once by providing an array of task IDs. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `ids`. ### Behavior - Fetches several task records in one request, reducing the number of individual detail calls. - Results remain subject to the same authentication and ownership checks as single-record lookups. - Match returned records by their identifiers instead of relying on response ordering. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/motionTransfer/allRecords` — Get all motion transfer records. - `GET /api/v1/motionTransfer/{_id}` — Get motion transfer task detail. - `DELETE /api/v1/motionTransfer/{_id}` — Delete motion transfer task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1MotionTransferBatchDetail`
- JSON body fields:
  - `ids` (body, required; string[]; example: `["example"]`) — Array of task IDs to query
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/motionTransfer/batchDetail" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "ids": [
    "example"
  ]
}
JSON
```
- Responses:
  - `200` — Batch details retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/motionTransfer/{_id} — Get motion transfer task detail
Retrieve detailed information of a motion transfer task by its ID. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Retrieves the current server-side representation of the requested resource or task. - For asynchronous tasks, inspect the documented status and result fields before consuming generated media. - Repeat the request only as needed for polling and stop after the task reaches a terminal state. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid parameters. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/motionTransfer/allRecords` — Get all motion transfer records. - `DELETE /api/v1/motionTransfer/{_id}` — Delete motion transfer task. - `POST /api/v1/motionTransfer/start` — Start motion transfer task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1MotionTransferId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — Motion transfer task ID
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/motionTransfer/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Motion transfer task detail retrieved successfully
  - `400` — Bad Request - Invalid parameters
  - `401` — Unauthorized - Invalid or missing JWT token

##### DELETE /api/v1/motionTransfer/{_id} — Delete motion transfer task
Remove the authenticated user's motion-transfer task identified by `_id` from the task history without affecting other generated videos. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Deletes or marks the selected resource as deleted according to the endpoint's documented lifecycle rules. - Use the resource identifier from a list, creation, or detail response; deleting one resource does not affect unrelated records. - Do not assume an in-progress task can be cancelled unless the endpoint explicitly documents that behavior. ### Response - A `200` response confirms that the deletion request was applied to the selected record. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid parameters. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/motionTransfer/allRecords` — Get all motion transfer records. - `GET /api/v1/motionTransfer/{_id}` — Get motion transfer task detail. - `POST /api/v1/motionTransfer/start` — Start motion transfer task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `deleteApiV1MotionTransferId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — Motion transfer task ID
- Example request:
```bash
curl -X DELETE "https://video.a2e.ai/api/v1/motionTransfer/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Motion transfer task deleted successfully
  - `400` — Bad Request - Invalid parameters
  - `401` — Unauthorized - Invalid or missing JWT token
#### Product Avatar

##### POST /api/v1/productAvatar/start — Generate product avatar with AI (Async)
Generate AI-powered product avatar by combining product and person images with customizable positioning and styling. **⚠️ IMPORTANT: This is an ASYNCHRONOUS operation** ### Async Workflow 1. **Submit Task** - Call this endpoint to create a new generation task - Returns immediately with task `_id` and status `initialized` - Task is queued for processing 2. **Processing States** - The task goes through these states: - `initialized` → Task created, waiting in queue - `sent` → Task submitted to AI service - `pending` → Task received by AI service - `processing` → AI is generating the image - `completed` → Generation finished successfully - `failed` → Generation failed (check `failed_message`) 3. **Get Results** - Poll for task status and results: - Use `GET /api/v1/productAvatar/{_id}` to check status - Use `GET /api/v1/productAvatar/allRecords` to list all tasks - When `current_status` is `completed`, `result_image_url` contains the generated image 4. **Timeout Handling**: - Tasks timeout after 2 hours and automatically fail - Credits are automatically refunded on timeout or failure ### Best Practices - Poll every 3-5 seconds to check task status - Handle both `completed` and `failed` states - Store the returned `_id` to query results later. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `image_urls`, `product_rect`. - API-token callers may include `webhook_url` and `webhook_token` for best-effort terminal-state notifications; ordinary JWT/cookie calls ignore these fields. ### Behavior - This is an asynchronous operation: a successful submission creates a task and returns before processing finishes. - Persist the returned task identifier and use the corresponding detail or list operation to observe progress. - Treat the detail endpoint as the source of truth even when webhook delivery is enabled. ### Response - A `200` response confirms task acceptance; it does not by itself mean media generation has completed. - Retain the returned identifier and wait for a documented terminal status before using output URLs. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid parameters or missing required fields. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/productAvatar/allRecords` — List all product avatar tasks. - `GET /api/v1/productAvatar/{_id}` — Query task status and get result. - `DELETE /api/v1/productAvatar/{_id}` — Delete a product avatar task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1ProductAvatarStart`
- JSON body fields:
  - `name` (body, optional; string; example: `My Product Avatar`) — Name for the product avatar generation task (optional)
  - `image_urls` (body, required; string[]; min items: 2; max items: 2; example: `["https://example.com/product.jpg","https://example.com/person.jpg"]`) — Array of image URLs - [0] product image, [1] person image
  - `product_rect` (body, required; object) — Product positioning and transformation parameters
  - `prompt` (body, optional; string; example: `Professional product showcase`) — Additional prompt for AI generation (optional)
  - `timeout` (body, optional; number; default: `120`; example: `120`) — Processing timeout in seconds
  - `webhook_url` (body, optional; string; max length: 2048; example: `https://your-server.example.com/a2e/webhook`) — HTTPS URL to receive task.completed / task.failed notifications. Best-effort delivery, single attempt, no retries; clients should treat the detail API as the source of truth.
  - `webhook_token` (body, optional; string; max length: 256; example: `a-shared-secret`) — Optional plaintext token returned in the X-A2e-Webhook-Token header so receivers can verify the request originated from a2e.
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/productAvatar/start" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "name": "My Product Avatar",
  "image_urls": [
    "https://example.com/product.jpg",
    "https://example.com/person.jpg"
  ],
  "product_rect": {
    "x": 100,
    "y": 150,
    "width": 200,
    "height": 300,
    "rotation": 0,
    "scale": 1
  },
  "prompt": "Professional product showcase",
  "timeout": 120,
  "webhook_url": "https://your-server.example.com/a2e/webhook",
  "webhook_token": "a-shared-secret"
}
JSON
```
- Responses:
  - `200` — Product avatar generation started successfully
  - `400` — Bad Request - Invalid parameters or missing required fields
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/productAvatar/allRecords — List all product avatar tasks
Retrieve a paginated list of all product avatar generation tasks for the authenticated user. Use this endpoint to monitor task progress and retrieve results. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supported query parameters: `pageNum`, `pageSize`. Omitted values use the defaults shown in the parameter schema. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/productAvatar/{_id}` — Query task status and get result. - `DELETE /api/v1/productAvatar/{_id}` — Delete a product avatar task. - `POST /api/v1/productAvatar/start` — Generate product avatar with AI (Async) Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1ProductAvatarAllRecords`
- Request parameters:
  - `pageNum` (query, optional; integer; default: `1`; example: `1`) — Page number (starting from 1)
  - `pageSize` (query, optional; integer; default: `10`; example: `10`) — Number of items per page
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/productAvatar/allRecords?pageNum=1&pageSize=10" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Successfully retrieved task list
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/productAvatar/batchDetail — Batch query task details
Query details for multiple tasks at once by providing an array of task IDs. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `ids`. ### Behavior - Fetches several task records in one request, reducing the number of individual detail calls. - Results remain subject to the same authentication and ownership checks as single-record lookups. - Match returned records by their identifiers instead of relying on response ordering. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/productAvatar/allRecords` — List all product avatar tasks. - `GET /api/v1/productAvatar/{_id}` — Query task status and get result. - `DELETE /api/v1/productAvatar/{_id}` — Delete a product avatar task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1ProductAvatarBatchDetail`
- JSON body fields:
  - `ids` (body, required; string[]; example: `["example"]`) — Array of task IDs to query
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/productAvatar/batchDetail" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "ids": [
    "example"
  ]
}
JSON
```
- Responses:
  - `200` — Batch details retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/productAvatar/{_id} — Query task status and get result
Retrieve detailed information about a specific product avatar generation task. Use this endpoint to poll for task status and get the result when completed. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Retrieves the current server-side representation of the requested resource or task. - For asynchronous tasks, inspect the documented status and result fields before consuming generated media. - Repeat the request only as needed for polling and stop after the task reaches a terminal state. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid task ID. - `401` — Unauthorized - Invalid or missing JWT token. - `404` — Task not found. ### Related Operations - `GET /api/v1/productAvatar/allRecords` — List all product avatar tasks. - `DELETE /api/v1/productAvatar/{_id}` — Delete a product avatar task. - `POST /api/v1/productAvatar/start` — Generate product avatar with AI (Async) Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1ProductAvatarId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — Task ID returned from the start endpoint
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/productAvatar/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Successfully retrieved task details
  - `400` — Bad Request - Invalid task ID
  - `401` — Unauthorized - Invalid or missing JWT token
  - `404` — Task not found

##### DELETE /api/v1/productAvatar/{_id} — Delete a product avatar task
Soft delete a product avatar task. The task data will be marked as deleted but not removed from the database. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Deletes or marks the selected resource as deleted according to the endpoint's documented lifecycle rules. - Use the resource identifier from a list, creation, or detail response; deleting one resource does not affect unrelated records. - Do not assume an in-progress task can be cancelled unless the endpoint explicitly documents that behavior. ### Response - A `200` response confirms that the deletion request was applied to the selected record. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid task ID. - `401` — Unauthorized - Invalid or missing JWT token. - `404` — Task not found. ### Related Operations - `GET /api/v1/productAvatar/allRecords` — List all product avatar tasks. - `GET /api/v1/productAvatar/{_id}` — Query task status and get result. - `POST /api/v1/productAvatar/start` — Generate product avatar with AI (Async) Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `deleteApiV1ProductAvatarId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — Task ID to delete
- Example request:
```bash
curl -X DELETE "https://video.a2e.ai/api/v1/productAvatar/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task deleted successfully
  - `400` — Bad Request - Invalid task ID
  - `401` — Unauthorized - Invalid or missing JWT token
  - `404` — Task not found
#### Photobook

##### POST /api/v1/userPhotobook/start — Start photobook generation
Create a photobook generation task using one face image and optional location/clothing prompts. The service will generate 4, 8, 12, or 16 final photos depending on total_count. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `face_image_url`. ### Behavior - Validates the submitted payload and performs the operation described by the request schema. - Conditional fields, mutually exclusive inputs, limits, and defaults are enforced as documented by their schemas. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid parameters. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userPhotobook/allRecords` — Get photobook records. - `GET /api/v1/userPhotobook/{id}` — Get photobook record detail. - `DELETE /api/v1/userPhotobook/{id}` — Delete photobook record. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1UserPhotobookStart`
- JSON body fields:
  - `name` (body, optional; string; example: `Summer Travel Album`) — Display name for this photobook batch
  - `face_image_url` (body, required; string; example: `https://example.com/face.jpg`) — Source face image URL used for all generated photos
  - `location` (body, optional; string; example: `Paris street cafe at golden hour`) — Scene or location prompt
  - `clothing` (body, optional; string; example: `elegant white dress`) — Clothing prompt applied during the image edit step
  - `total_count` (body, optional; integer; allowed: `4`, `8`, `12`, `16`; default: `4`; example: `8`) — Total number of photos to generate
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/userPhotobook/start" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "name": "Summer Travel Album",
  "face_image_url": "https://example.com/face.jpg",
  "location": "Paris street cafe at golden hour",
  "clothing": "elegant white dress",
  "total_count": 8
}
JSON
```
- Responses:
  - `200` — Photobook task started successfully
  - `400` — Bad Request - Invalid parameters
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/userPhotobook/allRecords — Get photobook records
Return the authenticated user's photobook-generation records using `pageNum` and `pageSize`, with newest records presented first. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supported query parameters: `pageNum`, `pageSize`. Omitted values use the defaults shown in the parameter schema. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid pagination parameters. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userPhotobook/{id}` — Get photobook record detail. - `DELETE /api/v1/userPhotobook/{id}` — Delete photobook record. - `POST /api/v1/userPhotobook/start` — Start photobook generation. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1UserPhotobookAllRecords`
- Request parameters:
  - `pageNum` (query, optional; integer; default: `1`; example: `1`) — Page number
  - `pageSize` (query, optional; integer; default: `20`; example: `20`) — Page size
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/userPhotobook/allRecords?pageNum=1&pageSize=20" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Photobook records retrieved successfully
  - `400` — Bad Request - Invalid pagination parameters
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/userPhotobook/batchDetail — Batch query task details
Query details for multiple photobook tasks at once by providing an array of task IDs. Only records owned by the authenticated user are returned. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `ids`. ### Behavior - Fetches several task records in one request, reducing the number of individual detail calls. - Results remain subject to the same authentication and ownership checks as single-record lookups. - Match returned records by their identifiers instead of relying on response ordering. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userPhotobook/allRecords` — Get photobook records. - `GET /api/v1/userPhotobook/{id}` — Get photobook record detail. - `DELETE /api/v1/userPhotobook/{id}` — Delete photobook record. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1UserPhotobookBatchDetail`
- JSON body fields:
  - `ids` (body, required; string[]; example: `["example"]`) — Array of photobook task IDs to query
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/userPhotobook/batchDetail" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "ids": [
    "example"
  ]
}
JSON
```
- Responses:
  - `200` — Batch details retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/userPhotobook/{id} — Get photobook record detail
Get one photobook record by id. The endpoint also syncs the latest pipeline status before returning. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `id` in the URL path. ### Behavior - Retrieves the current server-side representation of the requested resource or task. - For asynchronous tasks, inspect the documented status and result fields before consuming generated media. - Repeat the request only as needed for polling and stop after the task reaches a terminal state. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. - `404` — Record not found. ### Related Operations - `GET /api/v1/userPhotobook/allRecords` — Get photobook records. - `DELETE /api/v1/userPhotobook/{id}` — Delete photobook record. - `POST /api/v1/userPhotobook/start` — Start photobook generation. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1UserPhotobookId`
- Request parameters:
  - `id` (path, required; string; example: `507f1f77bcf86cd799439011`) — Photobook record id
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/userPhotobook/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Photobook record detail retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token
  - `404` — Record not found

##### DELETE /api/v1/userPhotobook/{id} — Delete photobook record
Remove the photobook record identified by `id` only when it belongs to the authenticated user; unrelated photobook records are unchanged. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `id` in the URL path. ### Behavior - Deletes or marks the selected resource as deleted according to the endpoint's documented lifecycle rules. - Use the resource identifier from a list, creation, or detail response; deleting one resource does not affect unrelated records. - Do not assume an in-progress task can be cancelled unless the endpoint explicitly documents that behavior. ### Response - A `200` response confirms that the deletion request was applied to the selected record. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Photobook record cannot be deleted in its current status (for example, processing) - `401` — Unauthorized - Invalid or missing JWT token. - `404` — Not Found - Photobook record does not exist or is not accessible by the current user. ### Related Operations - `GET /api/v1/userPhotobook/allRecords` — Get photobook records. - `GET /api/v1/userPhotobook/{id}` — Get photobook record detail. - `POST /api/v1/userPhotobook/start` — Start photobook generation. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `deleteApiV1UserPhotobookId`
- Request parameters:
  - `id` (path, required; string; example: `507f1f77bcf86cd799439011`) — Photobook record id
- Example request:
```bash
curl -X DELETE "https://video.a2e.ai/api/v1/userPhotobook/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Photobook record deleted successfully
  - `400` — Bad Request - Photobook record cannot be deleted in its current status (for example, processing)
  - `401` — Unauthorized - Invalid or missing JWT token
  - `404` — Not Found - Photobook record does not exist or is not accessible by the current user

### Avatar & Video
#### Generate Avatar Videos

##### POST /api/v1/anchor/list — List available avatars
Returns the system and user-specific avatars available to the authenticated API user. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body when using the optional controls documented in the request schema. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid parameters. - `401` — Unauthorized - Invalid or missing JWT token. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1AnchorList`
- JSON body fields:
  - `web_type` (body, optional; string; allowed: `a2e`, `tyzn`; example: `a2e`) — Optional client type. Use a2e or tyzn to include default system avatars alongside user-specific avatars.
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/anchor/list" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "web_type": "a2e"
}
JSON
```
- Responses:
  - `200` — Operation completed successfully
  - `400` — Bad Request - Invalid parameters
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/video/generate — Generate AI video with avatar
Generate AI video with avatar using audio source and selected avatar. Either audioSrc or custom_voice is required. For background replacement, use back_id for system backgrounds or custom_back_id for backgrounds created by /api/v1/custom_back/add. The avatar must have an original background saved, or the request must provide anchor_background_img or anchor_background_color. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `anchor_id`, `anchor_type`. - API-token callers may include `webhook_url` and `webhook_token` for best-effort terminal-state notifications; ordinary JWT/cookie calls ignore these fields. ### Behavior - This is an asynchronous operation: a successful submission creates a task and returns before processing finishes. - Persist the returned task identifier and use the corresponding detail or list operation to observe progress. - Treat the detail endpoint as the source of truth even when webhook delivery is enabled. ### Response - A `200` response confirms task acceptance; it does not by itself mean media generation has completed. - Retain the returned identifier and wait for a documented terminal status before using output URLs. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid parameters or missing required audio source. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/video/detail` — detail. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1VideoGenerate`
- JSON body fields:
  - `title` (body, optional; string; max length: 40; example: `My AI Video`) — Video title (optional, max 40 characters)
  - `audioSrc` (body, optional; string; example: `https://example.com/audio.mp3`) — Audio source URL (required if custom_voice not provided)
  - `custom_voice` (body, optional; string; example: `https://example.com/custom_voice.wav`) — Custom voice audio URL (required if audioSrc not provided)
  - `anchor_id` (body, required; string; example: `507f1f77bcf86cd799439011`) — Avatar/anchor ID (MongoDB ObjectId)
  - `anchor_type` (body, required; number; example: `0`) — Avatar type (0 for system avatar, 1 for custom avatar)
  - `anchor_background_img` (body, optional; string; example: `https://example.com/original-avatar-background.jpg`) — Original avatar background image URL. Required for background replacement if the avatar record does not already have background_img or background_color.
  - `anchor_background_color` (body, optional; string; example: `rgba(255,255,255,1)`) — Original avatar background color in RGBA format. Required for background replacement if the avatar record does not already have background_img or background_color.
  - `back_id` (body, optional; string; example: `507f1f77bcf86cd799439012`) — System background template ID (MongoDB ObjectId). Mutually exclusive with custom_back_id; sending both returns error 30005.
  - `face_swap_id` (body, optional; string; example: `507f1f77bcf86cd799439013`) — Face swap template ID (MongoDB ObjectId)
  - `custom_back_id` (body, optional; string; example: `507f1f77bcf86cd799439014`) — Custom background ID returned by /api/v1/custom_back/add (MongoDB ObjectId). Mutually exclusive with back_id; sending both returns error 30005.
  - `color` (body, optional; string; example: `rgba(0,0,0,1)`) — Color setting in RGBA format
  - `wl_model` (body, optional; string; example: `default`) — Watermark/logo model setting
  - `isSkipRs` (body, optional; boolean; example: `false`) — Skip resolution scaling
  - `web_bg_width` (body, optional; number; default: `0`; example: `1920`) — Output canvas/background width. Required when using back_id, custom_back_id, or color.
  - `web_bg_height` (body, optional; number; default: `0`; example: `1080`) — Output canvas/background height. Required when using back_id, custom_back_id, or color.
  - `web_people_width` (body, optional; number; default: `0`; example: `800`) — Avatar width in output layout. Required when using back_id, custom_back_id, or color.
  - `web_people_height` (body, optional; number; default: `0`; example: `600`) — Avatar height in output layout. Required when using back_id, custom_back_id, or color.
  - `web_people_x` (body, optional; number; default: `0`; example: `100`) — Avatar X position in web layout
  - `web_people_y` (body, optional; number; default: `0`; example: `50`) — Avatar Y position in web layout
  - `web_dist_bg_width` (body, optional; number; default: `-1`; example: `1920`) — Distributed background width
  - `web_dist_bg_height` (body, optional; number; default: `-1`; example: `1080`) — Distributed background height
  - `web_dist_bg_x` (body, optional; number; default: `0`; example: `0`) — Distributed background X position
  - `web_dist_bg_y` (body, optional; number; default: `0`; example: `0`) — Distributed background Y position
  - `resolution` (body, optional; number; default: `1080`; example: `1080`) — Video resolution (height in pixels)
  - `msg` (body, optional; string; example: `Custom video generation`) — Additional message or notes
  - `erode_factor` (body, optional; number; example: `0.5`) — Erosion factor for image processing
  - `isSkipGp` (body, optional; boolean; example: `false`) — Skip green screen processing
  - `isCaptionEnabled` (body, optional; boolean; example: `true`) — Enable captions/subtitles
  - `gp_model` (body, optional; object) — Green screen processing model settings
  - `isToPublicPool` (body, optional; boolean; example: `false`) — Add to public pool for sharing
  - `lip_model` (body, optional; string; example: `default`) — Lip sync model selection
  - `captionAlign` (body, optional; object) — Caption alignment and styling settings
  - `webhook_url` (body, optional; string; max length: 2048; example: `https://your-server.example.com/a2e/webhook`) — HTTPS URL to receive task.completed / task.failed notifications. Best-effort delivery, single attempt, no retries; clients should treat the detail API as the source of truth.
  - `webhook_token` (body, optional; string; max length: 256; example: `a-shared-secret`) — Optional plaintext token returned in the X-A2e-Webhook-Token header so receivers can verify the request originated from a2e.
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/video/generate" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "title": "My AI Video",
  "audioSrc": "https://example.com/audio.mp3",
  "anchor_id": "507f1f77bcf86cd799439011",
  "anchor_type": 0
}
JSON
```
- Responses:
  - `200` — Video generation started successfully
  - `400` — Bad Request - Invalid parameters or missing required audio source
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/video/detail — Get record details
detail. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supported query parameters: `video_id`. Omitted values use the defaults shown in the parameter schema. ### Behavior - Retrieves the current server-side representation of the requested resource or task. - For asynchronous tasks, inspect the documented status and result fields before consuming generated media. - Repeat the request only as needed for polling and stop after the task reaches a terminal state. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `POST /api/v1/video/generate` — Generate AI video with avatar. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1VideoDetail`
- Request parameters:
  - `video_id` (query, required; string; example: `507f1f77bcf86cd799439011`) — Video task ID returned by the generate endpoint
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/video/detail?video_id=507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Operation completed successfully
  - `401` — Unauthorized - Invalid or missing JWT token
#### Create Avatars

##### POST /api/v1/custom_avatar/add — Add new record
Create a custom avatar in the authenticated user's library from the submitted avatar media and metadata. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - No request body or operation-specific parameters are required. ### Behavior - Reads the requested information without creating a generation task. - Use the returned fields as documented; availability may depend on the caller and current resource state. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid parameters. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `POST /api/v1/custom_avatar/list` — List items. - `POST /api/v1/custom_avatar/del` — del. - `GET /api/v1/custom_avatar/all_tags` — all tags. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1CustomAvatarAdd`
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/custom_avatar/add" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Item created successfully
  - `400` — Bad Request - Invalid parameters
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/custom_avatar/list — Create/Run list
Return the authenticated user's custom avatars using the submitted pagination and filtering controls. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - No request body or operation-specific parameters are required. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid parameters. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `POST /api/v1/custom_avatar/add` — Add new item. - `POST /api/v1/custom_avatar/del` — del. - `GET /api/v1/custom_avatar/all_tags` — all tags. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1CustomAvatarList`
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/custom_avatar/list" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Item retrieved successfully
  - `400` — Bad Request - Invalid parameters
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/custom_avatar/del — Delete record
Remove the authenticated user's custom avatar identified by the submitted record ID. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - No request body or operation-specific parameters are required. ### Behavior - Reads the requested information without creating a generation task. - Use the returned fields as documented; availability may depend on the caller and current resource state. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid parameters. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `POST /api/v1/custom_avatar/list` — List items. - `POST /api/v1/custom_avatar/add` — Add new item. - `GET /api/v1/custom_avatar/all_tags` — all tags. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1CustomAvatarDel`
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/custom_avatar/del" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Operation completed successfully
  - `400` — Bad Request - Invalid parameters
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/custom_avatar/all_tags — List all tags
Return the distinct tags available for organizing and filtering the authenticated user's custom avatars. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - No request body or operation-specific parameters are required. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `POST /api/v1/custom_avatar/list` — List items. - `POST /api/v1/custom_avatar/add` — Add new item. - `POST /api/v1/custom_avatar/del` — del. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1CustomAvatarAllTags`
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/custom_avatar/all_tags" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Operation completed successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### PUT /api/v1/custom_avatar/{_id} — Update record
update. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Updates the identified resource using the fields accepted by the request schema and the operation's access controls. - Fields omitted from the request retain their existing values unless the schema states otherwise. - Read the returned record or call the detail operation to confirm the persisted state. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request. - `401` — Unauthorized - Invalid or missing JWT token. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `putApiV1CustomAvatarId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — _id parameter
- Example request:
```bash
curl -X PUT "https://video.a2e.ai/api/v1/custom_avatar/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Successful response
  - `400` — Bad Request
  - `401` — Unauthorized - Invalid or missing JWT token
#### Background Matting

##### POST /api/v1/custom_back/add — Add new custom background
Create a custom background in the authenticated user's library from the submitted background image and metadata. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `img_url`. ### Behavior - Validates the submitted payload and performs the operation described by the request schema. - Conditional fields, mutually exclusive inputs, limits, and defaults are enforced as documented by their schemas. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid parameters or missing img_url. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `POST /api/v1/custom_back/list` — List items. - `POST /api/v1/custom_back/del` — del. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1CustomBackAdd`
- JSON body fields:
  - `img_url` (body, required; string; example: `https://example.com/background.jpg`) — URL of the background image to add
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/custom_back/add" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "img_url": "https://example.com/background.jpg"
}
JSON
```
- Responses:
  - `200` — Background item created successfully
  - `400` — Bad Request - Invalid parameters or missing img_url
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/custom_back/list — Create/Run list
Return the authenticated user's custom backgrounds using the submitted pagination and filtering controls. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - No request body or operation-specific parameters are required. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid parameters. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `POST /api/v1/custom_back/add` — Add new custom background. - `POST /api/v1/custom_back/del` — del. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1CustomBackList`
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/custom_back/list" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Item retrieved successfully
  - `400` — Bad Request - Invalid parameters
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/custom_back/del — Delete record
Remove the authenticated user's custom background identified by the submitted record ID. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - No request body or operation-specific parameters are required. ### Behavior - Reads the requested information without creating a generation task. - Use the returned fields as documented; availability may depend on the caller and current resource state. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid parameters. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `POST /api/v1/custom_back/list` — List items. - `POST /api/v1/custom_back/add` — Add new custom background. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1CustomBackDel`
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/custom_back/del" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Operation completed successfully
  - `400` — Bad Request - Invalid parameters
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/custom_back/allBackground — List all backgrounds
allBackground. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - No request body or operation-specific parameters are required. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `POST /api/v1/custom_back/randomBackground` — randomBackground. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1CustomBackAllBackground`
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/custom_back/allBackground" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Successful response
  - `400` — Bad Request
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/custom_back/randomBackground — Get a random background
randomBackground. ### Request - This operation does not declare bearer authentication in the published specification. - No request body or operation-specific parameters are required. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request. ### Related Operations - `POST /api/v1/custom_back/allBackground` — allBackground.
- Operation ID: `postApiV1CustomBackRandomBackground`
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/custom_back/randomBackground" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Successful response
  - `400` — Bad Request
#### Video Twin

##### POST /api/v1/userVideoTwin/upload — Upload file
upload. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - No request body or operation-specific parameters are required. ### Behavior - Reads the requested information without creating a generation task. - Use the returned fields as documented; availability may depend on the caller and current resource state. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userVideoTwin/records` — Get video twin records. - `GET /api/v1/userVideoTwin/{_id}` — detail. - `POST /api/v1/userVideoTwin/training` — training. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1UserVideoTwinUpload`
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/userVideoTwin/upload" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Successful response
  - `400` — Bad Request
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/userVideoTwin/training — Start training
training. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - No request body or operation-specific parameters are required. ### Behavior - Reads the requested information without creating a generation task. - Use the returned fields as documented; availability may depend on the caller and current resource state. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userVideoTwin/records` — Get video twin records. - `GET /api/v1/userVideoTwin/{_id}` — detail. - `POST /api/v1/userVideoTwin/upload` — upload. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1UserVideoTwinTraining`
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/userVideoTwin/training" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Successful response
  - `400` — Bad Request
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/userVideoTwin/uploadStatus — Get video twin upload status
Check the upload status of video twin files for the authenticated user. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - No request body or operation-specific parameters are required. ### Behavior - Retrieves the current server-side representation of the requested resource or task. - For asynchronous tasks, inspect the documented status and result fields before consuming generated media. - Repeat the request only as needed for polling and stop after the task reaches a terminal state. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userVideoTwin/records` — Get video twin records. - `GET /api/v1/userVideoTwin/{_id}` — detail. - `POST /api/v1/userVideoTwin/upload` — upload. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1UserVideoTwinUploadStatus`
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/userVideoTwin/uploadStatus" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Upload status retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/userVideoTwin/userRecords — Get user video twin records
Return every video-twin record available to the authenticated user, including its current training state and result metadata. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - No request body or operation-specific parameters are required. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userVideoTwin/records` — Get video twin records. - `GET /api/v1/userVideoTwin/{_id}` — detail. - `POST /api/v1/userVideoTwin/upload` — upload. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1UserVideoTwinUserRecords`
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/userVideoTwin/userRecords" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Video twin records retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/userVideoTwin/remove — Remove video twin
Remove the video twin identified in the request from the authenticated user's collection without affecting unrelated records. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `_id`. ### Behavior - Validates the submitted payload and performs the operation described by the request schema. - Conditional fields, mutually exclusive inputs, limits, and defaults are enforced as documented by their schemas. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid video twin ID. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userVideoTwin/records` — Get video twin records. - `GET /api/v1/userVideoTwin/{_id}` — detail. - `POST /api/v1/userVideoTwin/upload` — upload. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1UserVideoTwinRemove`
- JSON body fields:
  - `_id` (body, required; string; example: `507f1f77bcf86cd799439011`) — ID of the video twin to remove
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/userVideoTwin/remove" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "_id": "507f1f77bcf86cd799439011"
}
JSON
```
- Responses:
  - `200` — Video twin removed successfully
  - `400` — Bad Request - Invalid video twin ID
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/userVideoTwin/records — Get video twin records
Retrieve paginated video twin records with optional filters. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supported query parameters: `pageNum`, `pageSize`, `status`. Omitted values use the defaults shown in the parameter schema. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userVideoTwin/{_id}` — detail. - `POST /api/v1/userVideoTwin/upload` — upload. - `POST /api/v1/userVideoTwin/training` — training. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1UserVideoTwinRecords`
- Request parameters:
  - `pageNum` (query, optional; integer; default: `1`; min: 1; example: `1`) — Page number (starts from 1)
  - `pageSize` (query, optional; integer; default: `10`; min: 1; max: 100; example: `10`) — Number of records per page
  - `status` (query, optional; string; allowed: `pending`, `processing`, `completed`, `failed`; example: `completed`) — Filter by status
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/userVideoTwin/records?pageNum=1&pageSize=10&status=completed" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Records retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/userVideoTwin/startTraining — Start video twin training
Begin training a new video twin model with image or video source. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body when using the optional controls documented in the request schema. ### Behavior - Validates the submitted payload and performs the operation described by the request schema. - Conditional fields, mutually exclusive inputs, limits, and defaults are enforced as documented by their schemas. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid parameters. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userVideoTwin/records` — Get video twin records. - `GET /api/v1/userVideoTwin/{_id}` — detail. - `POST /api/v1/userVideoTwin/upload` — upload. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1UserVideoTwinStartTraining`
- JSON body fields:
  - `name` (body, optional; string; example: `My Video Twin`) — Name for the video twin
  - `image_url` (body, optional; string; example: `https://example.com/face.jpg`) — URL of the source image
  - `video_url` (body, optional; string; example: `https://example.com/video.mp4`) — URL of the source video
  - `video_background_image` (body, optional; string; example: `https://example.com/bg.jpg`) — URL of background image
  - `video_background_color` (body, optional; string; example: `rgba(255,255,255,1)`) — Background color in RGBA format
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/userVideoTwin/startTraining" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "name": "My Video Twin",
  "image_url": "https://example.com/face.jpg",
  "video_url": "https://example.com/video.mp4",
  "video_background_image": "https://example.com/bg.jpg",
  "video_background_color": "rgba(255,255,255,1)"
}
JSON
```
- Responses:
  - `200` — Video twin training started successfully
  - `400` — Bad Request - Invalid parameters
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/userVideoTwin/continueTraining — Continue video twin training
Continue training an existing video twin model that was previously paused. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `_id`. ### Behavior - Validates the submitted payload and performs the operation described by the request schema. - Conditional fields, mutually exclusive inputs, limits, and defaults are enforced as documented by their schemas. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid video twin ID. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userVideoTwin/records` — Get video twin records. - `GET /api/v1/userVideoTwin/{_id}` — detail. - `POST /api/v1/userVideoTwin/upload` — upload. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1UserVideoTwinContinueTraining`
- JSON body fields:
  - `_id` (body, required; string; example: `507f1f77bcf86cd799439011`) — ID of the video twin to continue training
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/userVideoTwin/continueTraining" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "_id": "507f1f77bcf86cd799439011"
}
JSON
```
- Responses:
  - `200` — Training continued successfully
  - `400` — Bad Request - Invalid video twin ID
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/userVideoTwin/trainingRecords — Get training records
Retrieve all video twin training records for the authenticated user. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - No request body or operation-specific parameters are required. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userVideoTwin/records` — Get video twin records. - `GET /api/v1/userVideoTwin/{_id}` — detail. - `POST /api/v1/userVideoTwin/upload` — upload. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1UserVideoTwinTrainingRecords`
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/userVideoTwin/trainingRecords" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Training records retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/userVideoTwin/batchDetail — Batch query task details
Query details for multiple tasks at once by providing an array of task IDs. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `ids`. ### Behavior - Fetches several task records in one request, reducing the number of individual detail calls. - Results remain subject to the same authentication and ownership checks as single-record lookups. - Match returned records by their identifiers instead of relying on response ordering. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userVideoTwin/records` — Get video twin records. - `GET /api/v1/userVideoTwin/{_id}` — detail. - `POST /api/v1/userVideoTwin/upload` — upload. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1UserVideoTwinBatchDetail`
- JSON body fields:
  - `ids` (body, required; string[]; example: `["example"]`) — Array of task IDs to query
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/userVideoTwin/batchDetail" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "ids": [
    "example"
  ]
}
JSON
```
- Responses:
  - `200` — Batch details retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/userVideoTwin/{_id} — Get record details
detail. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Retrieves the current server-side representation of the requested resource or task. - For asynchronous tasks, inspect the documented status and result fields before consuming generated media. - Repeat the request only as needed for polling and stop after the task reaches a terminal state. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userVideoTwin/records` — Get video twin records. - `POST /api/v1/userVideoTwin/upload` — upload. - `POST /api/v1/userVideoTwin/training` — training. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1UserVideoTwinId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — _id parameter
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/userVideoTwin/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Successful response
  - `400` — Bad Request
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/userVideoTwin/retry — Retry a failed task
retry. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - No request body or operation-specific parameters are required. ### Behavior - Requests another processing attempt for an eligible failed task. - Eligibility, charging, and state transitions follow the task-specific rules exposed by the response. - Continue monitoring the same or returned task identifier after the retry is accepted. ### Response - A `200` response confirms task acceptance; it does not by itself mean media generation has completed. - Retain the returned identifier and wait for a documented terminal status before using output URLs. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userVideoTwin/records` — Get video twin records. - `GET /api/v1/userVideoTwin/{_id}` — detail. - `POST /api/v1/userVideoTwin/upload` — upload. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1UserVideoTwinRetry`
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/userVideoTwin/retry" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Successful response
  - `400` — Bad Request
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/userVideoTwin/eyeContact — Start eye contact enhancement
Enhance video twin with improved eye contact using AI processing. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body when using the optional controls documented in the request schema. ### Behavior - Validates the submitted payload and performs the operation described by the request schema. - Conditional fields, mutually exclusive inputs, limits, and defaults are enforced as documented by their schemas. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid parameters. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userVideoTwin/records` — Get video twin records. - `GET /api/v1/userVideoTwin/{_id}` — detail. - `POST /api/v1/userVideoTwin/upload` — upload. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1UserVideoTwinEyeContact`
- JSON body fields:
  - `_id` (body, optional; string; example: `507f1f77bcf86cd799439011`) — ID of the video twin to enhance
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/userVideoTwin/eyeContact" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "_id": "507f1f77bcf86cd799439011"
}
JSON
```
- Responses:
  - `200` — Eye contact enhancement started successfully
  - `400` — Bad Request - Invalid parameters
  - `401` — Unauthorized - Invalid or missing JWT token

### Voice & Audio
#### TTS and Voice Clone

##### POST /api/v1/anchor/tts_list — List system voices (TTS presets)
List available system TTS voices/presets for the current user. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - No request body or operation-specific parameters are required. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid parameters. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `POST /api/v1/anchor/language_list` — List supported languages/regions for voices. - `POST /api/v1/anchor/voice_list` — List available voices by country/region. - `GET /api/v1/anchor/voice_list` — List available voices (GET) Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1AnchorTtsList`
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/anchor/tts_list" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Voice preset list
  - `400` — Bad Request - Invalid parameters
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/anchor/language_list — List supported languages/regions for voices
List supported language & region options. Optional `voice_map_type` can be used to filter results. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body when using the optional controls documented in the request schema. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid parameters. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `POST /api/v1/anchor/tts_list` — List system voices (TTS presets) - `POST /api/v1/anchor/voice_list` — List available voices by country/region. - `GET /api/v1/anchor/voice_list` — List available voices (GET) Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1AnchorLanguageList`
- JSON body fields:
  - `voice_map_type` (body, optional; string; example: `en-US`) — Filter by locale mapping type (e.g. en-US)
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/anchor/language_list" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "voice_map_type": "en-US"
}
JSON
```
- Responses:
  - `200` — Language/region list
  - `400` — Bad Request - Invalid parameters
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/anchor/voice_list — List available voices by country/region
List available voices filtered by `country`, `region`, and `voice_map_type`. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body when using the optional controls documented in the request schema. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid parameters. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `POST /api/v1/anchor/tts_list` — List system voices (TTS presets) - `POST /api/v1/anchor/language_list` — List supported languages/regions for voices. - `GET /api/v1/anchor/voice_list` — List available voices (GET) Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1AnchorVoiceList`
- JSON body fields:
  - `country` (body, optional; string; example: `en`) — Country/language code (default en)
  - `region` (body, optional; string; example: `US`) — Region code (default US)
  - `voice_map_type` (body, optional; string; example: `en-US`) — Locale mapping type (default en-US)
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/anchor/voice_list" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "country": "en",
  "region": "US",
  "voice_map_type": "en-US"
}
JSON
```
- Responses:
  - `200` — Voice list
  - `400` — Bad Request - Invalid parameters
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/anchor/voice_list — List available voices (GET)
List available voices. Defaults: country=en, region=US, voice_map_type=en-US. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supported query parameters: `country`, `region`, `voice_map_type`. Omitted values use the defaults shown in the parameter schema. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `POST /api/v1/anchor/tts_list` — List system voices (TTS presets) - `POST /api/v1/anchor/language_list` — List supported languages/regions for voices. - `POST /api/v1/anchor/voice_list` — List available voices by country/region. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1AnchorVoiceList`
- Request parameters:
  - `country` (query, optional; string; default: `en`; example: `en`) — country parameter
  - `region` (query, optional; string; default: `US`; example: `US`) — region parameter
  - `voice_map_type` (query, optional; string; default: `en-US`; example: `en-US`) — voice_map_type parameter
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/anchor/voice_list?country=en&region=US&voice_map_type=en-US" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Item retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/video/send_tts — Generate text-to-speech audio
Convert text to speech using AI voices with customizable parameters. ### Voice Selection Must provide **either** `tts_id` (system voice) **or** `user_voice_id` (custom cloned voice): - `tts_id`: Use built-in system voice (400+ voices available) - `user_voice_id`: Use your own custom cloned voice (requires `country` and `region` parameters) ### Text Limitations - **API users**: Maximum 1000 characters per request - **Web users**: Maximum 3000 characters per request - Text length is calculated including all Unicode characters ### Rate Limiting & Captcha For non-API users, captcha verification may be required after frequent usage: - Use `type` parameter to specify captcha type (`turnstile` or `aliyun_captcha`) - Provide corresponding `turnstile_token` or `captchaVerifyParam` when captcha is required - API token users skip captcha verification. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `msg`. ### Behavior - Validates the submitted payload and performs the operation described by the request schema. - Conditional fields, mutually exclusive inputs, limits, and defaults are enforced as documented by their schemas. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Invalid request parameters. - `401` — Unauthorized - Invalid or missing JWT token. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1VideoSendTts`
- JSON body fields:
  - `msg` (body, required; string; min length: 1; max length: 3000; example: `Welcome. Let's start your AI journey.`) — Text content to convert to speech (1-3000 characters)
  - `tts_id` (body, optional; string; example: `66dc3c1b7dc1f1c483cc5ab8`) — System voice ID (MongoDB ObjectId). Must provide either tts_id or user_voice_id.
  - `user_voice_id` (body, optional; string; example: `66f1234567890abcdef12345`) — Custom cloned voice ID (MongoDB ObjectId). Must provide either tts_id or user_voice_id.
  - `country` (body, optional; string; default: `en`; example: `en`) — Locale language part (e.g. 'en', 'zh', 'pt', 'ja'). Optional when using user_voice_id, defaults to 'en'. Combine with `region` to form locale like 'en-US'/'zh-CN'. Values should come from POST /api/v1/anchor/language_list (top-level `value`).
  - `region` (body, optional; string; default: `US`; example: `US`) — Locale region part (e.g. 'US', 'CN', 'BR', 'JP'). Optional when using user_voice_id, defaults to 'US'. Combine with `country` to form locale like 'en-US'/'zh-CN'. Values should come from POST /api/v1/anchor/language_list (child `value`).
  - `speechRate` (body, optional; number; default: `1`; min: 0.5; max: 2; example: `1`) — Speech speed multiplier (0.5-2.0)
  - `type` (body, optional; string; allowed: `turnstile`, `aliyun_captcha`; example: `turnstile`) — Captcha type (required when captcha verification is needed)
  - `turnstile_token` (body, optional; string; example: `0x4AAAAAAxxxxxxxxxxxxxxxxxx`) — Captcha token (required when type is 'turnstile')
  - `captchaVerifyParam` (body, optional; string; example: `xxxxxxxxxxxx`) — Captcha verification parameter (required when type is 'aliyun_captcha')
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/video/send_tts" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "msg": "Welcome. Let's start your AI journey.",
  "tts_id": "66dc3c1b7dc1f1c483cc5ab8",
  "user_voice_id": "66f1234567890abcdef12345",
  "country": "en",
  "region": "US",
  "speechRate": 1,
  "type": "turnstile",
  "turnstile_token": "0x4AAAAAAxxxxxxxxxxxxxxxxxx",
  "captchaVerifyParam": "xxxxxxxxxxxx"
}
JSON
```
- Responses:
  - `200` — Text-to-speech generation successful
  - `400` — Invalid request parameters
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/tts/preview/list — Get TTS preview list
Return the authenticated user's non-deleted TTS preview records created during the last 24 hours, ordered for recent-preview playback. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supported query parameters: `pageSize`, `current`. Omitted values use the defaults shown in the parameter schema. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `DELETE /api/v1/tts/preview/{id}` — Delete TTS preview record. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1TtsPreviewList`
- Request parameters:
  - `pageSize` (query, optional; integer; default: `20`; min: 1; max: 100; example: `20`) — Number of items per page
  - `current` (query, optional; integer; default: `1`; min: 1; example: `1`) — Current page number
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/tts/preview/list?pageSize=20&current=1" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — TTS preview list retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### DELETE /api/v1/tts/preview/{id} — Delete TTS preview record
Soft-delete the authenticated user's TTS preview record identified by `id`; the underlying audio object is not physically removed by this operation. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `id` in the URL path. ### Behavior - Deletes or marks the selected resource as deleted according to the endpoint's documented lifecycle rules. - Use the resource identifier from a list, creation, or detail response; deleting one resource does not affect unrelated records. - Do not assume an in-progress task can be cancelled unless the endpoint explicitly documents that behavior. ### Response - A `200` response confirms that the deletion request was applied to the selected record. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. - `404` — Record not found. ### Related Operations - `GET /api/v1/tts/preview/list` — Get TTS preview list. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `deleteApiV1TtsPreviewId`
- Request parameters:
  - `id` (path, required; string; example: `507f1f77bcf86cd799439011`) — TTS preview record ID to delete
- Example request:
```bash
curl -X DELETE "https://video.a2e.ai/api/v1/tts/preview/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — TTS preview record deleted successfully
  - `401` — Unauthorized - Invalid or missing JWT token
  - `404` — Record not found

##### POST /api/v1/userVoice/training — Start voice training
Create an asynchronous custom-voice training task from the submitted voice samples. - **Concurrency:** A user may submit only one training request at a time; concurrent submissions are rejected by the service guard. - **Charging:** Coin usage depends on `model`. A failed creation attempt rolls back the charge automatically. - **Status:** After creation, poll `GET /api/v1/userVoice/trainingRecord` and inspect `current_status` for progress. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `name`, `voice_urls`. - API-token callers may include `webhook_url` and `webhook_token` for best-effort terminal-state notifications; ordinary JWT/cookie calls ignore these fields. ### Behavior - This is an asynchronous operation: a successful submission creates a task and returns before processing finishes. - Persist the returned task identifier and use the corresponding detail or list operation to observe progress. - Treat the detail endpoint as the source of truth even when webhook delivery is enabled. ### Response - A `200` response confirms task acceptance; it does not by itself mean media generation has completed. - Retain the returned identifier and wait for a documented terminal status before using output URLs. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid training data. - `401` — Unauthorized - Invalid or missing JWT token. - `403` — Forbidden - Voice clone limit exceeded. ### Related Operations - `DELETE /api/v1/userVoice/{_id}` — Delete voice training record. - `GET /api/v1/userVoice/{_id}` — Get voice training record detail. - `PUT /api/v1/userVoice/{_id}` — Update voice training record name. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1UserVoiceTraining`
- JSON body fields:
  - `name` (body, required; string; example: `My Custom Voice`) — Name of the voice model
  - `voice_urls` (body, required; string[]; min items: 1; example: `["https://example.com/audio1.wav","https://example.com/audio2.wav"]`) — Array of audio file URLs for training
  - `gender` (body, optional; string; allowed: `female`, `male`; default: `female`; example: `female`) — Voice gender
  - `denoise` (body, optional; boolean; example: `true`) — Whether to apply denoising
  - `enhance_voice_similarity` (body, optional; boolean; example: `true`) — Whether to enhance voice similarity
  - `model` (body, optional; string; allowed: `a2e`, `cartesia`, `minimax`, `elevenlabs`; default: `a2e`; example: `a2e`) — Voice model to use
  - `language` (body, optional; string; example: `en-US`) — Language code from client (e.g. en-US, zh-CN). If omitted, server will infer from request headers.
  - `webhook_url` (body, optional; string; max length: 2048; example: `https://your-server.example.com/a2e/webhook`) — HTTPS URL to receive task.completed / task.failed notifications. Best-effort delivery, single attempt, no retries; clients should treat the detail API as the source of truth.
  - `webhook_token` (body, optional; string; max length: 256; example: `a-shared-secret`) — Optional plaintext token returned in the X-A2e-Webhook-Token header so receivers can verify the request originated from a2e.
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/userVoice/training" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "name": "My Custom Voice",
  "voice_urls": [
    "https://example.com/audio1.wav",
    "https://example.com/audio2.wav"
  ],
  "gender": "female",
  "denoise": true,
  "enhance_voice_similarity": true,
  "model": "a2e",
  "language": "en-US",
  "webhook_url": "https://your-server.example.com/a2e/webhook",
  "webhook_token": "a-shared-secret"
}
JSON
```
- Responses:
  - `200` — Voice training record created successfully
  - `400` — Bad Request - Invalid training data
  - `401` — Unauthorized - Invalid or missing JWT token
  - `403` — Forbidden - Voice clone limit exceeded

##### GET /api/v1/userVoice/trainingRecord — Get voice training records
Return the authenticated user's voice-training records across queued, processing, completed, and failed states. - **Ordering:** Records are sorted by `createdAt` in descending order, newest first. - **Status values:** `current_status` may be `sent`, `pendding`, `processing`, `completed`, or `failed`. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - No request body or operation-specific parameters are required. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `DELETE /api/v1/userVoice/{_id}` — Delete voice training record. - `GET /api/v1/userVoice/{_id}` — Get voice training record detail. - `PUT /api/v1/userVoice/{_id}` — Update voice training record name. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1UserVoiceTrainingRecord`
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/userVoice/trainingRecord" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Successful response
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/userVoice/completedRecord — Get completed voice training records
Return only the authenticated user's completed voice-training records (`current_status=completed`). - **Ordering:** Records are sorted by `createdAt` in descending order, newest first. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - No request body or operation-specific parameters are required. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `DELETE /api/v1/userVoice/{_id}` — Delete voice training record. - `GET /api/v1/userVoice/{_id}` — Get voice training record detail. - `PUT /api/v1/userVoice/{_id}` — Update voice training record name. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1UserVoiceCompletedRecord`
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/userVoice/completedRecord" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Successful response
  - `401` — Unauthorized - Invalid or missing JWT token

##### DELETE /api/v1/userVoice/{_id} — Delete voice training record
Soft-delete the authenticated user's voice-training record by setting `deleted=true`; the stored record is not physically removed. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Deletes or marks the selected resource as deleted according to the endpoint's documented lifecycle rules. - Use the resource identifier from a list, creation, or detail response; deleting one resource does not affect unrelated records. - Do not assume an in-progress task can be cancelled unless the endpoint explicitly documents that behavior. ### Response - A `200` response confirms that the deletion request was applied to the selected record. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userVoice/{_id}` — Get voice training record detail. - `PUT /api/v1/userVoice/{_id}` — Update voice training record name. - `POST /api/v1/userVoice/training` — Start voice training. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `deleteApiV1UserVoiceId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — MongoDB ObjectId of the voice training record
- Example request:
```bash
curl -X DELETE "https://video.a2e.ai/api/v1/userVoice/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Successful response
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/userVoice/{_id} — Get voice training record detail
Return one voice-training record owned by the authenticated user, identified by `_id`. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Retrieves the current server-side representation of the requested resource or task. - For asynchronous tasks, inspect the documented status and result fields before consuming generated media. - Repeat the request only as needed for polling and stop after the task reaches a terminal state. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid _id. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `DELETE /api/v1/userVoice/{_id}` — Delete voice training record. - `PUT /api/v1/userVoice/{_id}` — Update voice training record name. - `POST /api/v1/userVoice/training` — Start voice training. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1UserVoiceId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — MongoDB ObjectId of the voice training record
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/userVoice/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Successful response
  - `400` — Bad Request - Invalid _id
  - `401` — Unauthorized - Invalid or missing JWT token

##### PUT /api/v1/userVoice/{_id} — Update voice training record name
Rename the authenticated user's voice-training record identified by `_id`; no training inputs or status fields are changed. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. - Send an `application/json` body. Required fields: `name`. ### Behavior - Updates the identified resource using the fields accepted by the request schema and the operation's access controls. - Fields omitted from the request retain their existing values unless the schema states otherwise. - Read the returned record or call the detail operation to confirm the persisted state. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid request body. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `DELETE /api/v1/userVoice/{_id}` — Delete voice training record. - `GET /api/v1/userVoice/{_id}` — Get voice training record detail. - `POST /api/v1/userVoice/training` — Start voice training. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `putApiV1UserVoiceId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — MongoDB ObjectId of the voice training record
- JSON body fields:
  - `name` (body, required; string; example: `My Renamed Voice`) — New name of the voice record
- Example request:
```bash
curl -X PUT "https://video.a2e.ai/api/v1/userVoice/507f1f77bcf86cd799439011" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "name": "My Renamed Voice"
}
JSON
```
- Responses:
  - `200` — Successful response
  - `400` — Bad Request - Invalid request body
  - `401` — Unauthorized - Invalid or missing JWT token
#### AI Dubbing

##### POST /api/v1/userDubbing/startDubbing — Start AI dubbing task
startDubbing. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body when using the optional controls documented in the request schema. - API-token callers may include `webhook_url` and `webhook_token` for best-effort terminal-state notifications; ordinary JWT/cookie calls ignore these fields. ### Behavior - This is an asynchronous operation: a successful submission creates a task and returns before processing finishes. - Persist the returned task identifier and use the corresponding detail or list operation to observe progress. - Treat the detail endpoint as the source of truth even when webhook delivery is enabled. ### Response - A `200` response confirms task acceptance; it does not by itself mean media generation has completed. - Retain the returned identifier and wait for a documented terminal status before using output URLs. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userDubbing/allRecords` — Get all task records. - `GET /api/v1/userDubbing/{_id}` — Get task details. - `DELETE /api/v1/userDubbing/{_id}` — Delete dubbing task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1UserDubbingStartDubbing`
- JSON body fields:
  - `webhook_url` (body, optional; string; max length: 2048; example: `https://your-server.example.com/a2e/webhook`) — HTTPS URL to receive task.completed / task.failed notifications. Best-effort delivery, single attempt, no retries; clients should treat the detail API as the source of truth.
  - `webhook_token` (body, optional; string; max length: 256; example: `a-shared-secret`) — Optional plaintext token returned in the X-A2e-Webhook-Token header so receivers can verify the request originated from a2e.
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/userDubbing/startDubbing" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "webhook_url": "https://your-server.example.com/a2e/webhook",
  "webhook_token": "a-shared-secret"
}
JSON
```
- Responses:
  - `200` — Successful response
  - `400` — Bad Request
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/userDubbing/allRecords — Get all task records
Return the authenticated user's dubbing tasks, newest first, using the requested page number and page size. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supported query parameters: `pageNum`, `pageSize`. Omitted values use the defaults shown in the parameter schema. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userDubbing/{_id}` — Get task details. - `DELETE /api/v1/userDubbing/{_id}` — Delete dubbing task. - `POST /api/v1/userDubbing/startDubbing` — startDubbing. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1UserDubbingAllRecords`
- Request parameters:
  - `pageNum` (query, optional; integer; min: 1; example: `1`) — Page number
  - `pageSize` (query, optional; integer; example: `10`) — Page size
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/userDubbing/allRecords?pageNum=1&pageSize=10" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task list retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/userDubbing/allProcessing — List processing records
allProcessing. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - No request body or operation-specific parameters are required. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userDubbing/allRecords` — Get all task records. - `GET /api/v1/userDubbing/{_id}` — Get task details. - `DELETE /api/v1/userDubbing/{_id}` — Delete dubbing task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1UserDubbingAllProcessing`
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/userDubbing/allProcessing" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Successful response
  - `400` — Bad Request
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/userDubbing/{_id} — Get task details
Return the authenticated user's dubbing task identified by `_id`, including its current processing status and available output fields. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Retrieves the current server-side representation of the requested resource or task. - For asynchronous tasks, inspect the documented status and result fields before consuming generated media. - Repeat the request only as needed for polling and stop after the task reaches a terminal state. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userDubbing/allRecords` — Get all task records. - `DELETE /api/v1/userDubbing/{_id}` — Delete dubbing task. - `POST /api/v1/userDubbing/startDubbing` — startDubbing. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1UserDubbingId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — Task ID
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/userDubbing/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task details retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### DELETE /api/v1/userDubbing/{_id} — Delete dubbing task
Remove the authenticated user's dubbing task identified by `_id` from the task history without affecting other dubbing records. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Deletes or marks the selected resource as deleted according to the endpoint's documented lifecycle rules. - Use the resource identifier from a list, creation, or detail response; deleting one resource does not affect unrelated records. - Do not assume an in-progress task can be cancelled unless the endpoint explicitly documents that behavior. ### Response - A `200` response confirms that the deletion request was applied to the selected record. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid task ID. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userDubbing/allRecords` — Get all task records. - `GET /api/v1/userDubbing/{_id}` — Get task details. - `POST /api/v1/userDubbing/startDubbing` — startDubbing. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `deleteApiV1UserDubbingId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — ID of the dubbing task
- Example request:
```bash
curl -X DELETE "https://video.a2e.ai/api/v1/userDubbing/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task deleted successfully
  - `400` — Bad Request - Invalid task ID
  - `401` — Unauthorized - Invalid or missing JWT token
#### ThinkSound

##### POST /api/v1/thinkSound/start — Start ThinkSound generation
Generate audio-visual content from video using AI with customizable parameters. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `video_url`. - API-token callers may include `webhook_url` and `webhook_token` for best-effort terminal-state notifications; ordinary JWT/cookie calls ignore these fields. ### Behavior - This is an asynchronous operation: a successful submission creates a task and returns before processing finishes. - Persist the returned task identifier and use the corresponding detail or list operation to observe progress. - Treat the detail endpoint as the source of truth even when webhook delivery is enabled. ### Response - A `200` response confirms task acceptance; it does not by itself mean media generation has completed. - Retain the returned identifier and wait for a documented terminal status before using output URLs. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid parameters or video format. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/thinkSound/allRecords` — Get all ThinkSound records. - `DELETE /api/v1/thinkSound/{_id}` — Delete ThinkSound task. - `GET /api/v1/thinkSound/{_id}` — Get ThinkSound task details. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1ThinkSoundStart`
- JSON body fields:
  - `name` (body, optional; string; example: `My Audio-Visual Generation`) — Name of the ThinkSound task
  - `video_url` (body, required; string; example: `https://example.com/video.mp4`) — URL of the source video (must be .mp4, .avi, .mov, or .mkv)
  - `caption` (body, optional; string; default: ``; example: `Generate audio for this silent video`) — Caption for the generation
  - `cot_description` (body, optional; string; default: ``; example: `Detailed description of the audio generation process`) — Chain of thought description
  - `seed` (body, optional; number; example: `12345`) — Random seed for reproducible results
  - `webhook_url` (body, optional; string; max length: 2048; example: `https://your-server.example.com/a2e/webhook`) — HTTPS URL to receive task.completed / task.failed notifications. Best-effort delivery, single attempt, no retries; clients should treat the detail API as the source of truth.
  - `webhook_token` (body, optional; string; max length: 256; example: `a-shared-secret`) — Optional plaintext token returned in the X-A2e-Webhook-Token header so receivers can verify the request originated from a2e.
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/thinkSound/start" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "name": "My Audio-Visual Generation",
  "video_url": "https://example.com/video.mp4",
  "caption": "Generate audio for this silent video",
  "cot_description": "Detailed description of the audio generation process",
  "seed": 12345,
  "webhook_url": "https://your-server.example.com/a2e/webhook",
  "webhook_token": "a-shared-secret"
}
JSON
```
- Responses:
  - `200` — ThinkSound generation started successfully
  - `400` — Bad Request - Invalid parameters or video format
  - `401` — Unauthorized - Invalid or missing JWT token

##### DELETE /api/v1/thinkSound/{_id} — Delete ThinkSound task
Remove the authenticated user's ThinkSound generation task identified by `_id` from the task history without affecting other generated-audio records. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Deletes or marks the selected resource as deleted according to the endpoint's documented lifecycle rules. - Use the resource identifier from a list, creation, or detail response; deleting one resource does not affect unrelated records. - Do not assume an in-progress task can be cancelled unless the endpoint explicitly documents that behavior. ### Response - A `200` response confirms that the deletion request was applied to the selected record. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid task ID. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/thinkSound/allRecords` — Get all ThinkSound records. - `GET /api/v1/thinkSound/{_id}` — Get ThinkSound task details. - `POST /api/v1/thinkSound/start` — Start ThinkSound generation. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `deleteApiV1ThinkSoundId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — ID of the ThinkSound task to delete
- Example request:
```bash
curl -X DELETE "https://video.a2e.ai/api/v1/thinkSound/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — ThinkSound task deleted successfully
  - `400` — Bad Request - Invalid task ID
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/thinkSound/{_id} — Get ThinkSound task details
Retrieve detailed information about a specific ThinkSound generation task. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Retrieves the current server-side representation of the requested resource or task. - For asynchronous tasks, inspect the documented status and result fields before consuming generated media. - Repeat the request only as needed for polling and stop after the task reaches a terminal state. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid task ID format. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/thinkSound/allRecords` — Get all ThinkSound records. - `DELETE /api/v1/thinkSound/{_id}` — Delete ThinkSound task. - `POST /api/v1/thinkSound/start` — Start ThinkSound generation. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1ThinkSoundId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — ID of the ThinkSound task
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/thinkSound/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — ThinkSound task details retrieved successfully
  - `400` — Bad Request - Invalid task ID format
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/thinkSound/allRecords — Get all ThinkSound records
Retrieve paginated list of ThinkSound generation tasks for the authenticated user. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supported query parameters: `pageNum`, `pageSize`. Omitted values use the defaults shown in the parameter schema. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid pagination parameters. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `DELETE /api/v1/thinkSound/{_id}` — Delete ThinkSound task. - `GET /api/v1/thinkSound/{_id}` — Get ThinkSound task details. - `POST /api/v1/thinkSound/start` — Start ThinkSound generation. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1ThinkSoundAllRecords`
- Request parameters:
  - `pageNum` (query, optional; integer; default: `1`; min: 1; example: `1`) — Page number (starts from 1)
  - `pageSize` (query, optional; integer; default: `10`; min: 1; max: 100; example: `10`) — Number of records per page
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/thinkSound/allRecords?pageNum=1&pageSize=10" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — ThinkSound records retrieved successfully
  - `400` — Bad Request - Invalid pagination parameters
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/thinkSound/batchDetail — Batch query task details
Query details for multiple tasks at once by providing an array of task IDs. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `ids`. ### Behavior - Fetches several task records in one request, reducing the number of individual detail calls. - Results remain subject to the same authentication and ownership checks as single-record lookups. - Match returned records by their identifiers instead of relying on response ordering. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/thinkSound/allRecords` — Get all ThinkSound records. - `DELETE /api/v1/thinkSound/{_id}` — Delete ThinkSound task. - `GET /api/v1/thinkSound/{_id}` — Get ThinkSound task details. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1ThinkSoundBatchDetail`
- JSON body fields:
  - `ids` (body, required; string[]; example: `["example"]`) — Array of task IDs to query
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/thinkSound/batchDetail" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "ids": [
    "example"
  ]
}
JSON
```
- Responses:
  - `200` — Batch details retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

### Post Processing
#### Caption Removal

##### POST /api/v1/userCaptionRemoval/start — Start caption removal task
Create an asynchronous caption-removal task for the submitted source video and return the record used to monitor processing. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `name`, `source_url`. - API-token callers may include `webhook_url` and `webhook_token` for best-effort terminal-state notifications; ordinary JWT/cookie calls ignore these fields. ### Behavior - This is an asynchronous operation: a successful submission creates a task and returns before processing finishes. - Persist the returned task identifier and use the corresponding detail or list operation to observe progress. - Treat the detail endpoint as the source of truth even when webhook delivery is enabled. ### Response - A `200` response confirms task acceptance; it does not by itself mean media generation has completed. - Retain the returned identifier and wait for a documented terminal status before using output URLs. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid parameters. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userCaptionRemoval/allRecords` — Get all task records. - `GET /api/v1/userCaptionRemoval/{_id}` — Get task details. - `DELETE /api/v1/userCaptionRemoval/{_id}` — Delete caption removal task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1UserCaptionRemovalStart`
- JSON body fields:
  - `name` (body, required; string; example: `Remove captions from video`) — Name of the caption removal task
  - `source_url` (body, required; string; example: `https://example.com/video.mp4`) — URL of the source video
  - `webhook_url` (body, optional; string; max length: 2048; example: `https://your-server.example.com/a2e/webhook`) — HTTPS URL to receive task.completed / task.failed notifications. Best-effort delivery, single attempt, no retries; clients should treat the detail API as the source of truth.
  - `webhook_token` (body, optional; string; max length: 256; example: `a-shared-secret`) — Optional plaintext token returned in the X-A2e-Webhook-Token header so receivers can verify the request originated from a2e.
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/userCaptionRemoval/start" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "name": "Remove captions from video",
  "source_url": "https://example.com/video.mp4",
  "webhook_url": "https://your-server.example.com/a2e/webhook",
  "webhook_token": "a-shared-secret"
}
JSON
```
- Responses:
  - `200` — Caption removal task started successfully
  - `400` — Bad Request - Invalid parameters
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/userCaptionRemoval/allRecords — Get all task records
Return the authenticated user's caption-removal tasks, newest first, using the requested page number and page size. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supported query parameters: `pageNum`, `pageSize`. Omitted values use the defaults shown in the parameter schema. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userCaptionRemoval/{_id}` — Get task details. - `DELETE /api/v1/userCaptionRemoval/{_id}` — Delete caption removal task. - `POST /api/v1/userCaptionRemoval/start` — Start caption removal task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1UserCaptionRemovalAllRecords`
- Request parameters:
  - `pageNum` (query, optional; integer; min: 1; example: `1`) — Page number
  - `pageSize` (query, optional; integer; example: `10`) — Page size
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/userCaptionRemoval/allRecords?pageNum=1&pageSize=10" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task list retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/userCaptionRemoval/allProcessing — List processing records
allProcessing. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - No request body or operation-specific parameters are required. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userCaptionRemoval/allRecords` — Get all task records. - `GET /api/v1/userCaptionRemoval/{_id}` — Get task details. - `DELETE /api/v1/userCaptionRemoval/{_id}` — Delete caption removal task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1UserCaptionRemovalAllProcessing`
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/userCaptionRemoval/allProcessing" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Successful response
  - `400` — Bad Request
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/userCaptionRemoval/batchDetail — Batch query task details
Query details for multiple tasks at once by providing an array of task IDs. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `ids`. ### Behavior - Fetches several task records in one request, reducing the number of individual detail calls. - Results remain subject to the same authentication and ownership checks as single-record lookups. - Match returned records by their identifiers instead of relying on response ordering. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userCaptionRemoval/allRecords` — Get all task records. - `GET /api/v1/userCaptionRemoval/{_id}` — Get task details. - `DELETE /api/v1/userCaptionRemoval/{_id}` — Delete caption removal task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1UserCaptionRemovalBatchDetail`
- JSON body fields:
  - `ids` (body, required; string[]; example: `["example"]`) — Array of task IDs to query
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/userCaptionRemoval/batchDetail" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "ids": [
    "example"
  ]
}
JSON
```
- Responses:
  - `200` — Batch details retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### GET /api/v1/userCaptionRemoval/{_id} — Get task details
Return the authenticated user's caption-removal task identified by `_id`, including its current processing status and available output fields. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Retrieves the current server-side representation of the requested resource or task. - For asynchronous tasks, inspect the documented status and result fields before consuming generated media. - Repeat the request only as needed for polling and stop after the task reaches a terminal state. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userCaptionRemoval/allRecords` — Get all task records. - `DELETE /api/v1/userCaptionRemoval/{_id}` — Delete caption removal task. - `POST /api/v1/userCaptionRemoval/start` — Start caption removal task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1UserCaptionRemovalId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — Task ID
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/userCaptionRemoval/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task details retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### DELETE /api/v1/userCaptionRemoval/{_id} — Delete caption removal task
Remove the authenticated user's caption-removal task identified by `_id` from the task history without affecting other records. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Deletes or marks the selected resource as deleted according to the endpoint's documented lifecycle rules. - Use the resource identifier from a list, creation, or detail response; deleting one resource does not affect unrelated records. - Do not assume an in-progress task can be cancelled unless the endpoint explicitly documents that behavior. ### Response - A `200` response confirms that the deletion request was applied to the selected record. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid task ID. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userCaptionRemoval/allRecords` — Get all task records. - `GET /api/v1/userCaptionRemoval/{_id}` — Get task details. - `POST /api/v1/userCaptionRemoval/start` — Start caption removal task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `deleteApiV1UserCaptionRemovalId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — ID of the caption removal task
- Example request:
```bash
curl -X DELETE "https://video.a2e.ai/api/v1/userCaptionRemoval/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task deleted successfully
  - `400` — Bad Request - Invalid task ID
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/userCaptionRemoval/retry — Retry a failed task
retry. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - No request body or operation-specific parameters are required. ### Behavior - Requests another processing attempt for an eligible failed task. - Eligibility, charging, and state transitions follow the task-specific rules exposed by the response. - Continue monitoring the same or returned task identifier after the retry is accepted. ### Response - A `200` response confirms task acceptance; it does not by itself mean media generation has completed. - Retain the returned identifier and wait for a documented terminal status before using output URLs. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userCaptionRemoval/allRecords` — Get all task records. - `GET /api/v1/userCaptionRemoval/{_id}` — Get task details. - `DELETE /api/v1/userCaptionRemoval/{_id}` — Delete caption removal task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1UserCaptionRemovalRetry`
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/userCaptionRemoval/retry" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Successful response
  - `400` — Bad Request
  - `401` — Unauthorized - Invalid or missing JWT token
#### Upscale

##### POST /api/v1/userUpscale/start — Start upscale task
Create an asynchronous media-upscaling task for the submitted image or video source and return the record used to monitor processing. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `source_url`. - API-token callers may include `webhook_url` and `webhook_token` for best-effort terminal-state notifications; ordinary JWT/cookie calls ignore these fields. ### Behavior - This is an asynchronous operation: a successful submission creates a task and returns before processing finishes. - Persist the returned task identifier and use the corresponding detail or list operation to observe progress. - Treat the detail endpoint as the source of truth even when webhook delivery is enabled. ### Response - A `200` response confirms task acceptance; it does not by itself mean media generation has completed. - Retain the returned identifier and wait for a documented terminal status before using output URLs. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request. - `401` — Unauthorized. ### Related Operations - `GET /api/v1/userUpscale/allRecords` — Get all task records. - `GET /api/v1/userUpscale/{_id}` — Get task details. - `DELETE /api/v1/userUpscale/{_id}` — Delete task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1UserUpscaleStart`
- JSON body fields:
  - `name` (body, optional; string; example: `Upscale media`) — Name of the upscale task
  - `source_url` (body, required; string; example: `https://example.com/video.mp4`) — URL of the source image or video
  - `webhook_url` (body, optional; string; max length: 2048; example: `https://your-server.example.com/a2e/webhook`) — HTTPS URL to receive task.completed / task.failed notifications. Best-effort delivery, single attempt, no retries; clients should treat the detail API as the source of truth.
  - `webhook_token` (body, optional; string; max length: 256; example: `a-shared-secret`) — Optional plaintext token returned in the X-A2e-Webhook-Token header so receivers can verify the request originated from a2e.
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/userUpscale/start" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "name": "Upscale media",
  "source_url": "https://example.com/video.mp4",
  "webhook_url": "https://your-server.example.com/a2e/webhook",
  "webhook_token": "a-shared-secret"
}
JSON
```
- Responses:
  - `200` — Successful response
  - `400` — Bad Request
  - `401` — Unauthorized

##### GET /api/v1/userUpscale/allRecords — Get all task records
Return the authenticated user's media-upscaling tasks, newest first, using the requested page number and page size. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supported query parameters: `pageNum`, `pageSize`. Omitted values use the defaults shown in the parameter schema. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userUpscale/{_id}` — Get task details. - `DELETE /api/v1/userUpscale/{_id}` — Delete task. - `POST /api/v1/userUpscale/start` — Start upscale task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1UserUpscaleAllRecords`
- Request parameters:
  - `pageNum` (query, optional; integer; min: 1; example: `1`) — Page number
  - `pageSize` (query, optional; integer; example: `10`) — Page size
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/userUpscale/allRecords?pageNum=1&pageSize=10" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task list retrieved successfully
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/userUpscale/batchDetail — Batch query task details
Query details for multiple tasks at once by providing an array of task IDs. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `ids`. ### Behavior - Fetches several task records in one request, reducing the number of individual detail calls. - Results remain subject to the same authentication and ownership checks as single-record lookups. - Match returned records by their identifiers instead of relying on response ordering. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - Non-success responses use the published error envelope; surface the returned message and code to diagnostics. ### Related Operations - `GET /api/v1/userUpscale/allRecords` — Get all task records. - `GET /api/v1/userUpscale/{_id}` — Get task details. - `DELETE /api/v1/userUpscale/{_id}` — Delete task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1UserUpscaleBatchDetail`
- JSON body fields:
  - `ids` (body, required; string[]; example: `["example"]`) — Array of task IDs to query
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/userUpscale/batchDetail" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "ids": [
    "example"
  ]
}
JSON
```
- Responses:
  - `200` — Batch details retrieved successfully

##### GET /api/v1/userUpscale/{_id} — Get task details
Return the authenticated user's media-upscaling task identified by `_id`, including its current processing status and available output fields. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Retrieves the current server-side representation of the requested resource or task. - For asynchronous tasks, inspect the documented status and result fields before consuming generated media. - Repeat the request only as needed for polling and stop after the task reaches a terminal state. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - Non-success responses use the published error envelope; surface the returned message and code to diagnostics. ### Related Operations - `GET /api/v1/userUpscale/allRecords` — Get all task records. - `DELETE /api/v1/userUpscale/{_id}` — Delete task. - `POST /api/v1/userUpscale/start` — Start upscale task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1UserUpscaleId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — Task ID
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/userUpscale/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task details retrieved successfully

##### DELETE /api/v1/userUpscale/{_id} — Delete task
Remove the authenticated user's media-upscaling task identified by `_id` from the task history without affecting other records. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supply `_id` in the URL path. ### Behavior - Deletes or marks the selected resource as deleted according to the endpoint's documented lifecycle rules. - Use the resource identifier from a list, creation, or detail response; deleting one resource does not affect unrelated records. - Do not assume an in-progress task can be cancelled unless the endpoint explicitly documents that behavior. ### Response - A `200` response confirms that the deletion request was applied to the selected record. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `GET /api/v1/userUpscale/allRecords` — Get all task records. - `GET /api/v1/userUpscale/{_id}` — Get task details. - `POST /api/v1/userUpscale/start` — Start upscale task. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `deleteApiV1UserUpscaleId`
- Request parameters:
  - `_id` (path, required; string; example: `507f1f77bcf86cd799439011`) — Task ID to delete
- Example request:
```bash
curl -X DELETE "https://video.a2e.ai/api/v1/userUpscale/507f1f77bcf86cd799439011" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Task deleted successfully
  - `401` — Unauthorized - Invalid or missing JWT token

### Utilities
#### Miscellaneous

##### POST /api/v1/r2/get_upload_presigned_url — Get pre-signed upload URL
Legacy endpoint for generating a pre-signed R2 PUT URL. Prefer /api/v1/r2/upload-presigned-url for new integrations. If bucket is omitted, files are uploaded to 3days-apac by default. urlPrefix changes the leading object-key path and defaults to adam2eve. cdnDomain changes the CDN domain suffix and defaults to the existing makefun.ai behavior. The returned key is scoped to {urlPrefix}/{env}/user/{user_id}/. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `key`. ### Behavior - Validates the submitted payload and performs the operation described by the request schema. - Conditional fields, mutually exclusive inputs, limits, and defaults are enforced as documented by their schemas. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid parameters. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `POST /api/v1/r2/upload-presigned-url` — Get pre-signed upload URL. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1R2GetUploadPresignedUrl`
- JSON body fields:
  - `key` (body, required; string; example: `example_key`) — key parameter
  - `bucket` (body, optional; string; example: `3days-apac`) — R2 bucket. Defaults to 3days-apac.
  - `urlPrefix` (body, optional; string; example: `adam2eve`) — Leading object-key path. Defaults to adam2eve.
  - `cdnDomain` (body, optional; string; example: `makefun.ai`) — CDN domain suffix without scheme or path. Defaults to the existing makefun.ai behavior.
  - `expiresIn` (body, optional; integer; min: 60; example: `60`) — expiresIn parameter
  - `contentType` (body, optional; string; example: `image/png`) — MIME type to bind to the upload request.
  - `fileSize` (body, optional; number; example: `1048576`) — Optional file size in bytes. When provided, the pre-signed URL binds Content-Length.
  - `contentLength` (body, optional; number; example: `1048576`) — Optional Content-Length in bytes. Takes priority over fileSize if both are provided.
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/r2/get_upload_presigned_url" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "key": "example_key",
  "bucket": "3days-apac",
  "urlPrefix": "adam2eve",
  "cdnDomain": "makefun.ai",
  "expiresIn": 60,
  "contentType": "image/png",
  "fileSize": 1048576,
  "contentLength": 1048576
}
JSON
```
- Responses:
  - `200` — Item retrieved successfully
  - `400` — Bad Request - Invalid parameters
  - `401` — Unauthorized - Invalid or missing JWT token

##### POST /api/v1/r2/upload-presigned-url — Get pre-signed upload URL
Generate a pre-signed R2 PUT URL for direct browser/client upload. If bucket is omitted, files are uploaded to 3days-apac by default. urlPrefix changes the leading object-key path and defaults to adam2eve outside site runtimes. cdnDomain changes the CDN domain suffix and defaults to the existing makefun.ai behavior outside site runtimes. Site runtimes reject urlPrefix and cdnDomain overrides to preserve isolated storage routing. The returned key is scoped to {urlPrefix}/{env}/user/{user_id}/. Use cdnUrl as the public file URL after the PUT upload succeeds. API-token calls are charged using the R2 pricing rule; normal logged-in web/app calls are free. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `key`. ### Behavior - Validates the submitted payload and performs the operation described by the request schema. - Conditional fields, mutually exclusive inputs, limits, and defaults are enforced as documented by their schemas. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid parameters. - `401` — Unauthorized - Invalid or missing JWT token. ### Related Operations - `POST /api/v1/r2/get_upload_presigned_url` — Get pre-signed upload URL. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1R2UploadPresignedUrl`
- JSON body fields:
  - `key` (body, required; string; example: `example_key`) — key parameter
  - `bucket` (body, optional; string; example: `3days-apac`) — R2 bucket. Defaults to 3days-apac.
  - `urlPrefix` (body, optional; string; example: `adam2eve`) — Leading object-key path outside site runtimes. Site runtimes reject this override.
  - `cdnDomain` (body, optional; string; example: `makefun.ai`) — CDN domain suffix outside site runtimes. Site runtimes reject this override.
  - `expiresIn` (body, optional; integer; min: 60; example: `60`) — expiresIn parameter
  - `contentType` (body, optional; string; example: `image/png`) — MIME type to bind to the upload request.
  - `fileSize` (body, optional; number; example: `1048576`) — Optional file size in bytes. When provided, the pre-signed URL binds Content-Length.
  - `contentLength` (body, optional; number; example: `1048576`) — Optional Content-Length in bytes. Takes priority over fileSize if both are provided.
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/r2/upload-presigned-url" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "key": "example_key",
  "bucket": "3days-apac",
  "urlPrefix": "adam2eve",
  "cdnDomain": "makefun.ai",
  "expiresIn": 60,
  "contentType": "image/png",
  "fileSize": 1048576,
  "contentLength": 1048576
}
JSON
```
- Responses:
  - `200` — Operation completed successfully
  - `400` — Bad Request - Invalid parameters
  - `401` — Unauthorized - Invalid or missing JWT token
#### Credits

##### POST /api/v1/generation/quote — Estimate generation credit consumption
Returns a credit estimate without creating a task, calling a generation provider, or charging credits. For agent use, send `endpoint` plus the exact `requestBody` intended for that generation endpoint. Only pricing-related fields are interpreted; a successful quote does not validate the complete generation request. The legacy normalized quote body remains supported for backward compatibility. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Send an `application/json` body. Required fields: `endpoint`, `requestBody`. ### Behavior - Validates the submitted payload and performs the operation described by the request schema. - Conditional fields, mutually exclusive inputs, limits, and defaults are enforced as documented by their schemas. ### Response - On `200`, consume the fields defined by that response schema below. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Unsupported endpoint or invalid/missing pricing input. - `401` — Missing or invalid bearer token. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `postApiV1GenerationQuote`
- JSON body fields:
  - `endpoint` (body, required; string; example: `/api/v1/userWan25/start`) — Generation route path. A leading `POST ` is accepted but optional.
  - `requestBody` (body, required; object; example: `{"model":"wan2.7-i2v","task_type":"first_last_frame","duration":"5","resolution":"720p","audio":true,"image_url":"https://example.com/first.png","last_frame_url":"https://example.com/last.png"}`) — The exact JSON body intended for the generation request.
- Example request:
```bash
curl -X POST "https://video.a2e.ai/api/v1/generation/quote" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  --data-binary @- <<'JSON'
{
  "endpoint": "/api/v1/userWan25/start",
  "requestBody": {
    "model": "wan2.7-i2v",
    "task_type": "first_last_frame",
    "duration": "5",
    "resolution": "720p",
    "audio": true,
    "image_url": "https://example.com/first.png",
    "last_frame_url": "https://example.com/last.png"
  }
}
JSON
```
- Responses:
  - `200` — Credit estimate. `generationRequestValidated=false` means only pricing inputs were checked.
  - `400` — Unsupported endpoint or invalid/missing pricing input
  - `401` — Missing or invalid bearer token

##### GET /api/v1/transactionRecord/creditsHistory — Get credits history
Retrieve paginated credits transaction history for the authenticated user. Positive amounts are credit grants or purchases; negative amounts are credit consumption. ### Request - Send a valid bearer token. The server evaluates the operation in the authenticated caller's access context. - Supported query parameters: `pageNum`, `pageSize`, `is_consumption`, `startDate`, `endDate`. Omitted values use the defaults shown in the parameter schema. ### Behavior - Returns the collection visible in the current request and authorization context. - Apply the documented pagination and filter parameters when present; use response metadata to continue paging. - Record fields and status values have the same meaning as in the corresponding detail operation. ### Response - The `200` response contains the requested collection in the response envelope documented below. - An empty collection is a successful result when no matching records are available. - Do not infer undocumented fields or statuses; clients should tolerate additional response properties. ### Errors - `400` — Bad Request - Invalid query parameters. - `401` — Unauthorized - Invalid or missing token. Authentication: set header Authorization: Bearer <token> (supports user JWT or sk_ API token).
- Operation ID: `getApiV1TransactionRecordCreditsHistory`
- Request parameters:
  - `pageNum` (query, optional; integer; default: `1`; min: 1; example: `1`) — Page number, starting from 1.
  - `pageSize` (query, optional; integer; default: `10`; min: 1; example: `10`) — Number of records per page.
  - `is_consumption` (query, optional; boolean; example: `false`) — When true, only returns consumption records; when false, only returns credit income records.
  - `startDate` (query, optional; string; example: `example`) — Inclusive ISO date-time lower bound for createdAt.
  - `endDate` (query, optional; string; example: `example`) — Inclusive ISO date-time upper bound for createdAt.
- Example request:
```bash
curl -X GET "https://video.a2e.ai/api/v1/transactionRecord/creditsHistory?pageNum=1&pageSize=10&is_consumption=false&startDate=example&endDate=example" \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```
- Responses:
  - `200` — Credits history retrieved successfully
  - `400` — Bad Request - Invalid query parameters
  - `401` — Unauthorized - Invalid or missing token