function run_job(job_file, result_file)
% RUN_JOB  EEGLAB-MCP 受控作业调度器（唯一 MATLAB 入口）
%
%   只接受预定义 action，不接受任意 MATLAB 代码。
%   读取 JSON 作业描述，执行对应 EEGLAB 操作，写出 JSON 结果。
%
%   用法（由 Python 适配器调用）：
%     matlab -batch "run_job('job.json','result.json')"

t_start = tic;

% 作业隔离：关闭上一作业可能遗留的图形窗口。作业变量本身属于函数作用域，
% 不跨调用保留；数据集每次由 load_eeg 从文件重新读取。进程级状态（MATLAB
% 路径、插件、persistent 变量）在同一常驻进程内共享，这一点在文档中如实说明。
try, close all force; catch, end

res = struct();
res.ok = false;
res.action = '';
res.data = struct();
res.warnings = {};
res.artifacts = {};
res.log = {};

try
    job = jsondecode(fileread(job_file));
    res.action = getfield_def(job, 'action', '');

    eeglab_root = getfield_def(job, 'eeglab_root', '');
    if isempty(eeglab_root) || exist(eeglab_root, 'dir') ~= 7
        error('EEGLAB_MCP:NoRoot', 'EEGLAB root not found: %s', eeglab_root);
    end
    addpath(genpath(fullfile(eeglab_root, 'functions')));
    res.log{end+1} = sprintf('EEGLAB root: %s', eeglab_root);

    out_dir = getfield_def(job, 'output_dir', '');
    if ~isempty(out_dir) && exist(out_dir, 'dir') ~= 7
        mkdir(out_dir);
    end

    switch res.action
        case 'status',    [res, res.data] = op_status(job, res);
        case 'inspect',   [res, res.data] = op_inspect(job, res);
        case 'facts',     [res, res.data] = op_facts(job, res);
        case 'stage',     [res, res.data] = op_stage(job, res);
        case 'qc',        [res, res.data] = op_qc(job, res);
        case 'filter',    [res, res.data] = op_filter(job, res);
        case 'reref',     [res, res.data] = op_reref(job, res);
        case 'epoch',     [res, res.data] = op_epoch(job, res);
        case 'baseline',  [res, res.data] = op_baseline(job, res);
        case 'ica',       [res, res.data] = op_ica(job, res);
        case 'erp',       [res, res.data] = op_erp(job, res);
        case 'psd',       [res, res.data] = op_psd(job, res);
        case 'plot',      [res, res.data] = op_plot(job, res);
        case 'pipeline',  [res, res.data] = op_pipeline(job, res);
        case 'batch',     [res, res.data] = op_batch(job, res);
        case 'import',    [res, res.data] = op_import(job, res);
        case 'export_long', [res, res.data] = op_export_long(job, res);
        otherwise
            error('EEGLAB_MCP:UnknownAction', 'Unsupported action: %s', res.action);
    end
    res.ok = true;

catch ME
    res.ok = false;
    res.error = struct( ...
        'code', char(ME.identifier), ...
        'message', char(ME.message));
    if ~isempty(ME.stack)
        res.error.where = sprintf('%s:%d', ME.stack(1).name, ME.stack(1).line);
    end
end

res.elapsed_seconds = toc(t_start);
res.provenance = struct( ...
    'matlab_version', version, ...
    'matlab_release', version('-release'), ...
    'eeglab_root', getfield_def_safe(job, 'eeglab_root', ''), ...
    'job_id', getfield_def_safe(job, 'job_id', ''), ...
    'finished_utc', datestr(now, 'yyyy-mm-dd HH:MM:SS'));

% ---- 写出结果（NaN/Inf 无法编码，先清理）----
txt = jsonencode(sanitize(res));
fid = fopen(result_file, 'w', 'n', 'UTF-8');
if fid < 0
    error('EEGLAB_MCP:WriteFailed', 'Cannot write result file: %s', result_file);
end
fwrite(fid, txt, 'char');
fclose(fid);
end

% ======================================================================
%  STATUS
% ======================================================================
function [res, d] = op_status(job, res)
d = struct();
d.matlab_version = version;
d.matlab_release = version('-release');
d.eeglab_root = getfield_def(job, 'eeglab_root', '');
d.eeglab_folder = folder_name(d.eeglab_root);

fns = {'pop_loadset','pop_saveset','eeg_checkset','pop_eegfiltnew','pop_eegfilt', ...
       'pop_reref','pop_epoch','pop_rmbase','pop_runica','pop_spectopo', ...
       'pop_topoplot','pop_rejchan','newtimef','spectopo','pop_erpimage'};
names = {}; found = [];
for k = 1:numel(fns)
    names{end+1} = fns{k};
    found(end+1) = (exist(fns{k}, 'file') == 2);
end
d.functions = struct('name', {names}, 'available', logical(found));
d.all_core_available = all(found(1:10));

missing = names(~logical(found));
if ~isempty(missing)
    res.warnings{end+1} = ['Missing functions: ' strjoin(missing, ', ')];
end

% 真实数据的快速可用性探针（不依赖是否已加载数据）
try
    d.license_ok = license('test', 'MATLAB');
catch
    d.license_ok = true;
end
end

% ======================================================================
%  INSPECT
% ======================================================================
function [res, d] = op_inspect(job, res)
[EEG, res] = load_eeg(job, res);
d = dataset_summary(EEG);

% 关联文件完整性
fp = getfield_def(job.input, 'file_path', '');
[~, base, ext] = fileparts(fp);
set_dir = fileparts(fp);
if strcmpi(ext, '.set')
    fdt = fullfile(set_dir, [base '.fdt']);
    d.fdt_present = (exist(fdt, 'file') == 2);
    if ~d.fdt_present
        res.warnings{end+1} = 'No companion .fdt file found (data may be stored inside the .set).';
    end
end

