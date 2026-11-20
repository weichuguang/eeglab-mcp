# 方法学知识库与门控（Methodology Layer）

EEGLAB-MCP 不只是一组把 MATLAB 函数包起来的工具。它在执行之前先回答一个问题：**这次调用的参数，在这份数据上是否在方法学上成立？** 这个判断由两部分构成：

- **声明的知识**（`src/eeglab_mcp/data/` 下的 JSON）：47 条关于 EEGLAB 行为与方法学要求的声明，以及 39 个具名方法配置。
- **规则引擎**（`src/eeglab_mcp/gates.py`）：39 个检查函数。它只读 MATLAB 返回的事实（facts），在 Python 侧完成判断，因此可以脱离 MATLAB 单元测试。

知识是数据，判断是代码。两者分离，使声明可以被同行评审、被版本化，而不需要改动引擎。

## 一、为什么要放在执行之前

EEGLAB 的设计目标是“把分析做出来”，不是“阻止你做错”。`pop_eegfiltnew` 会在 128 Hz 数据上接受 100 Hz 低通，`pop_epoch` 会为一个 20 ms 的窗口生成 epoch，`pop_rmbase` 会接受落在 epoch 之外的基线窗——它们都会成功返回。问题不会在 MATLAB 报错时暴露，而会在论文的审稿意见里暴露。

门控把这些“能算但不应算”的情况提前到调用之前，并给出可执行的补救措施与依据编号。它挡住的是**不可解释的调用**，不是**结果不好看的调用**。

## 二、声明（Claims）

`data/claims.json` 共 47 条，按主题分组：FILT 8、REF 5、ICA 8、EPOCH 7、ASR 4、STAT 6、QC 5、GEN 4。每条声明的结构：

| 字段 | 含义 |
| --- | --- |
| `id` | 稳定编号，如 `EEGLAB-FILT-003`；门控结果里引用的就是它 |
| `topic` | FILT / REF / ICA / EPOCH / ASR / STAT / QC / GEN |
| `statement` | 一句话的方法学要求 |
| `source.kind` / `title` / `locator` | 依据：EEGLAB 官方文档、函数帮助或文献，含定位 |
| `risk` | 违反时的后果 |
| `applies_to` | 受约束的动作 |

声明正文均为对原始文档的**释义（paraphrase）**，`locator` 指向原文位置，读者可自行核对。这一点在 `claims.json` 的 `note` 字段中亦有说明。

## 三、方法配置（Method profiles）

`data/methods/*.json` 共 39 个配置，覆盖 10 个动作：

| 动作 | 配置数 | 示例 |
| --- | --- | --- |
| filter | 8 | `M-FILT-ERP-01`（0.1–30 Hz）、`M-FILT-LINE-50`（50 Hz 陷波） |
| reref | 4 | `M-REF-AVG-01`、`M-REF-REST-01`（当前不可执行） |
| ica | 5 | `M-ICA-RUNICA-01`、`M-ICA-ICLABEL-01`（未接入执行层） |
| epoch | 5 | `M-EPOCH-STIM-01`（−0.2–0.8 s） |
| baseline | 3 | `M-BASE-PRE-01`（−200–0 ms） |
| asr | 3 | `M-ASR-CLEAN-01`（cutoff 20，未接入执行层） |
| qc / stats / export / plot | 3 / 4 / 2 / 2 | `M-STAT-TTEST-01` 等 |

每个配置包含 `params`（该方法的参数）、`claims`（依据）、`gates`（前置检查）、`executable`（本版本能否真正执行）。39 个配置中 29 个可执行；其余 10 个明确标注为“未接入”，调用时会被 `capability_available` 检查阻断，而不是假装能跑。

## 四、配置如何被选中

调用方可以显式指定 `method`，也可以只给参数，由引擎匹配：

1. 若 `method` 的取值恰好是一个配置 ID，直接采用（因此 `reref(method="average")` 不会被误判成未知配置）。
2. 否则按参数匹配：调用方给出的每个参数都要与配置一致；**配置显式声明为 `null` 的参数表示“本方法不使用该参数”**，此时调用方若给出该参数即为不匹配（例如“不做基线”的配置不应匹配一个指定了基线窗的调用）。
3. 多个配置同时匹配时，依次比较：匹配的参数个数（多者优先）→ 调用方未要求但配置自带约束的个数（少者优先）→ 是否可执行 → ID。
4. 没有配置匹配时，使用该动作全部检查的并集构成临时配置（`M-ADHOC-*`）。并集对同一个检查取**最严格**的结论，避免因为按 ID 排序而继承某个配置的宽松版本。

