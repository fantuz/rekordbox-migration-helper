# Library quality roadmap

This roadmap separates implemented tools from work that still needs genuine library examples. It is not a measured ranking of issues reported by rekordbox users.

| Subject | Current implementation | Remaining validation or expansion |
| --- | --- | --- |
| Guided migration | Saved backup, capture, availability, destination-path, cleanup, export, restore and destination-comparison checklist | Run and record a complete native restore checklist on each claimed rekordbox/OS combination |
| Integrity checking | Quick saved-evidence checks and deep explicit analysis-root audits; Issue, Needs review, Unknown and Not checked stay distinct | Genuine historical schemas and cloud setups; no opaque overall health score |
| Shared collection context | Selected snapshot, capture date, scope, capabilities and staged-field counts across analysis tools | Save a workspace as a snapshot before snapshot-only tools can inspect the same collection |
| Shareable summaries | Prominent public aggregate summary, selected list and private explorer; exact field disclosure; XML-only entry | Summaries are not native backups; review disclosed fields before sharing |
| Export state | Captured versus working metadata labelled explicitly; cleanup/relocation plans remain separate from HTML snapshots | Full cleanup-plan projection into HTML needs matching native/XML export semantics and separate validation |
| Duplicates | Pair and many-copy review, keeper/donor selection, accumulated conflict checks and duplicate-impact distributions | Audio fingerprinting for renamed/re-encoded copies is future work; metadata similarity is not audio identity |
| Snapshot drift | Detailed cue/rating/playlist comparison plus collection evolution summaries | Genuine before/after migration examples, preserving ambiguous/unmatched identities |
| Playlist overlap | Bounded selected-playlist comparison with membership versus order distinction | Device-library comparisons need classic and OneLibrary decoders and fixtures |
| Session insights | Saved order with BPM/key/colour and adjacent BPM changes | Individual play timestamps and actual set duration are unavailable unless future evidence supports them |
| Metadata quality | Conservative spelling/spacing/Unicode variants, missing or implausible tags, explicit staged overrides | Artist identity/alias resolution still needs human review |
| Analysis assets and STEMS | Selected-root/ZIP inventory, ownership evidence, missing/unreferenced candidates, byte-budgeted hashes and STEMS-related counters | Candidate extensions do not prove STEMS readiness or safe deletion; no asset cleanup writer |
| Coverage | Preparation by genre/BPM, usage evidence, known zero versus unknown counts, rediscovery and random selections | Broader usage questions depend on the available captured history |
| MusicBrainz | Opt-in paced retrieval, identity review, year/genre staging, separate community scores with real votes | User reports successful candidates; rating coverage is not guaranteed. Wider provider integration is deferred |
| Performance | Cached duplicate pagination/graphs and GitHub time/memory benchmarks at 33k and 100k synthetic tracks | Measure real-library cases before adding a new search/database architecture |
| Long operations | Per-operation cooperative cancellation at safe checkpoints; completed reports/decisions/exports kept | Cancellation can wait for a read or database call; it does not roll back completed outputs |
| Build quality | Exact-commit/version trusted release artifact reuse, repeated package verification, pinned Linux runtime cache | CI runtime checks do not run the licensed rekordbox application |

The [validation matrix](VALIDATION-MATRIX.md) describes evidence still needed for v6, cloud Copy/Move, native restore and device formats. See [guided journeys](JOURNEYS.md), [sharing](OFFLINE-EXPLORER.md), [intelligence](LIBRARY-INTELLIGENCE.md), [performance](PERFORMANCE.md) and [compatibility](COMPATIBILITY.md) for current limits.

Future ideas include versioned hardware export-readiness rules, half/double-tempo disagreement review and optional audio identification. These are proposals rather than supported features. Audio reads, dependencies, identity confidence and maintenance costs should be evaluated separately.