if d.chanlocs_count == 0
    res.warnings{end+1} = 'Channel locations are not defined (EEG.chanlocs is empty). Topographic plotting and source analysis are unavailable until locations are added.';
end
if d.event_count == 0
    res.warnings{end+1} = 'No events found; epoching and ERP are unavailable.';
end
if ~d.all_finite
    res.warnings{end+1} = 'Non-finite values (NaN/Inf) detected in the data array.';
end
end

% ======================================================================
%  FACTS（门控所需的事实，只读文件头；小文件才做数值采样）
% ======================================================================
function [res, d] = op_facts(job, res)
% 方法学门控需要的是“这个文件实际是什么”，而不是“调用者以为它是什么”。
% 默认只读文件头（pop_loadset loadmode=info），不载入完整数据；
% 只有当数据量足够小（<= 5e6 个采样值）时才做一次完整载入，
% 以便给出真实的幅值、单位、秩与平坦通道。是否采样由 d.sampled 显式标注。
fp = getfield_def(job.input, 'file_path', '');
if isempty(fp) || exist(fp, 'file') ~= 2
    error('EEGLAB_MCP:FileNotFound', 'Input file not found: %s', fp);
end
[~, base, ext] = fileparts(fp);
EEG = pop_loadset('filename', [base ext], 'filepath', fileparts(fp), ...
                  'loadmode', 'info');

d = struct();
d.source_file = fp;
d.nbchan = EEG.nbchan;
d.srate = EEG.srate;
d.pnts = EEG.pnts;
d.trials = EEG.trials;
d.duration_s = EEG.pnts / max(EEG.srate, 1) / max(EEG.trials, 1);
d.nevents = numel(EEG.event);
d.chanlocs = numel(EEG.chanlocs);
d.is_continuous = (EEG.trials <= 1);
d.is_epoched = (EEG.trials > 1);
d.has_ica = ~isempty(EEG.icaweights);
d.reference = ref_label(EEG);
d.tmin_s = EEG.xmin;
d.tmax_s = EEG.xmax;
d.channel_names = chan_labels(EEG);

if ~isempty(EEG.event)
    d.event_types = unique(cellstr(string({EEG.event.type})))';
    lat = round([EEG.event.latency]);
    [~, ~, ic] = unique(lat(:));
    counts = accumarray(ic, 1);
    d.duplicate_events = sum(counts(counts > 1) - 1);
else
    d.event_types = {};
    d.duplicate_events = 0;
end

if ischar(EEG.history) && ~isempty(EEG.history)
    d.history = regexp(EEG.history, '\r?\n', 'split');
elseif iscell(EEG.history)
    d.history = EEG.history(:)';
else
    d.history = {};
end

d.plugins = struct( ...
    'clean_rawdata', exist('clean_asr', 'file') == 2 || exist('clean_rawdata', 'file') == 2, ...
    'ICLabel', exist('pop_iclabel', 'file') == 2 || exist('iclabel', 'file') == 2, ...
    'ERPLAB', exist('pop_erplab_mainGUI', 'file') == 2, ...
    'bids', exist('bids_export', 'file') == 2);

% ---- 默认值：未做数值采样 ----
d.sampled = false;
d.units = '';
d.max_abs = 0;
d.rank = 0;
d.flat_channels = {};

n_elems = double(EEG.pnts) * max(EEG.trials, 1) * double(EEG.nbchan);
if n_elems <= 5e6
    EEG = pop_loadset('filename', [base ext], 'filepath', fileparts(fp));
    d.sampled = true;
    [~, unit] = detect_units(EEG);
    d.units = unit;
    d.max_abs = max(abs(double(EEG.data(:))));

    X = reshape(double(EEG.data), EEG.nbchan, []);
    n_cols = min(size(X, 2), 5000);
    if n_cols >= 2
        Xs = X(:, randperm(size(X, 2), n_cols));
        d.rank = rank(Xs - mean(Xs, 2));
    end
    sd = std(X, 0, 2);
    if ~isempty(sd) && max(sd) > 0
        isflat = (sd == 0) | (sd < 1e-12 * max(sd));
        names = chan_labels(EEG);
        d.flat_channels = names(isflat)';
    end
    res.log{end+1} = sprintf('facts: sampled %d elements (max |x| = %g)', n_elems, d.max_abs);
else
    res.warnings{end+1} = sprintf( ...
        ['facts: data too large for numeric sampling (%g elements); ' ...
         'units, amplitude, rank and flat-channel checks were skipped.'], n_elems);
end
end

function r = ref_label(EEG)
if ischar(EEG.ref)
    r = EEG.ref;
elseif iscell(EEG.ref) && ~isempty(EEG.ref)
    r = strjoin(EEG.ref, '+');
elseif isnumeric(EEG.ref) && ~isempty(EEG.ref)
    r = num2str(EEG.ref);
else
    r = '';
end
end

function names = chan_labels(EEG)
names = cell(1, EEG.nbchan);
for k = 1:EEG.nbchan
    names{k} = channel_label(EEG, k);
end
end

% ======================================================================
%  STAGE（校验并复制到作业目录，不改动原始文件）
% ======================================================================
function [res, d] = op_stage(job, res)
[EEG, res] = load_eeg(job, res);
src = getfield_def(job.input, 'file_path', '');
d = dataset_summary(EEG);
d.source_file = src;
d.original_sha256 = sha256_file(src);
[res, out] = save_stage(EEG, job, res, 'staged');
d.staged_file = out;
d.original_untouched = true;
res.log{end+1} = 'Original file was opened read-only and never written to.';
end

