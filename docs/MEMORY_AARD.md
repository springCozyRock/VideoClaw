# A²RD-inspired mechanism extension

This extends Memory V1; it does not claim an official implementation or benchmark
reproduction. Source mechanism: supplied A²RD paper, Sections 3.1–3.3 and Appendix E.

## Implemented

- V3 plans a story-level reference dependency DAG, validates ids/cycles, records weak
  components and generates assets in topological order. Supplied character anchors
  are preserved byte-for-byte; environment references can be regenerated to match
  their style. Up to four additional story-grounded references are allowed. Generated
  reference designs remain planning assets, never completed video events.
- V3 extracts the actual generated first frame before video observation, then asks
  the video observer to correct/supplement that state with timed changes. It records
  both extraction levels and their source media. Intended conditioning frames are
  not silently substituted for actual generated boundaries.
- MLLM selection of narratively relevant prior segments and global references, with
  explicit allowed ids and bounded output. The adjacent segment is retained separately
  to judge continuity. Future plans are never retrieved as observed history.
- Current-segment identity validation and an independent textual plan audit prevent
  confusing a lookahead scene with the scene being generated.
- Adaptive extrapolation/interpolation using no-new-environment and next-continuity
  conditions. Wan3 receives real `first_frame`/`last_frame` media entries through an
  explicitly enabled compatibility adapter. Defaults in legacy launchers are unchanged.
- Boundary-frame inspection and targeted reference-conditioned editing; video
  inspection and prompt refinement. Extrapolation refinement extracts the actual end,
  edits its identity/state while preserving layout, then regenerates with both endpoints.
- Uniform 4 fps video observation plus actual boundary frames for review. The video
  sampler change is local to this adapter instance; existing benchmark evaluation
  transport continues to use its original sampling policy.
- MAPO-style positive/negative refinement cases. Metric sets must match. A case is positive only if all
  rubric scores strictly improve, negative only if all strictly worsen; mixed changes
  are excluded. Sparse character-trigram cosine retrieves cases of the same modality;
  an MLLM contrasts the cases and produces targeted prompt revisions.
- Eight frame rubric metrics, nine video metrics without a prescribed end and ten
  with frame-fit when interpolation is used. Quality thresholds and explicit goals
  remain visible even under best-candidate selection.

## Selection and truthfulness

The controller remains host-independent. In addition to the base V1 backend
contract, an AARD adapter supplies `select_context(query)`,
`render_with_end(segment, prompt, begin, end, target)`,
`end_edit_prompt(segment, candidate, context)` and
`refine_with_memory(kind, candidate, request, cases)`. V3 additionally supplies
`plan_global_references(request)` and
`observe_with_begin(path, segment, actual_begin_asset, initial_observation)`.
`prepare(context)` also
returns `no_new_environment`, `next_contiguous` and `end_frame_prompt`.
Its identity declares first/last-frame capabilities. VideoClaw is currently the
only host adapter exercised with real generation.

The expanded runner defaults to `best_available`: after the bounded search, select
the highest mean rubric score, even if defects remain. `accepted` still reports
whether every quality threshold/goal passed. Only goals marked completed by the
judge enter `completed_goals`; unmet/uncertain goals remain `unresolved_goals`.
The selected video's observations describe what was generated, including errors.
Subsequent prompts are told to correct accidental drift against global references.

`--selection strict` retains the V1 hard gate. Candidate budgets persist across
resume. Unknown external outcomes still block automatic resubmission.

## Requested case runs

`scripts/prepare_aard_cases.py` freezes DirectorBench `narrative_074` (5 segments,
5 canonical shots, 60 seconds) and MSVBench `story08` (9 native segments grouping
21 canonical shots, 60 seconds). The native grouping and prepared global references
are reused. Old videos and per-segment reference frames are not used as new evidence.
MSVBench includes its official character inputs in those global references.

Each experiment records exact input and asset hashes, code snapshot, dirty tree and
model choices. Each segment has at most two video candidates; boundary generation
also has a bounded budget. Failed early integration attempts remain separate
directories with their full receipts and are counted separately from successful runs.

```bash
python3 scripts/prepare_aard_cases.py --out experiments/NEW_EXPERIMENT
baselines/videoclaw/video-claw/video-claw/backend/.venv/bin/python \
  scripts/run_memory_aard.py \
  --session experiments/NEW_EXPERIMENT/narrative_074/inputs/session.json \
  --run experiments/NEW_EXPERIMENT/narrative_074 --execute
python3 scripts/status_memory_aard.py experiments/NEW_EXPERIMENT
```

The runner creates a normalized concatenated preview, validates duration, and saves
the actual selected clip paths and quality issues. It does not label these scores as
DirectorBench/MSVBench official evaluations. Original generated audio is retained;
silence is added only when a provider returns no audio stream.

## Remaining departures

- V2 delegated global references to VideoClaw and extracted frame/video states
  independently. V3 adds the DAG and hierarchical extraction, but retains supplied
  character anchors, caps additional assets, and uses the existing structured state
  schema rather than claiming the paper's exact unpublished implementation.
