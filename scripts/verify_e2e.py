"""End-to-end verification against the real EEGLAB sample dataset.

Writes outputs/VERIFICATION_REPORT.md from *actual* returned values.
Nothing here is hard-coded except the independently-verified expectations.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eeglab_mcp.config import load_settings  # noqa: E402
from eeglab_mcp.tools import Tools  # noqa: E402

S = load_settings()
T = Tools(S)
SAMPLE = str(S.eeglab.root / "sample_data" / "eeglab_data.set")
OUT = ROOT / "outputs" / "VERIFICATION_REPORT.md"

rows: list[str] = []
results: list[dict] = []


def step(title: str, fn):
    t0 = time.perf_counter()
    r = fn()
    dt = time.perf_counter() - t0
    results.append({"title": title, "ok": r.get("success"), "seconds": round(dt, 1), "raw": r})
    status = "PASS" if r.get("success") else "FAIL"
    print(f"[{status}] {title}  ({dt:.1f}s)")
    if not r.get("success"):
        print("        ", r.get("errors"))
    return r


def main() -> int:
    status = step("eeglab_get_status", lambda: T.get_status())
    inspected = step("eeglab_inspect_dataset", lambda: T.inspect_dataset(SAMPLE))
    loaded = step("eeglab_load_dataset", lambda: T.load_dataset(SAMPLE))
    pipe = step(
        "eeglab_run_pipeline(erp_analysis)",
        lambda: T.run_pipeline(SAMPLE, "erp_analysis", event_types=["square"]),
    )

    staged = None
    if pipe.get("success"):
        for a in pipe["artifacts"]:
            if a["kind"] == "eeglab_set":
                staged = a["path"]

    erp = None
    if staged:
        erp = step("eeglab_compute_erp", lambda: T.compute_erp(staged))
    plot = None
    if staged:
        plot = step("eeglab_plot_results(erp_waveform)", lambda: T.plot_results(staged, "erp_waveform"))
    qc = step("eeglab_qc_report", lambda: T.qc_report(SAMPLE))

    # ---------------------------------------------------------------- report
    d_status = status.get("result", {}) if status else {}
    d_insp = inspected.get("result", {}) if inspected else {}
    d_pipe = pipe.get("result", {}) if pipe else {}
    d_erp = erp.get("result", {}) if erp else {}
    d_qc = qc.get("result", {}) if qc else {}

    lines = [
        "# EEGLAB-MCP 验证报告",
        "",
        f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 测试数据：`{SAMPLE}`（EEGLAB 官方示例数据）",
        f"- MATLAB：{d_status.get('matlab_version', 'n/a')}",
        f"- EEGLAB：`{d_status.get('eeglab_folder', 'n/a')}`",
        f"- Python：{sys.version.split()[0]}",
        "",
        "> 本报告中的全部数值均来自工具真实返回值，未手工填写。",
        "",
        "## 一、执行结果",
        "",
        "| 步骤 | 结果 | 耗时 (s) |",
        "| --- | --- | --- |",
    ]
    for r in results:
        lines.append(f"| {r['title']} | {'PASS' if r['ok'] else 'FAIL'} | {r['seconds']} |")

    lines += [
        "",
        "## 二、独立核验的关键数值",
        "",
        "| 指标 | 工具返回值 | 独立核验值 | 结论 |",
        "| --- | --- | --- | --- |",
        f"| 采样率 (Hz) | {d_insp.get('sampling_rate_hz')} | 128 | {'一致' if d_insp.get('sampling_rate_hz') == 128 else '不一致'} |",
        f"| 通道数 | {d_insp.get('channel_count')} | 32 | {'一致' if d_insp.get('channel_count') == 32 else '不一致'} |",
        f"| 采样点数 | {d_insp.get('points')} | 30504 | {'一致' if d_insp.get('points') == 30504 else '不一致'} |",
        f"| 事件数 | {d_insp.get('event_count')} | 154 | {'一致' if d_insp.get('event_count') == 154 else '不一致'} |",
        f"| 数据维度 | {d_insp.get('data_size')} | [32 30504] | {'一致' if d_insp.get('data_size') == '[32 30504]' else '不一致'} |",
        f"| 通道位置数 | {d_insp.get('chanlocs_count')} | 0（该数据集确实无定位） | 已作为警告返回 |",
        "",
        "## 三、ERP 流程",
        "",
        f"- 生成的 epoch 数：**{d_pipe.get('trials')}**",
        f"- 执行步骤：{'；'.join(d_pipe.get('steps', []))}",
        f"- ERP 时间轴点数：{len(d_pipe.get('erp_times_s', []))}",
        f"- 时间范围：{d_pipe.get('erp_times_s', [0])[0]} s 至 {d_pipe.get('erp_times_s', [0])[-1]} s",
        "",
    ]
    if d_erp:
        lines += [
            "## 四、ERP 独立计算",
            "",
            f"- 试次数：**{d_erp.get('trial_count')}**",
            f"- 通道数：{d_erp.get('channel_count')}",
            f"- 波形通道：`{d_erp.get('waveform_channel')}`",
            f"- 波形点数：{len(d_erp.get('waveform_uv', []))}",
            "",
        ]
    if d_qc:
        cs = d_qc.get("channel_stats", {})
        lines += [
            "## 五、质量控制",
            "",
            f"- RMS 中位数：{cs.get('rms_median_uv', 0):.2f} µV",
            f"- RMS 范围：{cs.get('rms_min_uv', 0):.2f} — {cs.get('rms_max_uv', 0):.2f} µV",
            f"- 平坦通道：{cs.get('flat_channel_count')}",
            f"- 异常通道（>4×MAD）：{cs.get('outlier_channel_count')}",
            f"- 事件类型：{', '.join(d_qc.get('event_types', []))}",
            "",
            "**明确未检查的项目**（工具主动声明，避免过度解读）：",
            "",
        ]
        lines += [f"- {x}" for x in d_qc.get("not_checked", [])]
        lines.append("")

    artifacts = []
    for r in results:
        for a in (r["raw"].get("artifacts") or []):
            artifacts.append(a)
    if artifacts:
        lines += ["## 六、产物与校验值", "", "| 文件 | 类型 | 字节 | SHA-256（前 16 位） |", "| --- | --- | --- | --- |"]
        for a in artifacts:
            sha = (a.get("sha256") or "")[:16]
            lines.append(f"| `{Path(a['path']).name}` | {a.get('kind')} | {a.get('bytes')} | `{sha}` |")
        lines.append("")

    warns = []
    for r in results:
        for w in (r["raw"].get("warnings") or []):
            warns.append(f"- [{r['title']}] {w}")
    lines += ["## 七、警告（真实返回，未过滤）", ""] + (warns or ["- 无"]) + [""]

    # ------------------------------------------------- method gates
    gated = [(r["title"], r["raw"]["gate"]) for r in results if r["raw"].get("gate")]
    if gated:
        lines += [
            "## 八、方法学门控",
            "",
            f"- 知识库版本：`{gated[0][1].get('catalog_version')}`",
            "",
            "| 步骤 | 门控结论 | 匹配配置 | 通过 / 建议 / 阻断 |",
            "| --- | --- | --- | --- |",
        ]
        for title, g in gated:
            c = g.get("counts", {})
            lines.append(
                f"| {title} | {g.get('status')} | `{g.get('method_id')}` | "
                f"{c.get('pass', 0)} / {c.get('advisory', 0)} / {c.get('blocked', 0)} |"
            )
        lines.append("")
    else:
        lines += ["## 八、方法学门控", "", "- 本次运行的步骤均未经过门控。", ""]

    blk = [(r["title"], r["raw"]["gate"]) for r in results
           if (r["raw"].get("gate") or {}).get("status") == "blocked"]
    if blk:
        lines += ["### 被阻断的调用", ""]
        for title, g in blk:
            for item in g["items"]:
                if item["status"] == "blocked":
                    lines.append(f"- [{title}] `{item['check']}`：{item['message']} — {item['observed']}")
        lines.append("")

    # ------------------------------------------------- MATLAB native tests
    mt = ROOT / "outputs" / "matlab_tests.json"
    if mt.is_file():
        data = json.loads(mt.read_text(encoding="utf-8"))
        lines += [
            "## 九、MATLAB 原生测试",
            "",
            f"- 生成时间：{data.get('finished_utc')}",
            f"- EEGLAB 根目录：`{data.get('eeglab_root')}`",
            f"- 结果：**{data.get('passed')} / {data.get('total')} 通过**，失败 {data.get('failed')}",
            "",
            "| 检查 | 结果 | 观测值 |",
            "| --- | --- | --- |",
        ]
        for t in data.get("tests", []):
            detail = str(t["detail"]).replace("|", "\\|")
            lines.append(f"| `{t['name']}` | {'PASS' if t['passed'] else 'FAIL'} | {detail} |")
        lines.append("")
    else:
        lines += [
            "## 九、MATLAB 原生测试",
            "",
            "- 未找到 `outputs/matlab_tests.json`；先运行 `python scripts/run_matlab_tests.py`。",
            "",
        ]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("report ->", OUT)

    failed = [r for r in results if not r["ok"]]
    print(f"SUMMARY: {len(results) - len(failed)}/{len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