匹配结果与是否命中预设都会写入 `gate.json`（`matched_profile` 字段）。实验记录里能看出这次到底是“用了标准方法”还是“参数临时组合”。

## 五、检查与状态

39 个检查分属以下类别：

| 类别 | 检查 |
| --- | --- |
| 滤波 | `nyquist_lowpass`、`nyquist_notch`、`highpass_component_risk`、`filter_order_vs_length`、`filter_already_applied`、`line_frequency_match` |
| 重参考 | `reference_recorded`、`reference_channels_present`、`reference_before_ica`、`chanlocs_coverage` |
| ICA | `ica_sample_sufficiency`、`ica_input_continuous`、`ica_rank_sufficient`、`component_rejection_manual` |
| 分段与基线 | `event_types_present`、`event_types_not_structural`、`event_cooccurrence`、`event_semantics_user_confirmed`、`epoch_within_record`、`epoch_span`、`baseline_before_stimulus`、`baseline_length`、`baseline_within_epoch`、`baseline_skip_declared` |
| ASR | `asr_cutoff_range`、`raw_data_preserved`、`plugin_available` |
| 统计与导图 | `stats_unit_of_analysis`、`stats_window_declared`、`stats_multiple_comparison`、`window_independent_of_result`、`waveform_labeling`、`trials_sufficient` |
| 通用 | `data_unit_consistent`、`flat_channel_absent`、`capability_available`、`processing_stage_order`、`qc_limitations_declared`、`export_metadata_complete` |

每个检查返回两种状态之一：通过，或按其配置的 `on_fail` 判为 `advisory` / `blocked`。整次调用的结论取最严重者：

| 状态 | 含义 | 是否执行计算 |
| --- | --- | --- |
| `pass` | 全部检查通过 | 是 |
| `advisory` | 存在风险，但这是研究者的判断空间（例：100 ms 的分段窗） | 是，风险写入 `warnings` |
| `blocked` | 存在无法解释的调用（例：低通高于奈奎斯特频率） | **否**，返回 `GATE_BLOCKED`，`job_id` 为空 |
| `override_accepted` | 有阻断项，但使用者提供了理由 | 是，理由与原始阻断项一并写入 `gate.json` |
| `unknown_method` | 指定的配置不存在 | 否 |

`blocked` 时不产生任何 MATLAB 计算，也不产生中间文件——这在测试中被显式断言（`tests/test_gates.py`）。`advisory` 与 `blocked` 的区别是刻意的：前者是方法学取舍，后者是参数与数据自相矛盾。

### 安全门控始终附加

`nyquist_lowpass` 与 `nyquist_notch` 不受配置控制：无论调用匹配了哪个配置，只要低通或陷波频率达到奈奎斯特频率就会被阻断。这条规则的存在，是因为曾出现 `filter(lowpass_hz=100)` 在 128 Hz 数据上匹配到“50 Hz 陷波”配置并顺利通过的情况——配置可以漏，安全底线不能漏。

## 六、override 的约束

`override_gate=true` 不是“跳过检查”的开关：

- 必须同时给出至少 20 个字符的 `override_reason`，否则返回 `GATE_OVERRIDE_REASON_REQUIRED`，计算不执行。
- 原始阻断项不会被删除。`gate.json` 同时保存 `status: override_accepted`、理由、以及 `overridden_checks` 列表。
- 没有阻断项时 override 不生效（`accepted: false`），避免把“本来就没问题”记录成“人工放行”。

这条设计使得审计时可以区分三类作业：正常通过、被阻断后未执行、被阻断但人工放行并说明原因。

## 七、事实（Facts）从哪来

门控不读 `.set` 的二进制内容，而是让 MATLAB 返回事实：`run_job.m` 的 `facts` 动作先以 `pop_loadset(..., 'loadmode', 'info')` 只读文件头（毫秒级），得到通道数、采样率、采样点、事件类型、参考、ICA 字段、插件清单等；只有当数据量小于 5×10⁶ 个元素时才完整加载，进一步计算单位、最大绝对值、秩与平坦通道，否则在结果中标注 `sampled: false` 并不给出这些数值。

因此“事实”永远来自真实文件，不会因为门控而假设数据是什么。结果按 `(路径, mtime, 大小)` 缓存，同一文件在一次会话中只读一次头。