- Shot-end selection from a non-adjacent historical video is not implemented.
- For intentional temporal/scene cuts, a new beginning frame is synthesized; the paper's
  blanket reuse of the previous end is not applied across such cuts in this adaptation.
- Interpolation targets a plausible current ending aligned with lookahead when
  appropriate, rather than strictly synthesizing the next segment's opening. There
  is no separate next-segment reference retrieval pass for this boundary.
- Frame refinement does not yet implement the paper's explicit Edit-versus-Regenerate
  decision. Rubric groups are judged together in one call rather than separate calls.
- MAPO retrieval uses transparent sparse similarity, not the paper's dense semantic
  embeddings, and its database starts empty rather than with unpublished seed cases.
- Prompt experience is scoped to one run; cross-story experience sharing is absent.
- Small bounded serial candidate search replaces the paper's batch candidate setting.
- Qwen/Wan models replace the paper's Gemini/Nano Banana/Veo stack. Four-fps sampling
  is still incomplete observation of fine motion and cannot establish physical truth.

## Validation

Core/native tests exercise sequential state flow, quality reporting, resume, budget
preservation, actual provider argument forwarding, media decoding, adaptive mode
selection, end-frame co-optimization, MAPO labels, and immutable-plan audit. Real
generation results must be interpreted separately from these protocol tests.

The video observer requires `opencv-python-headless==4.11.0.86` (installed in the
VideoClaw backend virtualenv for this run), Pillow and FFmpeg/FFprobe. Before a paid
run, verify that a local video can be decoded and sampled in that same interpreter.

`reconcile_aard_review.py RUN` can recover a stopped review from a completed raw
response only when its request, modality, observation, media path, every score and
every expected goal match the checkpoint. It normalizes nested/flat score fields;
it never fills missing values or changes quality decisions. Every recovery records
the response hash. `supervise_memory_aard.py RUN...` supervises the existing bounded
runs, resumes only this known recovery case and halts for other failures. Neither
script resets or resubmits an uncertain image/video generation operation.

With `--supplemental-reviews`, the supervisor may additionally invoke
`repair_aard_review.py` once for a review with no valid complete response. This
explicitly recorded integration-run revision keeps media, rubric and current
intent, removes redundant full-story/history metadata, and supplies an output
schema. It obtains new model judgments rather than pretending to recover missing
scores. A saved intent with no completed response blocks resubmission. These extra
judge calls remain included in raw usage and are not a uniform benchmark protocol.

## V3 experiment isolation and reliability

The running V2 source must remain unchanged until both cases finish. V3 runs from
`experiments/memory_aard_20261031_v3/code_snapshot/memory` via
`scripts/run_memory_aard_snapshot.py`. The launcher verifies all snapshot Python
hashes and native host runtime/transport hashes before importing the snapshot.
`prepare_aard_v3_cases.py` copies V2's frozen input plans and reference bytes into
new directories; it never imports V2 generated clips or learned prompt experiences.

V3 bounds per-segment model context to current/next intent and retrieved observed
history. Reviews have an explicit final JSON schema; frame reviews exclude deep
video goals. Flat score layouts are normalized losslessly without raising low
scores or suppressing defects. Upload references have unique names with verified
identical bytes. Each MAPO operation freezes the experience retrieval it originally
used, so later learning cannot change a replayed operation's inputs.

V2's already-running integration jobs use separately audited support recovery:
known pre-submission filename collisions, lossless raw review reconciliation,
explicit supplemental reviews, and chronological replay of uncommitted MAPO
experience. Story08 segment 4 required an assistant-authored source-grounded plan
correction followed by an independent model audit. That intervention is preserved
in `plan_repairs` and prevents treating V2 as an unassisted benchmark result.
V2 story08 segment 7 also used a locally reviewed source projection after a broad
planning request was rejected by the provider's text inspection. The actual current
shot is fully clothed adult characters viewing a sunset. The rejected request and
unchanged source are retained; no independent provider plan audit is claimed there.

V3 narrative_074 segment 5 exposed another source-fidelity problem: automatic
plans omitted the explicit return-home feeding event or placed feeding in the
ruins. A Codex-assisted candidate restored the full action order and home transition
and then passed an independent Qwen audit. This intervention is also logged; neither
full run is an unassisted reproduction. A concatenated video and high internal
scores do not establish that every original narrative requirement was satisfied.

The first V3 native-environment offline suite passed 40 tests, including DAG
ordering/cycle rejection, anchor preservation, replay without repeated generation,
actual-begin hierarchical extraction, native engine behavior and Wan3 endpoint
forwarding. Two earlier compact judge probes returned valid JSON in approximately
6 and 29 seconds; those are latency/schema checks, not video quality evidence.

Qwen `limit_burst_rate` rejections are recorded separately from schema failures.
The provider documents a default 100,000 TPM for qwen3.5-omni-plus; simultaneous
multimodal requests can exceed it even with low request counts. Frozen V3 runners
can be resumed through `run_aard_queued_slow.py`, which serializes requests with a
30-second shared gap while preserving their payloads. The measured completed-response
token window is only a diagnostic proxy for provider accounting. Unknown media
generation outcomes are never blindly resubmitted.

