import {field, form} from '../components/common/forms.js';
import {empty, heading, status, table} from '../components/common/layout.js';
import {intakeOutcome, intakeState, missingReason, outcomeTone} from '../constants/labels.js';
import {state} from '../stores/studio.js';
import {dateTime, esc, signed} from '../utils/format.js';

function number(value) {
  return value == null ? '—' : Number(value).toFixed(4);
}

function conflictRows(conflicts) {
  const labels = {hvac: '风机', position: '测点', traffic: '车流', noise: 'LAeq', band: '工作时带'};
  return (conflicts ?? []).flatMap(item => Object.entries(item.fields).map(([key, values]) =>
    `<tr><td class="mono">${esc(item.session)} · ${esc(item.reference)}</td><td>${labels[key] ?? esc(key)}</td>
      <td class="numeric">${esc(values.local)}</td><td class="numeric">${esc(values.incoming)}</td></tr>`));
}

function evidencePanel(run) {
  const evidence = run.evidence;
  if (run.state === 'queued') {
    return '<div class="empty" role="status"><strong>已进入复算队列</strong><p>原件已锁定，完成后会自动更新。</p></div>';
  }
  if (run.state === 'failed') {
    return `<div class="notice" role="alert">复算过程遇到异常，原件与来件指纹保持不动。${state.account.role === 'admin' || state.account.role === 'analyst' ? '<button class="secondary" data-retry-intake>重试复算</button>' : ''}</div>`;
  }
  const outcome = intakeOutcome[run.outcome] ?? '来件复算完成';
  const claimed = run.claim ?? evidence?.claim ?? {};
  const recomputed = evidence?.recomputed ?? {};
  const rows = [
    `<tr><td>配对样本</td><td class="numeric">${claimed.n ?? '—'}</td><td class="numeric">${recomputed.n ?? '—'}</td></tr>`,
    `<tr><td>原始 Pearson r</td><td class="numeric">${signed(claimed.raw)}</td><td class="numeric">${signed(recomputed.raw)}</td></tr>`,
    `<tr><td>残差偏相关 r</td><td class="numeric">${signed(claimed.partial)}</td><td class="numeric">${signed(recomputed.partial)}</td></tr>`,
    `<tr><td>两系数绝对差</td><td colspan="2" class="numeric">r ${number(evidence?.deltas?.raw)} · 偏相关 ${number(evidence?.deltas?.partial)}</td></tr>`,
    `<tr><td>矩阵秩／列数</td><td colspan="2" class="numeric">${recomputed.rank ?? '—'} / ${(recomputed.columns ?? []).length || '—'}</td></tr>`,
    `<tr><td>残差自由度</td><td colspan="2" class="numeric">${recomputed.df ?? '—'}</td></tr>`,
  ];
  const missing = evidence?.missing;
  const missingNote = missing ? `<p class="notice" data-missing="${esc(missing.reason)}">${missingReason[missing.reason] ?? '缺少可复算的样本或设置。'}${missing.warnings?.length ? `（${missing.warnings.map(code => esc(code)).join('、')}）` : ''}${missing.rows?.length ? `（${missing.rows.length} 行缺字段）` : ''}</p>` : '';
  const warnings = recomputed.warnings?.length ? `<p class="notice">${recomputed.warnings.map(code => esc(code)).join('、')}</p>` : '';
  const conflicts = run.conflicts ?? [];
  const conflictBlock = conflicts.length
    ? `<h3>同号读数冲突</h3><p class="interpretation">两棚对同一次声测的读数不同。复算只用外棚随附数值，本棚实测未被覆盖。</p>${table(['声测', '字段', '本棚实测', '外棚来件'], conflictRows(conflicts))}`
    : '';
  return `<div class="result-body"><div class="coefficients">
      <div><span>来件原结论</span><strong>${signed(claimed.partial)}</strong></div>
      <div><span>复算偏相关</span><strong>${signed(recomputed.partial)}</strong></div>
      <div><span>复算样本</span><strong>${recomputed.n ?? '—'}<small> 条</small></strong></div>
    </div>
    <p class="interpretation">${status(outcome, outcomeTone[run.outcome] ?? 'signal')} ${run.outcome === 'supported' ? '复算支持原结论，可进入复测安排。' : run.outcome === 'coefficient_mismatch' ? '样本足够，但复算系数与来件声明对不上，需先对稿。' : run.outcome === 'missing_samples' ? '随附声测或声明样本不足，原件保留待补样。' : '当前算法无法从随附材料复算，原件保留。'}</p>
    ${missingNote}${warnings}
    ${table(['量', '来件声明', '本次复算'], rows)}${conflictBlock}
    <div class="panel-actions"><button class="secondary" data-download-intake>导出原件与复算证据</button></div></div>`;
}

