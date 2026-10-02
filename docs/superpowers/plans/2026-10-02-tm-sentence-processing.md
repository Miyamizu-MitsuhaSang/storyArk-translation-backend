# TM 语句处理模块实施计划

> **执行说明：** 按任务逐项实施；每个 Python 行为均先写失败测试，再实现。

**目标：** 提供中、英、日语句处理器，默认使用后端 tokenizer + 非负稀疏 TF-IDF，按语言开关可选使用本地 Hugging Face 模型并投影到 SDK 稀疏向量格式。

**架构：** `AppSettings` 保存三组独立的模型开关和本地路径，默认全部关闭。`SentenceProcessor` 关闭时不导入 sentence-transformers；开启时惰性加载相应语种模型，归一化 embedding 后经确定性随机超平面投影生成非负稀疏向量。TM API 和现有 worker 不接入此模块。

**技术栈：** Python 3.13、Pydantic Settings、标准库分词/TF-IDF、可选 `sentence-transformers`、pytest。

**设计文档：** `docs/superpowers/specs/2026-10-02-tm-sentence-processing-design.md`

## 全局约束

- `TM_SEMANTIC_MODEL_ZH_ENABLED`、`TM_SEMANTIC_MODEL_EN_ENABLED`、`TM_SEMANTIC_MODEL_JA_ENABLED` 默认均为 `false`。
- 未开启的语种不导入、不初始化语义模型；语义依赖仅在 `semantic` extra 中。
- `SentenceProcessor.encode(text, language)` 始终返回 SDK 兼容的 `list[tuple[int, float]]`。
- TM worker 索引必须按语言对分区；本计划不接入 TM API/worker，也不开放 `match_mode=semantic`。
- 模型权重保存在 Git 忽略的 `models/semantic/`，不提交仓库。

---

### 任务 1：增加独立语言开关并测试配置

**文件：** 修改 `app/core/config.py`；测试 `tests/test_config.py`。

**接口：** `AppSettings.tm_semantic_model_{zh,en,ja}_enabled: bool = False`；`AppSettings.tm_semantic_model_{zh,en,ja}_path: Path` 指向各自的本地模型目录。

- [x] 测试三个开关默认关闭。
- [x] 测试 `.env.app` 中每个开关可被独立设置，且模型路径可覆盖。
- [x] 运行 `uv run pytest tests/test_config.py -q`，确认新字段缺失导致失败。
- [x] 添加设置字段和默认模型路径，不修改现有 `rag_candidate_threshold`。
- [x] 重跑 `uv run pytest tests/test_config.py -q`。

### 任务 2：实现 tokenizer、稀疏向量器和按开关路由

**文件：** 新建 `app/infrastructure/translation_memory/sentence_processing.py`；修改 `pyproject.toml`、`uv.lock`；新建 `tests/test_translation_memory_sentence_processing.py`。

**接口：**

```python
SentenceTokenizer.tokenize(text: str, language: str) -> list[str]
TranslationMemoryVectorizer(version: str, max_features: int = 50000)
TranslationMemoryVectorizer.fit(entries: Iterable[tuple[str, str]]) -> TranslationMemoryVectorizer
TranslationMemoryVectorizer.encode(text: str, language: str) -> list[tuple[int, float]]
SentenceProcessor(settings: AppSettings | None = None)
SentenceProcessor.fit(entries: Iterable[tuple[str, str]]) -> None
SentenceProcessor.encode(text: str, language: str) -> list[tuple[int, float]]
```

- [x] 先测试语言别名、unsupported language、中文/日文 n-gram、英文词项、空白文本和标点。
- [x] 先测试词汇表排序确定性、未知词忽略、TF-IDF 权重非负、特征唯一排序、归一化和版本字段。
- [x] 先测试开关关闭时 fake encoder 从未创建；开启某一种语言时只请求对应模型 ID 和本地路径。
- [x] 先测试语义稠密向量经固定 seed 的随机超平面投影后为确定性、非负且维度固定的 sparse vector。
- [x] 运行 `uv run pytest tests/test_translation_memory_sentence_processing.py -q`，确认功能缺失失败。
- [x] 实现三种 tokenizer 规则、稳定 TF-IDF 词表、按开关选择模型或本地向量器，以及惰性 Hugging Face 加载。
- [x] 把 `sentence-transformers` 放入 `[project.optional-dependencies].semantic`，更新并检查 lock；基础依赖不包含该库。
- [x] 重跑针对性测试。

### 任务 3：补充模型下载说明并完成验证

**文件：** 修改 `README.md`、`.gitignore`，并在处理器模块注释中记录安装/下载流程。

- [x] README 说明当前 TM 查询/reindex worker 不调用该模块；默认模块行为是后端 tokenizer + TF-IDF。
- [x] README 与代码注释列出三个 HF 模型、三个开关、`uv sync --extra semantic` 和各自 `hf download ... --local-dir ...` 命令。
- [x] 说明模型目录需本地存在，运行时不隐式联网；模型许可需按模型卡确认。
- [x] 忽略 `models/semantic/`。
- [x] 运行 `uv run pytest tests/test_config.py tests/test_translation_memory_sentence_processing.py -q`，再运行 `uv run pytest -q`。
- [x] 检查 `git diff --check`、README 原有修改和计划中“dense semantic 不在范围内”的表述。
