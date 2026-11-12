"""Repair safety and entry points; isolated Git repositories and fake models."""
from dataclasses import asdict
import json
import threading
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest

from test_ship_cli import staged_repo, _git  # noqa: F401
from gai.common.git import staged_snapshot
from gai.fix.engine import FixSession


@pytest.fixture
def session(staged_repo, monkeypatch):
    s = FixSession(staged_repo)
    record = {'schema': 1, 'id': 'a' * 32, 'snapshot': asdict(staged_snapshot()),
              'staged_files': ['a.txt'], 'result': {'parsed_ok': True, 'summary': 'test',
              'commit_message': '', 'review': [{'severity': 'warning', 'file': 'a.txt',
              'line': 1, 'issue': 'wrong greeting', 'suggestion': 'use goodbye'}]}}
    s.use_record(record)
    def ask(system, payload):
        if 'phase' in payload:
            return {'checks': [{'id': i['id'], 'status': 'resolved' if payload['phase'] == 'after_fix' else 'still_present',
                                'reason': 'checked source'} for i in payload['issues']], 'new_findings': [], 'summary': 'checked'}
        return {'edits': [{'file': 'a.txt', 'issue_ids': [1], 'before': 'hello world', 'after': 'goodbye'}], 'unresolved': []}
    monkeypatch.setattr(s, 'ask', ask)
    return s


def preview(s):
    s.validate()
    s.generate([1])
    return s.proposal['public']['ticket']


def test_apply_verify_preserves_index_head_and_backup(session):
    original = (session.root / 'a.txt').read_bytes()
    snapshot = staged_snapshot()
    ticket = preview(session)
    assert (session.root / 'a.txt').read_bytes() == original
    session.apply(ticket)
    assert (session.root / 'a.txt').read_text().strip() == 'goodbye'
    assert staged_snapshot() == snapshot
    assert (session.folder / '000.before').read_bytes() == original
    session.verify()
    assert session.phase == 'verified'
    assert json.loads((session.folder / 'session.json').read_text(encoding='utf-8'))['phase'] == 'verified'
    with pytest.raises(RuntimeError):
        session.apply(ticket)


def test_unstaged_changes_are_never_overwritten(session):
    (session.root / 'a.txt').write_text('hand edits\n')
    session.validate()
    assert session.findings[0]['blocked']
    with pytest.raises(RuntimeError):
        session.generate([1])
    assert (session.root / 'a.txt').read_text() == 'hand edits\n'


@pytest.mark.parametrize('change', ['file', 'index', 'ticket', 'expired'])
def test_stale_preview_rejected(session, change):
    ticket = preview(session)
    if change == 'file':
        (session.root / 'a.txt').write_text('new manual change')
    elif change == 'index':
        (session.root / 'b.txt').write_text('new index file')
        _git(session.root, 'add', 'b.txt')
    elif change == 'ticket':
        ticket = 'invalid'
    else:
        session.proposal['expires'] = 0
    before = (session.root / 'a.txt').read_bytes()
    with pytest.raises(RuntimeError):
        session.apply(ticket)
    assert (session.root / 'a.txt').read_bytes() == before


@pytest.mark.parametrize('name', ['../outside', '.git/config', '.gai/file', 'C:/secret', 'a\\b', '/tmp/file'])
def test_unsafe_paths_rejected(session, name):
    with pytest.raises(RuntimeError):
        session.safe_path(name)


@pytest.mark.parametrize('edit', [
    {'file': 'b.txt', 'issue_ids': [1], 'before': 'hello world', 'after': 'bad'},
    {'file': 'a.txt', 'issue_ids': [2], 'before': 'hello world', 'after': 'bad'},
    {'file': 'a.txt', 'issue_ids': [1], 'before': 'missing', 'after': 'bad'},
])
def test_invalid_model_edits_do_not_write(session, monkeypatch, edit):
    session.validate()
    monkeypatch.setattr(session, 'ask', lambda *a: {'edits': [edit]})
    before = (session.root / 'a.txt').read_bytes()
    with pytest.raises(RuntimeError):
        session.generate([1])
    assert (session.root / 'a.txt').read_bytes() == before
    assert session.proposal is None


