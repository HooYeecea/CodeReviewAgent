"""Read-only archive queries, conservative comparison and a local browser."""
from datetime import datetime
import json
import re
import webbrowser

import typer

from gai.cli_common import app, console, err_console
from gai.common.git import ensure_repo
from gai.common.i18n import H
from gai.review.archive import atomic_text, ReviewCollection
from gai.review.names import report_stem, valid_component

reviews_app = typer.Typer(invoke_without_command=True, help=H("Browse and compare saved reviews.", "浏览、筛选及对比已保存审查。"))
app.add_typer(reviews_app, name="reviews")


def records(root=None):
    root = ensure_repo(root).resolve()
    folder = root / ".gai" / "reviews"
    if folder.is_symlink() or not folder.resolve().is_relative_to(root):
        raise RuntimeError("Unsafe review directory")
    found, invalid = [], 0
    for index in sorted(folder.glob("*/index.json")):
        if index.is_symlink() or index.parent.is_symlink() or not index.resolve().is_relative_to(folder.resolve()):
            invalid += 1
            continue
        try:
            data = json.loads(index.read_text(encoding="utf-8"))
            items = data["reviews"]
            if not isinstance(items, list):
                raise ValueError("Invalid archive")
            for item in items:
                if (not isinstance(item, dict) or not re.fullmatch("[0-9a-f]{32}", str(item.get("id", "")))
                        or not isinstance(item.get("snapshot"), dict) or not isinstance(item.get("result"), dict)
                        or not valid_component(report_stem(item))
                        or any(item.get(k) is not None and not isinstance(item[k], str)
                               for k in ("reviewed_at", "saved_at", "title", "commit"))
                        or not isinstance(item["snapshot"].get("ref", ""), str)
                        or not isinstance(item["result"].get("scope", {}), dict)
                        or not isinstance(item["result"].get("coverage", {}), dict)):
                    raise ValueError("Invalid review record")
                from gai.review.engine import parse_review_response
                if not parse_review_response(json.dumps(item["result"])).parsed_ok:
                    raise ValueError("Invalid review result")
            for item in items:
                found.append({**item, "report_path": str(index.parent / (report_stem(item) + ".md"))})
        except (OSError, ValueError, KeyError, TypeError):
            invalid += 1
    if invalid:
        err_console.print(f"跳过无法读取的报告目录 / Skipped unreadable archives: {invalid}", markup=False)
    return sorted(found, key=lambda r: r.get("reviewed_at") or r.get("saved_at") or "")


def select(items, identity):
    matches = [r for r in items if r["id"].startswith(identity)]
    if len(matches) != 1:
        raise RuntimeError("审查 ID 不存在或不唯一 / Review ID missing or ambiguous")
    return matches[0]


def compare(old, new):
    def keyed(record):
        return {(item["file"], " ".join(item["issue"].casefold().split())): item
                for item in record["result"]["review"]}
    before, after = keyed(old), keyed(new)
    return {"old_id": old["id"], "new_id": new["id"],
            "new": [after[k] for k in sorted(after.keys() - before.keys())],
            "still_reported": [after[k] for k in sorted(after.keys() & before.keys())],
            "pending_resolution": [before[k] for k in sorted(before.keys() - after.keys())],
            "note": "未再报告不等于已修复；按文件与问题文本匹配，文本改写可能算新增。 / Missing findings need confirmation; matching uses file and issue text."}


def filter_records(items, query="", branch="", commit="", severity="", since="", until=""):
    for date in (since, until):
        if date:
            datetime.strptime(date, "%Y-%m-%d")
    if since and until and since > until:
        raise ValueError("--since must not be later than --until")
    if severity and severity not in {"critical", "warning", "info"}:
        raise ValueError("severity must be critical, warning or info")
    return [r for r in items if
            (not query or query.casefold() in json.dumps(r, ensure_ascii=False).casefold())
            and (not branch or r["snapshot"].get("ref", "").removeprefix("refs/heads/") == branch)
            and (not commit or (r.get("commit") or r.get("result", {}).get("scope", {}).get("head", "")).startswith(commit))
            and (not severity or any(i["severity"] == severity for i in r["result"]["review"]))
            and (not since or (r.get("reviewed_at") or r.get("saved_at", ""))[:10] >= since)
            and (not until or (r.get("reviewed_at") or r.get("saved_at", ""))[:10] <= until)]


