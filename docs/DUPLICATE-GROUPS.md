# Review more than two copies

Choose **Duplicate review → Review as → Groups** to inspect a recording with several candidate copies. One keeper can receive preparation from multiple donors. Pair view remains available for detailed cue comparisons.

The group panel lists **every member**, its title/artist/ID, manual/automatic cue counts, rating, addition date and reference path. Select one keeper, then use the member checkboxes to include or exclude donors. Exclude an alternate mix, edit or remaster that should remain a separate track. Selecting a keeper here applies to the group plan; choosing a card in the pair inspector applies to that individual comparison.

## Read the plan before staging

The plan runs the same rules as staging, on a separate decision copy:

- **Ready to stage:** this donor directly matches the keeper and its preparation can join the accumulated result under the selected policies.
- **Held for review:** cue/rating choices conflict, another staged keeper overlaps, or there is no direct supporting match to this keeper. Inspect the relevant pair. A manual cue conflict stays held even if the automatic-cue policy is enabled.
- **Excluded:** this donor will not be included in this new group action.
- **Already staged:** an earlier decision already sends this donor to this keeper. Excluding a donor does not undo an existing decision; use Undo for that.

Example: A is the keeper, B adds hot cue B and C adds hot cue C. Both can merge into A. If D assigns a different manual position to hot cue B, D is held because it conflicts with preparation already added from B. Pairwise checks against the original A alone would miss that conflict. The combined preview catches it before staging.

Compatible cues accumulate across donors. An existing nonzero keeper rating is retained; if it is blank, the first compatible nonzero donor rating can fill it. A conflicting nonzero rating requires an explicit choice. Group members have a stable order, and the preview shows the result for that order. Auto/manual origin is inferred from editable cue labels, not guaranteed provenance.

**Stage this recording group** applies only the ready merges. Held and excluded members remain separate. This prepares working-copy decisions; it does not remove original audio or alter the live rekordbox database. **Undo last batch** removes that group action and restores any earlier choices it replaced. Ordinary reports and the export recap retain the applied decisions and held reasons.

## Groups are candidate relationships

A connected group does not prove every member is the same recording. A↔B and B↔C do not establish A↔C. The tool requires direct keeper/donor evidence and never automatically merges an indirect-only candidate. Metadata, cue agreement and saved waveforms can narrow a review; explicit local file hashes provide stronger file-content evidence where files are available.

Pair counts and track counts describe different work. Four fully connected copies can produce six comparisons but at most three removals; the displayed potential reduction is a bound, not a promise that all copies can be merged. Filters can also narrow the visible group. Group staging is bounded to 100 known members; oversized or malformed requests are rejected rather than partly applied.
