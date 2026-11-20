function M = compute_psd_metrics(spectra_db, freqs, scale)
% COMPUTE_PSD_METRICS  从 spectopo 的 dB 功率谱推导频段功率与工频提示。
%
%   M = compute_psd_metrics(spectra_db, freqs, scale)
%
%   spectra_db : nchan × nfreq，spectopo 输出的 dB 功率谱
%                （EEGLAB 的定义：10*log10(功率谱密度)，轴标签 µV²/Hz）
%   freqs      : 1 × nfreq 或 nfreq × 1 频率轴（Hz）
%   scale      : detect_units 返回的换算到微伏的比例（伏特数据为 1e6）
%
%   独立成文件而不是 run_job.m 的子函数，是为了让 MATLAB 原生测试
%   直接验证算法本身（dB 线性化、频段积分、工频判定），而不是验证副本。

freqs = double(freqs(:));
spectra_db = double(spectra_db);
nfreq = numel(freqs);

if nfreq < 2
    error('EEGLAB_MCP:BadData', ...
        'PSD requires at least 2 frequency bins (got %d).', nfreq);
end
if size(spectra_db, 2) ~= nfreq
    error('EEGLAB_MCP:BadData', ...
        'Spectrum size [%d %d] does not match %d frequency bins.', ...
        size(spectra_db, 1), size(spectra_db, 2), nfreq);
end

df = freqs(2) - freqs(1);
if df <= 0 || max(abs(diff(freqs) - df)) > 1e-6 * df
    error('EEGLAB_MCP:BadData', 'Frequency axis is not evenly spaced.');
end

warnings = {};
if ~isfinite(spectra_db)
    warnings{end+1} = 'Spectrum contains non-finite values; bands were computed ignoring them.';
end

% dB -> µV²/Hz。spectopo 的 dB 是 10*log10(pwelch 功率)；伏特数据整体
% 低 20*log10(1e6)=120 dB，因此频段功率乘 scale^2，而不是乘 scale。
psd_uv2_hz = 10 .^ (spectra_db / 10) * scale^2;

% 标准频段；上限裁剪到实际最高频点（不是请求的 fmax）。
names = {'delta', 'theta', 'alpha', 'beta', 'gamma'};
f_lo = [1 4 8 13 30];
f_hi = [4 8 13 30 45];
f_hi_eff = min(f_hi, freqs(end));
included = f_hi_eff > f_lo;

nband = numel(names);
band_mean = nan(1, nband);
band_chan = nan(size(spectra_db, 1), nband);
for b = 1:nband
    if ~included(b), continue; end
    sel = freqs >= f_lo(b) & freqs <= f_hi_eff(b);
    if ~any(sel), continue; end
    band_chan(:, b) = sum(psd_uv2_hz(:, sel), 2, 'omitnan') * df;
    band_mean(b) = mean(band_chan(:, b), 'omitnan');
end
if ~any(included)
    warnings{end+1} = sprintf( ...
        'No standard band fits below %.1f Hz; band powers are empty.', freqs(end));
end
if any(included) && any(~included)
    warnings{end+1} = sprintf( ...
        'Bands above %.1f Hz were cropped or omitted (fmax too low for gamma).', freqs(end));
end

% 工频提示：峰值频段比邻近频段抬升 ≥10 dB 才报告。只做提示，不替代陷波。
line_noise = struct('f0_hz', {}, 'n_channels_over', {}, 'median_rise_db', {});
for f0 = [50 60]
    if f0 - 3 < freqs(1) || f0 + 3 > freqs(end), continue; end
    peak_sel = freqs >= f0 - 2 & freqs <= f0 + 2;
    nb_sel = (freqs >= f0 - 3 & freqs < f0 - 2) | (freqs > f0 + 2 & freqs <= f0 + 3);
    if ~any(peak_sel) || ~any(nb_sel), continue; end
    peak_db = max(spectra_db(:, peak_sel), [], 2);
    nb_db = median(spectra_db(:, nb_sel), 2);
    rise = peak_db - nb_db;
    if median(rise, 'omitnan') >= 10
        line_noise(end+1) = struct( ...
            'f0_hz', f0, ...
            'n_channels_over', sum(rise >= 10), ...
            'median_rise_db', median(rise, 'omitnan'));
    end
end

M = struct();
M.freqs_hz = freqs;
M.df_hz = df;
M.psd_uv2_hz = psd_uv2_hz;
M.band = struct( ...
    'name', {names}, ...
    'f_lo_hz', f_lo, ...
    'f_hi_hz', f_hi_eff, ...
    'included', logical(included), ...
    'mean_uv2', band_mean);
M.band_channel_uv2 = band_chan;
M.line_noise = line_noise;
M.warnings = warnings;
end
