# 实验（11-09）：在仓库根目录跑 python3 tools/yudao-ontology/experiments/rename_candidates.py ce9c688^ 02d1d59 <文档…> > candidates.txt
# 从 git diff 自动推断改名候选：成对删/加的行，按字比对，数「旧片段 → 新片段」出现几次
import re,subprocess,sys,difflib,collections
A,B=sys.argv[1],sys.argv[2]
paths=sys.argv[3:]
def git(*a): return subprocess.run(["git",*a],capture_output=True,text=True).stdout
def clean(t): return re.sub(r"\s+"," ",re.sub(r"<[^>]+>","",t)).strip()
pairs=collections.Counter(); lines=0
for p in paths:
    d=git("diff","-U0","--no-color",A,B,"--",p)
    for hunk in re.split(r"^@@.*$",d,flags=re.M)[1:]:
        rem=[clean(l[1:]) for l in hunk.splitlines() if l.startswith("-") and not l.startswith("---")]
        add=[clean(l[1:]) for l in hunk.splitlines() if l.startswith("+") and not l.startswith("+++")]
        used=set()
        for r in rem:
            best=max(((difflib.SequenceMatcher(None,r,x).ratio(),i) for i,x in enumerate(add) if i not in used),default=(0,None))
            if best[0]<0.6: continue
            used.add(best[1]); x=add[best[1]]; lines+=1
            sm=difflib.SequenceMatcher(None,r,x,autojunk=False)
            for op,i1,i2,j1,j2 in sm.get_opcodes():
                if op=="replace" and i2-i1<=12 and j2-j1<=14: pairs[(r[i1:i2],x[j1:j2])]+=1
print("成对的改动行",lines,"不同的「旧→新」片段",len(pairs))
for (o,n),c in pairs.most_common(int(__import__('os').environ.get("TOP","25"))): print(f"{c:4d}  {o} → {n}")
