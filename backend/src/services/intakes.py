import json
import time
from pathlib import Path

from fastapi import HTTPException
from pymysql.err import IntegrityError, OperationalError

from src.config.runtime import database
from src.constants.labels import ALGORITHM, COEFFICIENT_TOLERANCE, IntakeOutcome, Role
from src.models.studio import audit, decode_json
from src.services.correlation import calculate
from src.utils.documents import encode, fingerprint

INTAKE_COLUMNS = """i.id, i.intake_key, i.source_studio, i.title, i.method_id, i.method_version,
                    i.algorithm, i.state, i.outcome, i.fingerprint, i.attempts, i.claim, i.result,
                    i.decision, i.publication, i.created_at, i.finished_at, i.reviewed_at,
                    a.email AS owner, reviewer.email AS reviewer"""
INTAKE_FROM = """FROM intakes i JOIN accounts a ON i.owner_id=a.id
                 LEFT JOIN accounts reviewer ON i.reviewer_id=reviewer.id"""
DETAIL_COLUMNS = INTAKE_COLUMNS + ', i.original, i.conflicts, i.evidence'
MISSING_WARNINGS = {'TOO_FEW_ROWS', 'NO_CONTROL_VARIATION', 'LOW_RESIDUAL_DF'}


def _normalise(data):
    document = data.model_dump(mode='json')
    document['readings'] = sorted(document['readings'],
                                   key=lambda row: (row['session'] or '~', row['reference'] or '~'))
    if document.get('method'):
        document['method']['controls'] = list(document['method']['controls'])
    return document


def _incomplete_rows(readings):
    """Rows that arrived without one of the inputs needed to pair them, kept for traceability."""
    return [{'session': row.get('session'), 'reference': row.get('reference'),
             'missing': [key for key in ('session', 'reference', 'band', 'hvac', 'position', 'traffic', 'noise')
                         if row.get(key) is None]}
            for row in readings if any(row.get(key) is None for key in
                                       ('session', 'reference', 'band', 'hvac', 'position', 'traffic', 'noise'))]


def local_conflicts(cursor, readings):
    paired = [row for row in readings if row.get('session') and row.get('reference')]
    if not paired:
        return []
    codes = sorted({row['session'] for row in paired})
    placeholders = ','.join(['%s'] * len(codes))
    cursor.execute(f'''SELECT s.code, s.band, r.reference, r.hvac, r.position, r.traffic,
                              CAST(r.noise AS DOUBLE) AS noise
                       FROM readings r JOIN sessions s ON s.id=r.session_id
                       WHERE s.code IN ({placeholders})''', codes)
    local = {(row['code'], row['reference']): row for row in cursor.fetchall()}
    conflicts = []
    for row in paired:
        hit = local.get((row['session'], row['reference']))
        if hit is None:
            continue
        fields = {}
        for key in ('hvac', 'position', 'traffic'):
            if row.get(key) is not None and hit[key] != row[key]:
                fields[key] = {'local': hit[key], 'incoming': row[key]}
        if row.get('noise') is not None and abs(float(hit['noise']) - float(row['noise'])) > 1e-6:
            fields['noise'] = {'local': float(hit['noise']), 'incoming': row['noise']}
        if row.get('band') is not None and hit['band'] != row['band']:
            fields['band'] = {'local': hit['band'], 'incoming': row['band']}
        if fields:
            conflicts.append({'session': row['session'], 'reference': row['reference'], 'fields': fields})
    return conflicts


def _local_method(cursor, method):
    if not method:
        return None
    cursor.execute('SELECT id, predictor, controls FROM methods WHERE version=%s', (method['version'],))
    row = cursor.fetchone()
    if row is None or row['predictor'] != method['predictor']:
        return None
    if json.loads(row['controls']) != method['controls']:
        return None
    return row['id']


