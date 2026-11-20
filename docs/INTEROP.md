# 与 MNE-MCP / Pingouin-MCP 的互操作规范

本文件说明 EEGLAB-MCP 如何与心理科学数据中心已有的两个 MCP 服务器协同工作，
使三者可以被同一个智能体以同一种方式编排。

---

## 一、共同遵循的约定

三个服务器遵循同一套设计原则：

| 原则 | EEGLAB-MCP 的落实 |
| --- | --- |
| **持久会话** | MATLAB 常驻工作进程（`matlab_worker.m`），工具之间不重复冷启动 |
| **结果即代码** | 每个作业目录保留 `job.json`（完整参数）+ `matlab_stdout.log`（真实执行记录） |
| **假设显式** | `qc_report` 主动列出"未检查项"；滤波/分段/ICA 均返回参数与适用条件 |
| **错误即消息** | 返回 `errors[].code` + `message` + `hint`，不使用异常栈作为唯一信息 |
| **逃生通道** | **有意不提供**（见第四节） |

---

## 二、交接格式：长格式表

MNE-MCP 与 Pingouin-MCP 之间以**长格式表格**交接：每行一个观测。
EEGLAB-MCP 通过 `eeglab_export_long_table` 产出同一格式，可直接进入统计环节。

```
subject,condition,channel,mean_uv,trial
sub-001,square,ch1,9.949896,1
sub-001,square,ch1,19.436320,2
...
```

| 列 | 含义 | 类型 |
| --- | --- | --- |
| `subject` | 被试标识（建议使用数据中心的 PSID） | string |
| `condition` | 条件标签，取自 epoch 的事件类型 | string |
| `channel` | 通道标签 | string |
| `mean_uv` | 测量窗口内的平均幅值，单位 µV | float |
| `trial` | 试次序号 | int |

**为什么是这个格式**：它与 MNE-MCP 导出的长表列名一致，也是 Pingouin 绝大多数检验
（`ttest`、`anova`、`mixed_anova`、`corr`）可直接消费的输入形态，避免 JSON ↔ 宽表 ↔ 长表反复转换。

**已验证**：端到端验证记录的 32 通道 × 80 试次 = 2560 行输出，
可被 pandas 直接读取（无缺失值、`mean_uv` 为浮点）。

### 频域交接：`psd_channels.csv`

`eeglab_compute_psd` 额外产出逐通道功率谱，供 MNE / pandas / R 直接读取：

```
channel,freq_hz,power_db,power_uv2_hz
ch1,0,42.13,163.3
ch1,0.125,40.87,122.2
...
```

| 列 | 含义 | 类型 |
| --- | --- | --- |
| `channel` | 通道标签（无定位时为 `chN`） | string |
| `freq_hz` | 频率（全分辨率，不做 300 点降采样） | float |
| `power_db` | Welch 功率谱密度，dB 基准 `10*log10(µV²/Hz)` | float |
| `power_uv2_hz` | 线性化的功率谱密度，单位 µV²/Hz | float |

标准频段功率（delta/theta/alpha/beta/gamma，单位 µV²）直接放在工具返回的
`result.bands` 中，无需再从 CSV 积分。

---

## 三、返回信封的字段对应

| EEGLAB-MCP | MNE-MCP | 说明 |
| --- | --- | --- |
| `success` | 同名 | 仅表示计算完成 |
| `job_id` | 同名 | 任务标识 |
| `result` | 同名 | 结构化结果 |
| `warnings` | 同名 | 不阻断但需注意 |
| `errors[]` | 同名 | `code` / `message` / `hint` |
| `artifacts[]` | 同名 | `path` / `kind` / `bytes` / `sha256` |
| `provenance` | 同名 | 软件版本、输入标识、执行时间 |
| `interpretation_limits` | 同名 | 明确"成功 ≠ 结论成立" |

---

## 四、有意的差异：不提供任意代码执行

MNE-MCP 提供 `mne_run_code`、Pingouin-MCP 提供 `stat_run_code` 作为逃生通道。
**EEGLAB-MCP 不提供等价工具，这是刻意的设计。**

原因：MATLAB 脚本一旦允许拼接执行，就会绕过路径白名单与参数校验，
形成任意代码执行面。本服务的替代方案是：

1. 所有能力通过 21 个固定工具暴露；
2. 多步分析通过 `eeglab_run_pipeline` 的**预定义流水线**组合；
3. 未被封装的需求，通过扩展 `matlab/run_job.m` 中新增 `case` 来满足——
   新增能力需要经过代码审查与测试，而不是运行时拼接。

这是三者在安全模型上的唯一实质差异，使用时应知晓：**EEGLAB 侧的能力边界由工具清单决定，
不由模型临时决定。**

---

## 五、典型编排链路

```
① 导入与检查
   eeglab_import_data（EDF/BDF/CNT → .set）
   eeglab_inspect_dataset（采样率、通道、事件）
   eeglab_qc_report（平坦通道、异常通道）

② 信号处理（MATLAB/EEGLAB）
   eeglab_run_pipeline(erp_analysis)   # 滤波 → 重参考 → 分段 → 基线
   或 eeglab_filter_data → eeglab_epoch_data → eeglab_baseline_correct

③ 交接（本文件第二节）
   eeglab_export_long_table(window 0.25–0.45 s)   # 幅值 -> 统计
   eeglab_compute_psd                             # 频域 -> 谱/频段功率

④ 统计推断 / 时频
   Pingouin-MCP：stat_data_quality_check → stat_ttest / stat_anova / stat_corr
   MNE-MCP      ：时频（ERSP/ITC）见下节

⑤ 报告
   三个服务器的 artifacts 合并归档；每个产物均带 SHA-256
```

### 时频（ERSP/ITC）用 MNE-MCP

EEGLAB-MCP 刻意不实现时频。已实测可行的编排（MNE 1.12.1）：

```python
# 分段 .set 不能用 mne_load_raw（它只接受连续数据），需走 mne_run_code
mne_run_code("epochs = mne.io.read_epochs_eeglab(r'<epoched.set>', verbose='ERROR')")
mne_run_code("epochs.apply_baseline((None, 0))")
# 然后调用结构化工具
mne_tfr_morlet(epochs_name="epochs", fmin=4, fmax=40, n_freqs=20)
```

注意：MNE 内部以**伏特**保存 EEG 数据，读取 EEGLAB 的 µV 数据时会自动换算
（实测 38.7 µV → 3.87e-05 V）。不要在 MNE 侧再手工乘/除 1e6，除非你明确知道
数据在 `.set` 中的存储单位。

**批量场景**：`eeglab_batch_process` 一次调用处理多个被试，单文件失败不中断整批，
返回 `items[].ok` 与 `items[].error_message`，可据此决定是否将某一被试排除在统计之外——
**排除规则必须显式记录，不能静默丢弃。**
