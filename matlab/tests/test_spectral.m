function results = test_spectral()
% TEST_SPECTRAL  验证 dB 语义、频段积分、单位换算、fmax 裁剪与工频判定。
%
%   算法本身用人工构造的谱验证（确定性）；频谱估计路径用合成信号验证
%   （宽带噪声的带内功率应接近其方差；持续正弦会被 Hann 旁瓣高估）。

results = struct('name', {}, 'passed', {}, 'detail', {});
rng(42);

% ---- 1. dB -> 线性功率的语义
freqs = (0:0.5:45)';
db = 10 * log10(20) * ones(4, numel(freqs));   % 20 uV^2/Hz
M = compute_psd_metrics(db, freqs, 1);
expected_alpha = 11 * 20 * 0.5;                % 8..13 Hz 共 11 个 bin
results(end + 1) = mcp_check('psd:db_definition', ...
    abs(M.band.mean_uv2(3) - expected_alpha) < 1e-6, ...
    sprintf('alpha = %.2f uV^2（期望 %.2f）', M.band.mean_uv2(3), expected_alpha));

% ---- 2. 单位换算：scale^2 把线性功率换算到 µV²；伏特谱整体低 120 dB
M_s = compute_psd_metrics(db, freqs, 1e6);     % 同一 dB，但按伏特解释
db_v = db - 120;                               % 同一物理谱，以伏特存储
M_v = compute_psd_metrics(db_v, freqs, 1e6);
ratio = M_s.psd_uv2_hz(1) / M.psd_uv2_hz(1);   % 仅 scale 改变 -> 1e12
results(end + 1) = mcp_check('psd:unit_scaling', ...
    abs(M_v.band.mean_uv2(3) - expected_alpha) < 1e-6 && abs(ratio - 1e12) < 1, ...
    sprintf('alpha(V) = %.2f uV^2，scale^2 比值 %.3g', M_v.band.mean_uv2(3), ratio));

% ---- 3. 宽带噪声的带内功率应接近其方差
N = 60 * 128;
x = 10 * randn(1, N);
X = fft(x);
f = (0:N - 1) * (128 / N);
keep = (f >= 8 & f <= 13) | (f >= 128 - 13 & f <= 128 - 8);
X(~keep) = 0;
y = real(ifft(X));
y = y * sqrt(100 / var(y));                    % 带内标准差 10 uV
[spectra, sf] = spectopo(y, 0, 128, 'plot', 'off');
My = compute_psd_metrics(spectra, sf, 1);
results(end + 1) = mcp_check('psd:band_integration', ...
    My.band.mean_uv2(3) > 60 && My.band.mean_uv2(3) < 160, ...
    sprintf('alpha = %.1f uV^2（宽带噪声方差 100）', My.band.mean_uv2(3)));

% ---- 4. 持续正弦：带内积分应等于 A^2/2（实测 spectopo 已在窗口间归一化）
t = (0:N - 1) / 128;
s = 10 * sin(2 * pi * 10 * t);
[spectra_s, sf2] = spectopo(s, 0, 128, 'plot', 'off');
Ms = compute_psd_metrics(spectra_s, sf2, 1);
results(end + 1) = mcp_check('psd:sine_power', ...
    Ms.band.mean_uv2(3) > 30 && Ms.band.mean_uv2(3) < 70, ...
    sprintf('10 uV 正弦 alpha = %.1f uV^2（A^2/2 = 50）', Ms.band.mean_uv2(3)));

% ---- 5. fmax 裁剪：gamma 不在可测范围时应标记为未包含
freqs20 = (0:0.5:20)';
M20 = compute_psd_metrics(zeros(2, numel(freqs20)), freqs20, 1);
M05 = compute_psd_metrics(zeros(2, 2), [0; 0.5], 1);
results(end + 1) = mcp_check('psd:fmax_crop', ...
    M20.band.included(5) == false && ~any(M05.band.included) && ~isempty(M05.warnings), ...
    sprintf('20 Hz 时 gamma included=%d；0.5 Hz 时任何频段 included=%d', ...
        M20.band.included(5), any(M05.band.included)));

% ---- 6. 工频提示：邻近频段抬升 >=10 dB 才报告
freqs_ln = (0:0.5:64)';
clean = 20 * ones(4, numel(freqs_ln));
bump = clean;
bump(:, freqs_ln >= 48 & freqs_ln <= 52) = 35;
Mc = compute_psd_metrics(clean, freqs_ln, 1);
Mb = compute_psd_metrics(bump, freqs_ln, 1);
results(end + 1) = mcp_check('psd:line_noise', ...
    isempty(Mc.line_noise) && numel(Mb.line_noise) == 1 && ...
    Mb.line_noise(1).f0_hz == 50, ...
    sprintf('干净谱 %d 个提示，含工频谱 %d 个提示', ...
        numel(Mc.line_noise), numel(Mb.line_noise)));
end
