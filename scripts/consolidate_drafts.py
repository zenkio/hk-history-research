"""Consolidate the AI drafts of a multi-AI page without writing anything from memory.

Owner rule 2026-10-30: the consolidated version must contain ALL points of ALL drafts, built from the drafts'
own text, never from the writer's memory, and be more enriched than the best single draft (a summary is wrong).

For each of the seven sections: the base draft (Nemotron 3 Ultra) is kept sentence for sentence, then every
sentence of every other draft that adds something is appended under "More from the other drafts" with the model
named. A sentence adds something when it holds a number the base lacks or fewer than 65% of its words appear in
the base. Dates and numbers that belong to a fact record get a hover marker. `check()` fails when the result
drops a base sentence, is shorter than the base, or loses a number found in any draft.

Usage (in the data checkout): python3 scripts/consolidate_drafts.py content/05_Multi_AI/<page>.md data/consolidated_facts/<page>.json
"""
import json,re,sys
CANON=["What happened","Background","Hong Kong at this time","China at this time","Britain at this time","Consequences","Uncertain or disputed points"]
STOP=set("the and for that with from this were was are has had have its his her their they them not but who which when where than then also into over after before about been being such more most some other only both between under during while there these those would could should may might can will one two".split())
def callouts(s):
    out={}; cur=None
    for line in s.split("\n"):
        m=re.match(r"> \[!info\]- (.+?)(?::| \(|$)",line)
        if m and line.startswith("> [!info]-"):
            cur=m.group(1).strip(); out[cur]=[]; continue
        if cur is not None:
            if line.startswith(">"): out[cur].append(line[1:].lstrip(" ") if line.startswith("> ") else "")
            else: cur=None
    return out
def canon_idx(title,num):
    t=title.lower()
    if "uncertain" in t or "disputed" in t: return 6
    if "consequence" in t: return 5
    if "hong kong" in t: return 2
    if "china and britain" in t: return 3
    if t.startswith("china") or "china at" in t: return 3
    if "britain" in t: return 4
    if "background" in t: return 1
    if "happened" in t: return 0
    return None if num is None else int(num)-1
def sections(lines):
    secs={}; cur=None
    for l in lines:
        if l.startswith("_Model") or l.startswith("_Author"): continue
        m=re.match(r"\*\*(\d)\.\s*([^*]+?)\*\*\s*(.*)$",l) or re.match(r"\*\*()([^*]+?)\.\*\*\s*(.*)$",l)
        if m and (m.group(1) or l.startswith("**") ):
            idx=canon_idx(m.group(2),m.group(1) or None)
            if idx is not None:
                cur=idx; secs.setdefault(cur,[]); 
                if m.group(3).strip(): secs[cur].append(m.group(3))
                continue
        if cur is not None and l.strip(): secs[cur].append(l)
    return secs
def clean(l):
    l=re.sub(r"^\s*(?:[*\-•]|\d+\.)\s+","",l)
    l=l.replace("**","").replace("*","").replace("_","")
    return re.sub(r"\s+"," ",l).strip()
def sentences(lines):
    out=[]
    for l in lines:
        l=clean(l)
        if not l: continue
        parts=re.split(r"(?<=[.!?])\s+(?=[A-Z0-9“\"(])",l)
        out+= [p.strip() for p in parts if len(p.strip())>3]
    return out
def toks(s): return {w for w in re.findall(r"[a-z]{3,}|\d[\d,.]*\d|\d",s.lower()) if w not in STOP}
def nums(s): return {w.strip(",.") for w in re.findall(r"\d[\d,.]*\d",s)}
def short(name):
    return "Claude" if name.startswith("Claude") else name
def build(page_md):
    c=callouts(page_md)
    base_name=[k for k in c if k.startswith("Nemotron")][0]
    S={k:sections(v) for k,v in c.items()}
    base=S[base_name]
    base_sents={i:sentences(base.get(i,[])) for i in range(7)}
    allbase=" ".join(" ".join(v) for v in base_sents.values())
    bt=toks(allbase); bn=nums(allbase)
    res=[]; stats={"added":0,"seen":0}
    for i in range(7):
        head=f"**{i+1}. {CANON[i]}**"
        res.append(head+" "+" ".join(base_sents[i]))
        added=[]; addtoks=[]
        for k in c:
            if k==base_name: continue
            for snt in sentences(S[k].get(i,[])):
                stats["seen"]+=1
                t=toks(snt)
                if len(t)<3: continue
                cont=len(t&bt)/len(t)
                newnum=bool(nums(snt)-bn)
                novel=newnum or cont<0.65
                if not novel: continue
                if any(len(t&a)/max(1,len(t|a))>0.6 for a in addtoks): continue
                added.append(f"{snt} ({short(k)})"); addtoks.append(t); stats["added"]+=1
        if added: res.append("**More from the other drafts.** "+" ".join(added))
    return res,stats

