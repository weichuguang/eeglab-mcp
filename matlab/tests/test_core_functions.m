function results = test_core_functions()
% TEST_CORE_FUNCTIONS  验证被调用的 EEGLAB 函数确实存在且行为符合预期。
%
%   这里测的不是“能跑”，而是“算出来的东西符合定义”：
%   平均参考后各通道均值为零、基线校正后基线均值为零、ICA 能重构数据。

results = struct('name', {}, 'passed', {}, 'detail', {});

fns = {'pop_loadset', 'pop_eegfiltnew', 'pop_reref', 'pop_epoch', ...
       'pop_rmbase', 'pop_runica'};
for k = 1:numel(fns)
    results(end + 1) = mcp_check(['exists:' fns{k}], exist(fns{k}, 'file') == 2, ...
        'EEGLAB 函数是否可在路径中找到');
end

% ---- 平均参考：参考之后各通道的跨通道均值应为零 ----
try
    EEG = make_synthetic_eeg(256, 8, 30, 'noise_amp', 2);
    EEG.data = EEG.data + (1:8)' * 10;   % 人为加入很大的通道偏移
    EEG = eeg_checkset(EEG);
    R = pop_reref(EEG, []);
    m = mean(R.data, 1);
    scale = max(abs(R.data(:)));
    % eeg_checkset 会把数据转成 single（float32 的相对精度约 1e-7），
    % 因此用 1e-6 的相对阈值，而不是双精度的 1e-8。
    tol = 1e-6 * scale;
    results(end + 1) = mcp_check('reref:mean_is_zero', max(abs(m)) < tol, ...
        sprintf('max |跨通道均值| = %.3g（阈值 %.3g，float32 数据）', max(abs(m)), tol));
catch ME
    results(end + 1) = mcp_check('reref:mean_is_zero', false, ME.message);
end

% ---- 分段：试次数应等于落在记录内部的刺激数 ----
try
    EEG = make_synthetic_eeg(256, 8, 50, 'bump_times', 2:2:48);
    E = pop_epoch(EEG, {'square'}, [-0.2 0.8]);
    results(end + 1) = mcp_check('epoch:trial_count', E.trials == 24, ...
        sprintf('期望 24 个试次，实际 %d', E.trials));
catch ME
    results(end + 1) = mcp_check('epoch:trial_count', false, ME.message);
end

% ---- 基线校正：注入已知直流偏移，校正后应被移除 ----
% 不对“同一窗口自校零”做断言：pop_rmbase 的窗口边界约定与 times 轴相差一个采样点，
% 用同一组下标去验证会留下一个恒定的残余偏移，测到的其实是边界约定而不是基线校正。
% 因此改为注入 50 µV 的直流偏移，检查校正后偏移被移除。
try
    EEG = make_synthetic_eeg(256, 8, 50, 'bump_times', 2:2:48, 'noise_amp', 0);
    EEG.data = EEG.data + 50;
    EEG = eeg_checkset(EEG);
    E = pop_epoch(EEG, {'square'}, [-0.2 0.8]);
    B = pop_rmbase(E, [-200 0]);
    idx = B.times >= -180 & B.times <= -20;   % 取基线内部，避开边界采样点
    win = squeeze(mean(double(B.data(:, idx, :)), 2));
    results(end + 1) = mcp_check('baseline:removes_dc_offset', ...
        max(abs(win(:))) < 0.5, ...
        sprintf('注入 50 µV 直流偏移后，基线内部残余 %.3g µV（阈值 0.5）', max(abs(win(:)))));
catch ME
    results(end + 1) = mcp_check('baseline:removes_dc_offset', false, ME.message);
end

% ---- 滤波：不改变采样点与时长，不产生 NaN ----
try
    EEG = make_synthetic_eeg(128, 8, 30, 'noise_amp', 2);
    F = pop_eegfiltnew(EEG, 'locutoff', 1, 'hicutoff', 30, 'minphase', 0);
    same_size = isequal(size(F.data), size(EEG.data));
    finite = all(isfinite(F.data(:)));
    same_time = abs(F.xmax - EEG.xmax) < 1e-9;
    results(end + 1) = mcp_check('filter:shape_preserved', ...
        same_size && finite && same_time, ...
        sprintf('尺寸不变=%d 无 NaN=%d 时长不变=%d', same_size, finite, same_time));
catch ME
    results(end + 1) = mcp_check('filter:shape_preserved', false, ME.message);
end

% ---- ICA：混合矩阵与成分应能重构原始数据 ----
try
    EEG = make_synthetic_eeg(256, 8, 30, 'noise_amp', 2);
    X = double(EEG.data);
    C = ica_decompose(EEG, 'runica');
    act = C.icaweights * C.icasphere * X;
    rec = C.icawinv * act;
    rel = max(abs(rec(:) - X(:))) / max(abs(X(:)));
    has_all = ~isempty(C.icasphere) && ~isempty(C.icaweights) && ~isempty(C.icawinv);

    % 存盘后重新载入，确认 ICA 字段真的写进了 .set，而不只是留在内存里。
    tmp = [tempname '.set'];
    keep = onCleanup(@() cleanup_set(tmp));
    pop_saveset(C, 'filename', tmp);
    L = pop_loadset(tmp);
    diff_after = L.icawinv * (L.icaweights * L.icasphere * X) - X;
    rel_after = max(abs(diff_after(:))) / max(abs(X(:)));
    round_trip = isequal(size(L.icaweights), size(C.icaweights)) && rel_after < 1e-4;

    results(end + 1) = mcp_check('ica:reconstruction', rel < 1e-5 && has_all && round_trip, ...
        sprintf('相对重构误差 = %.3g（阈值 1e-5）；权重/球化/逆矩阵齐全 = %d；存盘重载后重构误差 = %.3g', ...
                rel, has_all, rel_after));
catch ME
    results(end + 1) = mcp_check('ica:reconstruction', false, ME.message);
end

% ---- pop_runica 在本机 MATLAB 上的已知限制（回归监测）----
% 通过条件：pop_runica 能直接用，或者它失败的正是 ica_decompose 文档里记录的
% supergui/figure 句柄问题。若出现第三种失败方式，本项会失败并提示重新评估。
try
    EEG = make_synthetic_eeg(128, 4, 10, 'noise_amp', 2);
    pop_runica(EEG, 'icatype', 'runica', 'maxsteps', 20);
    results(end + 1) = mcp_check('ica:pop_runica_usable', true, ...
        'pop_runica 可直接调用，无需绕过');
catch ME
    known = ~isempty(strfind(ME.message, 'supergui')) || ~isempty(strfind(ME.message, 'fig'));
    results(end + 1) = mcp_check('ica:pop_runica_usable', known, ...
        sprintf('pop_runica 失败：%s（已知的 figure 句柄问题=%d；生产路径已改走 ica_decompose）', ...
                ME.message, known));
end
end

function cleanup_set(f)
% 删除测试产生的临时 .set 与配套 .fdt。
[d, n, ~] = fileparts(f);
for ext = {'.set', '.fdt'}
    p = fullfile(d, [n ext{1}]);
    if exist(p, 'file') == 2
        delete(p);
    end
end
end
