import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import MarkdownIt from 'markdown-it';
import { renderMermaidSVGAsync } from 'beautiful-mermaid';

const root = fileURLToPath(new URL('../../', import.meta.url));
const index = 'docs/代码重构_文档索引.html';
const assets = 'docs/assets/refactor-docs';
const check = process.argv.includes('--check');
const md = new MarkdownIt({ html: false });
const esc = md.utils.escapeHtml;
const generated = new Map();
const read = file => fs.readFileSync(path.join(root, file), 'utf8').replace(/\r\n/g, '\n');
const html = file => file.replace(/\.md$/, '.html');
const url = (from, to) => path.posix.relative(path.posix.dirname(from), to).split('/').map(encodeURIComponent).join('/');
const link = (from, to, label) => `<a href="${url(from, to)}">${esc(label)}</a>`;

// 这两篇早期记录属于同一轮项目体检，但文件名早于系列命名约定。
const extra = [
  'docs/20261123_01_项目问题与缺失分析.md',
  'dev-notes/2026-11-24_01_项目体检问题修复第一批.md',
];
const files = [...new Set([...extra, ...['docs', 'dev-notes'].flatMap(dir =>
  fs.readdirSync(path.join(root, dir)).filter(name => name.includes('代码重构') && name.endsWith('.md'))
    .map(name => dir + '/' + name))])].sort();
const docs = new Map(files.map(file => {
  const tokens = md.parse(read(file), {});
  if (tokens[0]?.tag !== 'h1') throw Error(file + ' 缺少开头的一级标题');
  return [file, { file, title: tokens[1].content, tokens }];
}));
const notes = files.filter(f => f.startsWith('dev-notes/'));
const guides = files.filter(f => !notes.includes(f));

