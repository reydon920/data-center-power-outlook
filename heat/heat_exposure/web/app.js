const data = JSON.parse(document.getElementById('snapshot').textContent);
const sites = data.manifest.sites;
const colors = ['#ae4b26', '#246a80', '#6657a5', '#397548'];
const slider = document.getElementById('threshold');
slider.min = Math.min(-10, data.threshold);
slider.max = Math.max(50, data.threshold);
slider.value = data.threshold;
const start = Date.UTC(+data.manifest.start.slice(0,4), +data.manifest.start.slice(4,6)-1,
  +data.manifest.start.slice(6,8), +data.manifest.start.slice(8,10));
const fmt = value => value.toLocaleString('en-US', {maximumFractionDigits: 2});
const svgNS = 'http://www.w3.org/2000/svg';
function element(tag, text, attrs = {}) {
  const node = document.createElement(tag); node.textContent = text;
  Object.entries(attrs).forEach(([k, v]) => node.setAttribute(k, v));
  return node;
}
function drawMonths(months) {
  const chart = document.getElementById('monthly-chart');
  chart.replaceChildren();
  const monthKeys = Object.keys(months[sites[0].id]);
  const width = 1100, height = 350, left = 65, top = 30, plotH = 230, plotW = 1000;
  const peak = Math.max(1, ...Object.values(months).flatMap(group => Object.values(group).map(m => m.hot_hours)));
  function svg(tag, attrs, text = '') {
    const node = document.createElementNS(svgNS, tag);
    Object.entries(attrs).forEach(([k,v]) => node.setAttribute(k,v));
    node.textContent = text; chart.append(node); return node;
  }
  chart.setAttribute('viewBox', `0 0 ${width} ${height}`);
  svg('title', {}, `Monthly hours above ${slider.value} degrees Celsius`);
  for (let tick = 0; tick <= 4; tick++) {
    const y = top + plotH - tick / 4 * plotH;
    svg('line', {x1:left, x2:left+plotW, y1:y, y2:y, stroke:'#deded4'});
    svg('text', {x:left-10, y:y+5, 'text-anchor':'end'}, fmt(peak*tick/4));
  }
  monthKeys.forEach((key, index) => {
    const groupW = plotW / monthKeys.length, barW = groupW * 0.8 / sites.length;
    sites.forEach((site, j) => {
      const value = months[site.id][key].hot_hours;
      const rect = svg('rect', {x:left+index*groupW+groupW*0.1+j*barW,
        y:top+plotH-value/peak*plotH, width:barW-1, height:value/peak*plotH,
        fill:colors[j%colors.length]});
      const tip = document.createElementNS(svgNS,'title');
      tip.textContent = `${site.name}, ${key}: ${value} hours`; rect.append(tip);
    });
    svg('text', {x:left+(index+0.5)*groupW, y:top+plotH+27, 'text-anchor':'middle'}, key.slice(5));
  });
  svg('text', {x:15,y:18}, 'Hours');
  svg('text', {x:left+plotW/2,y:height-13,'text-anchor':'middle'}, 'Month (UTC; YYYY-MM in downloadable results)');
}
let summary, months;
function update() {
  const threshold = Number(slider.value);
  document.getElementById('chosen-threshold').textContent = `${threshold} °C`;
  summary = {}; months = {};
  const body = document.getElementById('summary'); body.replaceChildren();
  sites.forEach((site, i) => {
    const result = calculate(data.values[site.id], threshold);
    summary[site.id] = result;
    months[site.id] = monthly(data.values[site.id], start, threshold);
    const row = document.createElement('tr');
    row.append(element('th', site.name, {scope:'row', style:`color:${colors[i%colors.length]}`}));
    [result.coverage_pct+'%', fmt(result.missing_hours), fmt(result.hot_hours),
      fmt(result.degree_hours_c_h), fmt(result.longest_spell_hours)].forEach(value => row.append(element('td', value)));
    body.append(row);
  });
  const incomplete = Object.values(summary).some(result => result.missing_hours);
  document.getElementById('coverage-note').textContent = incomplete
    ? 'Incomplete coverage: observed counts are lower bounds. Missing hours break hot spells; compare coverage before ranking sites.'
    : 'Complete hourly coverage for every site in this snapshot. Counts still describe only this period.';
  drawMonths(months);
  const monthlyBody = document.getElementById('monthly-rows'); monthlyBody.replaceChildren();
  sites.forEach(site => Object.entries(months[site.id]).forEach(([month, result]) => {
    const row = document.createElement('tr');
    [site.name, month, result.coverage_pct+'%', result.hot_hours, fmt(result.degree_hours_c_h), result.longest_spell_hours]
      .forEach(value => row.append(element('td', value)));
    monthlyBody.append(row);
  }));
}
slider.addEventListener('input', update);
function csvCell(value) { return '"' + String(value).replaceAll('"','""') + '"'; }
document.getElementById('download').addEventListener('click', () => {
  const fields = Object.keys(summary[sites[0].id]);
  const rows = [['site','period','threshold_c',...fields]];
  sites.forEach(site => {
    rows.push([site.name,'whole snapshot',slider.value,...fields.map(key=>summary[site.id][key])]);
    Object.entries(months[site.id]).forEach(([month, result]) => rows.push([site.name,month,slider.value,...fields.map(key=>result[key])]));
  });
  const blob = new Blob([rows.map(row=>row.map(csvCell).join(',')).join('\n')], {type:'text/csv;charset=utf-8'});
  const url = URL.createObjectURL(blob), link = document.createElement('a');
  link.href = url; link.download = `heat-exposure-${slider.value}C.csv`; link.click();
  setTimeout(()=>URL.revokeObjectURL(url), 1000);
});
document.getElementById('period').textContent = `${data.manifest.start.slice(0,4)}-${data.manifest.start.slice(4,6)}-${data.manifest.start.slice(6,8)} through ${new Date(start+(data.values[sites[0].id].length-1)*3600000).toISOString().slice(0,10)} · UTC · NASA POWER T2M`;
const provenance = document.getElementById('sources');
data.manifest.sources.forEach(source => {
  const site = sites.find(site=>site.id===source.site), item = document.createElement('li');
  item.append(element('a', site.name, {href:source.url, rel:'noreferrer'}));
  item.append(document.createTextNode(` · ${site.latitude}, ${site.longitude} · retrieved ${source.retrieved_at}`));
  provenance.append(item);
});
update();
