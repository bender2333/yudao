# 实验（11-09）：在本目录跑，读 candidates.txt（同目录下 candidates-ce9c688-02d1d59.txt 改名即可），参数是候选至少出现几次
# 用自动推断的候选（不靠人登记）接 r2 模型对 48e2158 对不上的原句；每句试候选的组合，换完原文里真有才算接上
import os,sys,subprocess,tempfile,shutil,json,re,itertools
R="/home/claude/yudao"; MIN=int(sys.argv[1]) if len(sys.argv)>1 else 3
cands=[]
for l in open("cands.txt").read().splitlines()[1:]:
    m=re.match(r"\s*(\d+)\s+(.+?) → (.+)$",l)
    if m and int(m.group(1))>=MIN: cands.append((m.group(2),m.group(3)))
tmp=tempfile.mkdtemp()
subprocess.run(f"git -C {R} archive ad36dd8 tools/yudao-ontology | tar -x -C {tmp}",shell=True,check=True)
tools=os.path.join(tmp,"tools/yudao-ontology")
for f in ["quotecheck.py","names.py"]: shutil.copy(f"{R}/tools/yudao-ontology/{f}",tools)
env={**os.environ,"YUDAO_REPO":R,"YUDAO_COMMIT":"48e2158"}
subprocess.run([sys.executable,"quotecheck.py","48e2158"],cwd=tools,env=env,capture_output=True)
rows=json.load(open(os.path.join(tools,"reports/quotecheck.json")))["48e2158"]
sys.path.insert(0,tools); os.environ.update(env); import quotecheck
miss=[r for r in rows if r["found"] is False]
def ok(q,text): return all(quotecheck.norm(x) in text for p in q.split("……") for x in p.split("；") if quotecheck.norm(x))
healed=[];used=set()
for r in miss:
    text="".join(quotecheck.norm(quotecheck.html_text(t) if d.endswith(".html") else t) for d in r["doc"].split("、") for t in [quotecheck.show("48e2158",d)])
    rel=[c for c in cands if c[0] in r["quote"]]
    done=False
    for k in range(1,min(4,len(rel))+1):
        for combo in itertools.combinations(rel,k):
            if len({c[0] for c in combo})<k: continue
            q=r["quote"]
            for o,n in sorted(combo,key=lambda c:-len(c[0])): q=q.replace(o,n)
            if ok(q,text): healed.append(r); used.update(combo); done=True; break
        if done: break
print(f"候选（出现≥{MIN} 次）{len(cands)} 对；对不上 {len(miss)} 条，自动接上 {len(healed)} 条，剩 {len(miss)-len(healed)} 条（{len({r['quote'] for r in miss if r not in healed})} 句）")
print("真用上的候选:",sorted(used))
