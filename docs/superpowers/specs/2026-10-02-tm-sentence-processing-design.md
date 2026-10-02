# TM 语句处理模块设计

## 目标

为 TM 提供可复现的语句处理模块，并预备中文、英文、日文的 Hugging Face 语义模型。每种语言有独立的 ENV 开关，默认关闭。关闭时由后端自己的分词器和 TF-IDF 向量化器生成非负稀疏向量，不导入语义模型依赖；开启时才惰性加载该语言的模型，并将其稠密 embedding 经确定性随机超平面哈希转换为非负稀疏向量，以兼容当前 RAG SDK。当前 TM 查询和 reindex worker 尚未接入该模块，因此线上 TM 流程不会加载或调用这些模型。

## 边界与接口

实现位于 `app/infrastructure/translation_memory/sentence_processing.py`，配置位于 `app/core/config.py`，不改动 API、任务队列和 SDK。模块提供：

- `SentenceTokenizer.tokenize(text, language)`：规范化文本并按语言代码分词；英文使用词项，中文和日文使用稳定的字符 n-gram 规则，不依赖网络或模型文件。
- `TranslationMemoryVectorizer(version).fit(entries)`：基于 `(text, language)` 输入语料生成排序稳定的词汇表；`encode(text, language)` 产出 L2 归一化、非负、特征 ID 唯一且排序的 TF-IDF 稀疏向量。相同语料、版本和输入必须得到相同结果。
- `SEMANTIC_MODEL_IDS`：声明语言族到公开 Hugging Face 仓库的映射：`zh -> BAAI/bge-small-zh-v1.5`、`en -> BAAI/bge-small-en-v1.5`、`ja -> cl-nagoya/ruri-base`。
- `SemanticSparseProjector`：用固定 seed 的随机超平面将归一化稠密向量转换为非负稀疏二进制向量；同一向量和投影版本始终得到相同结果。投影 seed、超平面数和投影版本必须进入索引元数据。
- `HuggingFaceSemanticEncoder`：只有对应语言的 `TM_SEMANTIC_MODEL_<LANG>_ENABLED=true` 时才惰性导入可选的 `sentence-transformers` 并从配置的本地目录加载模型。三种语言独立开关，默认均为 `false`；本次不把 `SentenceProcessor` 接入现有 TM API 或 worker。

语义依赖放入可选 extra；缺少依赖或本地模型目录时给出可操作错误。默认路径位于被 Git 忽略的 `models/semantic/<model-name>`，模型代码只读取本地目录，不隐式联网。索引元数据记录模型 ID/revision、语言族、原始维度、输出归一化方式和投影版本。SDK 接收的始终是稀疏向量 `list[tuple[int, float]]`，不得将原始稠密 embedding 直接传给它。

## 模型下载

使用 `uv sync --extra semantic` 安装模型运行库和 Hugging Face CLI 后，将模型下载到各自的本地目录。README 和语义适配器注释应给出三条 `hf download <repo-id> --local-dir <path>` 示例及三个 ENV 开关。模型文件不提交到 Git；下载前需阅读对应模型卡的许可与使用限制。

## 验证

- 单元测试覆盖中、英、日分词，空白/标点输入、确定性词汇表、未知词处理、非负稀疏向量和向量版本。
- 测试三个 ENV 开关默认关闭且可独立启用；关闭时不导入或实例化语义模型。
- 测试随机超平面投影确定性、非负性、唯一排序特征和 SDK 维度约束；用 fake encoder 测试打开开关时的路由，不在 CI 下载权重。
- 回归测试确认现有 TM 搜索和 `rebuild_index` 任务路径没有实例化语义模型。
- 更新 README，准确声明当前 TM 流程仍为后端分词及直接稀疏向量化，并提供模型下载/离线放置步骤。
