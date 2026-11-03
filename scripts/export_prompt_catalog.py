"""Export the actual English instruction templates and language policy for paper review.

This reads source files only; it never imports model SDKs or calls a model.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import string
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from prompting.language import VERSION, language_instruction


def build_catalog(root=ROOT):
    backend=root/'video-claw/video-claw/backend'
    templates=[]
    for path in sorted((backend/'prompts').rglob('*_en.txt')):
        text=path.read_text(encoding='utf-8')
        fields=sorted({field for _,field,_,_ in string.Formatter().parse(text) if field})
        templates.append({'path':str(path.relative_to(root)), 'template_id':str(path.relative_to(backend/'prompts'))[:-7].replace('/','.')+'@en-v2',
                          'instruction_language':'en','variables':fields,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'template':text})
    memory=[]
    for path in sorted((root/'memory').rglob('*.py')):
        source=path.read_text();tree=ast.parse(source)
        fragments=[]
        for node in ast.walk(tree):
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
                # Inline instructions stay in their existing call; fragments are not final rendered requests.
                chunks=[n.value for n in ast.walk(node) if isinstance(n,ast.Constant) and isinstance(n.value,str) and len(n.value)>80]
                if chunks:fragments.append({'function':node.name,'line':node.lineno,'inline_text_fragments':chunks})
        if fragments:memory.append({'path':str(path.relative_to(root)),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'fragments':fragments})
    return {'policy_version':VERSION,'instruction_language':'en','story_language_selection':'explicit > script body > idea > title > default zh',
            'speech_rule':'Existing speech is verbatim; new speech follows story language.',
            'additional_compilation_model_calls':0,'language_policy_examples':{lang:language_instruction(lang) for lang in ('zh','en')},
            'templates':templates,'memory_inline_source_inventory':memory,
            'note':'Templates contain variables. Memory entries are source fragments, not final requests. Actual final requests are recorded in prompt_traces/judge_calls.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'docs/prompt_catalog.json')
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args();text=json.dumps(build_catalog(),ensure_ascii=False,indent=2)+'\n'
    if args.check:
        if not args.output.is_file() or args.output.read_text()!=text:raise SystemExit('Prompt catalog differs from current sources; regenerate it.')
        print('Prompt catalog matches current sources.')
    else:
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(text)
        print(str(args.output))


if __name__=='__main__':main()
