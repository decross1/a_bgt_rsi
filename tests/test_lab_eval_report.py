"""Source-bound numeric reporting keeps failed calls and private data out."""
from __future__ import annotations

from pathlib import Path

import pytest

from bench.flash_next_ab import lab_eval_report as report


def test_family_metrics_include_timeouts_and_all_declared_denominators():
    family = report._family({'outcomes': [
        {'family': 'objective', 'status': 'returned', 'passed': True,
         'calls': [{'status': 'returned'}], 'wall_s': 1.5},
        {'family': 'objective', 'status': 'timeout', 'passed': False,
         'calls': [{'status': 'timeout'}], 'wall_s': 75.0},
        {'family': 'historical', 'status': 'error', 'passed': False,
         'calls': [{'status': 'error'}], 'wall_s': 3.0},
    ]})
    assert family['objective'] == {
        'declared': 2, 'attempted': 2, 'returned': 1,
        'timeout': 1, 'error': 0, 'cancelled': 0, 'passed': 1,
        'wall_s_including_failures': 76.5,
    }
    assert family['historical']['declared'] == 1
    assert family['historical']['error'] == 1


def test_publication_reader_rejects_unregistered_path_before_read(tmp_path: Path):
    outside = tmp_path / 'index.json'
    outside.write_text('{}')
    with pytest.raises(report.ReportError, match='direct registered child'):
        report.read_publication(outside)
