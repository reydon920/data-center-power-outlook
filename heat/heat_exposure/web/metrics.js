/* Same definitions as core.py; exported for offline parity tests in Node. */
function calculate(values, threshold) {
  if (!Number.isFinite(threshold)) throw new Error('Threshold must be finite');
  let valid = 0, hot = 0, degrees = 0, longest = 0, run = 0;
  for (const value of values) {
    if (value === null) { run = 0; continue; }
    if (!Number.isFinite(value)) throw new Error('Invalid temperature');
    valid++;
    if (value > threshold) {
      hot++; degrees += value - threshold; run++;
      longest = Math.max(longest, run);
    } else { run = 0; }
  }
  return {expected_hours: values.length, valid_hours: valid,
    missing_hours: values.length - valid,
    coverage_pct: values.length ? Math.round(valid / values.length * 10000) / 100 : 0,
    hot_hours: hot, degree_hours_c_h: Math.round((degrees + Number.EPSILON) * 100) / 100,
    longest_spell_hours: longest};
}

function monthly(values, start, threshold) {
  const groups = {};
  values.forEach((value, i) => {
    const month = new Date(start + i * 3600000).toISOString().slice(0, 7);
    (groups[month] ??= []).push(value);
  });
  return Object.fromEntries(Object.entries(groups).map(([month, rows]) => [month, calculate(rows, threshold)]));
}
if (typeof module !== 'undefined') module.exports = {calculate, monthly};
