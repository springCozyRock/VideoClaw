"""Bridge to the project-wide prompt policy, also when backend is launched directly."""
from pathlib import Path
import sys

for directory in Path(__file__).resolve().parents:
    if (directory / 'prompting' / 'language.py').is_file():
        if str(directory) not in sys.path:
            sys.path.insert(0, str(directory))
        break
from prompting.language import (VERSION, project_language, language_instruction,
                                media_prompt, record_prompt, assert_speech_preserved)
