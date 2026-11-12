# Community ratings: a separate, optional enrichment layer

This is a feasibility proposal, not an enabled online feature. The application currently makes no community-rating queries and does not upload library metadata. Artwork is outside the proposed scope.

## Providers and what the number means

| Provider | Useful signal | Fit and limits |
| --- | --- | --- |
| MusicBrainz | Community ratings for entities including recordings, with vote counts | Best first candidate for a personal-use pilot. Exact recordings/remixes must be matched; unrated and thinly rated tracks must remain unknown. Ratings are supplementary data, not the CC0 core dataset. |
| Discogs | Community average and vote count for a release | An album/single/pressing score is not a track score. Current API terms restrict data handling and displaying stale data, including a six-hour freshness condition; a permanent offline ratings export is not a straightforward fit. |
| Charts, streaming counts, likes | Popularity or chart position | These do not measure the same thing as a community quality rating. Do not silently convert them into stars or average them with ratings. |

MusicBrainz documents supplementary ratings under CC BY-NC-SA 3.0, while its core metadata is CC0. Any external-score export needs attribution and appropriate data-license handling distinct from this application's MIT code. Discogs terms need particular care before storing or sharing a score indefinitely. This is a design constraint to resolve before enabling a provider, not a claim of provider permission.

Sources: [MusicBrainz API](https://musicbrainz.org/doc/MusicBrainz_API), [database contents](https://musicbrainz.org/doc/MusicBrainz_Database), [data license](https://musicbrainz.org/doc/About/Data_License), [rate limiting](https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting), [Discogs API](https://www.discogs.com/developers/#page:database,header:database-community-release-rating), [Discogs API terms](https://support.discogs.com/hc/en-us/articles/360009334593-API-Terms-of-Use).

## Recommended first version

1. The user selects a small batch and explicitly starts a lookup. Show exactly which provider receives artist/title/version/duration or identifiers; do not send paths, audio or the whole library by default.
2. Prefer existing ISRC/MBID identifiers when present; otherwise search artist/title plus remix/version and duration. Show candidate evidence and let the user confirm the recording. A title-only match is insufficient.
3. Save score, vote count, provider entity type/ID, original scale, source URL, retrieval time, match confidence and user approval in a separate local SQLite database. Missing ratings remain NULL, never zero stars. Keep provider scores separate rather than averaging unlike entities.
4. Display a distinct **community score**, alongside the existing **personal stars**. Low vote counts and unconfirmed matches stay visible. No automatic rekordbox rating overwrite.
5. Cache within provider rules, remember failed/no-rating matches, support retry/backoff and allow users to remove enrichment data. Exclude these scores from shared offline exports until the provider's licensing/freshness requirements are implemented.

A possible schema is `recording_identity`, `provider_match` and `rating_observation`, with indexes on `(provider, entity_type, entity_id)` and a link to the local stable recording identity. Store `raw_score`, `scale_max`, `votes`, `retrieved_at`, `expires_at`, `license`, `match_status` and `reviewed_at`. Do not use a filename as the only identity; duplicates and relocation must not lose the association. Tokens belong in an OS credential store if a provider needs authentication, not the SQLite observations or exported HTML.

## Cost and risk estimate

These are engineering estimates for one developer, not a fixed quote. A manually confirmed MusicBrainz-only pilot is roughly 3–6 working days. A dependable batch feature with identity matching, retry/cache policy, SQLite migrations, cancellation, review UI and cross-platform tests is closer to 2–3 weeks. Allow roughly half a day to a day per month for routine dependency/API maintenance, with extra work if terms, endpoints or matching behavior change.

The main risks are incorrect remix matches, poor rating coverage, small-vote bias, release-versus-track confusion and provider terms changing. A representative opt-in trial of 100–300 tracks should measure coverage and review effort before committing to a full-library implementation.

MusicBrainz normally limits a client IP to approximately one request per second. One request for each of 33,000 tracks is already about 9.2 hours; a search plus a lookup can roughly double that before retries. Batch selection, persistent matching and deduplication matter more than raw CPU. A local pilot need not have a hosting bill, but future commercial use or provider licensing can change costs.

Recommendation: build a small MusicBrainz-only, user-confirmed pilot later; keep community scores in the sidecar and personal stars untouched. Treat no available rating as a normal outcome.