MONTHS="January|February|March|April|May|June|July|August|September|October|November|December"
UNITS="million|chests|chest|sacks|tonnes|taels|warships|troops|years|days|rounds|sq|square|per|km|miles"


def mark_facts(paragraphs, facts):
    """Wrap the date / number of each fact record in {{id|text}} where the surrounding sentence is about that
    fact (at least 35% of the fact's words, and two of them, appear in the sentence). Returns the paragraphs and
    the ids placed. A fact whose sentence is not found stays unmarked in the text (it is still in the list)."""
    out = list(paragraphs)
    placed = set()
    for fact in facts:
        wanted = [n for n in re.findall(r"\d[\d,.]*\d|\d", fact["text"]) if len(n.strip(",.")) >= 2]
        wanted.sort(key=len, reverse=True)  # the year or the large figure first
        words = {w for w in toks(fact["text"]) if not w[0].isdigit()}
        if not wanted or len(words) < 2:
            continue
        best = None
        for pi, para in enumerate(out):
            for piece_start, piece in _plain_pieces(para):
                for seg in re.finditer(r"[^.!?]+(?:\.\d[^.!?]*)*[.!?]?", piece):
                    shared = words & toks(seg.group(0))
                    score = len(shared) / len(words)
                    if len(shared) < 2 or score < 0.35 or (best and score <= best[0]):
                        continue
                    for num in wanted:
                        m = re.search(r"(?:\b\d{1,2} (?:%s) )?(?:\b(?:%s) \d{1,2},? )?(?<![\w.,])%s(?:[–-]\d[\d,.]*)?(?: (?:%s)\b)?"
                                      % (MONTHS, MONTHS, re.escape(num), UNITS), seg.group(0))
                        if m and m.group(0).strip():
                            best = (score, pi, piece_start + seg.start() + m.start(), piece_start + seg.start() + m.end())
                            break
        if best:
            _, pi, start, end = best
            para = out[pi]
            out[pi] = para[:start] + "{{%s|%s}}" % (fact["id"], para[start:end].strip().replace("|", "/")) + para[end:]
            placed.add(fact["id"])
    return out, placed


def _plain_pieces(para):
    """(offset, text) of the parts of a paragraph that are outside {{...}} markers."""
    pos = 0
    for piece in re.split(r"(\{\{[\w-]+\|.*?\}\})", para):
        if piece and not piece.startswith("{{"):
            yield pos, piece
        pos += len(piece)


def check(page_md, paragraphs):
    """Problems found in the consolidation; empty means the three automated checks pass."""
    plain = re.sub(r"\{\{[\w-]+\|(.*?)\}\}", r"\1", " ".join(paragraphs))
    plain = re.sub(r"\s+", " ", plain)
    c = callouts(page_md)
    base_name = [k for k in c if k.startswith("Nemotron")][0]
    base = sections(c[base_name])
    problems = []
    base_words = 0
    for i in range(7):
        for snt in sentences(base.get(i, [])):
            base_words += len(snt.split())
            if snt not in plain:
                problems.append("base sentence missing: " + snt[:80])
    if len(plain.split()) < base_words:
        problems.append(f"shorter than the base: {len(plain.split())} < {base_words} words")
    seen = set()
    for k, v in c.items():
        for i in range(7):
            seen |= nums(" ".join(sentences(sections(v).get(i, []))))
    for n in sorted(seen):
        if n not in plain:
            problems.append("number from a draft is missing: " + n)
    return problems


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("page")
    ap.add_argument("record")
    args = ap.parse_args(argv)
    page_md = open(args.page, encoding="utf-8").read()
    record = json.load(open(args.record, encoding="utf-8"))
    paragraphs, stats = build(page_md)
    problems = check(page_md, paragraphs)
    paragraphs, placed = mark_facts(paragraphs, record["facts"])
    record["narrative"] = paragraphs
    json.dump(record, open(args.record, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    words = sum(len(re.sub(r"\{\{[\w-]+\|", "", p).split()) for p in paragraphs)
    print(f"{args.page}: {stats['added']} of {stats['seen']} other-draft sentences added, {words} words, "
          f"{len(placed)} of {len(record['facts'])} facts marked, {len(problems)} problems")
    for p in problems:
        print("  PROBLEM:", p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
