"""Bind complete native MCP stdout to its executed root script, offline only."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import prepare


def unwrap(value):
    for _ in range(10):
        assert isinstance(value, dict)
        assert not value.get('isError') and value.get('ok', True) is True
        assert not any(v for k, v in value.items() if 'truncated' in k)
        assert not any(v for k, v in value.items() if 'chars_dropped' in k)
        if 'stdout' in value:
            assert value.get('output_complete') is True
            assert value.get('ok') is True and not value.get('stderr')
            assert isinstance(value['stdout'], str) and value['stdout']
            return value['stdout']
        if 'result' in value:
            value = value['result']
            continue
        content = value.get('content')
        assert isinstance(content, list) and len(content) == 1
        assert content[0]['type'] == 'text'
        value = json.loads(content[0]['text'])
    raise AssertionError('Unexpected nested MCP response')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--raw', type=Path, required=True)
    parser.add_argument('--script', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    output = unwrap(json.loads(args.raw.read_bytes()))
    envelope = {'status':'ok', 'script':str(args.script.resolve()),
                'sha256':prepare.sha(args.script), 'output':output,
                'raw_receipt':str(args.raw.resolve()),
                'raw_receipt_sha256':prepare.sha(args.raw),
                'provenance':'Root supplied executed-script association; native complete stdout preserved verbatim.'}
    prepare.write(args.out, envelope)
    print(json.dumps({'out':str(args.out), 'stdout_chars':len(output), 'raw_sha256':envelope['raw_receipt_sha256']}))


if __name__ == '__main__':
    main()
