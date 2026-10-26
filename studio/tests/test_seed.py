"""First start: an empty content folder is filled from starter/ (and an existing one is never touched)."""
import json

import server


def test_seed_empty_folder(tmp_path):
    d = tmp_path / 'data'
    server.seed_data_dir(dict(backend='local', local_path=str(d)))
    assert (d / 'projects').is_dir() and (d / 'upload').is_dir() and (d / 'references').is_dir()
    assert json.loads((d / 'posting_log.json').read_text())['posts'] == []
    assert '**A.' in (d / 'qa_rules.md').read_text() and not list(d.rglob('.gitkeep'))


def test_seed_never_overwrites_and_skips_buckets(tmp_path):
    d = tmp_path / 'data'; (d / 'projects').mkdir(parents=True); (d / 'qa_rules.md').write_text('mine')
    server.seed_data_dir(dict(backend='local', local_path=str(d)))
    assert (d / 'qa_rules.md').read_text() == 'mine' and not (d / 'style.md').exists()
    e = tmp_path / 'other'
    server.seed_data_dir(dict(backend='s3', local_path=str(e)))
    assert not e.exists()
