function EEG = make_synthetic_eeg(srate, nbchan, seconds, varargin)
% MAKE_SYNTHETIC_EEG  构造一个已知答案的 EEG 结构体。
%
%   EEG = make_synthetic_eeg(256, 32, 120, 'bump_times', 5:3:116, ...
%                                'bump_amp', 5, 'bump_sigma_ms', 40);
%
%   测试的意义在于“我们知道自己注入了什么”，因此可以判断处理之后
%   峰潜伏期、幅值和试次数是否仍然正确。

p = struct('bump_times', [], 'bump_amp', 5, 'bump_sigma_ms', 40, 'noise_amp', 2, ...
           'event_times', []);
for k = 1:2:numel(varargin)
    p.(varargin{k}) = varargin{k + 1};
end

n = round(srate * seconds);
% EEGLAB 的某些插件会把随机数发生器切到 legacy 模式，此时直接 rng(seed)
% 会报错；先回到默认发生器再设种子，保证合成数据可复现。
try
    rng('default');
    rng(42);
catch
    rand('state', 42);
    randn('state', 42);
end
data = randn(nbchan, n) * p.noise_amp;

if ~isempty(p.bump_times)
    sigma = p.bump_sigma_ms / 1000;
    half = ceil(4 * sigma * srate);
    for t = p.bump_times(:)'
        centre = round(t * srate) + 1;
        idx = max(1, centre - half):min(n, centre + half);
        shape = exp(-0.5 * ((idx - centre) / (sigma * srate)).^2);
        data(:, idx) = data(:, idx) + p.bump_amp * shape;
    end
end

EEG = struct();
EEG.setname = 'synthetic';
EEG.filename = '';
EEG.filepath = '';
EEG.subject = '';
EEG.group = '';
EEG.condition = '';
EEG.session = [];
EEG.comments = 'synthetic data with a known ERP';
EEG.nbchan = nbchan;
EEG.trials = 1;
EEG.pnts = n;
EEG.srate = srate;
EEG.xmin = 0;
EEG.xmax = (n - 1) / srate;
EEG.times = (0:n - 1) / srate * 1000;
EEG.data = data;
EEG.icaact = [];
EEG.icawinv = [];
EEG.icaweights = [];
EEG.icasphere = [];
EEG.icachansind = [];
EEG.chanlocs = [];
EEG.urchanlocs = [];
EEG.chaninfo = struct();
EEG.ref = 'common';
EEG.event = [];
EEG.urevent = [];
EEG.eventdescription = {};
EEG.epoch = [];
EEG.epochdescription = {};
EEG.reject = struct();
EEG.stats = struct();
EEG.specdata = [];
EEG.specicaact = [];
EEG.splinefile = '';
EEG.icasplinefile = '';
EEG.dipfit = [];
EEG.history = '';
EEG.saved = 'no';
EEG.etc = struct();

if isempty(p.event_times)
    event_times = p.bump_times;   % 默认：刺激与诱发成分同时刻
else
    event_times = p.event_times;
end

if ~isempty(event_times)
    for k = 1:numel(event_times)
        EEG.event(k).type = 'square';
        EEG.event(k).latency = round(event_times(k) * srate) + 1;
        EEG.event(k).duration = 0;
    end
    EEG.urevent = EEG.event;
end

EEG = eeg_checkset(EEG);
end
