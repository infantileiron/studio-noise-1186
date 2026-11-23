from src.config.runtime import database
from src.services.correlation import calculate
from src.services.intakes import local_conflicts
from src.utils.documents import encode, fingerprint
from src.utils.security import password_hash

WINDOWS = [
    ('FS-1109-A', '晨间校准', '2026-11-09', '07:40', 'early'),
    ('FS-1109-B', '日班旁白前', '2026-11-09', '14:20', 'day'),
    ('FS-1109-C', '晚间收棚', '2026-11-09', '20:10', 'late'),
    ('FS-1112-A', '晨间复测', '2026-11-12', '07:45', 'early'),
    ('FS-1112-B', '日班开棚', '2026-11-12', '14:15', 'day'),
    ('FS-1112-C', '晚班留底', '2026-11-12', '20:05', 'late'),
]
METHODS = [
    ('TRF-01', '时段校正 · 车流', 'traffic', ['band', 'hvac', 'position'], '对照未调整与控制后的车流关联。'),
    ('AIR-01', '同条件比风机', 'hvac', ['band', 'position'], '将风机档位作有序解释量，控制时段与测点。'),
    ('RANK-01', '共线边界复核', 'traffic', ['band', 'session'], '每个具体时段属于唯一班带，组合后矩阵秩亏。'),
]


def seed():
    with database() as cursor:
        for role in ('admin', 'analyst', 'viewer'):
            email = role + '@demo.local'
            cursor.execute('SELECT id FROM accounts WHERE email=%s', (email,))
            if not cursor.fetchone():
                cursor.execute('''INSERT INTO accounts(email,password_hash,role) VALUES (%s,%s,%s)
                                  ON DUPLICATE KEY UPDATE id=id''', (email, password_hash('Tape2026!'), role))
        for index, (code, title, day, hour, band) in enumerate(WINDOWS):
            cursor.execute('''INSERT INTO sessions(code,title,recorded_on,start_time,band,room,note)
                              VALUES (%s,%s,%s,%s,%s,'A 棚 · 临街间','无声段 60 秒，车流和声级同步计数')
                              ON DUPLICATE KEY UPDATE id=id''', (code, title, day, hour, band))
            cursor.execute('SELECT id FROM sessions WHERE code=%s', (code,))
            session_id = cursor.fetchone()['id']
            period = {'early': 0, 'day': 2, 'late': 1}[band]
            for level, hvac in enumerate(('quiet', 'normal', 'boost')):
                for side, position in enumerate(('booth', 'street')):
                    for repeat, sign in enumerate((-1, 1), 1):
                        traffic = 8 + 16 * period + 3 * sign + index // 3
                        noise = 26 + 5 * period + 2.5 * level + 2.1 * side + .12 * sign + .95 * (2 * side - 1) * sign
                        noise += .5 * (2 * (index // 3) - 1)
                        key = f'{code}-{level + 1}{side + 1}{repeat}'
                        cursor.execute('''INSERT INTO readings(session_id, reference, hvac, position, traffic, noise, note)
                                          VALUES (%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE id=id''',
                                       (session_id, key, hvac, position, traffic, round(noise, 2), '合成 LAeq 与同步车流'))
        for version, title, predictor, controls, note in METHODS:
            cursor.execute('''INSERT INTO methods(version,title,predictor,controls,note) VALUES (%s,%s,%s,%s,%s)
                              ON DUPLICATE KEY UPDATE id=id''', (version, title, predictor, encode(controls), note))
        _seed_intakes(cursor)
        summary = {}
        for table, keys in [('accounts', 'email'), ('sessions', 'code'), ('readings', 'session_id,reference'),
                            ('methods', 'version'), ('intakes', 'intake_key')]:
            cursor.execute(f'SELECT {keys} FROM {table} ORDER BY {keys}')
            rows = cursor.fetchall()
            summary[table] = {'count': len(rows), 'keys': rows}
        print(encode(summary))


def _samples(cursor):
    cursor.execute('''SELECT s.code AS session, s.band, r.reference, r.hvac, r.position, r.traffic,
                             CAST(r.noise AS DOUBLE) AS noise
                      FROM readings r JOIN sessions s ON s.id=r.session_id
                      ORDER BY s.code, r.reference''')
    return [dict(row) for row in cursor.fetchall()]


def _claim(rows):
    sample = [{'session_id': row['session'], 'code': row['session'], 'band': row['band'],
               'reference': row['reference'], 'hvac': row['hvac'], 'position': row['position'],
               'traffic': row['traffic'], 'noise': row['noise']} for row in rows]
    _, result = calculate({'algorithm': 'residual-pearson-v1',
                           'method': {'version': 'TRF-01', 'predictor': 'traffic',
                                      'controls': ['band', 'hvac', 'position']},
                           'readings': sample})
    return {'n': len(rows), 'raw': round(result['raw'], 6), 'partial': round(result['partial'], 6)}


def _seed_intakes(cursor):
    rows = _samples(cursor)
    if not rows:
        return
    method = {'version': 'TRF-01', 'predictor': 'traffic', 'controls': ['band', 'hvac', 'position']}
    # One intake whose samples and coefficients reproduce the original conclusion, and one whose
    # coefficients drifted, so the workflow shows both "supported" and "coefficient_mismatch".
    full = rows
    half = rows[:36]
    # Both studios logged the same 60-second sample once; the reading differs, so the retained
    # intake carries the conflict while the local reading stays untouched.
    shared = [dict(row) for row in full]
    shared[0]['noise'] = round(shared[0]['noise'] + 0.6, 2)
    drifted = {**_claim(half), 'partial': round(_claim(half)['partial'] + 0.083, 6)}
    documents = [
        {'intake_key': 'OUT-1123-01', 'source_studio': 'B 棚 · 内间', 'title': 'B 棚车流与底噪 · 11 月来件',
         'method': method, 'algorithm': 'residual-pearson-v1', 'claim': _claim(shared), 'readings': shared},
        {'intake_key': 'OUT-1123-02', 'source_studio': 'B 棚 · 内间', 'title': 'B 棚底噪 · 系数待对稿',
         'method': method, 'algorithm': 'residual-pearson-v1', 'claim': drifted, 'readings': half},
        {'intake_key': 'OUT-1102-07', 'source_studio': 'B 棚 · 内间', 'title': 'B 棚底噪 · 旧版记录',
         'algorithm': 'pearson-control-v0'},
    ]
    cursor.execute('SELECT id FROM accounts WHERE email=%s', ('analyst@demo.local',))
    owner = cursor.fetchone()['id']
    for document in documents:
        cursor.execute('SELECT id FROM intakes WHERE intake_key=%s', (document['intake_key'],))
        if cursor.fetchone():
            continue
        conflicts = local_conflicts(cursor, document.get('readings') or [])
        cursor.execute('''INSERT INTO intakes(intake_key, source_studio, title, owner_id, method_id,
                            method_version, algorithm, fingerprint, original, claim, conflicts)
                          VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                       (document['intake_key'], document['source_studio'], document['title'], owner,
                        None, (document.get('method') or {}).get('version', ''),
                        document.get('algorithm') or '', fingerprint(document),
                        encode(document), encode(document.get('claim')), encode(conflicts)))


if __name__ == '__main__':
    seed()