多阶段流水线（`erp_analysis` = 滤波 + 分段 + 基线）是个例外：后一阶段的输入是前一阶段的输出。引擎按流水线**自己声明的**分段窗口把 `is_epoched`、`tmin_s`、`tmax_s` 投影到下一阶段，而不是拿原始连续文件去问“这份数据分段了吗”。投影只用调用参数，不假设数据内容。

## 八、MATLAB 原生测试

方法学层回答“该不该算”，测试回答“算得对不对”。`matlab/tests/` 下的 5 个套件直接调用真实 EEGLAB 函数，共 29 项检查：

| 套件 | 验证内容 |
| --- | --- |
| `test_core_functions` | 函数存在；平均参考后跨通道均值为零；试次数；注入已知直流偏移后基线校正将其移除；滤波保持尺寸与时长；ICA 三元组可重构数据并经存盘重载后仍可重构 |
| `test_synthetic_erp` | 在已知时刻注入 5 µV、σ=40 ms 的高斯峰，检查试次数、峰潜伏期误差 ≤15 ms、幅值误差、基线为零；并直接验证两条声明（零相位滤波不移动潜伏期、1 Hz 高通削弱慢成分） |
| `test_unit_detection` | µV / V / 未知单位三种输入的单位判定与换算系数 |
| `test_plugin_presence` | clean_rawdata、ICLabel、ERPLAB、BIOSIG 的实际可用性（缺失时如实报告，不伪造通过） |
| `test_sample_dataset` | 在 EEGLAB 官方示例数据上完成读取、分段、ERP、频谱 |

运行方式：

```bash
python scripts/run_matlab_tests.py            # 写出 outputs/matlab_tests.json，失败时退出码非零
pytest tests -q                               # Python 侧：知识库完整性、门控行为、集成
```

测试不使用替身对象。这一点已经产生实际收益：`ica:pop_runica_usable` 检出 EEGLAB 13 的 `pop_runica` 在 MATLAB 上会强制打开“中断”图形按钮，而新版 MATLAB 的 figure 句柄是对象而非数值，`supergui` 因此报 `argument 'fig' must be numeric`——即这台机器上的 ICA 原本根本跑不起来。修复方式是 `matlab/ica_decompose.m`：批处理环境不需要中断按钮，直接调用 `runica` 并写回 `icaweights`/`icasphere`/`icachansind`/`icawinv`，再由 `eeg_checkset` 补齐派生字段。已验证的属性是：写回后可由 `icawinv` 重构回原数据，且存盘重载后仍可重构；它与 `pop_runica` 的 runica 分支是否逐元素一致未做逐点比对，因此不作等价性断言。该限制被保留为一条回归检查，若将来 `pop_runica` 可用，检查会如实报告“无需绕过”；若出现第三种失败方式，检查会失败并提示重新评估。

## 九、如何扩展

**加一条声明**：在 `claims.json` 的 `claims` 数组中追加，`id` 用 `EEGLAB-<TOPIC>-<序号>`。`pytest tests/test_gates.py::test_catalog_is_internally_consistent` 会检查每条声明至少被一个配置引用。

**加一个方法配置**：在对应的 `data/methods/*.json` 中追加，`gates` 里的 `check` 必须是已注册的检查名，`claim` 必须存在。`executable: false` 表示只做前置检查、不执行。

**加一个检查**：在 `gates.py` 中写一个 `(_Ctx) -> (bool, str)` 函数并注册到 `CHECKS`；`str` 是写给使用者看的观测值（应当包含具体数值），不是日志。

改完运行 `pytest tests/test_gates.py -q`。知识库的一致性检查（47 条声明、39 个配置、所有引用可解析、所有检查已注册）会在毫秒内给出结论。

## 十、边界

- 门控判断的是**调用是否可解释**，不是**结论是否成立**。通过门控的结果仍可能因为实验设计、样本量或统计推断而不成立，这一点写在每次返回的 `interpretation_limits` 中。
- 声明是释义而非原文，`locator` 提供给读者核对；不同 EEGLAB 版本的行为可能不同，`claims.json` 的 `eeglab_baseline` 记录了编写时使用的版本（13.0.0b）。
- 当前 10 个配置标注为不可执行（ASR、ICLabel、REST、统计），它们只做前置检查。工具不会把“检查通过”呈现为“功能可用”。
