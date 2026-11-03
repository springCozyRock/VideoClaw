# Prompt language policy

Policy: `english-instructions-source-speech/1`.

Fixed production instructions, evaluation directions and repair instructions use English. Story language is independent: explicit zh/en overrides automatic detection; otherwise script body takes precedence over idea, then title, then Chinese as the empty-input default. The resolved language and detection source are stored in project metadata and inherited by stages.

New narrative, dialogue and narration follow story language. Existing dialogue, narration, names and quotations remain verbatim in their original language and punctuation. JSON keys, IDs and existing enum tokens are unchanged.

The native workflow explicitly loads English templates for script generation/continuation, character/setting assets, storyboards, reference preparation/review and Doctor repair. Missing templates fail visibly. Historical Chinese templates remain available as source references but are not selected by active production paths.

The existing storyboard-design call may return source-language content plus English visual_prompt in the same response. The English rendering is bound to its source hash; changed source or omitted protected speech prevents reuse. Continuity corrections discard stale paired renderings.

There is no extra translation/compiler model request before image or video generation. Media boundaries only add a deterministic English instruction wrapper. Chinese speech and legacy source data can legitimately remain in that English-instruction request. Memory requests English visual/action/camera directions within its existing planning calls.

Final native text and Doctor-mediated media prompts are recorded locally under backend/code/data/prompt_traces, including policy version, model, template IDs and story language. Memory judge calls retain final requests under the run directory. These logs are ignored by Git and may contain private story content.

Run `python scripts/export_prompt_catalog.py` to export English templates, the policy and inline Memory source fragments to docs/prompt_catalog.json; use --check to detect drift. Templates/fragments are distinguished from actual rendered request logs.

Published benchmark tasks/rubrics, stored evidence, third-party baseline prompts and historical frozen snapshots retain their source language. Translating them would change the evaluation protocol.