def _insert(cursor, document, owner_id):
    """Insert a normalised document, returning (identifier, inserted, clash)."""
    checksum = fingerprint(document)
    method = document.get('method')
    method_id = _local_method(cursor, method)
    conflicts = local_conflicts(cursor, document['readings'])
    try:
        cursor.execute('''INSERT INTO intakes(intake_key, source_studio, title, owner_id, method_id,
                            method_version, algorithm, fingerprint, original, claim, conflicts)
                          VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                       (document['intake_key'], document['source_studio'], document['title'], owner_id,
                        method_id, method['version'] if method else '', document.get('algorithm') or '',
                        checksum, encode(document), encode(document.get('claim')), encode(conflicts)))
    except IntegrityError as error:
        if error.args and error.args[0] != 1062:
            raise
        cursor.execute('SELECT id, fingerprint FROM intakes WHERE intake_key=%s FOR UPDATE',
                       (document['intake_key'],))
        existing = cursor.fetchone()
        if existing is None:
            raise HTTPException(409, '同号来件正在并发登记，请稍后重看')
        return existing['id'], False, existing['fingerprint'] != checksum
    return cursor.lastrowid, True, False


def submit(data, account):
    document = _normalise(data)
    for attempt in range(3):
        try:
            with database() as cursor:
                identifier, inserted, clash = _insert(cursor, document, account['id'])
                audit(cursor, account['id'], 'intake.submit' if inserted else 'intake.duplicate',
                      str(identifier))
            break
        except OperationalError as error:
            # Concurrent same-key hand-offs can deadlock on the unique index; a deadlock is rolled
            # back so retrying lands on the retained row (or this request's own insert).
            if attempt == 2 or error.args[0] != 1213:
                raise HTTPException(409, '同号来件正在并发登记，请稍后重看') from error
            time.sleep(0.05 * (attempt + 1))
    if clash:
        # A newer document under an existing key never replaces the retained original.
        raise HTTPException(409, '同号来件已保留原件，新版未替换；如需复核请另用新来件编号')
    run = get_intake(identifier, account)
    run['duplicate'] = not inserted
    return run, inserted


def _visible(account):
    return ' WHERE i.reviewed_at IS NOT NULL' if account['role'] == Role.viewer else ''


def serialise(run):
    """Turn timestamps into JSON-safe strings without dropping the stored original document."""
    document = {key: value for key, value in run.items()}
    for key in ('created_at', 'finished_at', 'reviewed_at'):
        if document.get(key) is not None:
            document[key] = document[key].isoformat()
    return document


def _publication(cursor, identifier, row, text, account):
    """Remember which evidence version and recompute conclusion this retest arrangement used."""
    cursor.execute('SELECT reviewed_at FROM intakes WHERE id=%s', (identifier,))
    reviewed_at = cursor.fetchone()['reviewed_at']
    return {
        'kind': 'intake', 'intake_id': identifier, 'intake_key': row['intake_key'],
        'source_studio': row['source_studio'], 'title': row['title'],
        'evidence_version': {'method_version': row['method_version'], 'algorithm': row['algorithm'],
                             'document_fingerprint': row['fingerprint']},
        'recompute': json.loads(row['evidence']) if row['evidence'] else None,
        'decision': text, 'reviewer': account['email'], 'published_at': reviewed_at.isoformat(),
    }


def get_intake(identifier, account):
    scope = ' AND i.reviewed_at IS NOT NULL' if account['role'] == Role.viewer else ''
    with database() as cursor:
        cursor.execute('SELECT ' + DETAIL_COLUMNS + ' ' + INTAKE_FROM + ' WHERE i.id=%s' + scope, (identifier,))
        row = cursor.fetchone()
    if row is None:
        raise HTTPException(404, '找不到可阅来件')
    return decode_json(row, 'original', 'claim', 'result', 'conflicts', 'evidence', 'publication')


def list_intakes(account):
    with database() as cursor:
        cursor.execute('SELECT ' + INTAKE_COLUMNS + ' ' + INTAKE_FROM + _visible(account)
                       + ' ORDER BY i.id DESC LIMIT 100')
        return [decode_json(row, 'claim', 'result', 'publication') for row in cursor.fetchall()]


def retry(identifier, account):
    with database() as cursor:
        cursor.execute("SELECT id, state, reviewed_at FROM intakes WHERE id=%s FOR UPDATE", (identifier,))
        row = cursor.fetchone()
        if row is None:
            raise HTTPException(404, '找不到来件')
        if row['reviewed_at'] is not None:
            raise HTTPException(409, '该来件已安排复测，原件与结论不再重算')
        if row['state'] != 'failed':
            raise HTTPException(409, '仅复算失败的来件可重试，已入账的结论不会被重算覆盖')
        cursor.execute('''UPDATE intakes SET state='queued', outcome=NULL, result=NULL, evidence=NULL,
                            finished_at=NULL, attempts=attempts+1 WHERE id=%s''', (identifier,))
        audit(cursor, account['id'], 'intake.retry', str(identifier))
    return get_intake(identifier, account)


def publish_retest(identifier, text, account):
    with database() as cursor:
        cursor.execute('''SELECT state, outcome, reviewed_at, intake_key, source_studio, title, method_version,
                                 algorithm, fingerprint, evidence
                          FROM intakes WHERE id=%s FOR UPDATE''', (identifier,))
        row = cursor.fetchone()
        if row is None:
            raise HTTPException(404, '找不到来件')
        if row['state'] != 'complete' or row['outcome'] != IntakeOutcome.supported:
            raise HTTPException(409, '复算未支持原结论，不可安排复测')
        if row['reviewed_at']:
            raise HTTPException(409, '该来件已安排复测')
        cursor.execute('''UPDATE intakes SET decision=%s, reviewer_id=%s, reviewed_at=CURRENT_TIMESTAMP
                          WHERE id=%s''', (text, account['id'], identifier))
        publication = _publication(cursor, identifier, row, text, account)
        cursor.execute('UPDATE intakes SET publication=%s WHERE id=%s', (encode(publication), identifier))
        audit(cursor, account['id'], 'intake.retest', str(identifier))
    return get_intake(identifier, account)


def export(identifier, account):
    run = get_intake(identifier, account)
    if run['state'] not in ('complete', 'failed'):
        raise HTTPException(409, '来件尚无可导出的原件与复算证据')
    document = encode({
        'kind': 'intake', 'id': run['id'], 'intake_key': run['intake_key'],
        'source_studio': run['source_studio'], 'title': run['title'],
        'state': run['state'], 'outcome': run['outcome'], 'fingerprint': run['fingerprint'],
        'original': run['original'], 'claim': run['claim'], 'result': run['result'],
        'conflicts': run['conflicts'], 'evidence': run['evidence'], 'publication': run['publication'],
        'decision': run['decision'], 'reviewer': run['reviewer'],
        'created_at': run['created_at'].isoformat() if run['created_at'] else None,
        'finished_at': run['finished_at'].isoformat() if run['finished_at'] else None,
        'reviewed_at': run['reviewed_at'].isoformat() if run['reviewed_at'] else None,
    })
    with database() as cursor:
        audit(cursor, account['id'], 'intake.export', str(identifier))
    return Path(f'studio-intake-{identifier}.json').name, document


def recompute(original):
    """Recompute the partial correlation strictly from the incoming samples and variable version."""
    method, readings, claim = original.get('method'), original.get('readings') or [], original.get('claim')
    evidence = {
        'intake_key': original['intake_key'], 'source_studio': original['source_studio'],
        'method': ({'version': method['version'], 'predictor': method['predictor'],
                    'controls': method['controls']} if method else None),
        'algorithm': original.get('algorithm'), 'expected_algorithm': ALGORITHM,
        'claim': claim, 'provided_n': len(readings), 'tolerance': COEFFICIENT_TOLERANCE,
    }
    if original.get('algorithm') != ALGORITHM:
        # Old, unknown or missing algorithm: keep the original document, but the current service
        # cannot vouch for a recompute under a different method definition.
        evidence.update(outcome=IntakeOutcome.unsupported_algorithm,
                        missing={'reason': 'ALGORITHM_UNSUPPORTED', 'expected': ALGORITHM,
                                 'received': original.get('algorithm')})
        return IntakeOutcome.unsupported_algorithm, None, evidence
    if not method or claim is None:
        # Current algorithm name but the document does not carry the variable definition or the claim.
        evidence.update(outcome=IntakeOutcome.incomputable,
                        missing={'reason': 'MISSING_DEFINITION',
                                 'absent': [name for name, value in (('method', method), ('claim', claim))
                                            if value is None]})
        return IntakeOutcome.incomputable, None, evidence

    incomplete = _incomplete_rows(readings)
    rows = [{'session_id': row['session'], 'code': row['session'], 'band': row['band'],
             'reference': row['reference'], 'hvac': row['hvac'], 'position': row['position'],
             'traffic': row['traffic'], 'noise': row['noise']}
            for row in readings if row.get('session') and row.get('reference')
            and None not in (row.get('band'), row.get('hvac'), row.get('position'),
                             row.get('traffic'), row.get('noise'))]
    evidence['paired_n'] = len(rows)
    evidence['incomplete'] = incomplete
    state, result = calculate({'algorithm': ALGORITHM, 'method': method, 'readings': rows})
    evidence['recomputed'] = {key: result.get(key) for key in
                              ('n', 'raw', 'partial', 'rank', 'columns', 'df', 'warnings', 'absolute_drop')}

    missing = None
    if incomplete:
        missing = {'reason': 'INCOMPLETE_SAMPLES', 'rows': incomplete}
    elif claim.get('n') is not None and claim['n'] != len(rows):
        missing = {'reason': 'SAMPLE_COUNT_MISMATCH', 'claimed': claim['n'], 'provided': len(rows)}
    elif state == 'blocked' and set(result['warnings']) & MISSING_WARNINGS:
        missing = {'reason': 'INSUFFICIENT_SAMPLES', 'warnings': result['warnings']}
    if missing:
        evidence.update(outcome=IntakeOutcome.missing_samples, missing=missing)
        return IntakeOutcome.missing_samples, result, evidence
    if state == 'blocked':
        evidence.update(outcome=IntakeOutcome.incomputable,
                        missing={'reason': 'INCOMPUTABLE', 'warnings': result['warnings']})
        return IntakeOutcome.incomputable, result, evidence
    if result.get('raw') is None or result.get('partial') is None:
        evidence.update(outcome=IntakeOutcome.incomputable,
                        missing={'reason': 'INCOMPUTABLE', 'warnings': result.get('warnings', [])})
        return IntakeOutcome.incomputable, result, evidence

    raw_delta = abs(result['raw'] - claim['raw'])
    partial_delta = abs(result['partial'] - claim['partial'])
    evidence['deltas'] = {'raw': raw_delta, 'partial': partial_delta}
    if raw_delta <= COEFFICIENT_TOLERANCE and partial_delta <= COEFFICIENT_TOLERANCE:
        outcome = IntakeOutcome.supported
    else:
        outcome = IntakeOutcome.coefficient_mismatch
    evidence['outcome'] = outcome
    return outcome, result, evidence