def browser(items):
    folder = ReviewCollection("reviews", True).prepare_parent()
    payload = json.dumps(items, ensure_ascii=True).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    page = r"""<!doctype html><html lang="zh"><meta charset="utf-8"><title>审查报告 · gai</title>
<style>body{font:16px system-ui;background:#f5f7fa;color:#172033;max-width:1100px;margin:36px auto;padding:20px}
input,select,button{padding:10px;margin:4px;border:1px solid #ccd3df;border-radius:6px}
table{width:100%;border-collapse:collapse;background:white}td,th{padding:12px;text-align:left;border-bottom:1px solid #eee}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:white;padding:20px}small{color:#546176}</style>
<h1>审查报告 / Review library</h1><p>搜索、查看历史审查，并对比两次结果。</p>
<input id="q" placeholder="主题、文件、提交或问题"><select id="branch"><option value="">全部分支</option></select>
<select id="severity"><option value="">全部严重度</option><option>critical</option><option>warning</option><option>info</option></select>
<label>从 <input id="since" type="date"></label><label>到 <input id="until" type="date"></label>
<p><select id="old"></select> → <select id="new"></select><button id="compare">对比 / Compare</button></p>
<small>未再报告的问题仅标记为“待确认解决”；文本改写或审查范围不同可能影响对比。</small>
<table><thead><tr><th>时间</th><th>主题</th><th>分支</th><th>结果 / 覆盖</th><th>操作</th></tr></thead><tbody id="rows"></tbody></table>
<pre id="detail" aria-live="polite">选择一条记录查看详情。</pre>
<script type="application/json" id="data">PAYLOAD</script>
<script>
const data=JSON.parse(document.getElementById('data').textContent), $=id=>document.getElementById(id);
for(const branch of [...new Set(data.map(r=>r.snapshot.ref||''))]){
 const o=document.createElement('option');o.value=branch;o.textContent=branch;$('branch').append(o);
}
for(const id of ['old','new']) for(const r of data){
 const o=document.createElement('option');o.value=r.id;o.textContent=(r.title||r.id)+' · '+(r.reviewed_at||r.saved_at);$(id).append(o);
}
if(data.length)$('new').value=data[data.length-1].id;
const labels={passed:'未发现问题',issues:'发现问题',incomplete:'覆盖不完整',failed:'审查失败',complete:'完整',unknown:'未记录'};
const finding=i=>'['+i.severity+'] '+i.file+(i.line?':'+i.line:'')+'\n'+i.issue+'\n建议：'+(i.suggestion||'—');
function show(value){
 if(value.result){
 const r=value,c=r.result.coverage||{};
 $('detail').textContent=[r.title||'审查报告','时间：'+(r.reviewed_at||r.saved_at||'—'),
 '分支：'+(r.snapshot.ref||'—'),'模型：'+(r.model||'—'),
 '结果：'+(labels[r.result.status]||r.result.status),'覆盖：'+(labels[c.state]||'未记录'),
 '提交：'+(r.commit||r.result.scope?.head||'未关联'),'',
 r.result.summary||'无摘要','',
 ...r.result.review.map(finding),'',
 '忽略文件：'+(c.ignored_files||[]).join(', '),
 '部分审查：'+(c.partially_reviewed_files||[]).join(', '),
 '尚未审查：'+(c.unreviewed_files||[]).join(', ')].join('\n');
 }else $('detail').textContent=Object.entries(value).map(([label,items])=>
 label+'（'+items.length+'）\n'+(items.map(finding).join('\n\n')||'无')).join('\n\n');
}
function render(){
 $('rows').replaceChildren();
 for(const r of data){
 const date=(r.reviewed_at||r.saved_at||'').slice(0,10);
 if($('q').value&&!JSON.stringify(r).toLowerCase().includes($('q').value.toLowerCase()))continue;
 if($('branch').value&&r.snapshot.ref!==$('branch').value)continue;
 if($('severity').value&&!r.result.review.some(i=>i.severity===$('severity').value))continue;
 if($('since').value&&date<$('since').value||$('until').value&&date>$('until').value)continue;
 const tr=document.createElement('tr');
 for(const text of [date,r.title||r.id,r.snapshot.ref||'',(labels[r.result.status]||r.result.status)+' / '+(labels[r.result.coverage?.state]||'未记录')]){
 const td=document.createElement('td');td.textContent=text;tr.append(td);}
 const td=document.createElement('td'), b=document.createElement('button');b.textContent='查看';b.onclick=()=>show(r);td.append(b);tr.append(td);$('rows').append(tr);
 }}
for(const id of ['q','branch','severity','since','until'])$(id).oninput=render;
$('compare').onclick=()=>{
 const old=data.find(r=>r.id===$('old').value), newer=data.find(r=>r.id===$('new').value);if(!old||!newer)return;
 const key=i=>JSON.stringify([i.file,i.issue.toLowerCase().trim().replace(/\s+/g,' ')]);
 const a=new Map(old.result.review.map(i=>[key(i),i])),b=new Map(newer.result.review.map(i=>[key(i),i]));
 show({'新增':[...b].filter(([k])=>!a.has(k)).map(([,v])=>v),
 '仍然报告':[...b].filter(([k])=>a.has(k)).map(([,v])=>v),
 '待确认解决':[...a].filter(([k])=>!b.has(k)).map(([,v])=>v)});
};render();
</script></html>""".replace("PAYLOAD", payload)
    path = folder / "browser.html"
    atomic_text(path, page)
    return path


