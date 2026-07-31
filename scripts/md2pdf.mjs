/* Markdown -> styled HTML -> PDF via headless Chromium.
   No pandoc/weasyprint on this machine and pip is PEP-668 locked, so this uses
   what is already here: marked (bundled with nothing, so hand-rolled) + Playwright's
   print pipeline. The renderer below covers only the subset of markdown this
   document actually uses, which is checked by rendering and reading the result. */
import { chromium } from '/opt/homebrew/lib/node_modules/playwright/index.mjs';
import fs from 'fs';

const src = process.argv[2], out = process.argv[3];
const md = fs.readFileSync(src, 'utf8');

const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const inline = (s) =>
  esc(s)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2">$1</a>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*]+)\*/g, '$1<em>$2</em>');

const lines = md.split('\n');

/* Everything that can contain inline markup is buffered and only rendered when
   its block ends. Markdown joins soft-wrapped lines, so any inline pass that
   runs per-line will break on emphasis that straddles a wrap — which is exactly
   what leaked asterisks into the page in the first two attempts, first in
   paragraphs and then, after fixing those, in blockquotes and list items.
   Buffer every block type or the bug just moves. */
let html = '', inTable = false, inList = false, inQuote = false;
let para = [], quote = [], li = null;

const flushPara = () => { if (para.length) { html += `<p>${inline(para.join(' '))}</p>`; para = []; } };
const flushLi = () => {
  if (li !== null) {
    const body = li.join(' ');
    const box = /^\[ \]\s*/.test(body);
    html += `<li>${box ? '<span class="box"></span>' : ''}${inline(body.replace(/^\[ \]\s*/, ''))}</li>`;
    li = null;
  }
};
const closeList = () => { flushLi(); if (inList) { html += '</ul>'; inList = false; } };
const closeTable = () => { if (inTable) { html += '</tbody></table>'; inTable = false; } };
const closeQuote = () => {
  if (inQuote) { html += `<blockquote><p>${inline(quote.join(' '))}</p></blockquote>`; quote = []; inQuote = false; }
};
const closeAll = () => { flushPara(); closeList(); closeTable(); closeQuote(); };

for (const l of lines) {
  if (/^\s*$/.test(l)) { closeAll(); continue; }
  if (/^---+$/.test(l)) { closeAll(); html += '<hr>'; continue; }

  const h = l.match(/^(#{1,4})\s+(.*)$/);
  if (h) { closeAll(); html += `<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`; continue; }

  if (/^\|/.test(l)) {
    flushPara(); closeList(); closeQuote();
    if (/^\|[\s:|-]+\|$/.test(l)) continue;                     // separator row
    const cells = l.split('|').slice(1, -1).map((c) => c.trim());
    if (!inTable) { html += '<table><thead><tr>' + cells.map((c) => `<th>${inline(c)}</th>`).join('') + '</tr></thead><tbody>'; inTable = true; }
    else html += '<tr>' + cells.map((c) => `<td>${inline(c)}</td>`).join('') + '</tr>';
    continue;
  }
  closeTable();

  if (/^>\s?/.test(l)) { flushPara(); closeList(); inQuote = true; quote.push(l.replace(/^>\s?/, '').trim()); continue; }
  if (inQuote) { quote.push(l.trim()); continue; }              // lazy continuation

  const bullet = l.match(/^\s*[-*]\s+(.*)$/);
  const numbered = l.match(/^\s*(\d+)\.\s+(.*)$/);
  if (bullet || numbered) {
    flushPara(); flushLi();
    if (!inList) { html += '<ul>'; inList = true; }
    li = [numbered ? `**${numbered[1]}.** ${numbered[2]}` : bullet[1]];
    continue;
  }
  if (inList) { li ? li.push(l.trim()) : para.push(l.trim()); continue; }   // lazy continuation

  para.push(l.trim());
}
closeAll();

const page = `<!doctype html><html><head><meta charset="utf-8"><style>
@page { size: A4; margin: 20mm 18mm; }
body { font: 10.5pt/1.55 -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; color: #1a1d1f; }
h1 { font-size: 22pt; line-height: 1.15; margin: 0 0 6pt; letter-spacing: -0.02em; }
h2 { font-size: 14pt; margin: 20pt 0 6pt; letter-spacing: -0.015em; border-bottom: 1px solid #dcdfe1; padding-bottom: 4pt; break-after: avoid; }
h3 { font-size: 11.5pt; margin: 14pt 0 4pt; break-after: avoid; }
h4 { font-size: 10.5pt; margin: 10pt 0 3pt; break-after: avoid; }
p { margin: 0 0 7pt; }
ul { margin: 0 0 8pt; padding-left: 16pt; }
li { margin: 0 0 3pt; }
code { font: 9.5pt ui-monospace, SFMono-Regular, Menlo, monospace; background: #f2f3f4; padding: 1px 3px; border-radius: 3px; }
a { color: #0b6b52; text-decoration: none; border-bottom: 1px solid #b9d9cd; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0 12pt; font-size: 9.5pt; break-inside: avoid; }
th { text-align: left; background: #f2f3f4; font-weight: 600; }
th, td { border: 1px solid #dcdfe1; padding: 4pt 6pt; vertical-align: top; }
blockquote { margin: 8pt 0; padding: 7pt 12pt; background: #f4f7f6; border-left: 3px solid #0b6b52; }
blockquote p { margin: 0; }
hr { border: 0; border-top: 1px solid #e4e6e8; margin: 14pt 0; }
.box { display: inline-block; width: 8pt; height: 8pt; border: 1px solid #8d9296; border-radius: 2px; margin-right: 5pt; vertical-align: -1px; }
strong { font-weight: 650; }
</style></head><body>${html}</body></html>`;

fs.writeFileSync(out.replace(/\.pdf$/, '.debug.html'), page);

const b = await chromium.launch();
const p = await b.newPage();
await p.setContent(page, { waitUntil: 'load' });
await p.pdf({ path: out, format: 'A4', printBackground: true,
  displayHeaderFooter: true, headerTemplate: '<div></div>',
  footerTemplate: '<div style="font:8pt sans-serif;color:#8d9296;width:100%;padding:0 18mm;display:flex;justify-content:space-between"><span>Solace — Product Strategy, July 2026</span><span class="pageNumber"></span></div>',
  margin: { top: '20mm', bottom: '16mm', left: '18mm', right: '18mm' } });
await b.close();
console.log('wrote', out, (fs.statSync(out).size / 1024).toFixed(0) + 'KB');
