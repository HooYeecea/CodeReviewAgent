"""Execute generated tooltip/status JavaScript with hostile record strings."""
import json
import re
import shutil
import subprocess

import pytest

from gai.usage.report import render_usage_report_html
from gai.history.report import render_history_report_html


def test_generated_report_html_sinks_escape_record_strings():
    if not shutil.which("node"):
        pytest.skip("Node unavailable")
    usage = render_usage_report_html({})
    history = render_history_report_html({})
    def function(html, name):
        match = re.search(r"function " + name + r"\([^\n]*\) \{[\s\S]*?^\}", html, re.MULTILINE)
        assert match, name
        return match.group()
    status = re.search(r"const status = r.ok === false[\s\S]*?;", usage).group()
    script = """
const assert=require('node:assert/strict'),vm=require('node:vm');
const attack='<img src=x onerror=alert(1)> & "';
let opts;
const chart={setOption(v){opts=v;}};
const ctx=vm.createContext({
 document:{getElementById(){return {};},documentElement:{getAttribute(){return 'light';}}},
 echarts:{init(){return chart;},graphic:{LinearGradient:function(){}}},
 cssVar:(name,fallback)=>fallback,themeColors:()=>[],pieData:()=>[],baseText:()=>({}),
 I18N:{tokens:'tokens'},makeChart:()=>chart,ink:()=>'',muted:()=>'',charts:[],
 A:{heatmap_repo:{repos:[attack],commands:[attack],data:[[0,0,1]]}},attack
});
const safe=value=>{assert(!value.includes('<img'));assert(value.includes('&lt;img'));};
"""
    for name in ("esc", "initPie", "initBar", "initHeatmapGeneric"):
        script += "vm.runInContext(" + json.dumps(function(usage, name)) + ",ctx);\n"
    script += """
vm.runInContext("initPie('chart',[])",ctx);safe(opts.tooltip.formatter({name:attack,value:2,percent:1}));
vm.runInContext("initBar('chart',{labels:[],tokens:[]})",ctx);safe(opts.tooltip.formatter([{name:attack,value:2}]));
vm.runInContext("initHeatmapGeneric('chart','repo',[attack],[attack],[[0,0,1]])",ctx);
safe(opts.tooltip.formatter({value:[0,0,1]}));
"""
    script += "vm.runInContext(" + json.dumps(function(history, "initHeatmapRepo")) + ",ctx);\n"
    script += "vm.runInContext('initHeatmapRepo()',ctx);safe(opts.tooltip.formatter({data:[0,0,1]}));\n"
    script += "ctx.r={ok:false,error_kind:attack};safe(vm.runInContext(" + json.dumps(status + "\nstatus") + ",ctx));"
    subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
