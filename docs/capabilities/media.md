# Inbound media and private evidence — Task 27

This checkpoint implements the backend media boundary without creating or using
an OpenAI API key, as explicitly requested. Original inputs are preserved privately
before analysis. Live voice/image quality and cost validation remains pending;
this document does not certify production readiness.

## Inputs and results

| Input | Normalization | Without an analysis provider |
| --- | --- | --- |
| Text | Existing customer text | Available locally |
| Voice | `OpenAISpeechToTextProvider`, `gpt-4o-mini-transcribe` | Original retained; `PENDING_PROVIDER` after a clean scan |
| Image | `OpenAIImageObservationProvider`, `gpt-5.6-luna`, strict observation schema | Original retained; `PENDING_PROVIDER` after a clean scan |
| PDF | Bounded local text extraction | Extracted text, or human review for a scan with no text |
| Location | Validated finite latitude/longitude, name/address | Available locally |
| Contacts | Structured names, phones, emails, addresses, URLs and organization | Available locally; no URL is fetched |
| Video | Private original plus container type/size | Human review only; no advanced analysis |

Every observation is labeled `untrusted_customer_input`, carries
`identity_level_delta: 0`, and keeps `response_modality: text`. Neither file text
nor model observations prove identity, order ownership, claim eligibility or
authorization. Image processing has no tools and cannot execute business actions.
This does not add audio/image/video generation or OCR for scanned PDFs.

## Storage, validation and isolation

`media_evidence` records the tenant, WhatsApp account/provider object, trusted
conversation customer reference, first message, digest, private storage key,
size/type, scan result, processing state, usage and retention dates. One row per
tenant/account/provider object prevents repeated downloads and analysis. Different
provider objects retain independent records even when their content hashes match;
deleting one cannot remove another customer's evidence.

`media_observations` links each inbound message to its normalized result. It has
composite tenant foreign keys to the message and optional evidence. Original
message content and existing message grants remain unchanged. Both new tables
force RLS: the application can read within its tenant; identified backend actors
can insert/update; neither role gets table deletion privileges. This follows the
[Supabase RLS model](https://supabase.com/docs/guides/database/postgres/row-level-security).

The local adapter uses a private persistent volume with tenant/object/digest
paths, restrictive file permissions, exclusive writes and digest verification.
Path traversal and symlinks are rejected. Do not mount this directory as static
web content. Production deployment must provide a persistent private volume or a
reviewed equivalent adapter, including its backup policy.

The application bounds individual files to 20 MiB and images to 5 MiB. These are
application limits, not a declaration of every provider's maximum. Container
checks reject mismatched MIME types and truncated signatures/containers; they
are not a complete codec decoder or a malware scanner. `MalwareScanner` is a
mandatory hook before parsing, analysis or download access. Its default is
`UNAVAILABLE`: bytes remain quarantined, not silently treated as clean. The test
scanner is only a fixture and must never be configured as production protection.

PDF work runs in a disposable subprocess, with a 12-second wait limit, 8 CPU
seconds, at most 100 pages and 60,000 extracted characters. Linux also enforces
a 1 GiB address-space limit; macOS uses CPU/time/page/text limits. Encrypted,
malformed and oversized PDFs are rejected without deleting their private original.

## Provider and worker composition

`WhatsAppProvider.download_media` is the provider boundary. The native Meta
implementation resolves credentials only in the backend, looks up the object
through its configured HTTPS Graph endpoint with the phone-number binding,
allows only the configured code-owned Meta download hosts, disallows redirects,
bounds streamed bytes and checks provider size/SHA-256. A new lookup is used for
a new download; expiring provider URLs are not persisted as storage references.
No live WhatsApp download was used in development verification.

Construct `MediaService` with database sessions, the authorized WhatsApp provider,
private store, backend signing material, scanner, retention configuration and
optional voice/image providers. Inject it into the worker context as
`media_processor` and into the HTTP app as `app.state.media_service`. Missing
HTTP composition returns 503; no hidden service or credential is auto-created.
The worker hook is explicit and inactive when not injected.

The inbound worker normalizes after committing the inbound message, including
when human takeover prevents an AI response. The agent-turn hook waits for the
same normalization before reading the conversation. A tenant/object database
mutex serializes both paths. The runtime loads the separate observation as user
text, never as instructions or a higher identity level.

OpenAI adapters require an explicitly supplied client, disable automatic SDK
retries, and keep the approved models. Voice receives Spanish/English and bounded
business vocabulary context. Image analysis requests strict structured output,
no tools and `store=False`. API usage and latency are retained when returned;
unknown monetary cost stays `null`/`unpriced`, not a fabricated zero. The audio
request follows the [OpenAI transcription contract](https://developers.openai.com/api/docs/guides/speech-to-text).

## Recovery, access and deletion

A processing claim commits before external work. Replays reuse the stored result.
An interrupted claim becomes `HUMAN_REVIEW`, without an automatic second paid
request. An identified backend may explicitly retry `PENDING_PROVIDER` or a
non-infected quarantine after configuration/scanning is fixed; stored bytes are
reused. Infected files cannot be promoted by that retry path.

Platform-admin endpoints are scoped to `/admin/tenants/{tenant_id}/media`:

- `POST /{media_id}/access` issues a 60-second signed download URL.
- `GET /{media_id}/download` requires admin authentication plus the valid signature;
  it rechecks tenant/customer binding, clean scan, deletion and retention state.
  Responses are attachments with `no-store` and `nosniff`.
- `DELETE /{media_id}` revokes access, clears derived observations and removes the
  exact object's files. A tombstone prevents the provider object being reimported.

The signing primitive bounds grants to at most five minutes. A URL is not a
replacement for authentication. Deployment request logs must redact its signature
query parameter. Evidence access for Orders is supplied by `MediaService.allowed`,
using the same trusted customer reference as the conversation/customer directory.

Retention defaults to 90 days and is configurable at service composition.
`purge_expired` is a bounded backend operation; deployment must schedule it.
Expired observations are also suppressed at runtime before physical cleanup.
Deletion covers files written before a failed metadata commit and leaves cleanup
retryable if interrupted. Broader conversation/customer deletion remains Task 49.

## Verification and remaining acceptance work

Focused local checks cover structured inputs/container limits, real adapter
request contracts with sanitized fakes, provider URL restrictions, replay and
concurrent normalization, private signed HTTP access/expiry, quarantine, corrupted
PDFs, interrupted work, file cleanup, human takeover and both new tables' tenant
isolation. Existing milestone suites were not rerun.

`word_error_rate` and `latency_percentiles` are implemented and checked with small
deterministic fixtures. These arithmetic checks and synthetic audio are **not**
a voice-quality benchmark. Still pending by the user's credential deferral:
real Spanish/English/business speech-corpus WER, model p50/p95 latency and priced
cost, real image quality/refusal behavior and live Meta/OpenAI credentials/provider
checks. Production scanner, persistent storage, signing-material deployment and
scheduled retention also require operational configuration before release.
