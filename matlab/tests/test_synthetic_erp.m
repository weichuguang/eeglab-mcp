function results = test_synthetic_erp()
% TEST_SYNTHETIC_ERP  用已知答案的合成数据验证完整 ERP 流程。
%
%   在刺激后 300 ms 注入一个幅值已知的高斯成分，然后走
%   滤波 -> 分段 -> 基线 -> 平均 的全流程，检查：
%   峰潜伏期是否仍在 300 ms、幅值是否合理、基线是否被正确扣除。
%   最后用同一份数据验证“高通越高、慢成分越小”这一方法学论断。

results = struct('name', {}, 'passed', {}, 'detail', {});
stim = 5:3:116;
bump = stim + 0.3;

try
    EEG = make_synthetic_eeg(256, 32, 120, 'bump_times', bump, ...
        'event_times', stim, 'bump_amp', 5, 'bump_sigma_ms', 40, 'noise_amp', 2);

    [erp, times, n_trials] = run_erp(EEG, 0.1, 30);
    [peak_amp, peak_t] = peak_latency(erp, times);

    results(end + 1) = mcp_check('erp:trial_count', n_trials == numel(stim), ...
        sprintf('期望 %d 个试次，实际 %d', numel(stim), n_trials));
    results(end + 1) = mcp_check('erp:peak_latency', abs(peak_t - 300) <= 15, ...
        sprintf('峰潜伏期 %.1f ms（注入于 300 ms）', peak_t));
    results(end + 1) = mcp_check('erp:peak_amplitude', peak_amp > 3, ...
        sprintf('峰幅值 %.2f uV（注入 5 uV，经 0.1-30 Hz 滤波）', peak_amp));

    % 基线校正后，刺激前窗口的均值应接近零
    pre = times < 0;
    base = mean(erp(pre));
    results(end + 1) = mcp_check('erp:baseline_zero', abs(base) < 0.05, ...
        sprintf('刺激前平均 %.4f uV', base));

    % 方法学论断：1 Hz 高通会削弱 40 ms 量级的慢成分
    [erp_1hz, ~] = run_erp(EEG, 1.0, 30);
    [amp_1hz, t_1hz] = peak_latency(erp_1hz, times);
    results(end + 1) = mcp_check('claim:FILT-002:highpass_attenuates', ...
        amp_1hz < peak_amp, ...
        sprintf('0.1 Hz 高通 %.2f uV vs 1 Hz 高通 %.2f uV', peak_amp, amp_1hz));
    results(end + 1) = mcp_check('claim:FILT-001:zero_phase_latency', ...
        abs(t_1hz - peak_t) <= 15, ...
        sprintf('1 Hz 高通后峰潜伏期 %.1f ms（未滤波 %.1f ms）', t_1hz, peak_t));
catch ME
    results(end + 1) = mcp_check('erp:pipeline', false, ME.message);
end
end

% ----------------------------------------------------------------------
function [erp, times, n_trials] = run_erp(EEG, hp, lp)
F = pop_eegfiltnew(EEG, 'locutoff', hp, 'hicutoff', lp, 'minphase', 0);
E = pop_epoch(F, {'square'}, [-0.2 0.8]);
B = pop_rmbase(E, [-200 0]);
n_trials = B.trials;
times = B.times;
erp = mean(B.data, 3);
erp = mean(erp, 1);          % 通道均值：合成成分在所有通道上相同
end

function [amp, t] = peak_latency(erp, times)
win = times >= 200 & times <= 400;
segment = erp(win);
ts = times(win);
[amp, i] = max(segment);
t = ts(i);
end
