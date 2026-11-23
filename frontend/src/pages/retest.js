import {field, form} from '../components/common/forms.js';
import {empty, heading, status, table} from '../components/common/layout.js';
import {intakeOutcome, outcomeTone} from '../constants/labels.js';
import {state} from '../stores/studio.js';
import {dateTime, esc, signed} from '../utils/format.js';

function evidenceVersion(run, fallback = {}) {
  const version = run.publication?.evidence_version ?? fallback;
  const fingerprint = version.document_fingerprint ?? run.fingerprint ?? '';
  return {version: version.method_version ?? run.method_version ?? run.version ?? '—',
    algorithm: version.algorithm ?? run.algorithm ?? '本棚计算',
    fingerprint: fingerprint ? `${fingerprint.slice(0, 12)}…` : '—'};
}

function recomputed(run) {
  return run.publication?.recompute?.recomputed ?? run.result ?? {};
}

function intakeRows() {
  return state.intakes.filter(run => run.reviewed_at).map(run => {
    const evidence = evidenceVersion(run);
    const outcome = run.publication?.recompute?.outcome ?? run.outcome;
    return `<tr><td><a href="#intake/${run.id}"><strong>${esc(run.title)}</strong></a><small>${esc(run.intake_key)} · ${esc(run.source_studio)}</small></td>
      <td class="mono">${esc(evidence.version)}<small>${esc(evidence.algorithm)} · ${esc(evidence.fingerprint)}</small></td>
      <td class="numeric">${signed(recomputed(run).partial)}<small>来件声明 ${signed(run.claim?.partial)}</small></td>
      <td>${status(intakeOutcome[outcome] ?? '—', outcomeTone[outcome] ?? '')}</td>
      <td>${esc(run.decision)}<small>${esc(run.reviewer)} · ${dateTime(run.reviewed_at)}</small></td></tr>`;
  });
}

function diagnosticRows() {
  return state.diagnostics.filter(run => run.reviewed_at && run.state === 'complete').map(run => {
    const evidence = evidenceVersion(run);
    const values = recomputed(run);
    return `<tr><td><a href="#diagnostics/${run.id}"><strong>${esc(run.title)}</strong></a><small>本棚诊断 · ${dateTime(run.created_at)}</small></td>
      <td class="mono">${esc(evidence.version)}<small>${esc(evidence.algorithm)} · ${esc(evidence.fingerprint)}</small></td>
      <td class="numeric">${signed(values.partial)}<small>原始 ${signed(values.raw)}</small></td>
      <td>${status('本棚计算完成', 'signal')}</td>
      <td>${esc(run.decision)}<small>${esc(run.reviewer)} · ${dateTime(run.reviewed_at)}</small></td></tr>`;
  });
}

function diagnosticDetail(run) {
  return `<div class="retest-detail"><h2>${esc(run.title)}</h2><p>${status(run.reviewed_at ? '已发布' : '待复核', 'signal')}</p>
    <dl class="metadata"><div><dt>变量版本</dt><dd>${esc(run.version)}</dd></div><div><dt>配对样本</dt><dd>${run.result.n} 条</dd></div><div><dt>原始 r</dt><dd>${signed(run.result.raw)}</dd></div><div><dt>控制后 r</dt><dd>${signed(run.result.partial)}</dd></div></dl>
    ${run.reviewed_at ? `<div class="decision"><h3>隔音复测安排</h3><p>${esc(run.decision)}</p><small>${esc(run.reviewer)} · ${dateTime(run.reviewed_at)}</small></div><button class="secondary" data-download>导出发布清单</button>` :
      state.account.role === 'admin' ? form('publish', field('隔音复测安排', '<textarea name="text" rows="4" minlength="8" maxlength="500" placeholder="记录复测时间、固定的风机档位和测点，以及需复验的现场条件。" required></textarea>'), '发布复测清单') : '<p class="notice">等待业务负责人记录复测安排并发布。</p>'}
    <a class="text-link" href="#diagnostics/${run.id}">返回计算证据 →</a></div>`;
}

export function retest() {
  const run = state.detail;
  const rows = [...intakeRows(), ...diagnosticRows()];
  const detail = run?.state === 'complete' ? diagnosticDetail(run) : '';
  return `${heading('隔音复测清单', '每项安排都可追溯所用证据版本与复算结论。')}
    <div class="split"><section class="bound"><div class="section-label"><h2>已发布的复测安排</h2><span>${rows.length} 项</span></div>
      ${detail}
      ${rows.length ? table(['来源诊断', '证据版本', '控制后偏相关', '复算结论', '复测安排'], rows) : empty('当前没有可阅的复测安排', '底噪诊断完算后由业务负责人复核发布；来件需复算支持原结论才可安排。')}</section>
    <aside class="inset"><h2>待复核本棚诊断</h2>${state.diagnostics.filter(item => item.state === 'complete' && !item.reviewed_at).length ? `<div class="run-list">${state.diagnostics.filter(item => item.state === 'complete' && !item.reviewed_at).map(item => `<a href="#retest/${item.id}" ${item.id === run?.id ? 'aria-current="page"' : ''}><strong>${esc(item.title)}</strong><small>待复核 · ${esc(item.version)}</small></a>`).join('')}</div>` : '<p>没有待复核的本棚诊断。</p>'}</aside></div>`;
}