function publicationBlock(run) {
  const publication = run.publication;
  if (run.state !== 'complete') return '';
  if (!publication) {
    if (run.outcome !== 'supported') return `<p class="notice">复算未支持原结论，暂不可安排复测。</p>`;
    if (state.account.role === 'admin') {
      return `<h3>安排复测</h3>${form('retest-intake', field('隔音复测安排', '<textarea name="text" rows="4" minlength="8" maxlength="500" placeholder="记录复测时间、固定的风机档位和测点，以及需复验的现场条件。" required></textarea>'), '发布复测清单')}`;
    }
    return '<p class="notice">等待业务负责人记录复测安排并发布。</p>';
  }
  const version = publication.evidence_version ?? {};
  return `<div class="decision"><h3>隔音复测安排</h3><p>${esc(publication.decision)}</p>
    <dl class="metadata"><div><dt>证据版本</dt><dd>${esc(version.method_version ?? '—')} · ${esc(version.algorithm ?? '—')}</dd></div>
    <div class="digest"><dt>来件指纹</dt><dd class="mono">${esc(version.document_fingerprint ?? '—')}</dd></div>
    <div><dt>复算结论</dt><dd>${esc(intakeOutcome[publication.recompute?.outcome] ?? '—')}</dd></div></dl>
    <small>${esc(publication.reviewer)} · ${dateTime(publication.published_at)}</small></div>`;
}

export function intake() {
  const run = state.detail;
  const writable = ['admin', 'analyst'].includes(state.account.role);
  const sidebar = `<aside class="inset"><h2>来件</h2>${state.intakes.length ? `<div class="run-list">${state.intakes.map(item => `<a href="#intake/${item.id}" ${item.id === run?.id ? 'aria-current="page"' : ''}><strong>${esc(item.intake_key)}</strong><small>${esc(item.source_studio)} · ${intakeState[item.state]}${item.outcome ? ' · ' + intakeOutcome[item.outcome] : ''}</small></a>`).join('')}</div>` : '<p>提交外棚来件后，可在这里查看原件、冲突与复算结论。</p>'}</aside>`;
  let main;
  if (run) {
    main = `<section class="bound"><div class="section-label"><div><h2>${esc(run.title)}</h2><p class="mono">${esc(run.intake_key)} · ${esc(run.source_studio)} · ${esc(run.method_version)}</p></div>${status(intakeState[run.state], run.state === 'failed' ? 'alert' : 'signal')}</div>
      ${status(intakeOutcome[run.outcome] ?? '等待复算', outcomeTone[run.outcome] ?? '')}
      <dl class="metadata"><div><dt>来件算法</dt><dd>${esc(run.algorithm)}</dd></div><div><dt>变量版本</dt><dd>${esc(run.method_version)}</dd></div><div><dt>尝试次数</dt><dd>${run.attempts}</dd></div><div class="digest"><dt>来件指纹</dt><dd class="mono">${esc(run.fingerprint)}</dd></div></dl>
      ${evidencePanel(run)}${publicationBlock(run)}</section>`;
  } else {
    main = `<section class="bound"><div class="section-label"><h2>登记外棚来件</h2></div>${writable ? `<p class="interpretation">粘贴外棚交来的诊断原件（含声测样本、变量定义、算法与结论）。系统按来件样本和变量版本重新计算偏相关，原件与指纹一并留存。</p>${form('intakes', field('来件原件 JSON', '<textarea name="document" rows="14" class="mono" placeholder=\'{"intake_key":"OUT-1123-01","source_studio":"B 棚",...}\' required></textarea>'), '提交复算')}` : empty('等待外棚来件', '分析员登记来件后，这里会显示复算结论。')}</section>`;
  }
  return `${heading('来件复算', '按外棚声测样本与变量版本重算偏相关，分清缺样与系数对不上。', '')}<div class="split">${main}${sidebar}</div>`;
}