def test_failed_second_write_rolls_back_first(session, monkeypatch):
    import gai.fix.engine as engine
    (session.root / 'b.txt').write_text('hello world\n')
    _git(session.root, 'add', 'b.txt')
    record = session.report
    record['staged_files'].append('b.txt')
    record['result']['review'].append({**record['result']['review'][0], 'file': 'b.txt'})
    session.use_record(record)
    session.validate()
    monkeypatch.setattr(session, 'ask', lambda *a: {'edits': [
        {'file': name, 'issue_ids': [i], 'before': 'hello world', 'after': 'goodbye'}
        for i, name in enumerate(['a.txt', 'b.txt'], 1)]})
    session.generate([1, 2])
    original = {p: (session.root / p).read_bytes() for p in ['a.txt', 'b.txt']}
    replace = engine.os.replace
    def fail_second(src, dst):
        if str(src).endswith('001.candidate'):
            raise OSError('simulated disk failure')
        return replace(src, dst)
    monkeypatch.setattr(engine.os, 'replace', fail_second)
    with pytest.raises(OSError):
        session.apply(session.proposal['public']['ticket'])
    assert session.phase == 'rolled_back'
    assert all((session.root / p).read_bytes() == raw for p, raw in original.items())


def test_failed_verification_keeps_applied_patch(session, monkeypatch):
    session.apply(preview(session))
    monkeypatch.setattr(session, 'ask', lambda *a: {})
    with pytest.raises(RuntimeError):
        session.verify()
    assert session.phase == 'verification_failed'
    assert (session.root / 'a.txt').read_text().strip() == 'goodbye'


def test_gui_guards_and_full_flow(session):
    from gai.fix.gui import FixServer
    with FixServer(session) as server:
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with httpx.Client(base_url=server.origin, trust_env=False, timeout=20) as client:
                assert client.get('/api/state').status_code == 403
                client.headers['X-Gai-Token'] = server.token
                assert client.get('/api/state', headers={'Origin': 'https://evil.test'}).status_code == 403
                assert client.get('/api/state', headers={'Host': 'evil.test'}).status_code == 403
                assert client.get('/../pyproject.toml').status_code == 404
                assert "script-src 'self'" in client.get('/').headers['Content-Security-Policy']
                assert client.post('/api/validate', json={}).json()['phase'] == 'validated'
                patch = client.post('/api/generate', json={'ids': [1]}).json()
                assert patch['phase'] == 'preview'
                assert client.post('/api/apply', json={'ticket': 'wrong'}).status_code == 400
                assert client.post('/api/apply', json={'ticket': patch['proposal']['ticket']}).json()['phase'] == 'applied'
                assert client.post('/api/verify', json={}).json()['phase'] == 'verified'
        finally:
            server.shutdown()
            worker.join()


def test_review_fix_routes_new_record_and_archives(session, monkeypatch):
    from gai.cli import run
    from gai.review.engine import parse_review_response
    calls = []
    monkeypatch.setattr('gai.review.cmd.run_review', lambda **kw: parse_review_response(json.dumps(session.report['result'])))
    monkeypatch.setattr('gai.fix.cmd.start_fix', lambda **kw: calls.append(kw))
    assert run(['review', '--fix', '--gui', '--no-open']) == 0
    assert calls[0]['record']['repository'] == session.owner
    assert calls[0]['gui'] and not calls[0]['open_browser']
    assert session.catalog()


@pytest.mark.parametrize('args', [['review','--fix','--json'], ['review','--gui'], ['fix','--no-open']])
def test_invalid_cli_combinations(session, args):
    from gai.cli import run
    assert run(args) == 1


def test_gui_selection_confirmation_and_literal_rendering():
    if not shutil.which('node'):
        pytest.skip('Node.js not installed')
    subprocess.run(['node', str(Path(__file__).with_name('test_fix_ui.js'))], check=True, capture_output=True)


@pytest.mark.parametrize('raw', [b'\xef\xbb\xbfhello world\r\n', b'hello world'])
def test_preserves_bom_newlines_and_previews_missing_newline(session, raw):
    (session.root / 'a.txt').write_bytes(raw)
    _git(session.root, 'add', 'a.txt')
    ticket = preview(session)
    if not raw.endswith(b'\n'):
        assert '\\ No newline at end of file' in session.proposal['public']['files'][0]['diff']
    session.apply(ticket)
    assert (session.root / 'a.txt').read_bytes() == raw.replace(b'hello world', b'goodbye')


def test_history_selection_requires_local_archive_and_matching_owner(session, monkeypatch):
    report = {**session.report, 'report_path': str(session.root / '.gai/reviews/example/report.md')}
    monkeypatch.setattr(session, 'catalog', lambda: [report])
    session.select('aaaaaa')
    session.select('.gai/reviews/example/report.json')
    with pytest.raises(RuntimeError):
        session.select('../foreign-report.json')
    report['repository'] = {'root': 'other', 'git_dir': 'other'}
    with pytest.raises(RuntimeError):
        session.select('aaaaaa')


def test_ignored_file_does_not_reach_model(session, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr('gai.fix.engine.load_settings', lambda: SimpleNamespace(ignore_patterns=('*.txt',)))
    monkeypatch.setattr(session, 'ask', lambda *a: pytest.fail('Ignored source sent to model'))
    session.validate()
    assert session.findings[0]['blocked']
