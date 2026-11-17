"""Read the biomass and carbon tables in the GB/T 43648—2024 PDF."""

from functools import lru_cache
import re

NUMBER = r"\d+\.\d+"
ROMAN = r"[ⅠⅡⅢⅣⅤⅥ]"
REGION_ROW = re.compile(rf"^\s*(\d+)\s+(\S+)\s+(?:({ROMAN})\s+)?(.+?)\s*$")
MODEL_ROW = re.compile(rf"^\s*(\d+)\s+(\S+)\s+(?:({ROMAN})\s+)?((?:{NUMBER}\s+){{4}}{NUMBER})\s*$")
ANNEX_ROW = re.compile(rf"^\s*(\d+)\s+(.+?)\s+((?:{NUMBER}\s+){{5}})全国\s*$")
CARBON_ROW = re.compile(rf"^\s*(?:\d+\s+)?(\S+)\s+((?:{NUMBER}\s+){{6}}{NUMBER})(?:\s|$)")
ANNEX_EXAMPLES = {
    "其他松": ("赤松", "黑松"),
    "其他杉": ("油杉", "水杉", "池杉", "落羽杉"),
    "水胡黄": ("水曲柳", "胡桃楸", "黄菠萝"),
    "樟檫楠": ("樟树", "檫木", "楠木"),
    "其他硬阔": ("槭树", "槐树", "栾树", "榉树"),
    "其他软阔": ("楸树", "梧桐树", "喜树", "构树"),
}


@lru_cache(maxsize=2)
def load_tables(path, modified_ns):
    import pymupdf

    regions, models, carbon, annex = {}, {}, {}, {}
    with pymupdf.open(path) as pdf:

        for index in range(7, 14):
            table = None
            for line in pdf[index].get_text(sort=True).splitlines():
                heading = re.match(r"\s*表\s*([123])\s+主要树种", line)
                if heading:
                    table = int(heading[1])
                    continue
                match = (REGION_ROW if table == 1 else MODEL_ROW).fullmatch(line)
                if match and table == 1:
                    number, group, population, scope = match.groups()
                    regions[int(number)] = (group, population, scope)
                elif match and table in (2, 3):
                    number, group, population, params = match.groups()
                    models[table, int(number)] = (group, population, params.split(), index - 5)

        for index in (32, 33):
            page = pdf[index].get_text(sort=True)
            header = re.search(r"表\s*14\s+主要树种", page)
            if not header:
                raise ValueError("无法定位表14。")
            for line in page[header.end():].splitlines():
                match = CARBON_ROW.match(line)
                if match:
                    group, values = match.groups()
                    carbon[group] = (values.split()[1], index - 5)

        page = pdf[240].get_text(sort=True)
        if "表E.1" not in page or "43648" not in page:
            raise ValueError("无法定位 GB/T 43648—2024 表E.1。")
        for line in page.splitlines():
            match = ANNEX_ROW.fullmatch(line)
            if match:
                _, group, params = match.groups()
                annex["".join(group.split())] = params.split()

        note = "".join(page.split()).partition("注:")[2]
        aliases = {}
        for group, examples in ANNEX_EXAMPLES.items():
            clause = re.search(rf"{group}指[^;。]+", note)
            if clause:
                aliases.update({name: group for name in examples if name in clause[0]})

    if (len(regions), len(models), len(carbon), len(annex)) != (49, 98, 21, 14):
        raise ValueError(
            f"模型表提取不完整（{len(regions)}/{len(models)}/{len(carbon)}/{len(annex)}）。"
        )
    for (_, number), (group, population, _, _) in models.items():
        if regions[number][:2] != (group, population) or group not in carbon:
            raise ValueError(f"总体序号 {number} 在国标表格之间无法交叉核对。")
    return regions, models, carbon, annex, aliases