md.renderer.rules.link_open = (tokens, i, opts, env, self) => {
  const token = tokens[i];
  const href = token.attrGet('href');
  const [, pathname, suffix] = href.match(/^([^?#]*)([\s\S]*)$/);
  if (pathname && !/^(?:[\w+.-]+:|\/)/.test(pathname)) {
    const target = path.posix.join(path.posix.dirname(env.file), decodeURIComponent(pathname));
    if (docs.has(target)) token.attrSet('href', url(env.file, html(target)) + suffix);
  }
  return self.renderToken(tokens, i, opts);
};
const fence = md.renderer.rules.fence;
md.renderer.rules.fence = (tokens, i, ...rest) => tokens[i].meta?.figure ?? fence(tokens, i, ...rest);
const image = md.renderer.rules.image;
md.renderer.rules.image = (tokens, i, opts, env, self) => {
  const src = tokens[i].attrGet('src');
  if (!src.startsWith('data:')) {
    const pathname = decodeURIComponent(src.split(/[?#]/)[0]);
    if (/^(?:[\w+.-]+:|\/)/.test(pathname) ||
        !fs.statSync(path.resolve(root, path.dirname(env.file), pathname), { throwIfNoEntry: false })?.isFile()) {
      throw Error('离线图片需要有效的本地相对路径：' + src);
    }
  }
  return image(tokens, i, opts, env, self);
};
md.renderer.rules.table_open = () => '<div class="table-scroll"><table>\n';
md.renderer.rules.table_close = () => '</table></div>\n';

function shell(file, title, content) {
  return `<!doctype html>
<!-- 由 scripts/docs-html/export.mjs 生成，请编辑 Markdown 原稿。 -->
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(title)} · ADS 文档</title><link rel="stylesheet" href="${url(file, assets + '/reader.css')}"></head>
<body><nav class="bar" aria-label="主导航"><b>ADS · 开发文档</b>${link(file, index, '系列索引')}</nav>
<main>${content}</main></body></html>\n`;
}

async function renderArticle({ file, title, tokens }) {
  const headings = [];
  let section = title, figures = 0;
  for (const [i, t] of tokens.entries()) {
    if (t.type === 'heading_open' && t.tag === 'h2') {
      section = tokens[i + 1].content;
      const id = 'section-' + (headings.length + 1);
      t.attrSet('id', id);
      headings.push(`<li><a href="#${id}">${esc(section)}</a></li>`);
    }
    if (t.type !== 'fence' || t.info.trim() !== 'mermaid') continue;
    const label = (t.content.trimStart().startsWith('sequenceDiagram') ? '时序图' : '流程图') + '：' + section;
    const name = path.posix.basename(file, '.md');
    const target = `${assets}/${name}_图${++figures}.svg`;
    const svg = await renderMermaidSVGAsync(t.content, {
      font: 'Microsoft YaHei', bg: '#ffffff', fg: '#1d3839', accent: '#12645e', border: '#608781',
    });
    // 渲染器默认向 Google Fonts 导入字体，离线副本只使用系统字体。
    generated.set(target, svg.replace(/^\s*@import url\([^\n]*\);/gm, '').trimEnd() + '\n');
    const src = url(file, target);
    t.meta = { figure: `<figure><a href="${src}"><img src="${src}" alt="${esc(label)}"></a><figcaption>${esc(label)} · <a href="${src}">查看原图</a></figcaption></figure>\n` };
  }
  const siblings = notes.includes(file) ? notes : guides;
  const pos = siblings.indexOf(file);
  const adjacent = [[siblings[pos - 1], '上一篇'], [siblings[pos + 1], '下一篇']]
    .filter(([target]) => target).map(([target, prefix]) => link(file, html(target), prefix + '：' + docs.get(target).title));
  const toc = headings.length ? `<details><summary>本页目录（${headings.length} 节）</summary><ol>${headings.join('')}</ol></details>` : '';
  const body = md.renderer.render(tokens.slice(3), md.options, { file });
  return shell(file, title, `<header><p class="meta">${notes.includes(file) ? '开发笔记 · DevNote' : '项目文档'} · ${link(file, file, 'Markdown 原稿')}</p>
<h1>${esc(title)}</h1></header>${toc}
<article>${body}</article><nav class="adjacent" aria-label="相邻文档">${adjacent.join('\n')}</nav>`);
}

function renderIndex() {
  const item = f => `<li>${link(index, html(f), docs.get(f).title)}</li>`;
  const groups = new Map();
  for (const f of [...notes].reverse()) {
    const date = path.posix.basename(f).split('_')[0];
    if (!groups.has(date)) groups.set(date, []);
    groups.get(date).push(f);
  }
  const latest = notes.at(-1);
  return shell(index, '代码重构 · 文档索引', `<header><p class="meta">AI 自动开发系统 / 工程记录</p>
<h1>代码重构 · 文档索引</h1><p>从项目体检、重构方案到每次改动的测试和截图。共 ${guides.length} 篇项目文档、${notes.length} 篇开发笔记。</p>
<p class="latest">${link(index, html(latest), '最近更新 → ' + docs.get(latest).title)}</p></header>
<h2>项目文档</h2><ul class="catalog">${guides.map(item).join('\n')}</ul>
<h2>开发笔记</h2>${[...groups].map(([date, entries]) => `<section><h3>${esc(date)}</h3><ul class="catalog">${entries.map(item).join('\n')}</ul></section>`).join('\n')}`);
}

for (const doc of docs.values()) {
  try { generated.set(html(doc.file), await renderArticle(doc)); }
  catch (cause) { throw new Error('导出失败：' + doc.file, { cause }); }
}
generated.set(index, renderIndex());
let changed = 0;
for (const [file, content] of generated) {
  const dest = path.join(root, file);
  if (fs.existsSync(dest) && read(file) === content) continue;
  changed++;
  if (check) console.error('缺失或需要更新：' + file);
  else {
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    fs.writeFileSync(dest, content);
  }
}
console.log(`${docs.size} 篇文档、${[...generated.keys()].filter(f => f.endsWith('.svg')).length} 张图、1 个索引；${check ? '差异' : '更新'} ${changed} 个文件。`);
if (check && changed) process.exitCode = 1;