def fail(exc):
    err_console.print(str(exc), markup=False)
    raise typer.Exit(1) from exc


@reviews_app.callback()
def list_reviews(ctx: typer.Context,
                 query: str = typer.Option("", "--query", help=H("Search titles, files and findings.", "搜索主题、文件和问题。")),
                 branch: str = typer.Option("", "--branch", help=H("Exact branch name.", "按完整分支名筛选。")),
                 commit: str = typer.Option("", "--commit", help=H("Commit SHA or prefix.", "提交哈希或前缀。")),
                 severity: str = typer.Option("", "--severity", help=H("critical, warning or info.", "按 critical、warning、info 筛选。")),
                 since: str = typer.Option("", "--since", help=H("First recorded date, YYYY-MM-DD.", "开始日期，YYYY-MM-DD。")),
                 until: str = typer.Option("", "--until", help=H("Last recorded date, YYYY-MM-DD.", "结束日期，YYYY-MM-DD。")),
                 as_json: bool = typer.Option(False, "--json", help=H("Print JSON.", "输出 JSON。")),
                 html_report: bool = typer.Option(False, "--html", help=H("Generate the local browser page.", "生成本地报告浏览页。")),
                 open_browser: bool = typer.Option(False, "--open", help=H("Generate and open the local page.", "生成并打开本地浏览页。")),
                 cn: bool = typer.Option(False, "--cn")):
    if ctx.invoked_subcommand:
        return
    try:
        items = filter_records(records(), query, branch, commit, severity, since, until)
        if html_report or open_browser:
            path = browser(items)
            console.print(str(path), markup=False)
            if open_browser:
                webbrowser.open(path.as_uri())
        elif as_json:
            console.print_json(data=items)
        else:
            for record in items:
                console.print(f"{record['id']}  {record.get('reviewed_at') or record.get('saved_at')}  "
                              f"{record.get('title', '')}  {record['result'].get('status', 'unknown')}", markup=False)
            console.print(f"审查记录 / Reviews: {len(items)}")
    except (RuntimeError, OSError, ValueError) as exc:
        fail(exc)


@reviews_app.command("show", help=H("Show one review by ID or unique ID prefix.", "按 ID 或唯一前缀查看审查。"))
def show_review(identity: str, cn: bool = typer.Option(False, "--cn")):
    try:
        console.print_json(data=select(records(), identity))
    except (RuntimeError, OSError, ValueError) as exc:
        fail(exc)


@reviews_app.command("compare", help=H("Compare two reviews without claiming missing findings are fixed.", "对比两次审查，未再报告的问题标记为待确认解决。"))
def compare_reviews(old: str, new: str, cn: bool = typer.Option(False, "--cn")):
    try:
        items = records()
        console.print_json(data=compare(select(items, old), select(items, new)))
    except (RuntimeError, OSError, ValueError) as exc:
        fail(exc)
