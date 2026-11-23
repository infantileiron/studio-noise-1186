export const payload = {
  sessions: form => Object.fromEntries(form),
  readings: form => ({...Object.fromEntries(form),
    session_id: Number(form.get('session_id')), traffic: Number(form.get('traffic')), noise: Number(form.get('noise')),
  }),
  methods: form => ({...Object.fromEntries(form), controls: form.getAll('controls')}),
  diagnostics: form => ({title: form.get('title'), method_id: Number(form.get('method_id')),
    session_ids: form.getAll('session_ids').map(Number),
  }),
  intakes: form => {
    let document;
    try { document = JSON.parse(form.get('document')); }
    catch { throw new Error('来件需为合法 JSON'); }
    if (!document || typeof document !== 'object' || Array.isArray(document)) throw new Error('来件需为单个 JSON 对象');
    return document;
  },
};
