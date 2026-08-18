"""Structural sanity check on main.tex after the Method splice."""
import re
from collections import Counter

src = open("docs/paper/main.tex", encoding="utf-8").read()

# Strip comments so % lines do not perturb brace/environment counting.
body = "\n".join(re.sub(r"(?<!\\)%.*$", "", l) for l in src.split("\n"))

depth = 0
bad = False
for ch in re.sub(r"\\[{}]", "", body):
    if ch == "{":
        depth += 1
    elif ch == "}":
        depth -= 1
        if depth < 0:
            bad = True
print("braces balanced:", depth == 0 and not bad, f"(final depth {depth})")

envs = Counter(re.findall(r"\\begin\{(\w+\*?)\}", body))
ends = Counter(re.findall(r"\\end\{(\w+\*?)\}", body))
unbalanced = {k: (envs[k], ends[k]) for k in set(envs) | set(ends) if envs[k] != ends[k]}
print("environments balanced:", not unbalanced, unbalanced or "")

labels = set(re.findall(r"\\label\{([^}]+)\}", body))
refs = set(re.findall(r"\\ref\{([^}]+)\}", body))
print("dangling refs:", sorted(refs - labels) or "none")

bib = set(re.findall(r"\\bibitem\{([^}]+)\}", src)) or set(
    re.findall(r"@\w+\{([^,]+),", open("docs/paper/references.bib", encoding="utf-8").read())
)
cites = set()
for grp in re.findall(r"\\cite\{([^}]+)\}", body):
    cites.update(c.strip() for c in grp.split(","))
print("missing citations:", sorted(cites - bib) or "none")

print("remaining \\PH{} blocks:", len(re.findall(r"\\PH\{", body)))
print("remaining \\NUM{} cells:", len(re.findall(r"\\NUM\{", body)))

m = re.search(r"\\section\{Method\}(.*?)\\section\{Results\}", body, re.S)
sec5 = m.group(1)
print("--- Method section ---")
print("  \\PH left:", len(re.findall(r"\\PH\{", sec5)))
print("  \\NUM left:", len(re.findall(r"\\NUM\{", sec5)))
print("  subsections:", re.findall(r"\\subsection\{([^}]+)\}", sec5))
prose = re.sub(r"\\begin\{table\}.*?\\end\{table\}", "", sec5, flags=re.S)
prose = re.sub(r"\\PH\{.*?\n\n", "", prose, flags=re.S)
words = len(re.findall(r"[A-Za-z][A-Za-z'-]+", prose))
print("  approx prose words (tables and PH excluded):", words)