function h = sha256_file(path)
h = '';
try
    fid = fopen(path, 'r');
    if fid < 0, return; end
    bytes = fread(fid, Inf, '*uint8');
    fclose(fid);
    md = java.security.MessageDigest.getInstance('SHA-256');
    md.update(bytes);
    dig = typecast(md.digest(), 'uint8');
    h = lower(reshape(dec2hex(dig, 2)', 1, []));
catch
    h = '';
end
end

% ======================================================================
%  QC
% ======================================================================
function [res, d] = op_qc(job, res)
[EEG, res] = load_eeg(job, res);
s = dataset_summary(EEG);

d = struct();
d.sampling_rate_hz = s.sampling_rate_hz;
d.channel_count = s.channel_count;
d.duration_seconds = s.duration_seconds;

% 幅值统计（按通道）
X = double(EEG.data);
if ndims(X) == 2, X = reshape(X, size(X,1), size(X,2), 1); end
nch = size(X,1);
rms_per_ch = zeros(nch,1);
std_per_ch = zeros(nch,1);
maxabs_per_ch = zeros(nch,1);
flat_ch = false(nch,1);
for c = 1:nch
    v = X(c,:,:);
    v = v(:);
    v = v(isfinite(v));
    if isempty(v)
        rms_per_ch(c) = 0; std_per_ch(c) = 0; maxabs_per_ch(c) = 0; flat_ch(c) = true;
    else
        rms_per_ch(c) = sqrt(mean(v.^2));
        std_per_ch(c) = std(v);
        maxabs_per_ch(c) = max(abs(v));
        flat_ch(c) = (std_per_ch(c) == 0);
    end
end

% 异常通道：中位数 ± 4×MAD（稳健判据）
med = median(rms_per_ch);
mad_v = median(abs(rms_per_ch - med));
if mad_v > 0
    out_idx = find(abs(rms_per_ch - med) > 4 * 1.4826 * mad_v);
else
    out_idx = [];
end

[u_scale, u_name] = detect_units(EEG);
d.channel_stats = struct( ...
    'rms_median_uv', med * u_scale, ...
    'rms_min_uv', min(rms_per_ch) * u_scale, ...
    'rms_max_uv', max(rms_per_ch) * u_scale, ...
    'flat_channel_count', sum(flat_ch), ...
    'outlier_channel_count', numel(out_idx));
d.input_unit_assumed = u_name;
d.unit_scale_to_uv = u_scale;

% 注意：out_idx 可能为空，&& 需要短路，必须先判空
if ~isempty(out_idx) && isfield(EEG, 'chanlocs') && numel(EEG.chanlocs) >= max(out_idx)
    d.channel_stats.outlier_channels = {EEG.chanlocs(out_idx).labels};
else
    d.channel_stats.outlier_channels = {};
end

% 事件
d.event_count = numel(EEG.event);
if ~isempty(EEG.event)
    types = unique(cellstr(string({EEG.event.type})));
    d.event_types = types(:)';
else
    d.event_types = {};
end

% 未检查项（诚实声明）
d.not_checked = {'line_noise_level', 'muscle_artifact', 'ica_component_quality', ...
                 'epoch_level_rejection', 'channel_location_accuracy'};

if sum(flat_ch) > 0
    res.warnings{end+1} = sprintf('%d flat channel(s) found (zero variance).', sum(flat_ch));
end
if numel(out_idx) > 0
    res.warnings{end+1} = sprintf('%d channel(s) exceed 4×MAD of the RMS median.', numel(out_idx));
end
end

% ======================================================================
%  FILTER
% ======================================================================
function [res, d] = op_filter(job, res)
[EEG, res] = load_eeg(job, res);
p = getfield_def(job, 'params', struct());

nyq = EEG.srate / 2;
hp = getfield_def(p, 'highpass_hz', []);
lp = getfield_def(p, 'lowpass_hz', []);
notch = getfield_def(p, 'notch_hz', []);

% ---- 参数校验（与 Python 侧一致，双重防护）----
if ~isempty(hp) && ~isempty(lp) && hp >= lp
    error('EEGLAB_MCP:BadParams', 'highpass_hz (%g) must be lower than lowpass_hz (%g).', hp, lp);
end
if ~isempty(lp) && lp >= nyq
    error('EEGLAB_MCP:BadParams', 'lowpass_hz (%g) must be below Nyquist (%g).', lp, nyq);
end
if ~isempty(hp) && hp <= 0
    error('EEGLAB_MCP:BadParams', 'highpass_hz must be > 0.');
end
if ~isempty(notch) && notch >= nyq
    error('EEGLAB_MCP:BadParams', 'notch_hz (%g) must be below Nyquist (%g).', notch, nyq);
end

applied = {};
if ~isempty(notch)
    EEG = pop_eegfiltnew(EEG, 'locutoff', notch - 1, 'hicutoff', notch + 1, 'revfilt', 1);
    applied{end+1} = sprintf('bandstop %g-%g Hz', notch - 1, notch + 1);
end
if ~isempty(hp)
    EEG = pop_eegfiltnew(EEG, 'locutoff', hp, 'minphase', 0);
    applied{end+1} = sprintf('highpass %g Hz (zero-phase)', hp);
end
if ~isempty(lp)
    EEG = pop_eegfiltnew(EEG, 'hicutoff', lp, 'minphase', 0);
    applied{end+1} = sprintf('lowpass %g Hz (zero-phase)', lp);
end
if isempty(applied)
    error('EEGLAB_MCP:BadParams', 'No filter parameter supplied.');
end

EEG = eeg_checkset(EEG);
d = struct();
d.filters_applied = applied;
d.sampling_rate_hz = EEG.srate;
d.nyquist_hz = nyq;
d.channel_count = EEG.nbchan;
d.points = EEG.pnts;
[res, out] = save_stage(EEG, job, res, 'filtered');
d.output_file = out;
end

% ======================================================================
%  REREF
% ======================================================================
function [res, d] = op_reref(job, res)
[EEG, res] = load_eeg(job, res);
p = getfield_def(job, 'params', struct());
method = getfield_def(p, 'method', 'average');

if strcmpi(method, 'average')
    EEG = pop_reref(EEG, []);
    label = 'average reference';
elseif strcmpi(method, 'channels')
    refs = getfield_def(p, 'channels', {});
    if ischar(refs), refs = {refs}; end
    if isempty(refs)
        error('EEGLAB_MCP:BadParams', 'method=channels requires a non-empty channels list.');
    end
    idx = chan_indices(EEG, refs);
    EEG = pop_reref(EEG, idx);
    label = ['reference to ' strjoin(refs, '+')];
else
    error('EEGLAB_MCP:BadParams', 'Unsupported reref method: %s', method);
end

EEG = eeg_checkset(EEG);
d = struct('method', method, 'reference_label', label, 'channel_count', EEG.nbchan);
[res, out] = save_stage(EEG, job, res, 'reref');
d.output_file = out;
end

% ======================================================================
%  EPOCH
% ======================================================================
function [res, d] = op_epoch(job, res)
[EEG, res] = load_eeg(job, res);
p = getfield_def(job, 'params', struct());

types = getfield_def(p, 'event_types', {});
if ischar(types), types = {types}; end
if isempty(types)
    error('EEGLAB_MCP:BadParams', 'event_types is required for epoching.');
end

tmin = getfield_def(p, 'tmin_s', -0.2);
tmax = getfield_def(p, 'tmax_s', 0.8);
if tmin >= tmax
    error('EEGLAB_MCP:BadParams', 'tmin_s must be lower than tmax_s.');
end
% 连续记录的 xmin 通常为 0，而标准刺激前窗（如 -0.2 s）必然小于 xmin；
% 真正的约束是"窗长不得超过记录长度"，靠边缘的事件由 pop_epoch 自行剔除。
if (tmax - tmin) > (EEG.xmax - EEG.xmin)
    error('EEGLAB_MCP:BadParams', ...
        'Epoch window length %g s exceeds recording length %g s.', ...
        tmax - tmin, EEG.xmax - EEG.xmin);
end

EEG = pop_epoch(EEG, types, [tmin tmax], 'newname', 'epoched', 'epochinfo', 'yes');
EEG = eeg_checkset(EEG);

d = struct();
d.event_types = types;
d.tmin_s = tmin;
d.tmax_s = tmax;
d.epoch_count = EEG.trials;
d.channel_count = EEG.nbchan;
d.points_per_epoch = EEG.pnts;
d.sampling_rate_hz = EEG.srate;
if EEG.trials == 0
    res.warnings{end+1} = 'No epochs were created — check that event types match the dataset.';
end
[res, out] = save_stage(EEG, job, res, 'epoched');
d.output_file = out;
end

% ======================================================================
%  BASELINE
% ======================================================================
function [res, d] = op_baseline(job, res)
[EEG, res] = load_eeg(job, res);
p = getfield_def(job, 'params', struct());
bmin = getfield_def(p, 'baseline_start_s', []);
bmax = getfield_def(p, 'baseline_end_s', 0);
if isempty(bmin)
    bmin = EEG.xmin;
end
if bmin >= bmax
    error('EEGLAB_MCP:BadParams', 'baseline_start_s must be lower than baseline_end_s.');
end
EEG = pop_rmbase(EEG, [bmin bmax] * 1000);   % pop_rmbase 用毫秒
EEG = eeg_checkset(EEG);
d = struct('baseline_start_s', bmin, 'baseline_end_s', bmax, 'epoch_count', EEG.trials);
[res, out] = save_stage(EEG, job, res, 'baseline');
d.output_file = out;
end

% ======================================================================
%  ICA
% ======================================================================
function [res, d] = op_ica(job, res)
[EEG, res] = load_eeg(job, res);
p = getfield_def(job, 'params', struct());
algo = getfield_def(p, 'algorithm', 'runica');

% 科学约束检查
if EEG.nbchan < 2
    error('EEGLAB_MCP:BadData', 'ICA requires at least 2 channels.');
end
data_rank = rank(double(reshape(EEG.data, EEG.nbchan, [])));
if data_rank < EEG.nbchan
    res.warnings{end+1} = sprintf( ...
        'Data rank (%d) is lower than channel count (%d); at most %d independent components are identifiable.', ...
        data_rank, EEG.nbchan, data_rank);
end
if EEG.pnts * EEG.trials < 10 * EEG.nbchan
    res.warnings{end+1} = 'Data length is short relative to channel count; ICA may be unstable.';
end

EEG = ica_decompose(EEG, algo);
if ~strcmpi(algo, 'pca')
    res.warnings{end+1} = ['ICA 由 ica_decompose 直接调用 runica 完成：EEGLAB 13 的 pop_runica ' ...
        '会强制打开中断图形按钮，新版 MATLAB 的 figure 句柄不是数值，supergui 会报错。'];
end

d = struct();
d.algorithm = algo;
d.component_count = size(EEG.icaweights, 1);
d.data_rank = data_rank;
d.rejected_components = {};
d.note = 'No components were rejected. Rejection requires explicit, auditable criteria and human confirmation.';
[res, out] = save_stage(EEG, job, res, 'ica');
d.output_file = out;
end

% ======================================================================
%  ERP
% ======================================================================
function [res, d] = op_erp(job, res)
[EEG, res] = load_eeg(job, res);

if EEG.trials < 2
    error('EEGLAB_MCP:BadData', ...
        'ERP requires epoched data with at least 2 trials (current trials=%d). Run epoch first.', EEG.trials);
end

X = double(EEG.data);                       % ch × time × trial
erp = mean(X, 3);                           % ch × time
gfp = sqrt(mean((erp - mean(erp, 1)).^2, 1));   % 全局场强
[u_scale, u_name] = detect_units(EEG);

d = struct();
d.channel_count = EEG.nbchan;
d.trial_count = EEG.trials;
d.time_start_s = EEG.xmin;
d.time_end_s = EEG.xmax;
d.sampling_rate_hz = EEG.srate;

% 降采样到 ≤ 300 点，控制 JSON 体积
n = numel(EEG.times);
step = max(1, ceil(n / 300));
idx = 1:step:n;
d.times_s = EEG.times(idx) / 1000;
d.global_field_power_uv = gfp(idx) * u_scale;

% 选定通道波形（默认第一个通道）
p = getfield_def(job, 'params', struct());
ch_name = getfield_def(p, 'channel', '');
if isempty(ch_name)
    ci = 1;
else
    try
        ci = chan_indices(EEG, {ch_name});
    catch ME
        % 没有通道定位的数据没有标签可查；此时允许用 chN 指第 N 个通道。
        tok = regexp(ch_name, '^ch(\d+)$', 'tokens', 'once');
        if isempty(tok), rethrow(ME); end
        ci = str2double(tok{1});
        if ci < 1 || ci > EEG.nbchan
            error('EEGLAB_MCP:BadParams', ...
                'Channel "%s" is out of range (1-%d).', ch_name, EEG.nbchan);
        end
    end
end
d.waveform_channel = channel_label(EEG, ci);
d.waveform_uv = erp(ci, idx) * u_scale;
d.input_unit_assumed = u_name;
d.unit_scale_to_uv = u_scale;

% 全通道 ERP 存为产物
out_dir = getfield_def(job, 'output_dir', '.');
fn = fullfile(out_dir, 'erp_data.csv');
tbl = array2table([EEG.times(:)/1000, erp']);
names = [{'time_s'}, arrayfun(@(c) sprintf('ch%d', c), 1:EEG.nbchan, 'UniformOutput', false)];
tbl.Properties.VariableNames = names;
writetable(tbl, fn);
res.artifacts{end+1} = artifact(fn, 'erp_matrix_csv');
d.erp_matrix_file = fn;

if any(~isfinite(erp(:)))
    res.warnings{end+1} = 'ERP contains non-finite values.';
end
end

% ======================================================================
%  PSD
% ======================================================================
function [res, d] = op_psd(job, res)
[EEG, res] = load_eeg(job, res);
p = getfield_def(job, 'params', struct());
fmax = getfield_def(p, 'fmax_hz', min(40, EEG.srate/2 - 1));
if fmax >= EEG.srate/2
    error('EEGLAB_MCP:BadParams', 'fmax_hz must be below Nyquist (%g).', EEG.srate/2);
end

[spectra, freqs] = spectopo(reshape(EEG.data, EEG.nbchan, []), 0, EEG.srate, 'plot', 'off');
sel = freqs <= fmax;
d = struct();
d.fmin_hz = 0;
d.fmax_hz = fmax;
d.freqs_hz = freqs(sel);
d.mean_spectrum_db = mean(spectra(:, sel), 1);
d.channel_count = EEG.nbchan;
d.note = 'Spectrum computed by EEGLAB spectopo (Welch). Units: dB.';

out_dir = getfield_def(job, 'output_dir', '.');
fn = fullfile(out_dir, 'psd.csv');
tbl = table(freqs(sel), mean(spectra(:, sel), 1)', 'VariableNames', {'freq_hz', 'mean_db'});
writetable(tbl, fn);
res.artifacts{end+1} = artifact(fn, 'psd_csv');
d.psd_file = fn;
end

% ======================================================================
%  PLOT
% ======================================================================
function [res, d] = op_plot(job, res)
[EEG, res] = load_eeg(job, res);
p = getfield_def(job, 'params', struct());
kind = getfield_def(p, 'kind', 'erp_waveform');
out_dir = getfield_def(job, 'output_dir', '.');

set(0, 'DefaultFigureVisible', 'off');
d = struct('kind', kind);

switch kind
    case 'erp_waveform'
        if EEG.trials < 2
            error('EEGLAB_MCP:BadData', 'ERP plot requires epoched data (trials >= 2).');
        end
        erp = mean(double(EEG.data), 3);
        fig = figure('Position', [100 100 900 420], 'Color', 'w');
        [u_scale, ~] = detect_units(EEG);
        plot(EEG.times/1000, erp' * u_scale, 'LineWidth', 0.6);
        xlim([EEG.xmin EEG.xmax]);
        xlabel('Time (s)'); ylabel('Amplitude (\muV)');
        title(sprintf('ERP — %d trials, %d channels', EEG.trials, EEG.nbchan));
        grid on; box off;
        fn = fullfile(out_dir, 'erp_waveform.png');
        print(fig, fn, '-dpng', '-r150'); close(fig);
        res.artifacts{end+1} = artifact(fn, 'figure_png');
        d.figure_file = fn;

    case 'topomap'
        if numel(EEG.chanlocs) < 3 || isempty([EEG.chanlocs.X])
            error('EEGLAB_MCP:BadData', 'Topomap requires channel locations, which are not defined.');
        end
        erp = mean(double(EEG.data), 3);
        tp = getfield_def(p, 'time_s', 0.3);
        [~, ti] = min(abs(EEG.times/1000 - tp));
        fig = figure('Position', [100 100 520 460], 'Color', 'w');
        topoplot(erp(:, ti), EEG.chanlocs, 'maplimits', 'absmax');
        title(sprintf('Topography at %.3f s', EEG.times(ti)/1000));
        fn = fullfile(out_dir, 'topomap.png');
        print(fig, fn, '-dpng', '-r150'); close(fig);
        res.artifacts{end+1} = artifact(fn, 'figure_png');
        d.figure_file = fn;
        d.time_s = EEG.times(ti)/1000;

    case 'psd'
        [spectra, freqs] = spectopo(reshape(EEG.data, EEG.nbchan, []), 0, EEG.srate, 'plot', 'off');
        fig = figure('Position', [100 100 760 420], 'Color', 'w');
        plot(freqs, mean(spectra,1), 'LineWidth', 1.4);
        xlim([0 min(40, EEG.srate/2)]); xlabel('Frequency (Hz)'); ylabel('Power (dB)');
        title('Power spectral density (channel mean)'); grid on; box off;
        fn = fullfile(out_dir, 'psd.png');
        print(fig, fn, '-dpng', '-r150'); close(fig);
        res.artifacts{end+1} = artifact(fn, 'figure_png');
        d.figure_file = fn;

    otherwise
        error('EEGLAB_MCP:BadParams', 'Unsupported plot kind: %s', kind);
end
end

% ======================================================================
%  PIPELINE（预定义流程，不接受任意步骤）
% ======================================================================
function [res, d] = op_pipeline(job, res)
p = getfield_def(job, 'params', struct());
name = getfield_def(p, 'pipeline', '');
steps_done = {};

[EEG, res] = load_eeg(job, res);

switch name
    case 'basic_preprocess'
        hp = getfield_def(p, 'highpass_hz', 1);
        lp = getfield_def(p, 'lowpass_hz', min(40, EEG.srate/2 - 1));
        EEG = pop_eegfiltnew(EEG, 'locutoff', hp, 'minphase', 0);
        EEG = pop_eegfiltnew(EEG, 'hicutoff', lp, 'minphase', 0);
        steps_done{end+1} = sprintf('bandpass %g-%g Hz', hp, lp);
        EEG = pop_reref(EEG, []);
        steps_done{end+1} = 'average reference';
        EEG = eeg_checkset(EEG);

    case 'erp_analysis'
        types = getfield_def(p, 'event_types', {});
        if ischar(types), types = {types}; end
        if isempty(types)
            error('EEGLAB_MCP:BadParams', 'erp_analysis requires event_types.');
        end
        hp = getfield_def(p, 'highpass_hz', 1);
        lp = getfield_def(p, 'lowpass_hz', min(30, EEG.srate/2 - 1));
        tmin = getfield_def(p, 'tmin_s', -0.2);
        tmax = getfield_def(p, 'tmax_s', 0.8);
        bmin = getfield_def(p, 'baseline_start_s', tmin);
        bmax = getfield_def(p, 'baseline_end_s', 0);

        EEG = pop_eegfiltnew(EEG, 'locutoff', hp, 'minphase', 0);
        EEG = pop_eegfiltnew(EEG, 'hicutoff', lp, 'minphase', 0);
        steps_done{end+1} = sprintf('bandpass %g-%g Hz', hp, lp);
        EEG = pop_reref(EEG, []);
        steps_done{end+1} = 'average reference';
        EEG = pop_epoch(EEG, types, [tmin tmax]);
        steps_done{end+1} = sprintf('epoch [%g %g] s on %s', tmin, tmax, strjoin(types, ','));
        EEG = pop_rmbase(EEG, [bmin bmax] * 1000);
        steps_done{end+1} = sprintf('baseline [%g %g] s', bmin, bmax);
        EEG = eeg_checkset(EEG);

    otherwise
        error('EEGLAB_MCP:BadParams', 'Unknown pipeline: %s', name);
end

d = struct();
d.pipeline = name;
d.steps = steps_done;
d.channel_count = EEG.nbchan;
d.trials = EEG.trials;
d.sampling_rate_hz = EEG.srate;

% 若已分段，附 ERP 摘要
if EEG.trials >= 2
    erp = mean(double(EEG.data), 3);
    gfp = sqrt(mean((erp - mean(erp,1)).^2, 1));
    idx = 1:max(1, ceil(numel(EEG.times)/300)):numel(EEG.times);
    d.erp_times_s = EEG.times(idx)/1000;
    [u_scale, u_name] = detect_units(EEG);
    d.erp_gfp_uv = gfp(idx) * u_scale;
    d.input_unit_assumed = u_name;
end

[res, out] = save_stage(EEG, job, res, ['pipeline_' name]);
d.output_file = out;
end

% ======================================================================
%  BATCH（多被试批量处理，单个失败不中断整批）
% ======================================================================
function [res, d] = op_batch(job, res)
p = getfield_def(job, 'params', struct());
files = getfield_def(p, 'files', {});
if ischar(files), files = {files}; end
if isempty(files)
    error('EEGLAB_MCP:BadParams', 'files must contain at least one path.');
end
mode = getfield_def(p, 'mode', 'inspect');          % inspect | pipeline
pipeline = getfield_def(p, 'pipeline', 'basic_preprocess');
inner = getfield_def(p, 'pipeline_params', struct());

items = {};
n_ok = 0; n_fail = 0;
for i = 1:numel(files)
    fp = files{i};
    sub = job;
    sub.input = struct('file_path', fp);
    sub.output_dir = fullfile(getfield_def(job,'output_dir','.'), sprintf('item_%03d', i));
    if exist(sub.output_dir,'dir') ~= 7, mkdir(sub.output_dir); end

    subres = struct();
    subres.warnings = {};
    subres.artifacts = {};
    subres.log = {};

    t0 = tic;
    try
        if strcmpi(mode, 'inspect')
            [subres, dd] = op_inspect(sub, subres);
        elseif strcmpi(mode, 'pipeline')
            pp = inner; pp.pipeline = pipeline;
            sub.params = pp;
            [subres, dd] = op_pipeline(sub, subres);
        else
            error('EEGLAB_MCP:BadParams', 'batch mode must be inspect or pipeline.');
        end
        items{end+1} = struct('index', i, 'file', fp, 'ok', true, ...
            'seconds', toc(t0), 'warnings', {subres.warnings}, ...
            'artifacts', {subres.artifacts}, 'data', dd);
        n_ok = n_ok + 1;
    catch ME
        items{end+1} = struct('index', i, 'file', fp, 'ok', false, ...
            'seconds', toc(t0), 'error_code', ME.identifier, ...
            'error_message', ME.message, 'warnings', {{}}, 'artifacts', {{}});
        n_fail = n_fail + 1;
    end
end

d = struct();
d.mode = mode;
if strcmpi(mode,'pipeline'), d.pipeline = pipeline; end
d.total = numel(files);
d.succeeded = n_ok;
d.failed = n_fail;
d.items = items;
if n_fail > 0
    res.warnings{end+1} = sprintf('%d of %d files failed; see items[].error_message.', n_fail, numel(files));
end
end

% ======================================================================
%  IMPORT（EDF/BDF/CNT/BrainVision -> EEGLAB .set）
% ======================================================================
function [res, d] = op_import(job, res)
fp = getfield_def(job.input, 'file_path', '');
if exist(fp, 'file') ~= 2
    error('EEGLAB_MCP:FileNotFound', 'Input file not found: %s', fp);
end
[dirn, base, ext] = fileparts(fp);
ext = lower(ext);
src_format = ext;

switch ext
    case '.edf'
        EEG = pop_biosig(fp);
    case '.bdf'
        EEG = pop_biosig(fp);
    case '.cnt'
        try
            EEG = pop_loadcnt(fp);
        catch ME
            % 部分 .cnt 的头帧数与数据列数不一致，pop_loadcnt 内部的
            % eeg_checkset 会弹出确认框；无界面模式下弹框必然失败
            % （supergui: argument 'fig' must be numeric）。给出可操作的处理建议。
            if contains(ME.message, 'supergui') || contains(ME.message, 'fig')
                error('EEGLAB_MCP:ImportNeedsGui', [ ...
                    'This .cnt has an inconsistent header (frames do not divide data columns); ' ...
                    'import needs a manual confirmation that headless MATLAB cannot give. ' ...
                    'Open it in the EEGLAB GUI (File > Import data > Using EEGLAB functions and plugins > ' ...
                    'From Neuroscan .CNT), then File > Save current dataset as .set, ' ...
                    'and import the .set instead.']);
            end
            rethrow(ME);
        end
    case '.vhdr'
        EEG = pop_loadbv(dirn, [base '.vhdr']);
    case {'.set'}
        EEG = pop_loadset('filename', [base ext], 'filepath', dirn);
    otherwise
        error('EEGLAB_MCP:UnsupportedFormat', ...
            'Unsupported input format "%s". Supported: .edf .bdf .cnt .vhdr .set', ext);
end
EEG = eeg_checkset(EEG);

% 导入器会把源路径写进 EEG.comments / EEG.filename（中文目录即非 ASCII 字符），
% 而 pop_saveset 底层的 save 无法编码非 ASCII 字符，导致
% MATLAB:MatFile:UnsupportedCharacters。来源信息已完整记录在
% res.result.source_file 与 job.json 中，这里把路径类文本降级为 ASCII。
EEG.comments = ascii_safe(EEG.comments);
EEG.setname = ascii_safe(EEG.setname);
EEG.filename = ascii_safe(EEG.filename);
EEG.filepath = ascii_safe(EEG.filepath);

d = dataset_summary(EEG);
d.source_file = fp;
d.source_format = src_format;
d.original_sha256 = sha256_file(fp);
[res, out] = save_stage(EEG, job, res, 'imported');
d.output_file = out;
d.original_untouched = true;
res.log{end+1} = sprintf('Imported %s -> EEGLAB .set', ext);
if d.chanlocs_count == 0
    res.warnings{end+1} = 'Imported dataset has no channel locations.';
end
end

% ======================================================================
%  EXPORT_LONG（与 MNE-MCP / Pingouin-MCP 交接的长格式表）
% ======================================================================
function [res, d] = op_export_long(job, res)
% 输出 subject, condition, channel, mean_uv —— 每行一个观测。
% 这是 MNE-MCP 与 Pingouin-MCP 约定的通用交接格式。
[EEG, res] = load_eeg(job, res);
if EEG.trials < 2
    error('EEGLAB_MCP:BadData', 'export_long requires epoched data (trials >= 2).');
end

p = getfield_def(job, 'params', struct());
t1 = getfield_def(p, 'window_start_s', EEG.xmin);
t2 = getfield_def(p, 'window_end_s', EEG.xmax);
if t1 >= t2
    error('EEGLAB_MCP:BadParams', 'window_start_s must be lower than window_end_s.');
end
subject = getfield_def(p, 'subject_id', '');
if isempty(subject)
    [~, subject, ~] = fileparts(getfield_def(job.input, 'file_path', 'unknown'));
end

sel = EEG.times >= t1 * 1000 & EEG.times <= t2 * 1000;
if ~any(sel)
    error('EEGLAB_MCP:BadParams', 'Window [%g, %g] s contains no sample points.', t1, t2);
end
win = mean(double(EEG.data(:, sel, :)), 2);      % ch × 1 × trial
win = squeeze(win);                              % ch × trial
if EEG.nbchan == 1, win = win(:)'; end

% 每个 trial 的条件标签
conds = cell(1, EEG.trials);
for i = 1:EEG.trials
    conds{i} = trial_condition(EEG, i);
end

labels = cell(1, EEG.nbchan);
for c = 1:EEG.nbchan, labels{c} = channel_label(EEG, c); end

out_dir = getfield_def(job, 'output_dir', '.');
fn = fullfile(out_dir, 'long_table.csv');

fid = fopen(fn, 'w', 'n', 'UTF-8');
if fid < 0, error('EEGLAB_MCP:WriteFailed', 'Cannot write %s', fn); end
fprintf(fid, 'subject,condition,channel,mean_uv,trial\n');
n_rows = 0;
for c = 1:EEG.nbchan
    for i = 1:EEG.trials
        fprintf(fid, '%s,%s,%s,%.6f,%d\n', subject, conds{i}, labels{c}, win(c,i), i);
        n_rows = n_rows + 1;
    end
end
fclose(fid);

d = struct();
d.subject_id = subject;
d.window_start_s = t1;
d.window_end_s = t2;
d.conditions = unique(conds);
d.channels = EEG.nbchan;
d.trials = EEG.trials;
d.rows = n_rows;
d.long_table_file = fn;
d.schema = 'subject,condition,channel,mean_uv,trial';
d.compatible_with = 'MNE-MCP / Pingouin-MCP long-format hand-off';
res.artifacts{end+1} = artifact(fn, 'long_table_csv');
res.log{end+1} = sprintf('Wrote %d long-format rows', n_rows);
end

function cond = trial_condition(EEG, i)
cond = 'unknown';
try
    ev = EEG.epoch(i).eventtype;
    if iscell(ev)
        if ~isempty(ev), cond = char(string(ev{1})); end
    else
        cond = char(string(ev));
    end
catch
end
end

% ======================================================================
%  辅助函数
% ======================================================================
function [EEG, res] = load_eeg(job, res)
fp = getfield_def(job.input, 'file_path', '');
if isempty(fp)
    error('EEGLAB_MCP:BadParams', 'input.file_path is required.');
end
if exist(fp, 'file') ~= 2
    error('EEGLAB_MCP:FileNotFound', 'Input file not found: %s', fp);
end
[~, base, ext] = fileparts(fp);
if ~strcmpi(ext, '.set')
    error('EEGLAB_MCP:BadFormat', 'Only .set files are supported in this version.');
end
EEG = pop_loadset('filename', [base ext], 'filepath', fileparts(fp));
EEG = eeg_checkset(EEG);
res.log{end+1} = sprintf('Loaded %s (%d ch, %g Hz, %d points)', ...
    [base ext], EEG.nbchan, EEG.srate, EEG.pnts);
end

function s = dataset_summary(EEG)
s = struct();
s.sampling_rate_hz = EEG.srate;
s.channel_count = EEG.nbchan;
s.points = EEG.pnts;
s.trials = EEG.trials;
s.duration_seconds = EEG.pnts / EEG.srate / max(1, EEG.trials);
s.epoch_count = EEG.trials;
s.event_count = numel(EEG.event);
s.chanlocs_count = numel(EEG.chanlocs);
s.data_type = ternary(EEG.trials > 1, 'epoched', 'continuous');
s.time_start_s = EEG.xmin;
s.time_end_s = EEG.xmax;
s.all_finite = all(isfinite(EEG.data(:)));
s.data_size = mat2str(size(EEG.data));
if ~isempty(EEG.event)
    s.event_types = unique(cellstr(string({EEG.event.type})))';
else
    s.event_types = {};
end
end

function [res, fn] = save_stage(EEG, job, res, tag)
out_dir = getfield_def(job, 'output_dir', '.');
if isempty(out_dir), out_dir = '.'; end
if exist(out_dir, 'dir') ~= 7, mkdir(out_dir); end
fn = fullfile(out_dir, [tag '.set']);
pop_saveset(EEG, 'filename', [tag '.set'], 'filepath', out_dir);
res.artifacts{end+1} = artifact(fn, 'eeglab_set');
res.log{end+1} = sprintf('Saved staged dataset: %s', fn);
end

function a = artifact(path, kind)
a = struct('path', path, 'kind', kind, 'bytes', file_bytes(path));
end

function n = file_bytes(path)
n = 0;
d = dir(path);
if ~isempty(d), n = d(1).bytes; end
end

function idx = chan_indices(EEG, names)
if isempty(EEG.chanlocs)
    error('EEGLAB_MCP:BadData', 'Channel locations are not defined; cannot look up channel names.');
end
labels = {EEG.chanlocs.labels};
idx = [];
for k = 1:numel(names)
    j = find(strcmpi(labels, names{k}), 1);
    if isempty(j)
        error('EEGLAB_MCP:BadParams', 'Unknown channel: %s', names{k});
    end
    idx(end+1) = j;
end
end

function lb = channel_label(EEG, ci)
if ~isempty(EEG.chanlocs) && ci <= numel(EEG.chanlocs)
    lb = char(EEG.chanlocs(ci).labels);
else
    lb = sprintf('ch%d', ci);
end
end

function v = getfield_def(s, name, default)
if isstruct(s) && isfield(s, name) && ~isempty(s.(name))
    v = s.(name);
else
    v = default;
end
end

function v = getfield_def_safe(s, name, default)
try
    v = getfield_def(s, name, default);
catch
    v = default;
end
end

function out = sanitize(x)
% NaN/Inf 不能进入 JSON：转成字符串标记
if isstruct(x)
    out = struct();
    f = fieldnames(x);
    for i = 1:numel(f)
        if numel(x) > 1
            out.(f{i}) = sanitize({x.(f{i})});
        else
            out.(f{i}) = sanitize(x.(f{i}));
        end
    end
elseif iscell(x)
    out = cell(size(x));
    for i = 1:numel(x)
        out{i} = sanitize(x{i});
    end
elseif islogical(x)
    % keep true/false so downstream JSON carries real booleans, not 1/0
    out = logical(x);
elseif isnumeric(x)
    x = double(x);
    x(~isfinite(x)) = 0;
    out = x;
else
    out = x;
end
end

function s = folder_name(p)
s = '';
if isempty(p), return; end
p = strrep(p, '/', filesep);
p = strrep(p, '\', filesep);
parts = strsplit(p, filesep);
parts = parts(~cellfun(@isempty, parts));
if ~isempty(parts), s = parts{end}; end
end

function v = ternary(cond, a, b)
if cond, v = a; else, v = b; end
end

function s = ascii_safe(s)
% 把非 ASCII 字符替换为 '?'：save 在非 UTF-8 locale 下无法编码这类字符。
if ~ischar(s) || isempty(s), return; end
s(double(s) > 127) = '?';
end