`compare_aard_cases.py` performs a separate anonymous A/B assessment on matching
source plans and original character anchors. It never feeds generation or candidate
selection. The model's scores remain exploratory: an early response rewarded motion
over stillness even though the source requests a quiet standing shot. Human source
and video checks therefore take precedence over treating these scores as ground truth.

Wan3 endpoint contract checked against:
https://help.aliyun.com/zh/model-studio/wan3-video-generation-api-reference

First/last frame media cannot be combined with reference-image/video/audio media in
the same Wan3 request. References therefore condition boundary-image generation and
verification, rather than being falsely advertised as extra video inputs.


## V3 completed generation observations (2026-10-31)

Both V3 case videos completed at approximately 60 seconds. The final native offline
suite passed 49 tests with zero failures, errors, or skips. The suite tested the
exact frozen V3 memory source and mocked all paid provider calls; the record is
`experiments/memory_aard_20261031_v3/final_offline_validation.json`.

V3 generated six video candidates for narrative_074 and fourteen for story08.
Internal quality gates accepted 4/5 and 5/9 selected segments respectively. Across
202 completed V3 judge responses, none ended at the output length limit. These
are operational measurements, not evidence of uniform visual improvement.

Manual contact-sheet inspection found mixed outcomes. narrative_074 establishes a
return to the kitchen after the battle, but the ending has transition ghosting and
feeding details remain uncertain. story08 changes between photographic/3D imagery
and anime imagery across its segments. Its final selected clip substitutes a teacup
for the required jade pendant; this error is retained in unresolved goals. A global
reference graph alone has therefore not enforced a consistent full-story style or
all important props.

The strict all-metrics MAPO label rule yielded one positive experience for
narrative_074 and none for story08. This run cannot demonstrate a benefit from a
substantial learned prompt memory. Next experiments should distinguish the paper's
strict labeling policy from any proposed alternative, and validate source events,
props, style and identity before increasing candidate budgets.


## Delivery and comparison provenance

V2 completed both cases before V3 was installed into the remote repository's
`memory/`. Deployment verified the old source hashes, preserved the replaced files
under `experiments/memory_aard_20261031_v3/root_before_v3`, and verified all installed
memory Python files against the tested frozen V3 snapshot. The exact change record
is `root_deployment.json` in that experiment directory.

Final V2 video candidate counts were 7 and 16; V3 counts were 6 and 14 for
narrative_074 and story08 respectively. V2 completed 290 judge responses, of which
90 hit the output-length limit; V3 completed 202 with none hitting that limit.
These counts include completed supplementary judgments and exclude unknown or
failed calls; they are not a price estimate. The V2 completed internal gate counts
were 4/5 and 4/9; V3 counts were 4/5 and 5/9.

Independent paired assessment is stored in
`experiments/aard_v2_v3_comparison_20261031_r3`. Earlier assessment attempts remain
in their original directories. The receipt collector keeps the original judging
prompt, sources, rubric, counterbalanced candidate mapping and scores; it accepts
an omitted uncertainty field as absent and records `uncertainty_not_reported`,
never as model confidence. Two comparisons were recovered from the earliest
matching completed responses without additional scoring calls. Alternative raw
responses and their costs remain available. The collector's additional absence /
no-score-imputation test passed separately from the 49-test memory suite.

Both versions contain the logged operator-assisted plans described above. The
native VideoClaw plans also differ from original benchmark shots in some framing
and participant details. Neither internal gate counts nor paired model scores
constitute official DirectorBench/MSVBench scores or a controlled causal estimate
of the memory mechanism. Audio streams are preserved but audio fidelity has not
been evaluated; manual inspection here uses sampled frames, while model video
assessment uses 4 fps sampling.


## Completed independent paired assessment

All 14 segment pairs completed. Means below are exploratory Qwen scores on a
1–10 scale, not official benchmark measurements. Each cell is V2 → V3.

| Case | Identity | Environment | Motion | Narrative |
|---|---|---|---|---|
| narrative_074 | 8.60 → 9.40 | 6.60 → 9.80 | 7.80 → 8.40 | 6.40 → 9.60 |
| story08 | 8.67 → 8.33 | 8.89 → 8.56 | 7.00 → 7.00 | 7.11 → 7.22 |

The favorable aggregate trend is driven mainly by narrative_074. story08 did not
show a general improvement: identity and environment means decreased, motion was
unchanged, and narrative changed little. The manual checks agree that style and
key props remain unresolved. Assisted plans, different stochastic generations,
reference initialization, small sample size and evaluator errors prevent attributing
these differences solely to the newly added memory mechanisms.

Next priorities are global style/identity validation and explicit key-event/prop
checks, followed by the remaining A²RD mechanisms: non-adjacent historical shot-end
retrieval, explicit Edit/Regenerate decisions, separate next-shot reference retrieval
for interpolation, and richer semantic prompt-experience retrieval. Any change to
the paper's strict MAPO labels should be evaluated separately, not presented as an
exact reproduction.
