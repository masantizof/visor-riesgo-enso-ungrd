"""
migrar_paths_manifiestos.py
=============================
Uso único (no forma parte del pipeline). Corrige los `latest.json` ya
existentes en data_lake/ que se generaron en Windows: str(Path(...))
guarda las rutas con backslash, que en Linux (Streamlit Community Cloud)
se leen como un nombre de archivo literal en vez de un separador.
"""
import json
from pathlib import Path

fixed = 0
for p in Path("data_lake").rglob("latest.json"):
    data = json.loads(p.read_text(encoding="utf-8"))
    changed = False
    if "files" in data:
        for k, v in list(data["files"].items()):
            nv = v.replace("\\", "/")
            if nv != v:
                data["files"][k] = nv
                changed = True
    if changed:
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        fixed += 1
        print("fixed", p)
print("total fixed:", fixed)
