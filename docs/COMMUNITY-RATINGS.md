# Community ratings: a separate, optional enrichment layer

The optional MusicBrainz proof of concept is implemented and disabled by default. Other providers below are research candidates, not enabled integrations or a working provider selector. Opt-in retrieval sends only reviewed public tags/identifiers. Artwork is outside the scope. Sources and provider policies were reviewed on 13 November 2026 and must be checked again before integration.

## Providers and what the number means

| Provider | Useful signal | Fit and limits |
| --- | --- | --- |
| MusicBrainz | Community ratings for entities including recordings, with vote counts | Best first candidate for a personal-use pilot. Exact recordings/remixes must be matched; unrated and thinly rated tracks must remain unknown. Ratings are supplementary data, not the CC0 core dataset. |
| Discogs | Community average and vote count for a release | An album/single/pressing score is not a track score. Current API terms restrict data handling and displaying stale data, including a six-hour freshness condition; a permanent offline ratings export is not a straightforward fit. |
| TheAudioDB | Track/album metadata, genre/year and score/vote fields where populated | Promising second rating candidate, but its official example has missing track scores. Validate entity, scale, vote coverage and API-tier/distribution terms before normalization. Free development access is not blanket permission for all distribution channels. |
| Last.fm | Crowd tags, corrections, listener/play popularity | Useful for genre suggestions and identity review. An API key is needed. Tags, play counts and personal loves are not community star ratings. |
| ListenBrainz | Recording feedback and listening statistics | Love/hate feedback and popularity are separate signals, not a numeric quality rating. MusicBrainz identifiers help link evidence. Follow per-client pacing and server limit headers. |
| AcoustID | Audio fingerprint identification linked to recordings | Helps identify poorly tagged/unreferenced files. No ratings. A later adapter needs Chromaprint, an application key and explicit fingerprint-transfer consent; no audio/fingerprints are sent by the current pilot. |
| Charts, streaming counts, likes | Popularity or chart position | These do not measure the same thing as a community quality rating. Do not silently convert them into stars or average them with ratings. |

MusicBrainz documents supplementary ratings under CC BY-NC-SA 3.0, while its core metadata is CC0. Any external-score export needs attribution and appropriate data-license handling distinct from this application's MIT code. Discogs terms need particular care before storing or sharing a score indefinitely. This is a design constraint to resolve before enabling a provider, not a claim of provider permission.

Sources: [MusicBrainz API](https://musicbrainz.org/doc/MusicBrainz_API), [database contents](https://musicbrainz.org/doc/MusicBrainz_Database), [data license](https://musicbrainz.org/doc/About/Data_License), [rate limiting](https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting), [Discogs API](https://www.discogs.com/developers/#page:database,header:database-community-release-rating), [Discogs API terms](https://support.discogs.com/hc/en-us/articles/360009334593-API-Terms-of-Use).

Additional primary sources: [TheAudioDB API](https://www.theaudiodb.com/free_music_api), [example score fields](https://www.theaudiodb.com/docs_json), [terms](https://www.theaudiodb.com/docs_terms_of_use.php); [Last.fm track tags](https://www.last.fm/api/show/track.getTopTags), [track information](https://www.last.fm/api/show/track.getInfo), [API terms](https://www.last.fm/api/tos); [ListenBrainz recording feedback](https://listenbrainz.readthedocs.io/en/latest/users/api/recordings.html), [rate limits and authentication](https://listenbrainz.readthedocs.io/en/latest/users/api/); [AcoustID service guidelines](https://acoustid.org/webservice).

For a future multiple-choice provider UI, show capabilities before lookup: recording versus release scope, available fields, query disclosure, credentials, pacing and export policy. Keep an independent cache/adapter per provider and preserve raw values, vote counts, source URL and retrieval date. Do not silently fall back to another provider, scrape undocumented websites or share a developer's private API token in the portable build. Personal/noncommercial use does not remove provider terms or data-license requirements.

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

The MusicBrainz pilot, introduced in 0.4.5, provides bounded, user-confirmed lookups in [Library lab](LIBRARY-LAB.md), with public retrieval code, local-only working data, a force-off flag and selectable pacing. Community scores stay in the sidecar; personal stars remain an explicit manual choice. Treat no available rating as a normal outcome. The estimates above describe engineering/maintenance scope, not a guarantee of match or rating coverage.

## User-reported pilot result

The maintainer reports candidate matches in a real private library sample. The reported 150-track batch contained 21 candidate matches, 21 available years, two available genres, no returned ratings and three service errors. These are candidate counts, not 21 independently verified identities or a general accuracy estimate. No private tags or API responses are published. Wider provider integration remains deferred.

The current lookup already requests recording `ratings`. MusicBrainz supports aggregate ratings, but a recording can have no votes even when its release group has a rating. A missing recording rating remains unknown; album-level ratings and search relevance scores are never substituted for it. See the [MusicBrainz API include arguments](https://musicbrainz.org/doc/MusicBrainz_API#Misc_inc=_arguments).
