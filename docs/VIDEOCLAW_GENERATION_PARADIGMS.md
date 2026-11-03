# VideoClaw: four visual-input generation paradigms

Implemented against arXiv:2609.00646v2 §3.2:
https://arxiv.org/html/2609.00646v2#S3.SS2

## Usage

Select one of four modes on the project creation page or in the workflow model settings. API callers may pass `generation_paradigm` (preferred) or a canonical value in `video_generation_mode`:

| Paradigm | Reference preparation | Actual video conditioning |
| --- | --- | --- |
| `fflf2v` | Draw this segment's initial state, then its final state using the initial image and entity sheets | First + last frame |
| `grid2v` | Jointly draw up to four segment initial states in a 2x2 grid; slice in reading order | One cropped first frame per segment |
| `multiref2v` | Collect selected character, element and setting sheets | Reference images only; no first/last frame |
| `keyframe2v` | Independently draw each segment's initial state | First frame |

The generation unit remains **segment**, potentially containing multiple shots. Grid groups do not cross episodes. This is a VideoClaw adaptation of the paper, not a claim of exact shot-level benchmark reproduction. The paper evaluates the first three paradigms; the independent-keyframe implementation here uses one first frame per segment.

Example additional request fields (alongside existing idea/model settings):

```json
{
  "generation_paradigm": "fflf2v",
  "video_start_end_model": "wan2.7-i2v"
}
```

Existing fields `video_first_frame_model`, `video_start_end_model`, `video_reference_model` configure the underlying conditioning interfaces. `grid2v` and `keyframe2v` share the first-frame model field. Legacy `first_frame`, `start_end_frame`, `reference` selectors remain readable. Existing legacy first-frame preparation remains available; canonical selectors activate the new reference-preparation path.

Optional storyboard fields: `start_state`, `end_state`, `elements` (or `props`, a list of asset IDs/names). Element sheets are supplied in `character_design.elements` (or `.props`), using the existing asset shape `{id, name, description, selected}`. This change resolves and passes such assets; it does **not** automatically discover props in prose or generate missing element sheets. A named entity with no selected image fails explicitly. Add/select the asset before reference preparation.

## Behavior

- First/last-frame mode never uses the next segment's opening image as an implicit tail and never silently falls back to first-frame mode.
- Grid images are generated jointly, not composed from independently generated images. The original image, cell index, 2x2 layout and exact crop boxes are recorded. A requested cell regeneration redraws its group and updates all sibling cells.
- Reference assets carry paradigm, conditioning mode, source/segment hashes, referenced-image content identities and shot IDs. Manifests are saved under `backend/code/result/image/<session>/paradigms/<paradigm>/<source_hash>/manifest.json`; completed groups can resume. Rejected or interrupted groups have no success manifest.
- Independently generated endpoint frames and cropped grid cells receive VLM checks; rejected frames/groups have at most three image-generation attempts. This verifies model judgments, not guaranteed semantic correctness.
- Current-segment end frames use the same segment's last shot/end state and its opening image as a reference.
- Video request receipts live next to clips as `<segment>.generation.json`. Existing files only count as current output when the input hash matches. Failed generation after changed inputs cannot select a stale clip.
- Changing paradigm/image models/ratio/style invalidates reference, video and assembled artifacts. Video-model/resolution changes invalidate video and assembled artifacts. Editing storyboard/entity/reference artifacts invalidates dependent outputs. Existing media files remain on disk.
- Reference previews show entity sheets, endpoint images and original grids. Multi-reference preparation completes without a selected first frame.
- Capability checks and model pickers use implemented adapter capabilities. Unsupported input combinations are rejected before paid video submission. No new external model API was added. The project Wan3 wrapper now rejects conditioning it would otherwise discard; enabling its tail input still requires `install_adapters(enable_last_frame=True)` and compatible registered capabilities.

## Validation and deployment

Offline tests mock all image, VLM and video calls:

```bash
baselines/videoclaw/video-claw/video-claw/backend/.venv/bin/python -m unittest discover -s tests -p test_videoclaw_paradigms.py -v
```

TypeScript check:

```bash
cd baselines/videoclaw/video-claw/video-claw/frontend
node node_modules/typescript/bin/tsc --noEmit --incremental false
```

No paid model requests, server restart, or production UI deployment were performed. A running backend/frontend must load the updated sources before the new controls are usable. Real-model visual quality, API behavior, latency and cost still require a small end-to-end generation run.

The baseline directory is ignored by the parent Git repository. `patches/videoclaw/dramachain-paradigms.patch` preserves the baseline modifications plus the runtime adapter guard. On a matching original checkout, replay with `git apply --check` then `git apply` from the LongVideoMemory root. Do not reapply to the already updated server tree. Tests and this document are stored outside the ignored baseline directory.
