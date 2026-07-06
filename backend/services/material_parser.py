"""材料解析器：把上传/指定的材料文件统一变成 ExtractedMaterial。

支持：
- JSON（申报模板）：递归扁平化为 "表名.字段名: 值" 列表
- XLSX/XLSM（申报模板）：按“要素表”元数据抽取字段与多行表
- PDF（文本型）：PyMuPDF 按页提取
- DOCX：python-docx 按段落 + 表格提取
- TXT：按段落提取
不支持：
- 扫描型 PDF / 老 .doc（直接报错）
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .schemas import ExtractedMaterial, MaterialSegment

# 文件名关键字 -> 材料类型（用于自动归类，命中即用）
MATERIAL_TYPE_RULES = [
    ("上一次", "上一次登记申报模板"),
    ("上一笔", "上一次登记申报模板"),
    ("历史登记", "上一次登记申报模板"),
    ("证明发生需要更正事实", "证明发生需要更正事实的文件"),
    ("更正事实证明", "证明发生需要更正事实的文件"),
    ("证明发生变更事实", "证明发生变更事实的文件"),
    ("变更事实证明", "证明发生变更事实的文件"),
    ("证明文件", "证明发生变更事实的文件"),
    ("原预登记", "原预登记申报模板JSON"),
    ("baseline", "原预登记申报模板JSON"),
    ("Baseline", "原预登记申报模板JSON"),
    ("系统记录", "原预登记系统记录"),
    ("政信", "政信类证明材料"),
    ("融资平台债务", "政信类证明材料"),
    ("补充预登记申报模板", "申报模板"),
    ("补充预登记模板", "申报模板"),
    ("补充预登记申请书", "申请书"),
    ("补充说明", "补充说明材料"),
    ("要素报告表", "信托预登记要素报告表"),
    ("新型资产服务信托", "新型资产服务信托情况说明"),
    ("情况说明", "新型资产服务信托情况说明"),
    ("模板", "申报模板"),
    ("申请书", "申请书"),
    ("信托文件", "信托文件样本"),
    ("信托合同", "信托文件样本"),
    ("清算报告", "其他附件"),
]


def guess_material_type(filename: str) -> str:
    name = Path(filename).name
    for kw, mtype in MATERIAL_TYPE_RULES:
        if kw in name:
            return mtype
    if Path(filename).suffix.lower() in {".xlsx", ".xlsm"}:
        return "申报模板"
    return "其他附件"


def _flatten_json(obj: Any, prefix: str = "") -> list[tuple[str, str]]:
    """递归扁平化 JSON：返回 [(location, value), ...]。

    数组：用索引下标 [i]；空值/容器节点跳过。
    """
    out: list[tuple[str, str]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            sub = f"{prefix}.{k}" if prefix else str(k)
            out.extend(_flatten_json(v, sub))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            sub = f"{prefix}[{i}]"
            out.extend(_flatten_json(v, sub))
    else:
        # 叶子节点
        value_str = "" if obj is None else str(obj)
        out.append((prefix or "(root)", value_str))
    return out


def parse_json_template(path: Path, material_type: str | None = None) -> ExtractedMaterial:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    pairs = _flatten_json(data)
    segments = [
        MaterialSegment(location=loc, text=val)
        for loc, val in pairs
        # 保留空值也有意义（说明字段未填），但避免输出超大量纯空字段
        if val != "" or "." in loc
    ]
    return ExtractedMaterial(
        material_name=path.name,
        material_type=material_type or guess_material_type(path.name),
        file_kind="json",
        segments=segments,
    )


def _clean_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _clean_section_name(name: str) -> str:
    cleaned = name.split(".", 1)[1].strip() if "." in name else name.strip()
    if cleaned == "关联交易事项":
        return "关联交易信息"
    return cleaned


def _is_section_name(name: str) -> bool:
    stripped = name.strip()
    return len(stripped) > 2 and stripped[0].isdigit() and "." in stripped[:3]


def _excel_cell_value(wb: Any, sheet_name: str, col: str, row: Any) -> str:
    if sheet_name not in wb.sheetnames:
        return ""
    try:
        row_no = int(row)
    except (TypeError, ValueError):
        return ""
    return _clean_cell(wb[sheet_name][f"{col}{row_no}"].value)


def parse_excel_template(path: Path, material_type: str | None = None) -> ExtractedMaterial:
    try:
        from openpyxl import load_workbook
    except ImportError as e:
        raise RuntimeError("缺少依赖 openpyxl，请先 pip install -r requirements.txt") from e

    wb = load_workbook(path, read_only=False, data_only=True, keep_vba=False)
    segments: list[MaterialSegment] = []

    if "要素表" not in wb.sheetnames:
        for ws in wb.worksheets:
            for row_no, row in enumerate(ws.iter_rows(values_only=True), start=1):
                values = [_clean_cell(v) for v in row if _clean_cell(v)]
                if values:
                    segments.append(
                        MaterialSegment(location=f"{ws.title}!R{row_no}", text=" | ".join(values))
                    )
        return ExtractedMaterial(
            material_name=path.name,
            material_type=material_type or guess_material_type(path.name),
            file_kind="excel",
            segments=segments,
        )

    meta_ws = wb["要素表"]
    current_section = ""
    grid_fields: dict[str, dict[str, Any]] = {}

    for row in meta_ws.iter_rows(min_row=2, values_only=True):
        values = list(row) + [None] * 18
        name = _clean_cell(values[1])
        value_col = _clean_cell(values[5])
        value_row = _clean_cell(values[6])
        sheet_name = _clean_cell(values[13])
        if not name:
            continue
        if _is_section_name(name):
            current_section = _clean_section_name(name)
            continue
        if not current_section or not value_col or not value_row:
            continue
        if sheet_name and sheet_name != "产品要素":
            grid = grid_fields.setdefault(
                current_section,
                {"sheet_name": sheet_name, "fields": []},
            )
            grid["fields"].append((name, value_col))
            continue
        text = _excel_cell_value(wb, "产品要素", value_col, value_row)
        segments.append(
            MaterialSegment(location=f"{current_section}.{name}", text=text)
        )

    for section, grid in grid_fields.items():
        sheet_name = grid["sheet_name"]
        fields = grid["fields"]
        if sheet_name not in wb.sheetnames:
            continue
        ws = wb[sheet_name]
        row_index = 0
        empty_streak = 0
        for row_no in range(5, ws.max_row + 1):
            row_values = [
                _clean_cell(ws[f"{col}{row_no}"].value)
                for _, col in fields
            ]
            if not any(row_values):
                empty_streak += 1
                if empty_streak >= 20 and row_index > 0:
                    break
                continue
            empty_streak = 0
            for field_idx, (field_name, _) in enumerate(fields):
                segments.append(
                    MaterialSegment(
                        location=f"{section}[{row_index}].{field_name}",
                        text=row_values[field_idx],
                    )
                )
            row_index += 1

    return ExtractedMaterial(
        material_name=path.name,
        material_type=material_type or guess_material_type(path.name),
        file_kind="excel",
        segments=segments,
    )


def parse_pdf(path: Path, material_type: str | None = None) -> ExtractedMaterial:
    try:
        import fitz  # PyMuPDF
    except ImportError as e:
        raise RuntimeError("缺少依赖 pymupdf，请先 pip install -r requirements.txt") from e

    segments: list[MaterialSegment] = []
    with fitz.open(path) as doc:
        for page_no, page in enumerate(doc, start=1):
            text = page.get_text("text") or ""
            text = text.strip()
            if not text:
                # 扫描型/纯图片页：警告但不中断
                segments.append(
                    MaterialSegment(
                        location=f"第{page_no}页",
                        text="[本页无可提取文本，疑似扫描件或图片页，不在 demo 支持范围]",
                    )
                )
                continue
            segments.append(MaterialSegment(location=f"第{page_no}页", text=text))
    return ExtractedMaterial(
        material_name=path.name,
        material_type=material_type or guess_material_type(path.name),
        file_kind="pdf",
        segments=segments,
    )


def parse_docx(path: Path, material_type: str | None = None) -> ExtractedMaterial:
    try:
        from docx import Document
    except ImportError as e:
        raise RuntimeError("缺少依赖 python-docx，请先 pip install -r requirements.txt") from e

    doc = Document(str(path))
    segments: list[MaterialSegment] = []

    for idx, para in enumerate(doc.paragraphs, start=1):
        text = (para.text or "").strip()
        if not text:
            continue
        segments.append(MaterialSegment(location=f"第{idx}段", text=text))

    for ti, table in enumerate(doc.tables, start=1):
        rows_text: list[str] = []
        for row in table.rows:
            cells = [(c.text or "").strip().replace("\n", " ") for c in row.cells]
            rows_text.append(" | ".join(cells))
        if rows_text:
            segments.append(
                MaterialSegment(
                    location=f"表{ti}",
                    text="\n".join(rows_text),
                )
            )

    return ExtractedMaterial(
        material_name=path.name,
        material_type=material_type or guess_material_type(path.name),
        file_kind="docx",
        segments=segments,
    )


def parse_txt(path: Path, material_type: str | None = None) -> ExtractedMaterial:
    text = path.read_text(encoding="utf-8", errors="ignore")
    segments: list[MaterialSegment] = []
    for idx, chunk in enumerate(text.split("\n\n"), start=1):
        chunk = chunk.strip()
        if chunk:
            segments.append(MaterialSegment(location=f"第{idx}段", text=chunk))
    return ExtractedMaterial(
        material_name=path.name,
        material_type=material_type or guess_material_type(path.name),
        file_kind="txt",
        segments=segments,
    )


def parse_material(path: str | Path, material_type: str | None = None) -> ExtractedMaterial:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"材料文件不存在：{p}")
    suffix = p.suffix.lower()
    if suffix == ".json":
        return parse_json_template(p, material_type)
    if suffix in {".xlsx", ".xlsm"}:
        return parse_excel_template(p, material_type)
    if suffix == ".pdf":
        return parse_pdf(p, material_type)
    if suffix == ".docx":
        return parse_docx(p, material_type)
    if suffix in {".txt", ".md"}:
        return parse_txt(p, material_type)
    if suffix == ".doc":
        raise ValueError(
            f"不支持老版本 .doc 格式（{p.name}），请另存为 .docx 后再上传。"
        )
    raise ValueError(f"暂不支持的材料类型：{suffix}（{p.name}）")
