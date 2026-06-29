# Spec & Contract Detection

OpenAPI is the most common backend contract format but it is **REST-only** and
frequently **absent**. Detect the API style + framework first, then look for the
right spec file, then **fall back to reading route files** — the fallback is the
common case, not the exception.

## Detection order (stop at first hit)

1. **Explicit spec file present** → use it (most authoritative):
   | File pattern | Style | Notes |
   |---|---|---|
   | `openapi.{yaml,json}`, `swagger.{yaml,json}`, `*.openapi.*` | REST | OpenAPI/Swagger |
   | `openapi.json` served at `/openapi.json`, `/docs` | REST | FastAPI/NestJS auto-generate at runtime |
   | `schema.graphql`, `*.graphqls`, `**/*.gql` (SDL) | GraphQL | type defs |
   | `*.proto` | gRPC | also covers gRPC-web/Connect |
   | `asyncapi.{yaml,json}` | Event/WebSocket | Kafka, MQTT, WS |
   | `*.wsdl` | SOAP | legacy |
   | `openrpc.json` | JSON-RPC | |

2. **No spec → detect framework from manifest, then scan route source:**
   | Manifest signal | Framework | Where routes live (fallback scan) |
   |---|---|---|
   | `requirements.txt`/`pyproject` + `fastapi` | FastAPI | `@router.{get,post,...}` + path-derived/`prefix=` (or `/openapi.json` at runtime) |
   | `+ flask` | Flask | `@app.route` / `@bp.route` |
   | `+ django`/`manage.py` | Django/DRF | `urls.py` `urlpatterns`, DRF viewsets/routers; OpenAPI via drf-spectacular if installed |
   | `package.json` + `express` | Express | `app.{get,post}` / `router.*`, `src/routes/**` |
   | `+ @nestjs/*` | NestJS | controller decorators `@Get()/@Post()`; `@nestjs/swagger` auto-OpenAPI if set up |
   | `+ next`/`nuxt` | Next/Nuxt | file-based: `app/api/**/route.ts`, `pages/api/**`, `server/api/**` — NO spec, read files |
   | `+ @trpc/server` | tRPC | `appRouter` TS defs; procedures inferred from code, no file |
   | `+ apollo`/`graphql`/`type-graphql` | GraphQL | `**/*.graphql` SDL or code-first resolvers |
   | `go.mod` + `grpc`/`*.proto` | gRPC | `.proto` |
   | `go.mod` + `gin`/`echo`/`chi`/`fiber` | Go REST | `r.{GET,POST}` route registrations |
   | `Gemfile` + `rails` | Rails | `config/routes.rb`; rswag/OpenAPI if present |
   | `composer.json` + `laravel` | Laravel | `routes/api.php`, `routes/web.php` |

3. **Multiple styles** (e.g. REST + GraphQL gateway, or REST + WS) → record all;
   sync each against its own client surface.

## Client (app) side detection

Detect how the CLIENT declares endpoints — the surface to diff against the
backend. Hand-written constants drift; generated clients don't (diff the spec
instead).

| App manifest signal | Pattern | Where endpoints live |
|---|---|---|
| `pubspec.yaml` (Flutter) | string constants | `**/api_constants.dart`, `Dio`/`http` calls, `@GET/@POST` (retrofit/chopper) |
| `pubspec.yaml` + `retrofit`/`chopper` | annotated | abstract API interfaces — parse annotations |
| `pubspec.yaml` + `openapi_generator` | generated | a spec drives it → diff the SPEC, not the client |
| `package.json` + `axios`/`fetch` wrapper | string consts/wrapper | `**/api.*`, `**/endpoints.*`, `services/**` |
| `+ @trpc/client` | inferred | shares backend router types — drift impossible by design |
| `+ graphql`/`@apollo/client` | operations | `**/*.graphql`, `gql\`` template literals |
| `+ openapi-typescript`/`orval`/`@hey-api` | generated | spec-driven → diff the SPEC |
| `Package.swift` (iOS) | URLSession/Alamofire | endpoint enums/structs |
| Android `build.gradle` + Retrofit | annotated | `@GET/@POST` interfaces — parse annotations |

## Client-side improvement audit

When syncing, also flag client-quality issues (report, don't auto-fix unless asked):

- **Scattered endpoints** — URL string literals spread across files instead of
  one registry → drift risk. Suggest centralizing.
- **Hand-written client + backend HAS a spec** → suggest codegen
  (openapi-generator / orval / hey-api) to delete the drift surface entirely.
- **Field-name skew** — model JSON keys ≠ backend schema keys (snake_case vs
  camelCase handled inconsistently across models).
- **Unhandled documented errors** — backend documents a status/detail the client
  never branches on (e.g. a 429 limit string).
- **Verb/shape guesses** — client sends a body the route doesn't read, or omits a
  required field.
- **No base-URL switch** — hardcoded prod URL, no dev/local override → blocks
  `fullstack-run`.

## Matching across formats

Normalize before diffing: `{id}` ↔ `:id` ↔ `$id`; trailing slashes; version
prefixes; snake_case ↔ camelCase on field names. For GraphQL, match operation
names + field selections (not URL paths). For gRPC, match `service.Method`.
