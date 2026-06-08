import os

path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tool_runner.py")
with open(path, encoding="utf-8-sig") as f:
    lines = f.readlines()

hs = next(i for i, l in enumerate(lines) if l.strip() == "handlers = {")
he = next(i for i in range(hs+1, len(lines)) if lines[i].strip() == "}")
me = next(i for i in range(he+1, len(lines)) if "if __name__" in lines[i])

block = lines[hs:me+3]
del lines[hs:me+3]
lines.append("\n")
lines.extend(block)

with open(path, "w", encoding="utf-8") as f:
    f.writelines(lines)
print("handlers moved to line", len(lines) - len(block))
