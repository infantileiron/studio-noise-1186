import json
import logging
import os
import time
from pathlib import Path

from src.config.runtime import cache, database
from src.models.studio import audit
from src.services.correlation import calculate
from src.services.intakes import recompute
from src.utils.documents import encode, fingerprint

logger = logging.getLogger(__name__)
EXPORTS = Path(os.getenv('EXPORTS_DIR', '/exports'))


def _publish_copy(name, document):
    """Mirror evidence onto the shared export volume; the database copy remains authoritative."""
    try:
        pending = EXPORTS / f'.{name}.tmp'
        pending.write_text(encode(document), encoding='utf-8')
        os.replace(pending, EXPORTS / f'{name}.json')
    except OSError:
        logger.exception('Evidence %s not written to export share', name)


def _finish_diagnostic(cursor, identifier):
    cursor.execute("SELECT snapshot, fingerprint FROM diagnostics WHERE id=%s AND state='queued' FOR UPDATE",
                   (identifier,))
    task = cursor.fetchone()
    if task is None:
        return False
    try:
        snapshot = json.loads(task['snapshot'])
        if fingerprint(snapshot) != task['fingerprint']:
            raise ValueError('snapshot fingerprint mismatch')
        state, result = calculate(snapshot)
    except Exception:
        logger.exception('Diagnostic %s failed', identifier)
        state, result = 'failed', {'warnings': ['CALCULATION_FAILED']}
    # Only the worker that still sees a queued row accounts for it once; retries never double-post.
    cursor.execute('''UPDATE diagnostics SET state=%s, result=%s, finished_at=CURRENT_TIMESTAMP
                      WHERE id=%s AND state='queued' ''', (state, encode(result), identifier))
    if cursor.rowcount == 1:
        audit(cursor, None, f'diagnostic.{state}', str(identifier))
        _publish_copy(f'result-{identifier}', result)
    return True


def _finish_intake(cursor, identifier):
    cursor.execute('SELECT original, fingerprint, state FROM intakes WHERE id=%s FOR UPDATE', (identifier,))
    task = cursor.fetchone()
    if task is None or task['state'] != 'queued':
        return False
    try:
        original = json.loads(task['original'])
        if fingerprint(original) != task['fingerprint']:
            raise ValueError('intake fingerprint mismatch')
        outcome, result, evidence = recompute(original)
    except Exception:
        logger.exception('Intake %s failed', identifier)
        cursor.execute('''UPDATE intakes SET state='failed', outcome=NULL, result=NULL, evidence=NULL,
                            finished_at=CURRENT_TIMESTAMP
                          WHERE id=%s AND state='queued' ''', (identifier,))
        if cursor.rowcount == 1:
            audit(cursor, None, 'intake.failed', str(identifier))
        return True
    stored = None if result is None else {key: value for key, value in result.items() if key != 'rows'}
    # Accounting happens once: the queued guard plus the row lock avoids double posting on retry.
    cursor.execute('''UPDATE intakes SET state='complete', outcome=%s, result=%s, evidence=%s,
                        finished_at=CURRENT_TIMESTAMP
                      WHERE id=%s AND state='queued' ''',
                   (outcome, encode(stored) if stored is not None else None, encode(evidence), identifier))
    if cursor.rowcount == 1:
        audit(cursor, None, f'intake.{outcome}', str(identifier))
        _publish_copy(f'intake-{identifier}', evidence)
    return True


def process():
    with database() as cursor:
        cursor.execute('''SELECT id FROM intakes WHERE state='queued'
                          ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED''')
        task = cursor.fetchone()
        if task:
            return _finish_intake(cursor, task['id'])
        cursor.execute('''SELECT id FROM diagnostics WHERE state='queued'
                          ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED''')
        task = cursor.fetchone()
        if task:
            return _finish_diagnostic(cursor, task['id'])
        return False


def main():
    logging.basicConfig(level=logging.INFO)
    while True:
        try:
            completed = process()
            cache.set('studio:worker:heartbeat', 'ready', ex=12)
            if not completed:
                time.sleep(0.5)
        except Exception:
            logger.exception('Worker dependency unavailable')
            time.sleep(2)


if __name__ == '__main__':
    main()
