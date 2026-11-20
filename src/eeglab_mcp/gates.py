"""Method gates.

A gate is a preflight check attached to a method profile.  Every check is a
small pure function of three things:

* ``facts``   -- what MATLAB reports about the input file (header-only load)
* ``params``  -- the parameters the caller asked for
* ``gate``    -- the rule as written in the knowledge base (including args)

Checks run in Python, not in MATLAB, so the rule engine exists exactly once and
can be unit-tested without a MATLAB licence.  MATLAB is only asked for facts.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Callable

from .methodology import Catalog, GateSpec, MethodProfile, load_catalog

PASS = "pass"
ADVISORY = "advisory"
BLOCKED = "blocked"
OVERRIDE = "override_accepted"
UNKNOWN = "unknown_method"

_MIN_OVERRIDE_REASON = 20


class GateError(RuntimeError):
    def __init__(self, code: str, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint


@dataclass(frozen=True)
class Facts:
    """What the input file actually is, as reported by MATLAB."""

    nbchan: int = 0
    srate: float = 0.0
    pnts: int = 0
    trials: int = 1
    duration_s: float = 0.0
    nevents: int = 0
    chanlocs: int = 0
    has_ica: bool = False
    is_continuous: bool = True
    is_epoched: bool = False
    reference: str = ""
    units: str = ""
    max_abs: float = 0.0
    rank: int = 0
    flat_channels: tuple[str, ...] = ()
    duplicate_events: int = 0
    event_types: tuple[str, ...] = ()
    channel_names: tuple[str, ...] = ()
    plugins: dict[str, bool] = field(default_factory=dict)
    history: tuple[str, ...] = ()
    tmin_s: float | None = None
    tmax_s: float | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "Facts":
        def tup(key: str) -> tuple[str, ...]:
            value = payload.get(key) or []
            if isinstance(value, (str, int, float)):
                value = [value]
            return tuple(str(v) for v in value)

        def opt_float(key: str) -> float | None:
            value = payload.get(key)
            if value is None or value == "":
                return None
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        return cls(
            nbchan=int(payload.get("nbchan") or 0),
            srate=float(payload.get("srate") or 0.0),
            pnts=int(payload.get("pnts") or 0),
            trials=int(payload.get("trials") or 1),
            duration_s=float(payload.get("duration_s") or 0.0),
            nevents=int(payload.get("nevents") or 0),
            chanlocs=int(payload.get("chanlocs") or 0),
            has_ica=bool(payload.get("has_ica")),
            is_continuous=bool(payload.get("is_continuous", True)),
            is_epoched=bool(payload.get("is_epoched")),
            reference=str(payload.get("reference") or ""),
            units=str(payload.get("units") or ""),
            max_abs=float(payload.get("max_abs") or 0.0),
            rank=int(payload.get("rank") or 0),
            flat_channels=tup("flat_channels"),
            duplicate_events=int(payload.get("duplicate_events") or 0),
            event_types=tup("event_types"),
            channel_names=tup("channel_names"),
            plugins={str(k): bool(v) for k, v in (payload.get("plugins") or {}).items()},
            history=tup("history"),
            tmin_s=opt_float("tmin_s"),
            tmax_s=opt_float("tmax_s"),
        )


@dataclass(frozen=True)
class _Ctx:
    facts: Facts
    params: dict[str, Any]
    profile: MethodProfile | None
    gate: GateSpec

    def num(self, key: str, default: float | None = None) -> float | None:
        value = self.params.get(key, default)
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def arg(self, key: str, default: Any = None) -> Any:
        return self.gate.args.get(key, default)


Check = Callable[[_Ctx], tuple[bool, str]]


def _nyquist_lowpass(c: _Ctx) -> tuple[bool, str]:
    lp = c.num("lowpass_hz")
    if lp is None:
        return True, "未设置低通"
    nyq = c.facts.srate / 2.0
    if nyq <= 0:
        return False, "采样率未知，无法判断奈奎斯特频率"
    if lp >= nyq:
        return False, f"低通 {lp:g} Hz ≥ 奈奎斯特 {nyq:g} Hz"
    if lp > 0.9 * nyq:
        return False, f"低通 {lp:g} Hz 已接近奈奎斯特 {nyq:g} Hz，过渡带过窄"
    return True, f"低通 {lp:g} Hz < 奈奎斯特 {nyq:g} Hz"


def _nyquist_notch(c: _Ctx) -> tuple[bool, str]:
    notch = c.num("notch_hz")
    if notch is None:
        return True, "未设置陷波"
    nyq = c.facts.srate / 2.0
    if nyq <= 0:
        return False, "采样率未知"
    if notch >= nyq:
        return False, f"陷波 {notch:g} Hz ≥ 奈奎斯特 {nyq:g} Hz"
    return True, f"陷波 {notch:g} Hz < 奈奎斯特 {nyq:g} Hz"


def _highpass_component_risk(c: _Ctx) -> tuple[bool, str]:
    hp = c.num("highpass_hz")
    if hp is None:
        return True, "未设置高通"
    lo = float(c.arg("min_hz", 0.0))
    hi = float(c.arg("max_hz", 0.5))
    if hp < lo:
        return False, f"高通 {hp:g} Hz 低于 {lo:g} Hz，慢漂移可能未去除"
    if hp > hi:
        return False, f"高通 {hp:g} Hz 高于 {hi:g} Hz，会削弱慢成分"
    return True, f"高通 {hp:g} Hz 位于 {lo:g}–{hi:g} Hz 的相容区间"


def _filter_order_vs_length(c: _Ctx) -> tuple[bool, str]:
    hp = c.num("highpass_hz")
    if hp is None or hp <= 0:
        return True, "无高通，不产生长阶滤波器"
    srate = c.facts.srate or 1.0
    edge_s = 1.65 / hp
    duration = c.facts.duration_s or 0.0
    if duration <= 0:
        return True, f"估计边界瞬态约 {edge_s:.1f} s（数据长度未知）"
    ratio = edge_s / duration
    if ratio > 0.25 or edge_s > 60:
        return False, f"估计边界瞬态约 {edge_s:.1f} s，占记录 {ratio * 100:.0f}%"
    return True, f"估计边界瞬态约 {edge_s:.1f} s，占记录 {ratio * 100:.0f}%"


def _filter_already_applied(c: _Ctx) -> tuple[bool, str]:
    hits = [h for h in c.facts.history if "filt" in h.lower()]
    if hits:
        return False, f"历史记录中已有 {len(hits)} 次滤波"
    return True, "历史记录中没有滤波"


def _line_frequency_match(c: _Ctx) -> tuple[bool, str]:
    notch = c.num("notch_hz")
    lp = c.num("lowpass_hz")
    if notch is not None:
        if notch not in (50.0, 60.0):
            return False, f"陷波 {notch:g} Hz 不是常见线路频率"
        return True, f"陷波 {notch:g} Hz 与线路频率一致"
    if lp is not None and lp > 45:
        return False, f"低通 {lp:g} Hz 对 50/60 Hz 线路噪声衰减不足"
    return True, "通带已覆盖线路频率之外，或需单独核查频谱"


def _ica_sample_sufficiency(c: _Ctx) -> tuple[bool, str]:
    nbchan = c.facts.nbchan or 0
    if nbchan <= 0:
        return False, "通道数未知"
    samples = (c.facts.pnts or 0) * max(c.facts.trials, 1)
    ratio = samples / nbchan
    need = float(c.arg("samples_per_channel", 20))
    if ratio < need:
        return False, f"每通道约 {ratio:.0f} 个采样点，低于建议的 {need:g}"
    return True, f"每通道约 {ratio:.0f} 个采样点，满足 {need:g} 的下限"


def _ica_input_continuous(c: _Ctx) -> tuple[bool, str]:
    if c.facts.is_epoched:
        return False, f"输入已分段（{c.facts.trials} 个试次）"
    return True, "输入为连续数据"


def _ica_rank_sufficient(c: _Ctx) -> tuple[bool, str]:
    if c.facts.rank <= 0:
        return True, "秩未计算"
    if c.facts.rank < c.facts.nbchan:
        return False, f"数据秩 {c.facts.rank} < 通道数 {c.facts.nbchan}"
    return True, f"数据秩 {c.facts.rank} 与通道数一致"


def _processing_stage_order(c: _Ctx) -> tuple[bool, str]:
    if c.facts.has_ica:
        return False, "数据已完成 ICA 分解，后续滤波或重参考会使成分与数据失配"
    if c.facts.is_epoched:
        return False, "数据已分段"
    return True, "数据仍为连续状态，处理顺序正确"


def _chanlocs_coverage(c: _Ctx) -> tuple[bool, str]:
    if c.facts.nbchan <= 0:
        return False, "通道数未知"
    ratio = c.facts.chanlocs / c.facts.nbchan
    need = float(c.arg("min_ratio", 0.9))
    if ratio < need:
        return False, f"定位覆盖率 {ratio * 100:.0f}%，低于 {need * 100:.0f}%"
    return True, f"定位覆盖率 {ratio * 100:.0f}%"


def _reference_before_ica(c: _Ctx) -> tuple[bool, str]:
    if c.facts.has_ica:
        return False, "数据已完成 ICA 分解，改参考会使成分地形图失配"
    return True, "数据尚未分解，改参考安全"


def _flat_channel_absent(c: _Ctx) -> tuple[bool, str]:
    flat = c.facts.flat_channels
    if flat:
        shown = "、".join(flat[:6])
        more = f" 等 {len(flat)} 个" if len(flat) > 6 else ""
        return False, f"检测到平坦通道：{shown}{more}"
    return True, "未检测到平坦通道"


def _reference_recorded(c: _Ctx) -> tuple[bool, str]:
    if not c.facts.reference:
        return False, "数据未记录参考方式"
    return True, f"当前参考：{c.facts.reference}"


def _reference_channels_present(c: _Ctx) -> tuple[bool, str]:
    want = c.params.get("channels") or []
    if isinstance(want, str):
        want = [want]
    if not want:
        return False, "未指定参考电极"
    names = {n.lower() for n in c.facts.channel_names}
    if not names:
        return False, "无法读取通道列表"
    missing = [w for w in want if str(w).lower() not in names]
    if missing:
        return False, f"数据中不存在电极：{'、'.join(map(str, missing))}"
    return True, f"参考电极存在：{'、'.join(map(str, want))}"


def _capability_available(c: _Ctx) -> tuple[bool, str]:
    if c.profile is not None and not c.profile.executable:
        return False, "该配置在当前版本中标记为不可执行"
    return True, "该配置可执行"


def _component_rejection_manual(c: _Ctx) -> tuple[bool, str]:
    return True, "本步骤只分解，不剔除成分；剔除需人工确认并留痕"


def _plugin_available(c: _Ctx) -> tuple[bool, str]:
    name = c.arg("plugin")
    if not name:
        if c.profile is not None:
            if c.profile.stage == "asr":
                name = "clean_rawdata"
            elif "ICLabel" in c.profile.title:
                name = "ICLabel"
    if not name:
        return False, "无法确定所需插件"
    if c.facts.plugins.get(name):
        return True, f"插件 {name} 已安装"
    return False, f"插件 {name} 未安装"


def _event_types_present(c: _Ctx) -> tuple[bool, str]:
    want = c.params.get("event_types")
    if not want:
        return True, "未指定事件类型"
    if isinstance(want, str):
        want = [want]
    available = set(c.facts.event_types)
    missing = [str(w) for w in want if str(w) not in available]
    if missing:
        return False, f"事件中不存在：{'、'.join(missing)}"
    return True, f"事件标签存在：{'、'.join(map(str, want))}"


def _event_types_not_structural(c: _Ctx) -> tuple[bool, str]:
    want = c.params.get("event_types")
    if not want:
        return True, "未指定事件类型"
    if isinstance(want, str):
        want = [want]
    structural = {"boundary"} | {t.lower() for t in c.facts.event_types if "bound" in t.lower()}
    bad = [str(w) for w in want if str(w).lower() in structural]
    if bad:
        return False, f"{'、'.join(bad)} 是结构标记，不是刺激触发"
    return True, "请求的标签均为真实触发"


def _epoch_within_record(c: _Ctx) -> tuple[bool, str]:
    tmin = c.num("tmin_s")
    tmax = c.num("tmax_s")
    if tmin is None or tmax is None:
        return True, "未指定完整分段窗口"
    span = tmax - tmin
    duration = c.facts.duration_s
    if duration > 0 and span > duration:
        return False, f"窗口 {span:g} s 超过记录长度 {duration:g} s"
    return True, f"窗口 {span:g} s 在记录长度 {duration:g} s 之内"


def _epoch_span(c: _Ctx) -> tuple[bool, str]:
    tmin = c.num("tmin_s")
    tmax = c.num("tmax_s")
    if tmin is None or tmax is None:
        return True, "未指定完整分段窗口"
    span = tmax - tmin
    lo = float(c.arg("min_s", 0.2))
    hi = float(c.arg("max_s", 3.0))
    if span <= 0:
        return False, f"窗口跨度 {span:g} s 非正"
    if span < lo:
        return False, f"窗口跨度 {span:g} s 短于 {lo:g} s，可能截断成分"
    if span > hi:
        return False, f"窗口跨度 {span:g} s 长于 {hi:g} s，可能引入无关活动"
    return True, f"窗口跨度 {span:g} s 位于 {lo:g}–{hi:g} s"


def _baseline_before_stimulus(c: _Ctx) -> tuple[bool, str]:
    start = c.num("baseline_start_s")
    end = c.num("baseline_end_s")
    if start is None or end is None:
        return True, "未设置基线窗"
    if end > 0:
        return False, f"基线结束于 {end:g} s，晚于刺激零点"
    if start >= end:
        return False, f"基线区间非法：{start:g} → {end:g} s"
    return True, f"基线区间 {start:g} → {end:g} s 完全位于刺激之前"


def _baseline_length(c: _Ctx) -> tuple[bool, str]:
    start = c.num("baseline_start_s")
    end = c.num("baseline_end_s")
    if start is None or end is None:
        return True, "未设置基线窗"
    length = abs(end - start)
    need = float(c.arg("min_s", 0.1))
    if length < need:
        return False, f"基线仅 {length * 1000:.0f} ms，短于 {need * 1000:.0f} ms"
    return True, f"基线长 {length * 1000:.0f} ms"


def _baseline_within_epoch(c: _Ctx) -> tuple[bool, str]:
    if not c.facts.is_epoched:
        return False, "输入未分段，无法做基线校正"
    start = c.num("baseline_start_s")
    if start is None:
        return True, "未设置基线窗"
    tmin = c.facts.tmin_s
    if tmin is None:
        return True, "分段起点未知"
    if start < tmin - 1e-9:
        return False, f"基线起点 {start:g} s 早于分段起点 {tmin:g} s"
    return True, f"基线起点 {start:g} s 位于分段窗口内"


def _baseline_skip_declared(c: _Ctx) -> tuple[bool, str]:
    start = c.num("baseline_start_s")
    end = c.num("baseline_end_s")
    if start is None and end is None:
        return True, "已声明跳过基线校正"
    return False, "该配置要求跳过基线，但基线窗被设置"


def _event_cooccurrence(c: _Ctx) -> tuple[bool, str]:
    if c.facts.duplicate_events > 0:
        return False, f"存在 {c.facts.duplicate_events} 处同一采样点的重复事件"
    return True, "未发现同一采样点的重复事件"


def _event_semantics_user_confirmed(c: _Ctx) -> tuple[bool, str]:
    return True, "标签语义由研究者确认；系统不假设标签等同实验条件"


def _data_unit_consistent(c: _Ctx) -> tuple[bool, str]:
    unit = c.facts.units.strip().lower()
    if unit in {"uv", "µv", "μv", "microvolt", "microvolts"}:
        return True, f"数据单位 {c.facts.units}，与微伏约定一致"
    if not unit or unit in {"unknown", "v", "mv", "volt"}:
        return False, f"数据单位 {c.facts.units or '未知'}，与 EEGLAB 微伏约定不符"
    return True, f"数据单位 {c.facts.units}"


def _asr_cutoff_range(c: _Ctx) -> tuple[bool, str]:
    cutoff = c.num("asr_cutoff")
    if cutoff is None:
        return False, "未指定 ASR cutoff"
    lo = float(c.arg("min", 10))
    hi = float(c.arg("max", 30))
    if cutoff < lo or cutoff > hi:
        return False, f"cutoff {cutoff:g} 超出常用区间 {lo:g}–{hi:g}"
    return True, f"cutoff {cutoff:g} 位于常用区间"


def _raw_data_preserved(c: _Ctx) -> tuple[bool, str]:
    return True, "原始文件只读，处理结果写入新文件"


def _qc_limitations_declared(c: _Ctx) -> tuple[bool, str]:
    return True, "质量报告包含未执行项清单"


def _stats_unit_of_analysis(c: _Ctx) -> tuple[bool, str]:
    unit = str(c.params.get("unit", "") or "").lower()
    if unit == "subject":
        return True, "分析单位为被试"
    if unit == "trial":
        return False, "分析单位为试次，会产生伪重复"
    return False, f"未声明分析单位（当前：{unit or '空'}）"


def _stats_window_declared(c: _Ctx) -> tuple[bool, str]:
    if c.params.get("window_declared"):
        return True, "测量窗已声明"
    return False, "测量窗未声明"


def _stats_multiple_comparison(c: _Ctx) -> tuple[bool, str]:
    correction = str(c.params.get("correction", "") or "none").lower()
    if correction in {"cluster", "fdr", "bonferroni", "holm", "max_stat"}:
        return True, f"已声明校正方式：{correction}"
    return False, "未进行多重比较校正"


def _trials_sufficient(c: _Ctx) -> tuple[bool, str]:
    n = c.facts.trials if c.facts.is_epoched else c.facts.nevents
    need = int(c.arg("min", 10))
    if n < need:
        return False, f"可用试次 {n}，少于 {need}"
    return True, f"可用试次 {n}"


def _export_metadata_complete(c: _Ctx) -> tuple[bool, str]:
    return True, "统一信封记录来源文件、参数与校验值"


def _window_independent_of_result(c: _Ctx) -> tuple[bool, str]:
    return False, "窗口是否独立于结果无法由系统核验"


def _waveform_labeling(c: _Ctx) -> tuple[bool, str]:
    return False, "图上成分标注是否与数据峰位一致无法由系统核验"


def _fmax_below_nyquist(c: _Ctx) -> tuple[bool, str]:
    fmax = c.num("fmax_hz")
    if fmax is None:
        return True, "未设置频率上限（由 spectopo 按奈奎斯特自动裁剪）"
    nyq = c.facts.srate / 2.0
    if nyq <= 0:
        return False, "采样率未知，无法判断奈奎斯特频率"
    if fmax >= nyq:
        return False, f"频率上限 {fmax:g} Hz ≥ 奈奎斯特 {nyq:g} Hz"
    if fmax > 0.9 * nyq:
        return False, (
            f"频率上限 {fmax:g} Hz 已超过奈奎斯特的 90%（{0.9 * nyq:g} Hz），"
            "过渡带过窄"
        )
    return True, f"频率上限 {fmax:g} Hz < 奈奎斯特 {nyq:g} Hz"


def _psd_record_length_sufficient(c: _Ctx) -> tuple[bool, str]:
    need = float(c.arg("min_s", 10.0))
    if c.facts.is_epoched:
        d = (c.facts.pnts or 0) / (c.facts.srate or 1.0)
        label = "单试次"
    else:
        d = c.facts.duration_s
        label = "记录"
    if d <= 0:
        return True, f"记录时长未知（建议 ≥ {need:g} s）"
    return d >= need, f"{label} {d:.1f} s，Δf≈1/T={1.0 / d:.3f} Hz，建议 ≥ {need:g} s"


CHECKS: dict[str, Check] = {
    "nyquist_lowpass": _nyquist_lowpass,
    "nyquist_notch": _nyquist_notch,
    "highpass_component_risk": _highpass_component_risk,
    "filter_order_vs_length": _filter_order_vs_length,
    "filter_already_applied": _filter_already_applied,
    "line_frequency_match": _line_frequency_match,
    "ica_sample_sufficiency": _ica_sample_sufficiency,
    "ica_input_continuous": _ica_input_continuous,
    "ica_rank_sufficient": _ica_rank_sufficient,
    "processing_stage_order": _processing_stage_order,
    "chanlocs_coverage": _chanlocs_coverage,
    "reference_before_ica": _reference_before_ica,
    "flat_channel_absent": _flat_channel_absent,
    "reference_recorded": _reference_recorded,
    "reference_channels_present": _reference_channels_present,
    "capability_available": _capability_available,
    "component_rejection_manual": _component_rejection_manual,
    "plugin_available": _plugin_available,
    "event_types_present": _event_types_present,
    "event_types_not_structural": _event_types_not_structural,
    "epoch_within_record": _epoch_within_record,
    "epoch_span": _epoch_span,
    "baseline_before_stimulus": _baseline_before_stimulus,
    "baseline_length": _baseline_length,
    "baseline_within_epoch": _baseline_within_epoch,
    "baseline_skip_declared": _baseline_skip_declared,
    "event_cooccurrence": _event_cooccurrence,
    "event_semantics_user_confirmed": _event_semantics_user_confirmed,
    "data_unit_consistent": _data_unit_consistent,
    "asr_cutoff_range": _asr_cutoff_range,
    "raw_data_preserved": _raw_data_preserved,
    "qc_limitations_declared": _qc_limitations_declared,
    "stats_unit_of_analysis": _stats_unit_of_analysis,
    "stats_window_declared": _stats_window_declared,
    "stats_multiple_comparison": _stats_multiple_comparison,
    "trials_sufficient": _trials_sufficient,
    "export_metadata_complete": _export_metadata_complete,
    "window_independent_of_result": _window_independent_of_result,
    "waveform_labeling": _waveform_labeling,
    "fmax_below_nyquist": _fmax_below_nyquist,
    "psd_record_length_sufficient": _psd_record_length_sufficient,
}


# Applied to every call regardless of which profile matched: a cutoff above
# Nyquist is never acceptable, even if the matched profile does not mention it
# (e.g. a notched call that happens to pass a lowpass as well).
SAFETY_GATES: tuple[GateSpec, ...] = (
    GateSpec(
        check="nyquist_lowpass",
        on_fail=BLOCKED,
        claim="EEGLAB-FILT-003",
        message="低通截止频率必须低于奈奎斯特频率",
        remedy="降低 lowpass_hz，或确认采样率是否被正确读取",
    ),
    GateSpec(
        check="nyquist_notch",
        on_fail=BLOCKED,
        claim="EEGLAB-FILT-003",
        message="陷波频率必须低于奈奎斯特频率",
        remedy="确认采样率高于陷波频率的两倍",
    ),
)


@dataclass(frozen=True)
class GateItem:
    check: str
    status: str
    claim: str
    message: str
    remedy: str
    observed: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "check": self.check,
            "status": self.status,
            "claim": self.claim,
            "message": self.message,
            "remedy": self.remedy,
            "observed": self.observed,
        }


@dataclass(frozen=True)
class GateResult:
    action: str
    method_id: str
    method_title: str
    status: str
    matched: bool
    executable: bool
    items: tuple[GateItem, ...]
    claims: tuple[dict[str, Any], ...]
    override: dict[str, Any] | None
    notes: str
    catalog_version: str

    @property
    def blocked(self) -> bool:
        return self.status == BLOCKED

    def counts(self) -> dict[str, int]:
        out = {PASS: 0, ADVISORY: 0, BLOCKED: 0}
        for item in self.items:
            out[item.status] = out.get(item.status, 0) + 1
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "method_id": self.method_id,
            "method_title": self.method_title,
            "matched_profile": self.matched,
            "executable": self.executable,
            "catalog_version": self.catalog_version,
            "counts": self.counts(),
            "items": [i.to_dict() for i in self.items],
            "claims": list(self.claims),
            "override": self.override,
            "notes": self.notes,
        }


def _equal(a: Any, b: Any) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) < 1e-9
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_equal(x, y) for x, y in zip(a, b))
    return a == b


def _adhoc_profile(action: str, params: dict[str, Any], candidates: list[MethodProfile]) -> MethodProfile:
    """Build a profile from the union of an action's gates when nothing matches.

    The caller still gets the full check set; only the parameter defaults and
    the prose are generic.
    """
    # Different profiles may implement the same check with different severity
    # (e.g. a "no baseline" profile relaxes baseline checks). When parameters
    # match nothing we must not inherit an arbitrary profile's leniency, so the
    # strictest outcome for each check wins.
    severity = {PASS: 0, ADVISORY: 1, OVERRIDE: 2, BLOCKED: 3}
    by_check: dict[str, GateSpec] = {}
    claims: list[str] = []
    for prof in sorted(candidates, key=lambda p: p.id):
        for gate in prof.gates:
            prev = by_check.get(gate.check)
            if prev is None or severity.get(gate.on_fail, 0) > severity.get(prev.on_fail, 0):
                by_check[gate.check] = gate
        for cid in prof.claims:
            if cid not in claims:
                claims.append(cid)
    gates = list(by_check.values())
    return MethodProfile(
        id=f"M-ADHOC-{action.upper()}",
        stage=action,
        action=action,
        title="未预置的方法配置（按动作通用检查集评估）",
        intent="调用参数未匹配任何预设方法配置，使用该动作的通用检查集。",
        params={},
        claims=tuple(claims),
        gates=tuple(gates),
        executable=True,
        notes="如需精确的方法学门控，请显式指定 method 参数。",
    )


def resolve_profile(
    action: str, params: dict[str, Any], catalog: Catalog | None = None
) -> tuple[MethodProfile | None, bool]:
    """Pick the method profile that matches the requested parameters."""
    catalog = catalog or load_catalog()
    candidates = catalog.profiles_for_action(action)
    if not candidates:
        return None, False
    # ``method`` is also a legitimate parameter of the rereference tool, so only
    # treat it as a profile ID when it actually names one.
    explicit = params.get("method")
    is_profile_id = isinstance(explicit, str) and explicit in catalog.profiles
    if is_profile_id:
        prof = catalog.profiles[str(explicit)]
        if prof.action != action:
            return None, False
        return prof, True

    specified = {
        k: v for k, v in params.items() if v is not None and not (is_profile_id and k == "method")
    }
    scored: list[tuple[int, int, int, MethodProfile]] = []
    for prof in candidates:
        score = 0
        matched = True
        for key, value in specified.items():
            if key not in prof.params:
                continue  # the profile says nothing about this parameter
            expected = prof.params[key]
            if expected is None:
                # The profile explicitly leaves the parameter unset (e.g. the
                # "no baseline" profile). Supplying it describes a different
                # method, so this is a mismatch, not a wildcard.
                matched = False
                break
            if _equal(expected, value):
                score += 1
            else:
                matched = False
                break
        if not matched:
            continue
        # Prefer profiles that do not impose parameters the caller never asked
        # for (a multi-event epoch profile should not win over the plain one).
        extra = sum(1 for key, value in prof.params.items()
                    if value is not None and key not in specified)
        scored.append((score, extra, 0 if prof.executable else 1, prof))
    if scored:
        scored.sort(key=lambda item: (-item[0], item[1], item[2], item[3].id))
        return scored[0][3], True
    return _adhoc_profile(action, params, candidates), False


def evaluate(
    action: str,
    params: dict[str, Any],
    facts: Facts,
    method_id: str | None = None,
    override_gate: bool = False,
    override_reason: str = "",
    catalog: Catalog | None = None,
) -> GateResult:
    """Run the gates for ``action`` and return an aggregated result."""
    catalog = catalog or load_catalog()
    if method_id and method_id not in catalog.profiles:
        raise GateError(
            "METHOD_NOT_FOUND",
            f"方法配置 {method_id} 不存在",
            "调用 method_catalog 查看可用配置",
        )
    call_params = dict(params)
    if method_id:
        call_params["method"] = method_id

    profile, matched = resolve_profile(action, call_params, catalog)
    if profile is None:
        raise GateError(
            "METHOD_NOT_FOUND",
            f"方法配置 {method_id or action} 不存在或不适用于动作 {action}",
            "调用 method_catalog 查看可用配置",
        )

    effective = dict(profile.params)
    effective.update({k: v for k, v in params.items() if v is not None})

    gates = list(profile.gates)
    present = {g.check for g in gates}
    gates.extend(g for g in SAFETY_GATES if g.check not in present)

    items: list[GateItem] = []
    for gate in gates:
        fn = CHECKS.get(gate.check)
        if fn is None:
            items.append(
                GateItem(
                    check=gate.check,
                    status=ADVISORY,
                    claim=gate.claim,
                    message=gate.message,
                    remedy=gate.remedy,
                    observed="检查未注册，按建议处理",
                )
            )
            continue
        try:
            ok, observed = fn(_Ctx(facts=facts, params=effective, profile=profile, gate=gate))
        except Exception as exc:  # a broken check must never crash the call
            ok, observed = False, f"检查执行失败：{exc}"
        status = PASS if ok else gate.on_fail
        items.append(
            GateItem(
                check=gate.check,
                status=status,
                claim=gate.claim,
                message=gate.message,
                remedy=gate.remedy,
                observed=observed,
            )
        )

    blocked_items = [i for i in items if i.status == BLOCKED]
    advisory_items = [i for i in items if i.status == ADVISORY]
    status = BLOCKED if blocked_items else (ADVISORY if advisory_items else PASS)

    referenced = {i.claim for i in items if i.status in (BLOCKED, ADVISORY) and i.claim}
    if not referenced:
        referenced = set(profile.claims)
    claims = tuple(catalog.claims[c].to_dict() for c in sorted(referenced) if c in catalog.claims)

    result = GateResult(
        action=action,
        method_id=profile.id,
        method_title=profile.title,
        status=status,
        matched=matched,
        executable=profile.executable,
        items=tuple(items),
        claims=claims,
        override=None,
        notes=profile.notes,
        catalog_version=catalog.version,
    )
    return apply_override(result, override_gate, override_reason)


def apply_override(result: GateResult, override_gate: bool, override_reason: str) -> GateResult:
    """Turn a blocked result into ``override_accepted`` when a reason is given.

    The override never removes the blocked items: it only records that a human
    chose to proceed despite them, together with the reason.
    """
    if not override_gate:
        return result
    blocked = [i for i in result.items if i.status == BLOCKED]
    if not blocked:
        return replace(
            result,
            override={
                "accepted": False,
                "reason": override_reason,
                "note": "无阻断项，override 未生效",
            },
        )
    if len(override_reason.strip()) < _MIN_OVERRIDE_REASON:
        raise GateError(
            "GATE_OVERRIDE_REASON_REQUIRED",
            "override_gate 需要至少 20 个字符的 override_reason",
            "说明为何在阻断项存在的情况下仍继续；该说明会写入作业目录",
        )
    return replace(
        result,
        status=OVERRIDE,
        override={
            "accepted": True,
            "reason": override_reason.strip(),
            "overridden_checks": [i.check for i in blocked],
        },
    )


def merge_results(action: str, results: list[GateResult]) -> GateResult:
    """Combine several gate results (e.g. filter + epoch for a pipeline)."""
    if len(results) == 1:
        return results[0]
    items = tuple(i for r in results for i in r.items)
    statuses = {r.status for r in results}
    status = BLOCKED if BLOCKED in statuses else (OVERRIDE if OVERRIDE in statuses else
                                                  (ADVISORY if ADVISORY in statuses else PASS))
    seen: set[str] = set()
    claims: list[dict[str, Any]] = []
    for r in results:
        for c in r.claims:
            cid = c.get("id")
            if cid and cid not in seen:
                seen.add(cid)
                claims.append(c)
    return GateResult(
        action=action,
        method_id=" + ".join(r.method_id for r in results),
        method_title=" / ".join(r.method_title for r in results),
        status=status,
        matched=all(r.matched for r in results),
        executable=all(r.executable for r in results),
        items=items,
        claims=tuple(claims),
        override=next((r.override for r in results if r.override), None),
        notes="；".join(n for n in (r.notes for r in results) if n),
        catalog_version=results[0].catalog_version,
    )


def validate_catalog(catalog: Catalog | None = None) -> list[str]:
    """Integrity check used by tests and by ``eeglab_get_status``."""
    catalog = catalog or load_catalog()
    return catalog.validate(check_names=set(CHECKS))
