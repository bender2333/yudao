import ast
import hashlib
import json
import subprocess
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[2]
    model = json.loads((root / 'docs/C4/model.json').read_text(encoding='utf-8'))
    nodes = {item['id']: item for item in model['nodes']}
    assert len(nodes) == len(model['nodes']), '元素标识重复'
    relation_ids = [item['id'] for item in model['relationships']]
    assert len(set(relation_ids)) == len(relation_ids), '关系标识重复'
    expected_parent = {'container': 'software_system', 'data_store': 'software_system',
                       'component': 'container'}
    for item in nodes.values():
        parent = item['parent']
        if item['kind'] in expected_parent:
            assert parent in nodes, f"父级缺失：{item['id']}"
            assert nodes[parent]['kind'] == expected_parent[item['kind']], item['id']
        else:
            assert parent is None, item['id']
    for item in model['relationships']:
        assert item['source'] in nodes and item['target'] in nodes, item['id']
        assert item['description'] and item['mechanism'] and item['evidence'], item['id']
    count = 0
    for item in model['nodes'] + model['relationships']:
        assert item['evidence'], item['id']
        for entry in item['evidence']:
            path = (root / entry['path']).resolve()
            assert path.is_relative_to(root), entry['path']
            raw = path.read_bytes()
            assert hashlib.sha256(raw.replace(b'\r\n', b'\n')).hexdigest() == entry['sha256'], (
                f"源码已经变化，需要重新核对模型：{entry['path']}")
            scope = None
            if entry['symbol']:
                scope = ast.parse(raw.decode('utf-8-sig'))
                for part in entry['symbol'].split('.'):
                    matches = [child for child in scope.body
                               if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                               and child.name == part]
                    assert len(matches) == 1, entry
                    scope = matches[0]
                assert scope.lineno == entry['line'], entry
            count += 1
    head = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    print(f"代码基线：{model['source_commit']}")
    if head != model['source_commit']:
        print(f'当前提交：{head}；本次检查覆盖登记的证据文件，新增代码仍需人工审阅。')
    print(f"检查通过：{len(nodes)} 个元素，{len(relation_ids)} 条关系，{count} 项源码证据。")


if __name__ == '__main__':
    main()
