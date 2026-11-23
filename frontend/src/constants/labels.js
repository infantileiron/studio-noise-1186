export const role = {admin: '业务负责人', analyst: '声测分析员', viewer: '观察员'};
export const band = {early: '清晨', day: '日班', late: '晚间'};
export const hvac = {quiet: '低档', normal: '中档', boost: '高档'};
export const position = {booth: '录音位', street: '临街墙', door: '隔声门'};
export const predictor = {traffic: '同步车流', hvac: '风机档位'};
export const controls = {band: '工作时带', hvac: '风机档位', position: '测点位置', session: '具体录音时段'};
export const phase = {queued: '等待计算', complete: '计算完成', blocked: '计算阻断', failed: '运行失败'};
export const intakeState = {queued: '等待复算', complete: '复算完成', failed: '复算失败'};
export const intakeOutcome = {
  supported: '支持原结论',
  coefficient_mismatch: '系数对不上',
  missing_samples: '缺样',
  incomputable: '无法复算',
  unsupported_algorithm: '旧版算不动',
};
export const outcomeTone = {
  supported: 'signal', coefficient_mismatch: 'alert', missing_samples: 'alert',
  incomputable: 'alert', unsupported_algorithm: 'alert',
};
export const missingReason = {
  SAMPLE_COUNT_MISMATCH: '来件自报样本数与随附声测条数不一致。',
  INSUFFICIENT_SAMPLES: '随附声测不足以估计控制后的偏相关。',
  INCOMPLETE_SAMPLES: '部分声测行缺少配对所需的字段，已随原件保留但未纳入复算。',
  INCOMPUTABLE: '控制矩阵退化，按来件样本无法得到偏相关。',
  MISSING_DEFINITION: '来件缺少变量定义或原结论，只能留存原件。',
  ALGORITHM_UNSUPPORTED: '来件使用的旧算法不在当前复算范围，原件已留存。',
};
export const warnings = {
  TOO_FEW_ROWS: '配对声测少于 4 条，请加入更多实测时段。',
  RANK_DEFICIENT: '控制矩阵秩亏。具体时段已经包含工作时带信息，请减少重复控制。',
  NO_CONTROL_VARIATION: '至少一个控制量在本次样本里只有一个水平，请扩大时段或调整方案。',
  LOW_RESIDUAL_DF: '残差自由度小于 2，请增加样本或减少控制量。',
  ZERO_RESIDUAL_VARIATION: '至少一个变量残差近似恒定，无法计算偏相关。',
  CALCULATION_FAILED: '后台计算遇到异常，请核查服务后重新提交诊断。',
};
