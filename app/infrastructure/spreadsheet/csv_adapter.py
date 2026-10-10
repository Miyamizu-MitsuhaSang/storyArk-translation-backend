from __future__ import annotations

import csv
import io

from .contracts import CellAddress, SpreadsheetCell, SpreadsheetSpec


class CsvSpreadsheetError(ValueError):
    pass


class CsvSpreadsheetAdapter:
    def read(self, content: bytes, spec: SpreadsheetSpec) -> list[SpreadsheetCell]:
        rows = list(csv.reader(io.StringIO(content.decode("utf-8-sig"))))
        if not rows:
            raise CsvSpreadsheetError("CSV 文件不能为空")
        header = rows[0]
        indices = self._indices(header, spec)
        cells: list[SpreadsheetCell] = []
        for row_number, row in enumerate(rows[1:], start=2):
            source = row[indices[spec.source_column]].strip() if indices[spec.source_column] < len(row) else ""
            if not source:
                continue
            for target in spec.target_columns:
                target_index = indices[target.column]
                target_text = row[target_index].strip() if target_index < len(row) else ""
                cells.append(SpreadsheetCell((row_number, indices[spec.source_column], target_index), source, target.language, target_text or None))
        return cells

    def write(self, content: bytes, spec: SpreadsheetSpec, translations: dict[CellAddress, str]) -> bytes:
        rows = list(csv.reader(io.StringIO(content.decode("utf-8-sig"))))
        if not rows:
            raise CsvSpreadsheetError("CSV 文件不能为空")
        header = rows[0]
        indices = self._indices(header, spec, create_missing=True)
        for column, index in indices.items():
            while len(header) <= index:
                header.append("")
            header[index] = column
        for address, translated in translations.items():
            row_number, _, target_index = address
            if not isinstance(row_number, int) or row_number < 2 or row_number > len(rows):
                continue
            row = rows[row_number - 1]
            while len(row) <= target_index:
                row.append("")
            if spec.overwrite or not row[target_index].strip():
                row[target_index] = translated
        return self._encode(rows)

    @staticmethod
    def _indices(header: list[str], spec: SpreadsheetSpec, *, create_missing: bool = False) -> dict[str, int]:
        indices: dict[str, int] = {}
        for name in [spec.source_column, *(item.column for item in spec.target_columns)]:
            matches = [index for index, value in enumerate(header) if value == name]
            if len(matches) > 1:
                raise CsvSpreadsheetError(f"CSV 列重复: {name}")
            if not matches:
                if not create_missing or name == spec.source_column:
                    raise CsvSpreadsheetError(f"CSV 缺少列: {name}")
                indices[name] = len(header) + sum(1 for value in indices if value not in header)
            else:
                indices[name] = matches[0]
        return indices

    @staticmethod
    def _encode(rows: list[list[str]]) -> bytes:
        stream = io.StringIO(newline="")
        csv.writer(stream, lineterminator="\n").writerows(rows)
        return stream.getvalue().encode("utf-8")


__all__ = ["CsvSpreadsheetAdapter", "CsvSpreadsheetError"]
