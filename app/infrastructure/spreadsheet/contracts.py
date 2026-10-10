from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field, field_validator


class TableColumn(BaseModel):
    language: str = Field(min_length=1, max_length=16)
    column: str = Field(min_length=1, max_length=128)

    @field_validator("language", "column")
    @classmethod
    def strip_value(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("列配置不能为空")
        return value


class SpreadsheetSpec(BaseModel):
    source_column: str = Field(min_length=1, max_length=128)
    target_columns: list[TableColumn] = Field(min_length=1, max_length=32)
    sheet_names: list[str] | None = None
    overwrite: bool = False

    @field_validator("source_column")
    @classmethod
    def strip_source_column(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("源列不能为空")
        return value

    @field_validator("target_columns")
    @classmethod
    def validate_target_columns(cls, value: list[TableColumn]) -> list[TableColumn]:
        languages = [item.language for item in value]
        columns = [item.column for item in value]
        if len(set(languages)) != len(languages):
            raise ValueError("目标语言不能重复")
        if len(set(columns)) != len(columns):
            raise ValueError("目标列不能重复")
        return value


@dataclass(frozen=True)
class SpreadsheetCell:
    address: tuple[object, ...]
    source_text: str
    target_language: str
    target_text: str | None


CellAddress = tuple[object, ...]


__all__ = ["CellAddress", "SpreadsheetCell", "SpreadsheetSpec", "TableColumn"]
